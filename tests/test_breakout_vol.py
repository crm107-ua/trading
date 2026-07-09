"""Tests de lógica de BreakoutVol (indicadores shift y señales)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  MarketRegime,
  compute_prior_rolling_max,
  compute_prior_rolling_mean,
)


def _entry_mask(df: pd.DataFrame, vol_mult: float = 1.5) -> pd.Series:
  bull = df["btc_market_regime"] == MarketRegime.BULL.value
  vol_threshold = df["volume_mean_prior"] * vol_mult
  return (
    bull
    & (df["close"] > df["range_high"])
    & (df["volume"] > vol_threshold)
    & df["range_high"].notna()
    & df["volume_mean_prior"].notna()
    & (df["volume"] > 0)
  )


def _exit_mask(df: pd.DataFrame) -> pd.Series:
  return (df["close"] < df["range_high"]) & df["range_high"].notna() & (df["volume"] > 0)


def test_prior_rolling_max_excludes_current_bar() -> None:
  highs = pd.Series([10.0, 11.0, 12.0, 50.0, 14.0])
  prior = compute_prior_rolling_max(highs, 3)
  assert prior.iloc[3] == 12.0
  assert prior.iloc[3] != 50.0


def test_prior_rolling_mean_excludes_current_volume() -> None:
  vol = pd.Series([100.0, 100.0, 100.0, 10_000.0, 100.0])
  prior = compute_prior_rolling_mean(vol, 3)
  assert prior.iloc[3] == 100.0
  assert prior.iloc[3] != 10_000.0


def test_no_entry_without_bull_regime() -> None:
  df = pd.DataFrame(
    {
      "close": [105.0],
      "volume": [2000.0],
      "range_high": [100.0],
      "volume_mean_prior": [1000.0],
      "btc_market_regime": [MarketRegime.RANGE.value],
    }
  )
  assert not _entry_mask(df).iloc[0]


def test_entry_on_breakout_with_volume() -> None:
  df = pd.DataFrame(
    {
      "close": [105.0],
      "volume": [2000.0],
      "range_high": [100.0],
      "volume_mean_prior": [1000.0],
      "btc_market_regime": [MarketRegime.BULL.value],
    }
  )
  assert _entry_mask(df).iloc[0]


def test_no_entry_when_close_inside_range() -> None:
  df = pd.DataFrame(
    {
      "close": [99.0],
      "volume": [2000.0],
      "range_high": [100.0],
      "volume_mean_prior": [1000.0],
      "btc_market_regime": [MarketRegime.BULL.value],
    }
  )
  assert not _entry_mask(df).iloc[0]


def test_exit_on_invalidation_inside_range() -> None:
  df = pd.DataFrame({"close": [98.0], "volume": [500.0], "range_high": [100.0]})
  assert _exit_mask(df).iloc[0]


def test_hyperopt_param_count() -> None:
  source = (ROOT / "user_data" / "strategies" / "BreakoutVol.py").read_text()
  assert source.count("IntParameter") <= 6
