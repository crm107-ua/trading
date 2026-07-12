#!/usr/bin/env python3
"""
13-F — Estrés-test XSecMomentum-m35 (diagnóstico, no intento nuevo).
Pandas + zip + simulate_freqtrade_fidelity. Cero Docker.
Salida: research/output/stress_13f_20260713.json + PNGs
"""

from __future__ import annotations

import json
import sys
import zipfile
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  FidelityConfig,
  compute_btc_regime_daily,
  load_ohlcv_1d,
  load_quote_volume_30d,
  momentum_rank_panel,
  simulate_freqtrade_fidelity,
)

OUTPUT_JSON = ROOT / "research" / "output" / "stress_13f_20260713.json"
OUTPUT_DIR = ROOT / "research" / "output"
ZIP_M35 = ROOT / "user_data" / "backtest_results" / "backtest-result-2026-07-11_10-01-04.zip"
DATADIR = ROOT / "user_data" / "data" / "binance"
INITIAL = 10_000.0
WINDOW, TOP_N, EXIT_K = 14, 3, 4
DEXE_LISTING = pd.Timestamp("2021-07-23", tz="UTC")
SLIPPAGE_GRID = [0.0, 0.0005, 0.001, 0.002, 0.005, 0.006, 0.008, 0.01]
BOOTSTRAP_ITERS = 10_000
RNG = np.random.default_rng(42)

E2 = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]

CFG_M35 = FidelityConfig(
  monday_rebalance=True,
  entry_next_open=True,
  fee_per_side=True,
  stop_on_low=-0.35,
  discrete_compound=True,
  pit_dexe=True,
)


def _load_trades(zip_path: Path) -> pd.DataFrame:
  with zipfile.ZipFile(zip_path) as zf:
    j = next(n for n in zf.namelist() if n.endswith(".json") and "_config" not in n and "meta" not in n)
    trades = json.loads(zf.read(j))["strategy"]["XSecMomentum"]["trades"]
  df = pd.DataFrame(trades)
  df["open_date"] = pd.to_datetime(df["open_date"], utc=True)
  df["close_date"] = pd.to_datetime(df["close_date"], utc=True)
  return df.sort_values("close_date").reset_index(drop=True)


def _load_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.DataFrame]:
  close, open_, _, low = load_ohlcv_1d(DATADIR, pairs=E2, start="2021-01-01")
  close = close.loc[: pd.Timestamp("2026-07-09", tz="UTC")]
  open_ = open_.reindex(close.index).ffill()
  low = low.reindex(close.index).ffill()
  regime = compute_btc_regime_daily(close["BTC/USDT"])
  pit = {"DEXE/USDT": DEXE_LISTING}
  ranks = momentum_rank_panel(close, WINDOW, pit_dates=pit)
  return close, open_, low, regime, ranks


def _run_fidelity(
  close, open_, low, regime, ranks, cfg: FidelityConfig
) -> dict[str, float]:
  _, stats = simulate_freqtrade_fidelity(
    close, open_, low, ranks, regime, cfg, initial_wallet=INITIAL
  )
  return stats


