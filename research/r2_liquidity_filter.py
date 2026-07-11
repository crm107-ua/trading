#!/usr/bin/env python3
"""
R2 — Momentum con filtro de liquidez (intento #13, pre-registrado).

Hipótesis: el edge E2 no depende de la cola ilíquida.
Test: top-3 w14 W sobre universo E2 filtrado por volumen medio 30d (quote, USDT)
con 3 umbrales FIJADOS ANTES de calcular: 5M / 20M / 50M USDT/día. Los tres se
reportan; no se elige el umbral a posteriori.
Criterio: en el umbral 20M, versión B bate a equal-weight del universo filtrado
y a BTC B&H en AMBAS mitades (2021-23 / 2024-26).

Filtro point-in-time: elegibilidad en cada rebalanceo según volumen 30d hasta t-1.

Salidas: research/output/r2_liquidity_filter.json + r2_liquidity_filter.png
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  compute_metrics,
  load_closes_1d,
  portfolio_return,
  weights_btc_only,
  weights_top_n_momentum,
)

DATADIR = ROOT / "research" / "data_local" / "binance"
OUTPUT_JSON = ROOT / "research" / "output" / "r2_liquidity_filter.json"
OUTPUT_PNG = ROOT / "research" / "output" / "r2_liquidity_filter.png"

WINDOW = 14
TOP_N = 3
FEE = 0.001
FREQ = "W"
THRESHOLDS = (5_000_000, 20_000_000, 50_000_000)  # fijados antes de calcular
DECISIVE = 20_000_000

E2_PAIRS = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]

HALVES = {
  "2021-23": ("2021-01-01", "2023-12-31"),
  "2024-26": ("2024-01-01", "2026-12-31"),
}


def load_quote_volume_30d(pairs: list[str], index: pd.DatetimeIndex) -> pd.DataFrame:
  """Media móvil 30d del volumen quote (USDT) por par, desplazada 1 día (causal)."""
  frames: dict[str, pd.Series] = {}
  for pair in pairs:
    path = DATADIR / f"{pair.replace('/', '_')}-1d.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    idx = pd.to_datetime(df["date"], utc=True)
    qv = (df["volume"].astype(float) * df["close"].astype(float))
    qv.index = idx
    frames[pair] = qv.sort_index()
  qvol = pd.DataFrame(frames).sort_index()
  return qvol.rolling(30, min_periods=20).mean().shift(1).reindex(index)


def _make_masked_momentum(eligible: pd.DataFrame, stats: list[int] | None = None):
  def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    hist = eligible.loc[:t]
    if hist.empty:
      return pd.Series(0.0, index=p.columns)
    last = hist.iloc[-1]
    cols = [c for c in p.columns if c in last.index and bool(last[c])]
    if stats is not None:
      stats.append(len(cols))
    if not cols:
      return pd.Series(0.0, index=p.columns)
    w_sub = weights_top_n_momentum(p[cols], t, window=WINDOW, top_n=TOP_N)
    w = pd.Series(0.0, index=p.columns)
    w.loc[w_sub.index] = w_sub
    return w

  return fn


def _make_masked_equal(eligible: pd.DataFrame):
  def fn(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    hist = eligible.loc[:t]
    if hist.empty:
      return pd.Series(0.0, index=p.columns)
    last = hist.iloc[-1]
    cols = [c for c in p.columns if c in last.index and bool(last[c]) and p.loc[:t, c].notna().any()]
    w = pd.Series(0.0, index=p.columns)
    if cols:
      w.loc[cols] = 1.0 / len(cols)
    return w

  return fn


def _metrics(prices: pd.DataFrame, fn, fee: float) -> dict:
  rets, turnover = portfolio_return(prices, fn, FREQ, fee_per_rotation=fee)
  return asdict(compute_metrics(rets, turnover=turnover))


def _scope_slices(prices: pd.DataFrame):
  yield "full", prices
  for half, (a, b) in HALVES.items():
    yield half, prices.loc[slice(pd.Timestamp(a, tz="UTC"), pd.Timestamp(b, tz="UTC"))]


def main() -> int:
  prices = load_closes_1d(DATADIR, pairs=E2_PAIRS, start="2021-01-01")
  vol30 = load_quote_volume_30d(E2_PAIRS, prices.index)

  results: dict = {
    "params": {
      "window": WINDOW,
      "top_n": TOP_N,
      "fee_B": FEE,
      "freq": FREQ,
      "thresholds_usdt_fixed": list(THRESHOLDS),
      "decisive_threshold": DECISIVE,
    },
    "criterion": "en 20M: momentum B > EW-filtrado B y > BTC B&H B en AMBAS mitades",
    "thresholds": {},
  }

  curves: dict[str, pd.Series] = {}

  for thr in THRESHOLDS:
    eligible = vol30 > thr
    stats: list[int] = []
    fn_mom = _make_masked_momentum(eligible, stats)
    fn_ew = _make_masked_equal(eligible)

    thr_out: dict = {
      "avg_eligible_pairs_per_rebalance": None,
      "min_eligible_pairs": None,
    }
    for scope, pr in _scope_slices(prices):
      stats.clear()
      thr_out[scope] = {
        "momentum_A": _metrics(pr, fn_mom, 0.0),
        "momentum_B": _metrics(pr, fn_mom, FEE),
        "equal_weight_filtered_B": _metrics(pr, fn_ew, FEE),
        "btc_bh_B": _metrics(pr, weights_btc_only, FEE),
        "avg_eligible": float(np.mean(stats)) if stats else 0.0,
        "min_eligible": int(min(stats)) if stats else 0,
      }
    thr_out["avg_eligible_pairs_per_rebalance"] = thr_out["full"]["avg_eligible"]
    thr_out["min_eligible_pairs"] = thr_out["full"]["min_eligible"]
    results["thresholds"][f"{thr // 1_000_000}M"] = thr_out

    rets, _ = portfolio_return(prices, fn_mom, FREQ, fee_per_rotation=FEE)
    curves[f"vol>{thr // 1_000_000}M (B)"] = np.exp(rets.cumsum())

  # Evaluación del criterio pre-fijado en 20M
  t20 = results["thresholds"]["20M"]
  crit = {}
  for half in HALVES:
    crit[half] = {
      "momentum_B_wealth": t20[half]["momentum_B"]["final_wealth"],
      "ew_filtered_B_wealth": t20[half]["equal_weight_filtered_B"]["final_wealth"],
      "btc_B_wealth": t20[half]["btc_bh_B"]["final_wealth"],
      "beats_ew": bool(
        t20[half]["momentum_B"]["final_wealth"] > t20[half]["equal_weight_filtered_B"]["final_wealth"]
      ),
      "beats_btc": bool(
        t20[half]["momentum_B"]["final_wealth"] > t20[half]["btc_bh_B"]["final_wealth"]
      ),
    }
  crit["passes"] = bool(
    all(crit[h]["beats_ew"] and crit[h]["beats_btc"] for h in HALVES)
  )
  results["criterion_eval_20M"] = crit

  # Curva sin filtro como referencia
  def fn_free(p, t):
    return weights_top_n_momentum(p, t, window=WINDOW, top_n=TOP_N)

  rets_free, _ = portfolio_return(prices, fn_free, FREQ, fee_per_rotation=FEE)
  curves["sin filtro (B)"] = np.exp(rets_free.cumsum())

  OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT_JSON.write_text(json.dumps(results, indent=2), encoding="utf-8")

  import matplotlib

  matplotlib.use("Agg")
  import matplotlib.pyplot as plt

  fig, ax = plt.subplots(figsize=(11, 5))
  for label, wealth in curves.items():
    ax.plot(wealth.index, wealth.values, label=label, linewidth=1.2)
  ax.set_yscale("log")
  ax.set_ylabel("wealth (log)")
  ax.set_title("R2/#13 — top-3 momentum con filtro de volumen 30d (umbrales fijos)")
  ax.legend()
  ax.grid(True, alpha=0.3)
  fig.tight_layout()
  fig.savefig(OUTPUT_PNG, dpi=120)
  plt.close(fig)

  print(f"JSON: {OUTPUT_JSON}")
  print(f"PNG:  {OUTPUT_PNG}")
  for thr in THRESHOLDS:
    key = f"{thr // 1_000_000}M"
    t = results["thresholds"][key]
    print(
      f"{key}: full B={t['full']['momentum_B']['final_wealth']:.2f}x "
      f"(elegibles medio {t['avg_eligible_pairs_per_rebalance']:.1f}, min {t['min_eligible_pairs']}) | "
      f"21-23 B={t['2021-23']['momentum_B']['final_wealth']:.2f} vs EW {t['2021-23']['equal_weight_filtered_B']['final_wealth']:.2f} | "
      f"24-26 B={t['2024-26']['momentum_B']['final_wealth']:.2f} vs EW {t['2024-26']['equal_weight_filtered_B']['final_wealth']:.2f}"
    )
  print(f"Criterio 20M -> {'PASA' if crit['passes'] else 'FALLA'}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
