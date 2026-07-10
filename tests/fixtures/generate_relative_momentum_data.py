"""
Genera fixtures OHLCV para RelativeMomentum (5 pares, 1h/4h/1d).

Liderazgo diseñado:
  - 2024-01-10 → 2024-02-01: ETH fuerte
  - 2024-02-02 → 2024-02-20: BTC fuerte
  - 2024-02-21 → 2024-03-15: SOL fuerte

Ejecutar: python tests/fixtures/generate_relative_momentum_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent / "data_relative_momentum" / "binance"
PAIRS = ["BTC_USDT", "ETH_USDT", "BNB_USDT", "SOL_USDT", "XRP_USDT"]
BASE = {
  "BTC_USDT": 42_000.0,
  "ETH_USDT": 2_200.0,
  "BNB_USDT": 320.0,
  "SOL_USDT": 95.0,
  "XRP_USDT": 0.55,
}
RNG = np.random.default_rng(7)
START = "2023-06-01"


def _ohlcv(n: int, freq: str, base: float) -> pd.DataFrame:
  dates = pd.date_range(START, periods=n, freq=freq, tz="UTC")
  ret = RNG.normal(0, 0.0008, n)
  close = base * np.cumprod(1 + ret)
  open_ = np.roll(close, 1)
  open_[0] = base
  high = np.maximum(open_, close) * (1 + RNG.uniform(0.0003, 0.002, n))
  low = np.minimum(open_, close) * (1 - RNG.uniform(0.0003, 0.002, n))
  vol = RNG.uniform(500, 1500, n)
  return pd.DataFrame(
    {"date": dates, "open": open_, "high": high, "low": low, "close": close, "volume": vol}
  )


def _apply_leader_drift(df: pd.DataFrame, mult: float, start: str, end: str) -> pd.DataFrame:
  out = df.copy()
  mask = (out["date"] >= pd.Timestamp(start, tz="UTC")) & (
    out["date"] <= pd.Timestamp(end, tz="UTC")
  )
  idx = np.where(mask.to_numpy())[0]
  if len(idx) == 0:
    return out
  anchor = float(out.loc[idx[0] - 1, "close"]) if idx[0] > 0 else float(out.loc[0, "close"])
  for j, i in enumerate(idx):
    c = anchor * (1 + mult * (j + 1))
    out.loc[i, "close"] = c
    out.loc[i, "open"] = anchor * (1 + mult * j) if j else out.loc[i, "open"]
    out.loc[i, "high"] = max(out.loc[i, "open"], c) * 1.002
    out.loc[i, "low"] = min(out.loc[i, "open"], c) * 0.998
  tail = idx[-1] + 1
  if tail < len(out):
    scale = float(out.loc[idx[-1], "close"]) / float(out.loc[tail, "close"])
    out.loc[tail:, ["open", "high", "low", "close"]] *= scale
  return out


def _inject_bull_btc_4h(df: pd.DataFrame) -> pd.DataFrame:
  return _apply_leader_drift(df, mult=0.004, start="2024-01-10", end="2024-03-18")


def main() -> None:
  OUT_DIR.mkdir(parents=True, exist_ok=True)
  counts = {"1h": 7500, "4h": 1900, "1d": 400}
  leaders = {
    "ETH_USDT": ("2024-01-10", "2024-02-01", 0.012),
    "BTC_USDT": ("2024-02-02", "2024-02-20", 0.010),
    "SOL_USDT": ("2024-02-21", "2024-03-15", 0.014),
  }
  for pair in PAIRS:
    for tf, n in counts.items():
      freq = "D" if tf == "1d" else tf
      frame = _ohlcv(n, freq, BASE[pair])
      if pair in leaders:
        s, e, m = leaders[pair]
        frame = _apply_leader_drift(frame, mult=m, start=s, end=e)
      if pair == "BTC_USDT" and tf == "4h":
        frame = _inject_bull_btc_4h(frame)
      path = OUT_DIR / f"{pair}-{tf}.feather"
      frame.to_feather(path)
      print(f"wrote {path}")


if __name__ == "__main__":
  main()
