#!/usr/bin/env python3
"""
Reconciliación motores pandas ↔ Freqtrade (13-D, 2026-07-11).

Parte 1: anomalía stops + rotación (zips existentes).
Parte 2: ablación fidelidad incremental.
Salida: research/output/motor_reconciliation_20260711.json + png
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import asdict
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
  load_closes_1d,
  load_ohlcv_1d,
  make_liquidity_masked_momentum,
  momentum_rank_panel,
  portfolio_return,
  simulate_freqtrade_fidelity,
  weekly_return_correlation,
  weights_top_n_momentum,
  load_quote_volume_30d,
)

OUTPUT_JSON = ROOT / "research" / "output" / "motor_reconciliation_20260711.json"
OUTPUT_PNG = ROOT / "research" / "output" / "motor_reconciliation_20260711.png"
ZIP_CTRL = ROOT / "user_data" / "backtest_results" / "backtest-result-2026-07-10_16-26-23.zip"
ZIP_20M = ROOT / "user_data" / "backtest_results" / "backtest-result-2026-07-11_09-27-24.zip"
DATADIR = ROOT / "user_data" / "data" / "binance"

E2 = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]
WINDOW, TOP_N, EXIT_K, FEE = 14, 3, 4, 0.001
FT_STOP_ACTUAL = -0.1
DEXE_LISTING = pd.Timestamp("2021-07-23", tz="UTC")

FIDELITY_STEPS = [
  ("0_research_wfri_log", None),
  ("1_monday_slots", FidelityConfig(monday_rebalance=True)),
  ("2_entry_open_t1", FidelityConfig(monday_rebalance=True, entry_next_open=True)),
  ("3_fee_per_side", FidelityConfig(monday_rebalance=True, entry_next_open=True, fee_per_side=True)),
  (
    "4_stop_low_10pct",
    FidelityConfig(
      monday_rebalance=True,
      entry_next_open=True,
      fee_per_side=True,
      stop_on_low=FT_STOP_ACTUAL,
    ),
  ),
  (
    "5_discrete_compound",
    FidelityConfig(
      monday_rebalance=True,
      entry_next_open=True,
      fee_per_side=True,
      stop_on_low=FT_STOP_ACTUAL,
      discrete_compound=True,
    ),
  ),
  (
    "6_pit_dexe",
    FidelityConfig(
      monday_rebalance=True,
      entry_next_open=True,
      fee_per_side=True,
      stop_on_low=FT_STOP_ACTUAL,
      discrete_compound=True,
      pit_dexe=True,
    ),
  ),
]


def _load_trades(zip_path: Path, strategy: str) -> list[dict]:
  with zipfile.ZipFile(zip_path) as zf:
    j = next(n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n)
    return list(json.loads(zf.read(j))["strategy"][strategy]["trades"])


def _load_wallet(zip_path: Path) -> pd.Series:
  with zipfile.ZipFile(zip_path) as zf:
    name = next(n for n in zf.namelist() if n.endswith("_wallet.feather"))
    df = pd.read_feather(BytesIO(zf.read(name)))
  df["date"] = pd.to_datetime(df["date"], utc=True)
  return df.set_index("date")["total_quote"].sort_index()


def _load_archived_params(zip_path: Path) -> dict:
  with zipfile.ZipFile(zip_path) as zf:
    name = next(n for n in zf.namelist() if n.endswith("_XSecMomentum.json"))
    return json.loads(zf.read(name))


def part1_stop_anomaly(zip_path: Path, ranks: pd.DataFrame) -> dict:
  trades = _load_trades(zip_path, "XSecMomentum")
  params = _load_archived_params(zip_path)
  df = pd.DataFrame(trades)
  df["profit_pct"] = df["profit_ratio"] * 100
  df["duration_days"] = df["trade_duration"] / 1440

  by_reason: dict = {}
  for reason, g in df.groupby("exit_reason"):
    by_reason[reason] = {
      "n": int(len(g)),
      "profit_pct_mean": float(g["profit_pct"].mean()),
      "profit_pct_median": float(g["profit_pct"].median()),
      "profit_pct_min": float(g["profit_pct"].min()),
      "profit_pct_max": float(g["profit_pct"].max()),
      "duration_days_mean": float(g["duration_days"].mean()),
      "duration_days_median": float(g["duration_days"].median()),
      "profit_abs_sum": float(g["profit_abs"].sum()),
    }

  stops = df[df["exit_reason"] == "stop_loss"]
  rot = df[df["exit_reason"] == "xsec_rotation_exit"]

  stops_rank_gt4 = 0
  for _, t in stops.iterrows():
    pair = t["pair"]
    od, cd = pd.Timestamp(t["open_date"]), pd.Timestamp(t["close_date"])
    mondays = ranks.loc[od:cd].index[ranks.loc[od:cd].index.weekday == 0]
    for m in mondays:
      if pair in ranks.columns and pd.notna(ranks.loc[m, pair]) and ranks.loc[m, pair] > EXIT_K:
        stops_rank_gt4 += 1
        break

  rot_bad = 0
  for _, t in rot.iterrows():
    pair = t["pair"]
    cd = pd.Timestamp(t["close_date"])
    if cd in ranks.index and pair in ranks.columns:
      rk = ranks.loc[cd, pair]
      if pd.isna(rk) or rk <= EXIT_K:
        rot_bad += 1

  non_stop_pnl = float(df[df["exit_reason"] != "stop_loss"]["profit_abs"].sum())
  stop_pnl = float(stops["profit_abs"].sum())

  defect = {
    "strategy_class_stoploss": -0.35,
    "params_file_stoploss": params.get("params", {}).get("stoploss", {}),
    "actual_stop_ratio_in_trades": float(stops["stop_loss_ratio"].iloc[0]) if len(stops) else None,
    "verdict": (
      "DEFECTO_MATERIALIZACION: screen_strategy PARAMS_TEMPLATE fuerza stoploss=-0.1 "
      "en XSecMomentum.json, anulando stoploss=-0.35 de la clase. Screen PASA usó -10%, no -35%."
    ),
  }

  return {
    "n_trades": int(len(df)),
    "by_exit_reason": by_reason,
    "stop_loss_analysis": {
      "all_near_minus_10pct": bool((stops["profit_pct"] > -10.5).all() and (stops["profit_pct"] < -9.5).all()),
      "none_near_minus_35pct": bool((stops["profit_pct"] > -36).all()),
      "stops_with_monday_rank_gt4_before_exit": stops_rank_gt4,
      "rotation_exits_with_rank_lte4_on_close": rot_bad,
      "stop_pnl_sum": stop_pnl,
      "non_stop_pnl_sum": non_stop_pnl,
      "profile": "muchos_stops_pequenos_vs_cohetes" if abs(stop_pnl) < non_stop_pnl else "stops_dominan",
    },
    "params_override_defect": defect,
    "rotation_bug": stops_rank_gt4 > len(stops) * 0.5,
  }


def _weekly_holdings_from_trades(trades: list[dict]) -> dict[pd.Timestamp, set[str]]:
  """Pares abiertos cada lunes (señal) según trades Freqtrade."""
  holdings: dict[pd.Timestamp, set[str]] = {}
  for t in trades:
    od = pd.Timestamp(t["open_date"], tz="UTC").normalize()
    cd = pd.Timestamp(t["close_date"], tz="UTC").normalize()
    pair = t["pair"]
    # trade abierto en od; activo hasta cd exclusive en práctica diaria
    mondays = pd.date_range(od, cd, freq="W-MON", tz="UTC")
    for m in mondays:
      holdings.setdefault(m, set()).add(pair)
  return holdings


def _weekly_holdings_from_sim(
  close: pd.DataFrame,
  ranks: pd.DataFrame,
  regime: pd.Series,
  cfg: FidelityConfig,
) -> dict[pd.Timestamp, set[str]]:
  """Reconstruye holdings en lunes de señal vía simulación ligera."""
  _, stats = simulate_freqtrade_fidelity(
    close, close, close, ranks, regime, cfg, initial_wallet=10_000.0
  )
  del stats
  holdings: dict[pd.Timestamp, set[str]] = {}
  idx = close.index
  slots: list[str | None] = [None, None, None]
  startup_skip = 220
  for i, dt in enumerate(idx):
    if i < startup_skip:
      continue
    if dt.weekday() == 1 and i > 0 and idx[i - 1].weekday() == 0:
      signal_dt = idx[i - 1]
      if cfg.bear_filter and str(regime.loc[signal_dt]) == "BEAR":
        slots = [None, None, None]
      else:
        row = ranks.loc[signal_dt]
        for si, pair in enumerate(slots):
          if pair and pd.notna(row.get(pair, np.nan)) and float(row[pair]) > cfg.exit_rank_k:
            slots[si] = None
        held = {p for p in slots if p}
        cands = [
          (float(row[p]), p)
          for p in close.columns
          if pd.notna(row.get(p, np.nan)) and float(row[p]) <= cfg.top_n and p not in held
        ]
        cands.sort()
        for _, p in cands:
          if None in slots:
            slots[slots.index(None)] = p
      holdings[signal_dt] = {p for p in slots if p}
  return holdings


def portfolio_divergence(
  ft_trades: list[dict],
  close: pd.DataFrame,
  ranks: pd.DataFrame,
  regime: pd.Series,
  cfg: FidelityConfig,
) -> dict:
  ft_h = _weekly_holdings_from_trades(ft_trades)
  sim_h = _weekly_holdings_from_sim(close, ranks, regime, cfg)
  common = sorted(set(ft_h) & set(sim_h))
  mismatches = []
  for m in common:
    if ft_h[m] != sim_h[m]:
      mismatches.append(
        {
          "monday": m.isoformat(),
          "freqtrade": sorted(ft_h[m]),
          "sim": sorted(sim_h[m]),
        }
      )
  first = mismatches[0] if mismatches else None
  return {
    "mondays_compared": len(common),
    "mismatch_weeks": len(mismatches),
    "match_rate": 1.0 - len(mismatches) / len(common) if common else float("nan"),
    "first_sustained_divergence": first,
    "sample_mismatches": mismatches[:8],
  }


def _step_contribution(rows: list[dict]) -> list[dict]:
  out = []
  prev_mult = rows[0].get("final_wealth_mult") or rows[0].get("final_wealth")
  for r in rows[1:]:
    mult = r.get("final_wealth_mult") or r["final_wealth"]
    out.append(
      {
        "step": r["step"],
        "wealth_mult": mult,
        "delta_mult": mult - prev_mult,
        "delta_pct": (mult / prev_mult - 1.0) if prev_mult else float("nan"),
      }
    )
    prev_mult = mult
  return out


def part2_reconciliation(
  close: pd.DataFrame,
  open_: pd.DataFrame,
  low: pd.DataFrame,
  regime: pd.Series,
  ft_wallet: pd.Series,
  *,
  ft_trades: list[dict] | None = None,
) -> dict:
  fn = lambda p, t: weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)
  rows = []
  curves: dict[str, pd.Series] = {"freqtrade_actual": ft_wallet / ft_wallet.iloc[0]}

  # research baseline
  rets, turnover = portfolio_return(close, fn, "W", fee_per_rotation=FEE)
  m0 = compute_metrics(rets, turnover=turnover)
  rows.append(
    {
      "step": "0_research_wfri_log",
      "final_wealth": m0.final_wealth,
      "max_dd": m0.max_drawdown,
      "weekly_corr_vs_ft": weekly_return_correlation(np.exp(rets.cumsum()), ft_wallet),
    }
  )
  curves["0_research_wfri_log"] = np.exp(rets.cumsum()) * 10_000

  pit = {"DEXE/USDT": DEXE_LISTING}

  for label, cfg in FIDELITY_STEPS[1:]:
    assert cfg is not None
    pit_dates = pit if cfg.pit_dexe else None
    ranks = momentum_rank_panel(close, WINDOW, pit_dates=pit_dates)
    eq, stats = simulate_freqtrade_fidelity(close, open_, low, ranks, regime, cfg, initial_wallet=10_000.0)
    lr = equity_to_log_returns(eq)
    m = compute_metrics(lr)
    corr = weekly_return_correlation(eq, ft_wallet)
    rows.append(
      {
        "step": label,
        "config": asdict(cfg),
        "final_wealth_mult": stats["final_wealth_mult"],
        "final_wealth": float(eq.iloc[-1] / 10_000),
        "max_dd": m.max_drawdown,
        "weekly_corr_vs_ft": corr,
        "sim_stats": stats,
      }
    )
    curves[label] = eq

  final = rows[-1]
  ft_mult = float(ft_wallet.iloc[-1] / ft_wallet.iloc[0])
  gap_ratio = final["final_wealth_mult"] / ft_mult if ft_mult else float("nan")
  success = (
    final.get("weekly_corr_vs_ft", 0) > 0.9
    and abs(final["final_wealth_mult"] - ft_mult) / ft_mult < 0.30
  )

  portfolio_cmp = {}
  if ft_trades and not success:
    cfg_final = FIDELITY_STEPS[-1][1]
    assert cfg_final is not None
    pit = {"DEXE/USDT": DEXE_LISTING} if cfg_final.pit_dexe else None
    ranks_final = momentum_rank_panel(close, WINDOW, pit_dates=pit)
    portfolio_cmp = portfolio_divergence(ft_trades, close, ranks_final, regime, cfg_final)

  return {
    "steps": rows,
    "step_contribution": _step_contribution(rows),
    "freqtrade_control_mult": ft_mult,
    "gap_final_mult_ratio": gap_ratio,
    "reconciliation_success": success,
    "portfolio_comparison": portfolio_cmp,
    "curves_keys": list(curves.keys()),
    "_curves": curves,
  }


def part2_filter_20m_recheck(close: pd.DataFrame, open_: pd.DataFrame, low: pd.DataFrame, regime: pd.Series) -> dict:
  vol = load_quote_volume_30d(E2, close.index, datadir=DATADIR)
  eligible = vol.reindex(columns=close.columns) > 20_000_000
  fn_20m = make_liquidity_masked_momentum(eligible, window=WINDOW, top_n=TOP_N)
  fn_free = lambda p, t: weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)

  cfg = FIDELITY_STEPS[-1][1]
  assert cfg is not None
  pit = {"DEXE/USDT": DEXE_LISTING} if cfg.pit_dexe else None

  out = {}
  for label, fn in (("no_filter", fn_free), ("filter_20m", fn_20m)):
    ranks = momentum_rank_panel(close, WINDOW, pit_dates=pit)
    if label == "filter_20m":
      # mask ranks: ineligible pairs get NaN rank
      for pair in close.columns:
        if pair in eligible.columns:
          ranks.loc[~eligible[pair].fillna(False), pair] = np.nan
    eq, _ = simulate_freqtrade_fidelity(close, open_, low, ranks, regime, cfg, initial_wallet=10_000.0)
    out[label] = {"final_wealth_mult": float(eq.iloc[-1] / 10_000)}
  out["filter_improves"] = out["filter_20m"]["final_wealth_mult"] > out["no_filter"]["final_wealth_mult"]
  return out


def main() -> int:
  close, open_, high, low = load_ohlcv_1d(DATADIR, pairs=E2, start="2021-01-01")
  close = close.loc[: pd.Timestamp("2026-07-09", tz="UTC")]
  open_ = open_.reindex(close.index).ffill()
  low = low.reindex(close.index).ffill()
  regime = compute_btc_regime_daily(close["BTC/USDT"])
  ranks_wfri = momentum_rank_panel(close, WINDOW)

  p1 = part1_stop_anomaly(ZIP_CTRL, ranks_wfri)
  ft_trades = _load_trades(ZIP_CTRL, "XSecMomentum")
  ft_wallet = _load_wallet(ZIP_CTRL)
  ft_wallet = ft_wallet.loc[:close.index[-1]]

  p2 = part2_reconciliation(close, open_, low, regime, ft_wallet, ft_trades=ft_trades)
  curves = p2.pop("_curves")
  filter_recheck = part2_filter_20m_recheck(close, open_, low, regime)

  research_mult = p2["steps"][0]["final_wealth"]
  fidelity_mult = p2["steps"][-1]["final_wealth_mult"]
  correction_factor = research_mult / fidelity_mult if fidelity_mult else float("nan")

  out = {
    "date": "2026-07-11",
    "part1_stops": p1,
    "part2_reconciliation": p2,
    "filter_20m_reconciled_mode": filter_recheck,
    "instrument_correction": {
      "research_log_overestimate_factor": correction_factor,
    "research_vs_freqtrade_factor": research_mult / p2["freqtrade_control_mult"],
    "fidelity_vs_freqtrade_factor": fidelity_mult / p2["freqtrade_control_mult"],
      "research_log_mult": research_mult,
      "fidelity_mult": fidelity_mult,
      "freqtrade_mult": p2["freqtrade_control_mult"],
      "rule": (
        f"El motor log-continuo W-FRI (B) sobreestima ~{research_mult / p2['freqtrade_control_mult']:.2f}× vs Freqtrade; "
        f"modo fidelidad residual ~{fidelity_mult / p2['freqtrade_control_mult']:.2f}×. "
        "Criterios research (#14+) deben validarse en simulate_freqtrade_fidelity."
      ),
    },
    "remaining_gap": {
      "named_causes": [
        "PARAMS_TEMPLATE stoploss=-0.1 (defecto materialización screen)",
        "Latencia señal lunes → ejecución martes open (100% trades FT)",
        "Stake policy / min_stake / confirm_trade_entry no modelados",
        "ADX régimen: ta-lib en FT vs aproximación pandas",
        "Rank cross-section: merge per-pair FT vs panel global pandas",
      ],
      "first_portfolio_divergence": p2.get("portfolio_comparison", {}).get("first_sustained_divergence"),
    },
    "recommendation": {
      "stop_defect": p1["params_override_defect"]["verdict"],
      "screen_pasa_validity": "comprometido — stop real -10% no -35% documentado",
      "degradation_20m_recheck": (
        "confirmada" if not filter_recheck["filter_improves"] else "prematura — filtro mejora en modo fidelidad"
      ),
      "reconciliation": "parcial" if not p2["reconciliation_success"] else "ok",
    },
  }

  OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  fig, ax = plt.subplots(figsize=(11, 5))
  for label, series in curves.items():
    norm = series / series.iloc[0] if series.iloc[0] else series
    ax.plot(norm.index, norm.values, label=label, linewidth=1.1)
  ax.set_yscale("log")
  ax.set_title("Reconciliación motor — pasos fidelidad vs Freqtrade control")
  ax.legend(fontsize=7)
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  fig.savefig(OUTPUT_PNG, dpi=120)
  plt.close(fig)

  print(json.dumps(out["recommendation"], indent=2))
  print(f"JSON: {OUTPUT_JSON}")
  print(f"PNG:  {OUTPUT_PNG}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
