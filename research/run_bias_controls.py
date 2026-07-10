#!/usr/bin/env python3
"""Controles de sesgo E1/E2 — supervivencia PIT y concentración top-1."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  DEFAULT_DATADIR,
  dominant_pair_full_sample,
  load_closes_1d,
  pair_listing_dates,
  run_bias_control,
)

OUTPUT = ROOT / "research" / "output"
FEE = 0.001
NARROW = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "XRP/USDT"]


def _wide_pairs(min_rows: int = 1000) -> list[str]:
  from xsec_lab import list_available_1d_pairs
  import pandas as pd

  info = list_available_1d_pairs()
  pairs = [x["pair"] for x in info if x["rows"] >= min_rows and x["pair"].endswith("/USDT")]
  ok = []
  for x in info:
    if x["pair"] not in pairs:
      continue
    if pd.Timestamp(x["start"], tz="UTC") <= pd.Timestamp("2022-01-01", tz="UTC"):
      ok.append(x["pair"])
  return sorted(set(ok))


def _suite(name: str, prices, listing, *, window: int, top_n: int, freq: str) -> dict:
  modes = ("baseline", "pit", "exclude_dominant")
  rows = []
  for mode in modes:
    r = run_bias_control(
      prices,
      window=window,
      top_n=top_n,
      freq=freq,
      fee=FEE,
      listing_dates=listing,
      label=f"{name}_{mode}",
      mode=mode,
    )
    rows.append(asdict(r))
  dom = dominant_pair_full_sample(prices, window)
  baseline = next(x for x in rows if x["label"].endswith("_baseline"))
  pit = next(x for x in rows if x["label"].endswith("_pit"))
  excl = next(x for x in rows if x["label"].endswith("_exclude_dominant"))
  return {
    "name": name,
    "window": window,
    "top_n": top_n,
    "freq": freq,
    "dominant_pair_full_sample": dom,
    "results": rows,
    "pit_wealth_ratio_vs_baseline": pit["final_wealth"] / baseline["final_wealth"]
    if baseline["final_wealth"]
    else None,
    "exclude_dominant_wealth_ratio": excl["final_wealth"] / baseline["final_wealth"]
    if baseline["final_wealth"]
    else None,
    "baseline_max_dd": baseline["max_drawdown"],
  }


def main() -> int:
  OUTPUT.mkdir(parents=True, exist_ok=True)
  listing = pair_listing_dates(DEFAULT_DATADIR)

  e1_prices = load_closes_1d(pairs=NARROW, start="2021-01-01")
  e2_pairs = _wide_pairs()
  e2_prices = load_closes_1d(pairs=e2_pairs, start="2021-01-01")
  e2_prices = e2_prices.dropna(thresh=int(len(e2_prices.columns) * 0.5))

  report = {
    "e1_top1_w14_W": _suite("e1", e1_prices, listing, window=14, top_n=1, freq="W"),
    "e2_top3_w14_W": _suite("e2", e2_prices, listing, window=14, top_n=3, freq="W"),
    "e1_top1_max_dd_note": "top-1 concentra varianza — comparar max_drawdown con E2 top-3",
  }

  out = OUTPUT / "bias_controls_20260710.json"
  out.write_text(json.dumps(report, indent=2), encoding="utf-8")
  print(json.dumps({k: v.get("results", v) if isinstance(v, dict) else v for k, v in report.items()}, indent=2, default=str))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
