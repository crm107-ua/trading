"""Tests de lógica de MeanRevBB."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import MarketRegime, mean_rev_entry_mask  # noqa: E402


def test_entry_only_in_range_regime() -> None:
  df = pd.DataFrame(
    {
      "rsi": [25.0, 25.0],
      "close": [95.0, 95.0],
      "bb_lower": [100.0, 100.0],
      "volume": [1000.0, 1000.0],
      "btc_market_regime": [MarketRegime.BULL.value, MarketRegime.RANGE.value],
    }
  )
  mask = mean_rev_entry_mask(df)
  assert not mask.iloc[0]
  assert mask.iloc[1]


def test_hyperopt_param_count() -> None:
  source = (ROOT / "user_data" / "strategies" / "MeanRevBB.py").read_text()
  assert source.count("IntParameter") + source.count("DecimalParameter") <= 8
