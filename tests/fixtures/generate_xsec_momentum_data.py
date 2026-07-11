"""
Genera fixtures OHLCV 1d para XSecMomentum (5 pares + BTC 4h).

Diseño:
  - Liderazgo rotante (ETH → BTC → SOL) en rebalanceos semanales
  - Tramo BEAR sintético en BTC 4h (2024-03-01 → 2024-03-31)

Ejecutar: python tests/fixtures/generate_xsec_momentum_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).resolve().parent / "data_xsec_momentum" / "binance"
PAIRS = ["BTC_USDT", "ETH_USDT", "BNB_USDT", "SOL_USDT", "XRP_USDT"]
BASE = {
  "BTC_USDT": 42_000.0,
  "ETH_USDT": 2_200.0,
  "BNB_USDT": 320.0,
  "SOL_USDT": 95.0,
  "XRP_USDT": 0.55,
}
RNG = np.random.default_rng(10)
START = "2023-06-01"


def _ohlcv(n: int, freq: str, base: float) -> pd.DataFrame:
  dates = pd.date_range(START, periods=n, freq=freq, tz="UTC")
  ret = RNG.normal(0, 0.0005, n)
  close = base * np.cumprod(1 + ret)
  open_ = np.roll(close, 1)
  open_[0] = base
  high = np.maximum(open_, close) * (1 + RNG.uniform(0.0002, 0.001, n))
  low = np.minimum(open_, close) * (1 - RNG.uniform(0.0002, 0.001, n))
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


def _inject_bear_btc_4h(df: pd.DataFrame) -> pd.DataFrame:
  return _apply_leader_drift(df, mult=-0.006, start="2024-03-01", end="2024-03-31")


def main() -> None:
  OUT_DIR.mkdir(parents=True, exist_ok=True)
  leaders = {
    "ETH_USDT": ("2024-01-08", "2024-02-05", 0.015),
    "BTC_USDT": ("2024-02-12", "2024-03-04", 0.012),
    "SOL_USDT": ("2024-03-11", "2024-04-08", 0.018),
  }
  for pair in PAIRS:
    frame = _ohlcv(400, "D", BASE[pair])
    if pair in leaders:
      s, e, m = leaders[pair]
      frame = _apply_leader_drift(frame, mult=m, start=s, end=e)
    if pair == "BNB_USDT":
      # Cruza umbral 20M USDT/día a mitad del periodo (liquidez fixture XSecMomentum20M)
      frame.loc[:120, "volume"] = 100.0  # quote ~32k
      frame.loc[121:, "volume"] = 80_000.0  # quote ~25M @ ~320
      frame = _apply_leader_drift(frame, mult=0.018, start="2024-02-12", end="2024-04-08")
    path = OUT_DIR / f"{pair}-1d.feather"
    frame.to_feather(path)
    print(f"wrote {path}")

  btc4h = _ohlcv(1900, "4h", BASE["BTC_USDT"])
  btc4h = _inject_bear_btc_4h(btc4h)
  btc4h.to_feather(OUT_DIR / "BTC_USDT-4h.feather")
  print(f"wrote {OUT_DIR / 'BTC_USDT-4h.feather'}")


if __name__ == "__main__":
  main()
