#!/usr/bin/env python3
"""
Paridad Freqtrade vs research — máscara de elegibilidad liquidez 20M.

Compara fecha a fecha el conjunto de pares elegibles según:
  - ``xsec_momentum_core.liquidity_eligibility_mask`` (implementación Freqtrade)
  - ``research/r2_liquidity_filter.load_quote_volume_30d`` (research pandas)

Cero discrepancias requeridas antes del screen de confirmación.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))
sys.path.insert(0, str(ROOT / "research"))

from xsec_momentum_core import liquidity_eligibility_mask, quote_volume_usdt  # noqa: E402

DATADIR = ROOT / "research" / "data_local" / "binance"
OUTPUT = ROOT / "research" / "output" / "verify_20m_parity.json"
THRESHOLD = 20_000_000.0

E2_PAIRS = [
  f"{a}/USDT"
  for a in (
    "AAVE", "ADA", "BNB", "BTC", "DEXE", "DOGE", "ETH", "LTC",
    "NEAR", "SKL", "SOL", "TRX", "UNI", "XLM", "XRP", "ZEC",
  )
]


def _load_prices_index() -> pd.DatetimeIndex:
  path = DATADIR / "BTC_USDT-1d.feather"
  df = pd.read_feather(path)
  dates = pd.to_datetime(df["date"], utc=True)
  return pd.DatetimeIndex(dates.sort_values())


def _research_eligible(index: pd.DatetimeIndex) -> pd.DataFrame:
  """Réplica exacta de r2_liquidity_filter.load_quote_volume_30d + umbral."""
  frames: dict[str, pd.Series] = {}
  for pair in E2_PAIRS:
    path = DATADIR / f"{pair.replace('/', '_')}-1d.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    idx = pd.to_datetime(df["date"], utc=True)
    qv = quote_volume_usdt(df["volume"], df["close"])
    qv.index = idx
    frames[pair] = qv.sort_index()
  qvol = pd.DataFrame(frames).sort_index()
  rolling = qvol.rolling(30, min_periods=20).mean().shift(1).reindex(index)
  return rolling > THRESHOLD


def _freqtrade_eligible(index: pd.DatetimeIndex) -> pd.DataFrame:
  frames: dict[str, pd.Series] = {}
  for pair in E2_PAIRS:
    path = DATADIR / f"{pair.replace('/', '_')}-1d.feather"
    if not path.is_file():
      continue
    df = pd.read_feather(path)
    idx = pd.to_datetime(df["date"], utc=True)
    qv = quote_volume_usdt(df["volume"], df["close"])
    qv.index = idx
    frames[pair] = liquidity_eligibility_mask(
      qv.sort_index(), window=30, threshold=THRESHOLD, min_periods=20
    ).reindex(index)
  return pd.DataFrame(frames)


def main() -> int:
  index = _load_prices_index()
  research = _research_eligible(index)
  ft = _freqtrade_eligible(index)

  mismatches: list[dict] = []
  for pair in sorted(set(research.columns) | set(ft.columns)):
    r = research[pair].fillna(False) if pair in research.columns else pd.Series(False, index=index)
    f = ft[pair].fillna(False) if pair in ft.columns else pd.Series(False, index=index)
    diff = r.ne(f)
    if diff.any():
      first = diff[diff].index[0]
      mismatches.append(
        {
          "pair": pair,
          "n_diff": int(diff.sum()),
          "first_diff": str(first),
          "research": bool(r.loc[first]),
          "freqtrade": bool(f.loc[first]),
        }
      )

  payload = {
    "threshold_usdt": THRESHOLD,
    "window": 30,
    "min_periods": 20,
    "pairs_compared": len(E2_PAIRS),
    "n_mismatches": len(mismatches),
    "mismatches": mismatches[:20],
    "passes": len(mismatches) == 0,
  }
  OUTPUT.parent.mkdir(parents=True, exist_ok=True)
  OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
  print(json.dumps(payload, indent=2))
  return 0 if payload["passes"] else 1


if __name__ == "__main__":
  raise SystemExit(main())
