#!/usr/bin/env python3
"""Ejecuta E1–E4 y escribe artefactos en research/output/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  DEFAULT_DATADIR,
  compute_btc_regime_daily,
  event_study_extremes,
  list_available_1d_pairs,
  load_closes_1d,
  portfolio_return,
  run_benchmarks,
  run_strategy_grid,
  save_equity_curve,
  weekday_seasonality,
  weights_btc_only,
  weights_equal,
  weights_top_n_momentum,
)

OUTPUT = ROOT / "research" / "output"
FEE = 0.001
NARROW = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]
WINDOWS = [7, 14, 30]
TOP_NS_E1 = [1, 2]
TOP_NS_E2 = [3, 5]
FREQS = ["W", "M"]


def _best_row(grid: pd.DataFrame, bench_b: pd.DataFrame) -> dict:
  ew = bench_b[(bench_b["strategy"] == "equal_weight") & (bench_b["freq"] == "M")]
  ew_final = float(ew["final_b"].max()) if not ew.empty else 1.0
  btc = bench_b[(bench_b["strategy"] == "btc_buy_hold") & (bench_b["freq"] == "M")]
  btc_final = float(btc["final_b"].max()) if not btc.empty else 1.0
  grid = grid.copy()
  grid["beats_ew"] = grid["final_b"] > ew_final
  grid["beats_btc"] = grid["final_b"] > btc_final
  best = grid.sort_values("final_b", ascending=False).iloc[0].to_dict()
  best["ew_final_b"] = ew_final
  best["btc_final_b"] = btc_final
  return best


def run_e1() -> dict:
  prices = load_closes_1d(pairs=NARROW, start="2021-01-01")
  grid = run_strategy_grid(prices, windows=WINDOWS, top_ns=TOP_NS_E1, freqs=FREQS, fee=FEE)
  bench = run_benchmarks(prices, freqs=FREQS, fee=FEE)
  best = _best_row(grid, bench)
  any_beats_ew = bool(grid["final_b"].max() > bench[bench["strategy"] == "equal_weight"]["final_b"].max())
  verdict = "VIVA (implementación)" if any_beats_ew else "MUERTA en universo 5 pares"
  # Equity chart best vs benchmarks
  if any_beats_ew:
    row = grid.sort_values("final_b", ascending=False).iloc[0]
    fn = lambda p, t, w=int(row["window"]), n=int(row["top_n"]): weights_top_n_momentum(p, t, window=w, top_n=n)
    rets, _ = portfolio_return(prices, fn, row["freq"], fee_per_rotation=FEE)
    save_equity_curve(rets, OUTPUT / "e1_best_momentum_b.png", title=f"E1 best top-{int(row['top_n'])} w{int(row['window'])} {row['freq']}")
  rets_ew, _ = portfolio_return(prices, weights_equal, "M", fee_per_rotation=FEE)
  save_equity_curve(rets_ew, OUTPUT / "e1_equal_weight_b.png", title="E1 equal-weight (B)")
  rets_btc, _ = portfolio_return(prices, weights_btc_only, "M", fee_per_rotation=0.0)
  save_equity_curve(rets_btc, OUTPUT / "e1_btc_bh.png", title="E1 BTC B&H")
  return {
    "verdict": verdict,
    "any_beats_ew_b": any_beats_ew,
    "best": best,
    "grid": grid.to_dict(orient="records"),
    "benchmarks": bench.to_dict(orient="records"),
  }


def _wide_pairs(min_rows: int = 1000) -> list[str]:
  info = list_available_1d_pairs()
  pairs = [x["pair"] for x in info if x["rows"] >= min_rows and x["pair"].endswith("/USDT")]
  # excluir si empieza después de 2022
  ok = []
  for x in info:
    if x["pair"] not in pairs:
      continue
    if pd.Timestamp(x["start"], tz="UTC") <= pd.Timestamp("2022-01-01", tz="UTC"):
      ok.append(x["pair"])
  return sorted(set(ok))


def run_e2() -> dict:
  pairs = _wide_pairs()
  if len(pairs) < 10:
    return {"error": f"universo insuficiente ({len(pairs)} pares); ejecutar research/download_wide_1d.py"}
  prices = load_closes_1d(pairs=pairs, start="2021-01-01")
  prices = prices.dropna(thresh=int(len(prices.columns) * 0.5))
  grid = run_strategy_grid(prices, windows=WINDOWS, top_ns=TOP_NS_E2, freqs=FREQS, fee=FEE)
  bench = run_benchmarks(prices, freqs=FREQS, fee=FEE)
  best = _best_row(grid, bench)
  ew_max = float(bench[bench["strategy"] == "equal_weight"]["final_b"].max())
  btc_max = float(bench[bench["strategy"] == "btc_buy_hold"]["final_b"].max())
  interesting = bool(best["final_b"] > ew_max and best["final_b"] > btc_max)
  verdict = "INTERESANTE" if interesting else "NO pasa criterio B vs EW y BTC"
  row = grid.sort_values("final_b", ascending=False).iloc[0]
  fn = lambda p, t, w=int(row["window"]), n=int(row["top_n"]): weights_top_n_momentum(p, t, window=w, top_n=n)
  rets, _ = portfolio_return(prices, fn, row["freq"], fee_per_rotation=FEE)
  save_equity_curve(rets, OUTPUT / "e2_best_momentum_b.png", title=f"E2 best (n={len(pairs)} pairs)")
  rets_ew, _ = portfolio_return(prices, weights_equal, "M", fee_per_rotation=FEE)
  save_equity_curve(rets_ew, OUTPUT / "e2_equal_weight_b.png", title="E2 EW")
  return {
    "n_pairs": len(pairs),
    "pairs": pairs,
    "verdict": verdict,
    "interesting": interesting,
    "best": best,
    "ew_max_b": ew_max,
    "btc_max_b": btc_max,
    "grid_top5": grid.sort_values("final_b", ascending=False).head(5).to_dict(orient="records"),
  }


def run_e3(prices: pd.DataFrame) -> dict:
  btc = prices["BTC/USDT"] if "BTC/USDT" in prices.columns else prices.iloc[:, 0]
  regime = compute_btc_regime_daily(btc)
  events = event_study_extremes(prices, regime)
  if events.empty:
    return {"verdict": "SIN DATOS", "events": []}
  sig = events[events["tstat"].abs() > 2]
  both_halves = (
    sig.groupby(["pair", "side", "horizon"])
    .filter(lambda g: set(g["half"]) >= {"2021-23", "2024-26"} and (g["tstat"].abs() > 2).all())
  )
  verdict = "EFECTO (ambas mitades)" if not both_halves.empty else "NO pasa t-stat>2 en ambas mitades"
  return {
    "verdict": verdict,
    "n_significant_rows": len(sig),
    "n_stable_both_halves": len(both_halves),
    "top_effects": sig.sort_values("tstat", key=abs, ascending=False).head(10).to_dict(orient="records"),
  }


def run_e4(prices: pd.DataFrame) -> dict:
  wd = weekday_seasonality(prices)
  if wd.empty:
    return {"verdict": "SIN DATOS"}
  sig = wd[wd["tstat"].abs() > 2]
  stable = (
    sig.groupby(["pair", "weekday"])
    .filter(lambda g: set(g["half"]) >= {"2021-23", "2024-26"} and (g["tstat"].abs() > 2).all())
  )
  verdict = "EFECTO estable" if not stable.empty else "NO pasa en ambas mitades"
  return {
    "verdict": verdict,
    "n_significant": len(sig),
    "n_stable": len(stable),
    "top": sig.sort_values("tstat", key=abs, ascending=False).head(10).to_dict(orient="records"),
  }


def main() -> int:
  OUTPUT.mkdir(parents=True, exist_ok=True)
  results = {"e1": run_e1()}
  results["e2"] = run_e2()
  wide_pairs = _wide_pairs()
  if len(wide_pairs) >= 10:
    prices_wide = load_closes_1d(pairs=wide_pairs, start="2021-01-01")
    prices_wide = prices_wide.dropna(thresh=int(len(prices_wide.columns) * 0.5))
    results["e3"] = run_e3(prices_wide)
    results["e4"] = run_e4(prices_wide)
  else:
    results["e3"] = {"skipped": "universo ancho insuficiente"}
    results["e4"] = {"skipped": "universo ancho insuficiente"}
  out_json = OUTPUT / "experiments_20260710.json"
  out_json.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
  print(json.dumps({k: v.get("verdict", v) for k, v in results.items()}, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