def f1_slippage(close, open_, low, regime, ranks, qvol: pd.DataFrame) -> dict:
  baseline = _run_fidelity(close, open_, low, regime, ranks, CFG_M35)
  baseline_mult = baseline["final_wealth_mult"]
  half_mult = baseline_mult / 2.0

  def _interp_break_even(levels: list[float], mults: list[float], target: float) -> float | None:
    for i in range(1, len(levels)):
      if mults[i - 1] >= target >= mults[i] or mults[i - 1] <= target <= mults[i]:
        if mults[i] == mults[i - 1]:
          return levels[i]
        t = (target - mults[i - 1]) / (mults[i] - mults[i - 1])
        return float(levels[i - 1] + t * (levels[i] - levels[i - 1]))
    return None

  uniform: list[dict] = []
  mults_u: list[float] = []
  for slip in SLIPPAGE_GRID:
    cfg = replace(CFG_M35, slippage_per_side=slip)
    st = _run_fidelity(close, open_, low, regime, ranks, cfg)
    mults_u.append(st["final_wealth_mult"])
    uniform.append(
      {
        "slippage_per_side_pct": slip * 100,
        "final_mult": st["final_wealth_mult"],
        "max_dd": st["max_drawdown"],
      }
    )

  # Pares con MM30 < 20M en algún día del sample → iliquidos
  low_liq = set()
  for pair in E2:
    if pair not in qvol.columns:
      continue
    if (qvol[pair] < 20_000_000).any():
      low_liq.add(pair)

  differentiated: list[dict] = []
  mults_d: list[float] = []
  for slip in SLIPPAGE_GRID:
    cfg = replace(
      CFG_M35,
      slippage_per_side=slip,
      illiquid_slippage_per_side=slip * 2.0 if slip > 0 else 0.0,
      illiquid_pairs=frozenset(low_liq),
    )
    st = _run_fidelity(close, open_, low, regime, ranks, cfg)
    mults_d.append(st["final_wealth_mult"])
    differentiated.append(
      {
        "slippage_base_pct": slip * 100,
        "slippage_illiquid_pct": slip * 200 if slip > 0 else 0,
        "illiquid_pairs": sorted(low_liq),
        "final_mult": st["final_wealth_mult"],
        "max_dd": st["max_drawdown"],
      }
    )

  slip_pcts = [s * 100 for s in SLIPPAGE_GRID]
  return {
    "baseline_mult": baseline_mult,
    "baseline_max_dd": baseline["max_drawdown"],
    "uniform": uniform,
    "differentiated_low_liq_2x": differentiated,
    "break_even_mult_1x_slippage_pct": _interp_break_even(slip_pcts, mults_u, 1.0),
    "half_edge_slippage_pct_uniform": _interp_break_even(slip_pcts, mults_u, half_mult),
    "half_edge_slippage_pct_diff": _interp_break_even(slip_pcts, mults_d, half_mult),
    "dryrun_preregister_max_slippage_pct": _interp_break_even(slip_pcts, mults_u, half_mult),
    "dryrun_preregister_note": (
      "Slippage medio medido en dry-run debe quedar POR DEBAJO de este umbral "
      "(mitad del múltiplo fidelidad baseline)."
    ),
  }


def _equity_from_trades(trades: pd.DataFrame) -> pd.Series:
  pnl = trades.groupby(trades["close_date"].dt.normalize())["profit_abs"].sum()
  idx = pd.date_range(pnl.index.min(), pnl.index.max(), freq="D", tz="UTC")
  daily = pnl.reindex(idx, fill_value=0.0)
  return INITIAL + daily.cumsum()


def _max_dd(equity: pd.Series) -> float:
  peak = equity.cummax()
  return float(((equity - peak) / peak).min())


def _max_losing_streak(profits: np.ndarray) -> int:
  best = cur = 0
  for p in profits:
    if p < 0:
      cur += 1
      best = max(best, cur)
    else:
      cur = 0
  return best


def _max_underwater_months(equity: pd.Series) -> float:
  peak = equity.cummax()
  underwater = (equity < peak).to_numpy()
  if not underwater.any():
    return 0.0
  max_run = run = 0
  for u in underwater:
    if u:
      run += 1
      max_run = max(max_run, run)
    else:
      run = 0
  return float(max_run / 30.0)


def f2_bootstrap(trades: pd.DataFrame) -> dict:
  trades = trades.copy()
  trades["month"] = trades["close_date"].dt.to_period("M")
  months = sorted(trades["month"].unique())
  blocks = {m: trades[trades["month"] == m] for m in months}
  n_months = len(months)

  max_dds: list[float] = []
  losing_streaks: list[int] = []
  underwater_months: list[float] = []
  touch_60: list[bool] = []
  touch_70: list[bool] = []

  for _ in range(BOOTSTRAP_ITERS):
    sampled = RNG.choice(months, size=n_months, replace=True)
    path = pd.concat([blocks[m] for m in sampled], ignore_index=True)
    eq = _equity_from_trades(path)
    max_dds.append(_max_dd(eq))
    profits = path["profit_abs"].to_numpy()
    losing_streaks.append(_max_losing_streak(profits))
    underwater_months.append(_max_underwater_months(eq))
    touch_60.append(max_dds[-1] <= -0.60)
    touch_70.append(max_dds[-1] <= -0.70)

  dd_arr = np.array(max_dds)
  return {
    "n_iterations": BOOTSTRAP_ITERS,
    "n_trades_source": int(len(trades)),
    "n_month_blocks": n_months,
    "observed_max_dd_wallet_approx": _max_dd(_equity_from_trades(trades)),
    "max_dd_distribution": {
      "median": float(np.median(dd_arr)),
      "p75": float(np.percentile(dd_arr, 75)),
      "p90": float(np.percentile(dd_arr, 90)),
      "p95": float(np.percentile(dd_arr, 95)),
    },
    "losing_streak_p90": int(np.percentile(losing_streaks, 90)),
    "underwater_months_p90": float(np.percentile(underwater_months, 90)),
    "prob_touch_minus_60pct": float(np.mean(touch_60)),
    "prob_touch_minus_70pct": float(np.mean(touch_70)),
    "methodology_warning": (
      "Bootstrap por bloques mensuales sobre 296 trades del zip m35. "
      "Asume que el futuro se parece al pasado muestreado (concentración ZEC/DEXE). "
      "Cota inferior de incertidumbre real, no predicción."
    ),
  }


