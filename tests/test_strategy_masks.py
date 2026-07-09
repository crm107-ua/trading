"""Tests de máscaras puras en quant_core (TrendRider / MeanRev)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  MarketRegime,
  mean_rev_entry_mask,
  mean_rev_exit_mask,
  trend_rider_entry_mask,
  trend_rider_exit_mask,
)


def test_trend_rider_no_entry_without_bull() -> None:
  df = pd.DataFrame(
    {
      "ema_fast": [110.0],
      "ema_slow": [100.0],
      "adx": [30.0],
      "rsi": [60.0],
      "volume": [2000.0],
      "volume_mean": [1000.0],
      "btc_market_regime": [MarketRegime.BEAR.value],
    }
  )
  assert not trend_rider_entry_mask(df).iloc[0]


def test_trend_rider_entry_when_bull_aligned() -> None:
  df = pd.DataFrame(
    {
      "ema_fast": [110.0],
      "ema_slow": [100.0],
      "adx": [30.0],
      "rsi": [60.0],
      "volume": [2000.0],
      "volume_mean": [1000.0],
      "btc_market_regime": [MarketRegime.BULL.value],
    }
  )
  assert trend_rider_entry_mask(df).iloc[0]


def test_trend_rider_exit_mask_always_false() -> None:
  df = pd.DataFrame({"close": [1.0, 2.0]})
  mask = trend_rider_exit_mask(df)
  assert not mask.any()


def test_mean_rev_entry_only_in_range() -> None:
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


def test_mean_rev_exit_on_bb_middle_or_rsi() -> None:
  df = pd.DataFrame(
    {
      "close": [100.0, 90.0],
      "bb_middle": [100.0, 100.0],
      "rsi": [40.0, 55.0],
    }
  )
  mask = mean_rev_exit_mask(df, sell_rsi=50, bb_mid_tolerance=0.005)
  assert mask.iloc[0]
  assert mask.iloc[1]
