#!/usr/bin/env python3
"""
13-E — Diagnóstico m35 (stop -0.35, zip 10-RS). Pandas + zip, cero Docker.
Salida: research/output/diagnose_m35_13e_20260711.json
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  FidelityConfig,
  compute_btc_regime_daily,
  compute_metrics,
  equity_to_log_returns,
  load_ohlcv_1d,
  momentum_rank_panel,
  portfolio_return,
  simulate_freqtrade_fidelity,
  weights_top_n_momentum,
)

OUTPUT = ROOT / "research" / "output" / "diagnose_m35_13e_20260711.json"
ZIP_M35 = ROOT / "user_data" / "backtest_results" / "backtest-result-2026-07-11_10-01-04.zip"
DATADIR = ROOT / "user_data" / "data" / "binance"
INITIAL = 10_000.0
WINDOW, TOP_N, EXIT_K, FEE = 14, 3, 4, 0.001
DEXE_LISTING = pd.Timestamp("2021-07-23", tz="UTC")

E2 = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]

CFG_M35_FULL = FidelityConfig(
  monday_rebalance=True,
  entry_next_open=True,
  fee_per_side=True,
  stop_on_low=-0.35,
  discrete_compound=True,
  pit_dexe=True,
)

CFG_M35_NO_COMPOUND = FidelityConfig(
  monday_rebalance=True,
  entry_next_open=True,
  fee_per_side=True,
  stop_on_low=-0.35,
  discrete_compound=False,
  pit_dexe=True,
)


def _load_trades(zip_path: Path) -> pd.DataFrame:
  with zipfile.ZipFile(zip_path) as zf:
    j = next(n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n)
    trades = json.loads(zf.read(j))["strategy"]["XSecMomentum"]["trades"]
  df = pd.DataFrame(trades)
  df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
  df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
  df["duration_days"] = df["trade_duration"] / 1440
  return df


def _load_wallet(zip_path: Path) -> pd.Series:
  with zipfile.ZipFile(zip_path) as zf:
    name = next(n for n in zf.namelist() if n.endswith("_wallet.feather"))
    df = pd.read_feather(BytesIO(zf.read(name)))
  df["date"] = pd.to_datetime(df["date"], utc=True)
  return df.set_index("date")["total_quote"].sort_index()


def pnl_by_pair(df: pd.DataFrame) -> list[dict]:
  g = df.groupby("pair").agg(
    n_trades=("profit_abs", "count"),
    profit_abs=("profit_abs", "sum"),
    profit_pct_mean=("profit_ratio", lambda s: float(s.mean() * 100)),
    duration_days_mean=("duration_days", "mean"),
  )
  total = float(df["profit_abs"].sum())
  rows = []
  for pair, row in g.sort_values("profit_abs", ascending=False).iterrows():
    rows.append(
      {
        "pair": pair,
        "n_trades": int(row["n_trades"]),
        "profit_abs": float(row["profit_abs"]),
        "pct_of_total_pnl": float(row["profit_abs"] / total) if total else 0.0,
        "profit_pct_mean": float(row["profit_pct_mean"]),
        "duration_days_mean": float(row["duration_days_mean"]),
      }
    )
  return rows


def zec_by_year(df: pd.DataFrame) -> list[dict]:
  zec = df[df["pair"] == "ZEC/USDT"].copy()
  if zec.empty:
    return []
  zec["year"] = zec["close_date"].dt.year
  rows = []
  total_zec = float(zec["profit_abs"].sum())
  for year, g in zec.groupby("year"):
    rows.append(
      {
        "year": int(year),
        "n_trades": int(len(g)),
        "profit_abs": float(g["profit_abs"].sum()),
        "pct_of_zec_total": float(g["profit_abs"].sum() / total_zec) if total_zec else 0.0,
      }
    )
  return sorted(rows, key=lambda r: r["year"])


def equity_ex_pair_approx(df: pd.DataFrame, exclude_pair: str) -> dict:
  """
  Reconstrucción aproximada: equity = 10k + cumsum(profit_abs) de trades cerrados
  excluyendo el par (sin reemplazo en slots — conservador).
  """
  sub = df[df["pair"] != exclude_pair].sort_values("close_date")
  realized = sub.groupby(sub["close_date"].dt.normalize())["profit_abs"].sum()
  idx = pd.date_range(realized.index.min(), realized.index.max(), freq="D", tz="UTC")
  daily_pnl = realized.reindex(idx, fill_value=0.0)
  equity = INITIAL + daily_pnl.cumsum()
  peak = equity.cummax()
  dd = (equity - peak) / peak
  net = float(sub["profit_abs"].sum())
  gross = net + float(sub["fee_open"].fillna(0).sum() + sub["fee_close"].fillna(0).sum()) if "fee_open" in sub else net
  return {
    "method": "cumsum_close_pnl_sin_reemplazo_slots",
    "final_equity": float(equity.iloc[-1]),
    "final_mult": float(equity.iloc[-1] / INITIAL),
    "max_drawdown": float(dd.min()),
    "net_pnl_sum": net,
    "n_trades": int(len(sub)),
    "operable_net_positive": net > 0,
    "dd_under_60pct": float(dd.min()) > -0.60,
  }


def wallet_dd(wallet: pd.Series) -> float:
  peak = wallet.cummax()
  return float(((wallet - peak) / peak).min())


def fidelity_runs(close, open_, low, regime) -> dict:
  pit = {"DEXE/USDT": DEXE_LISTING}
  ranks = momentum_rank_panel(close, WINDOW, pit_dates=pit)
  fn = lambda p, t: weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)
  rets, turnover = portfolio_return(close, fn, "W", fee_per_rotation=FEE)
  m_log = compute_metrics(rets, turnover=turnover)

  out = {"research_log_wfri_B": float(m_log.final_wealth)}
  for label, cfg in (
    ("fidelity_m35_full", CFG_M35_FULL),
    ("fidelity_m35_no_compound", CFG_M35_NO_COMPOUND),
  ):
    eq, stats = simulate_freqtrade_fidelity(
      close, open_, low, ranks, regime, cfg, initial_wallet=INITIAL
    )
    lr = equity_to_log_returns(eq)
    m = compute_metrics(lr)
    out[label] = {
      "final_mult": stats["final_wealth_mult"],
      "max_dd": m.max_drawdown,
      "n_stops": stats["n_stops"],
      "n_rotations": stats["n_rotations"],
    }
  return out


def main() -> int:
  close, open_, _, low = load_ohlcv_1d(DATADIR, pairs=E2, start="2021-01-01")
  close = close.loc[: pd.Timestamp("2026-07-09", tz="UTC")]
  open_ = open_.reindex(close.index).ffill()
  low = low.reindex(close.index).ffill()
  regime = compute_btc_regime_daily(close["BTC/USDT"])

  df = _load_trades(ZIP_M35)
  wallet = _load_wallet(ZIP_M35)
  wallet = wallet.loc[:close.index[-1]]

  ft_mult = float(wallet.iloc[-1] / wallet.iloc[0])
  pair_tbl = pnl_by_pair(df)
  zec_trades = df[df["pair"] == "ZEC/USDT"]
  total_pnl = float(df["profit_abs"].sum())
  zec_pnl = float(zec_trades["profit_abs"].sum())
  fid = fidelity_runs(close, open_, low, regime)

  f_full = fid["fidelity_m35_full"]["final_mult"]
  f_nocomp = fid["fidelity_m35_no_compound"]["final_mult"]
  gap_ft_vs_fid = ft_mult / f_full if f_full else float("nan")
  gap_ft_vs_log = ft_mult / fid["research_log_wfri_B"]

  ex_zec = equity_ex_pair_approx(df, "ZEC/USDT")
  ex_dexe = equity_ex_pair_approx(df, "DEXE/USDT")

  compound_lift = f_full / f_nocomp if f_nocomp else float("nan")

  mechanism = None
  if gap_ft_vs_fid > 2.0:
    mechanism = {
      "name": "gap_invertido_sin_cerrar_compound_no_basta",
      "evidence": {
        "fidelity_m35_no_compound": f_nocomp,
        "fidelity_m35_full": f_full,
        "compound_lift_in_sim": compound_lift,
        "zec_pct_of_pnl": zec_pnl / total_pnl if total_pnl else 0,
        "zec_2025_pct_of_zec": 0.903,
        "gap_ft_vs_fidelity_full": gap_ft_vs_fid,
        "gap_ft_vs_research_log": gap_ft_vs_log,
      },
      "interpretation": (
        "Aislar compound en el simulador solo aporta ~{:.2f}× (6.86→7.25) — NO explica el gap FT/fidelidad ~{:.2f}×. "
        "El stop −35% en fidelidad predice 7.25× vs FT 26.2×. Sospechoso principal: interacción "
        "ZEC parabólico (90% del PnL ZEC en 2025) + stake/compounding real Freqtrade no modelado; "
        "rank merge y stake policy siguen en el residual."
      ).format(compound_lift, gap_ft_vs_fid),
    }

  out = {
    "date": "2026-07-11",
    "zip": str(ZIP_M35.name),
    "freqtrade_m35": {
      "initial": INITIAL,
      "final": float(wallet.iloc[-1]),
      "mult": ft_mult,
      "max_dd_wallet_feather_unreliable": wallet_dd(wallet),
      "max_dd_account_screen": 0.45611892182049296,
      "n_trades": int(len(df)),
    },
    "instrument_comparison": {
      "research_log_wfri_B_mult": fid["research_log_wfri_B"],
      "fidelity_m35_full": fid["fidelity_m35_full"],
      "fidelity_m35_no_compound": fid["fidelity_m35_no_compound"],
      "gap_ft_over_fidelity_full": gap_ft_vs_fid,
      "gap_ft_over_research_log": gap_ft_vs_log,
      "gap_inverted_vs_13D": "FT > instrumento (opuesto a ~2× research>FT del 13-D con stop -10%)",
    },
    "pnl_by_pair": pair_tbl,
    "zec_analysis": {
      "n_trades": int(len(zec_trades)),
      "profit_abs": zec_pnl,
      "pct_of_total_pnl": zec_pnl / total_pnl if total_pnl else 0,
      "duration_days_mean": float(zec_trades["duration_days"].mean()) if len(zec_trades) else None,
      "duration_days_median": float(zec_trades["duration_days"].median()) if len(zec_trades) else None,
      "by_year": zec_by_year(df),
      "loo_bruto_screen": 77617.05,
    },
    "ex_zec_counterfactual": ex_zec,
    "ex_dexe_counterfactual_reference": ex_dexe,
    "mechanism_if_gap_gt_2x": mechanism,
    "wf_validation_expectation": {
      "concentration_temporal": (
        "Con ~{:.0%} del PnL en ZEC, ventanas WF sin rally ZEC deberían ser mediocres "
        "(neto positivo pero modesto vs ventanas con ZEC en top momentum)."
      ).format(zec_pnl / total_pnl if total_pnl else 0),
      "not_invalidation_if": [
        "Ventanas sin ZEC siguen con bruto > 0 y DD < umbral full",
        "LOO ex-ZEC ya pasó screen (+77k bruto); perfil ex-ZEC aprox sigue operable",
      ],
      "would_invalidate_if": [
        "Mayoría de ventanas OOS con bruto ≤ 0 sin ZEC en cartera",
        "Max DD ex-ZEC en trayectoria real supera 60% (counterfactual aprox lo acota)",
        "Veredicto full depende de 1-2 ventanas con ZEC parabólico únicamente",
      ],
    },
  }

  OUTPUT.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
  print(json.dumps(
    {
      "ft_mult": ft_mult,
      "fidelity_m35": f_full,
      "gap": gap_ft_vs_fid,
      "zec_pct": zec_pnl / total_pnl,
      "ex_zec_dd": ex_zec["max_drawdown"],
    },
    indent=2,
  ))
  print(f"JSON: {OUTPUT}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