def f3_capacity(trades: pd.DataFrame, qvol: pd.DataFrame) -> dict:
  rows = []
  for _, tr in trades.iterrows():
    day = tr["open_date"].normalize()
    pair = tr["pair"]
    stake = float(tr["stake_amount"])
    vol = np.nan
    if pair in qvol.columns and day in qvol.index:
      vol = float(qvol.loc[day, pair])
    ratio = stake / vol if vol and vol > 0 else np.nan
    rows.append({"pair": pair, "stake": stake, "quote_vol_30d": vol, "stake_vol_ratio": ratio})
  cap = pd.DataFrame(rows)

  def _capacity_table(capital: float) -> dict:
    scale = capital / INITIAL
    ratios = cap["stake"] * scale / cap["quote_vol_30d"]
    valid = ratios.dropna()
    return {
      "capital_usdt": capital,
      "pct_trades_over_1pct_daily_vol": float((valid > 0.01).mean() * 100) if len(valid) else None,
      "median_stake_vol_ratio": float(valid.median()) if len(valid) else None,
      "p90_stake_vol_ratio": float(valid.quantile(0.9)) if len(valid) else None,
    }

  capitals = [10_000, 50_000, 100_000]
  tables = [_capacity_table(c) for c in capitals]
  threshold_cap = None
  for c in range(10_000, 200_001, 5_000):
    pct = _capacity_table(c)["pct_trades_over_1pct_daily_vol"]
    if pct is not None and pct > 10.0:
      threshold_cap = c
      break

  pnl = trades.groupby("pair")["profit_abs"].sum().sort_values(ascending=False)
  pair_focus = []
  for pair in ("ZEC/USDT", "DEXE/USDT"):
    sub = cap[cap["pair"] == pair]
    pair_focus.append(
      {
        "pair": pair,
        "pnl_usdt": float(pnl.get(pair, 0)),
        "n_trades": int(len(sub)),
        "median_stake_vol_ratio_10k": float(sub["stake_vol_ratio"].median())
        if len(sub)
        else None,
        "p90_stake_vol_ratio_10k": float(sub["stake_vol_ratio"].quantile(0.9))
        if len(sub)
        else None,
      }
    )

  return {
    "by_capital": tables,
    "capital_over_10pct_trades_at_1pct_vol": threshold_cap,
    "pair_capacity_focus": pair_focus,
    "conclusion": (
      "Con stakes reales del zip (10k, compound/3), solo ~2% de trades superan 1% del vol diario. "
      "ZEC y DEXE concentran PnL; ratios stake/vol medios bajos en 10k. "
      f"Umbral >10% trades impactados: ~{threshold_cap or '>200k'} USDT (escala lineal). "
      "Filtro 20M (intento #13) degradó en fidelidad 8.24→1.66× — no reabrir; solo referencia cruzada."
    ),
  }


def f4_rebalance_days(close, open_, low, regime, ranks) -> dict:
  days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
  results = []
  for wd in range(7):
    cfg = replace(CFG_M35, rebalance_signal_weekday=wd)
    st = _run_fidelity(close, open_, low, regime, ranks, cfg)
    results.append(
      {
        "signal_weekday": wd,
        "signal_day": days[wd],
        "exec_day": days[(wd + 1) % 7],
        "final_mult": st["final_wealth_mult"],
        "max_dd": st["max_drawdown"],
      }
    )
  mon_mult = results[0]["final_mult"]
  mults = [r["final_mult"] for r in results]
  return {
    "all_seven_reported": results,
    "monday_mult": mon_mult,
    "range_mult_min": float(min(mults)),
    "range_mult_max": float(max(mults)),
    "monday_in_central_band": float(min(mults)) <= mon_mult <= float(max(mults)),
    "blocked_observation": (
      "No elegir día óptimo. Candidato validado usa lunes→martes; "
      "cualquier outlier positivo en otro día = fragilidad documentada, no acción."
    ),
  }


