"""Tests de lógica de entrada de TrendRider (sin Freqtrade runtime)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import MarketRegime, mean_rev_entry_mask, trend_rider_entry_mask  # noqa: E402


def test_no_entry_without_bull_regime() -> None:
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


def test_entry_when_bull_and_trend_aligned() -> None:
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


def test_hyperopt_param_count() -> None:
  import importlib.util

  spec = importlib.util.spec_from_file_location(
    "trend_rider", ROOT / "user_data" / "strategies" / "TrendRider.py"
  )
  assert spec and spec.loader
  # Solo verificamos en código fuente que no hay más de 6 IntParameter
  source = (ROOT / "user_data" / "strategies" / "TrendRider.py").read_text()
  assert source.count("IntParameter") <= 6
