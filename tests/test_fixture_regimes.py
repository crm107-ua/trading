"""Verifica segmentos BULL/RANGE en fixtures sintéticos."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

talib = pytest.importorskip("talib", reason="TA-Lib requerido; usar scripts/regenerate_fixtures.ps1 en Docker")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from _base import QuantBaseStrategy  # noqa: E402
from quant_core import MarketRegime  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "data" / "binance"
BULL_START = pd.Timestamp("2024-01-10", tz="UTC")
BULL_END = pd.Timestamp("2024-02-25", tz="UTC")
RANGE_START = pd.Timestamp("2024-02-15", tz="UTC")
RANGE_END = pd.Timestamp("2024-03-18", tz="UTC")


@pytest.fixture(scope="module")
def btc_4h_labeled() -> pd.DataFrame:
  path = FIXTURE_DIR / "BTC_USDT-4h.feather"
  if not path.exists():
    pytest.skip("Fixtures no generados — ejecutar python tests/fixtures/generate_data.py")
  df = pd.read_feather(path)
  return QuantBaseStrategy.add_regime_indicators(df)


def test_bull_window_on_btc_4h(btc_4h_labeled: pd.DataFrame) -> None:
  dates = pd.to_datetime(btc_4h_labeled["date"], utc=True)
  window = (dates >= BULL_START) & (dates <= BULL_END)
  labels = btc_4h_labeled.loc[window, "market_regime"]
  assert len(labels) > 50
  bull_ratio = (labels == MarketRegime.BULL.value).mean()
  assert bull_ratio >= 0.6, f"Solo {bull_ratio:.1%} BULL en ventana alcista"


def test_range_window_on_btc_4h(btc_4h_labeled: pd.DataFrame) -> None:
  dates = pd.to_datetime(btc_4h_labeled["date"], utc=True)
  window = (dates >= RANGE_START) & (dates <= RANGE_END)
  labels = btc_4h_labeled.loc[window, "market_regime"]
  assert len(labels) > 30
  range_ratio = (labels == MarketRegime.RANGE.value).mean()
  assert range_ratio >= 0.5, f"Solo {range_ratio:.1%} RANGE en ventana lateral"