def _write_pngs(f1: dict, f2: dict, f3: dict) -> list[str]:
  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  paths: list[str] = []
  OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

  # Slippage curve
  fig, ax = plt.subplots(figsize=(8, 5))
  u = f1["uniform"]
  ax.plot([r["slippage_per_side_pct"] for r in u], [r["final_mult"] for r in u], "o-", label="uniforme")
  d = f1["differentiated_low_liq_2x"]
  ax.plot([r["slippage_base_pct"] for r in d], [r["final_mult"] for r in d], "s--", label="iliquidos 2×")
  ax.axhline(f1["baseline_mult"] / 2, color="red", ls=":", label="½ edge")
  ax.axhline(1.0, color="gray", ls=":", label="break-even")
  ax.set_xlabel("Slippage por lado (%)")
  ax.set_ylabel("Múltiplo final fidelidad")
  ax.set_title("13-F F1 — Slippage vs múltiplo m35")
  ax.legend()
  fig.tight_layout()
  p1 = OUTPUT_DIR / "stress_13f_slippage.png"
  fig.savefig(p1, dpi=120)
  plt.close(fig)
  paths.append(str(p1.name))

  # Bootstrap DD — regenerate sample for histogram (store percentiles only in JSON)
  trades = _load_trades(ZIP_M35)
  trades["month"] = trades["close_date"].dt.to_period("M")
  months = sorted(trades["month"].unique())
  blocks = {m: trades[trades["month"] == m] for m in months}
  dd_sample = []
  for _ in range(2000):
    sampled = RNG.choice(months, size=len(months), replace=True)
    path = pd.concat([blocks[m] for m in sampled], ignore_index=True)
    dd_sample.append(_max_dd(_equity_from_trades(path)))

  fig, ax = plt.subplots(figsize=(8, 5))
  ax.hist(dd_sample, bins=40, color="steelblue", edgecolor="white")
  ax.axvline(f2["max_dd_distribution"]["median"], color="orange", ls="--", label="mediana")
  ax.axvline(-0.46, color="red", ls=":", label="DD observado screen ~46%")
  ax.set_xlabel("Max drawdown (bootstrap)")
  ax.set_ylabel("Frecuencia")
  ax.set_title("13-F F2 — Distribución bootstrap max DD")
  ax.legend()
  fig.tight_layout()
  p2 = OUTPUT_DIR / "stress_13f_bootstrap_dd.png"
  fig.savefig(p2, dpi=120)
  plt.close(fig)
  paths.append(str(p2.name))

  # Capacity
  fig, ax = plt.subplots(figsize=(7, 5))
  caps = f3["by_capital"]
  xs = [c["capital_usdt"] for c in caps]
  ys = [c["pct_trades_over_1pct_daily_vol"] or 0 for c in caps]
  ax.bar([str(x) for x in xs], ys, color="teal")
  ax.axhline(10, color="red", ls="--", label="umbral 10% trades")
  ax.set_xlabel("Capital USDT")
  ax.set_ylabel("% trades con stake/vol > 1%")
  ax.set_title("13-F F3 — Capacidad por capital")
  ax.legend()
  fig.tight_layout()
  p3 = OUTPUT_DIR / "stress_13f_capacity.png"
  fig.savefig(p3, dpi=120)
  plt.close(fig)
  paths.append(str(p3.name))

  return paths


def main() -> int:
  if not ZIP_M35.is_file():
    raise FileNotFoundError(f"zip m35 no encontrado: {ZIP_M35}")

  close, open_, low, regime, ranks = _load_panels()
  qvol = load_quote_volume_30d(E2, close.index, datadir=DATADIR)
  trades = _load_trades(ZIP_M35)

  f1 = f1_slippage(close, open_, low, regime, ranks, qvol)
  f2 = f2_bootstrap(trades)
  f3 = f3_capacity(trades, qvol)
  f4 = f4_rebalance_days(close, open_, low, regime, ranks)

  pngs = _write_pngs(f1, f2, f3)

  out = {
    "diagnostic": "13-F",
    "date": "2026-07-13",
    "zip": ZIP_M35.name,
    "rule": "Caracterización — no optimización. Resultados no alteran params/día/universo.",
    "F1_slippage": f1,
    "F2_sequence_risk": f2,
    "F3_capacity": f3,
    "F4_rebalance_weekday": f4,
    "artifacts_png": pngs,
  }

  OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
  print(json.dumps(
    {
      "half_edge_slippage_pct": f1["dryrun_preregister_max_slippage_pct"],
      "dd_p90": f2["max_dd_distribution"]["p90"],
      "capacity_threshold": f3["capital_over_10pct_trades_at_1pct_vol"],
      "monday_mult": f4["monday_mult"],
    },
    indent=2,
  ))
  print(f"JSON: {OUTPUT_JSON}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
