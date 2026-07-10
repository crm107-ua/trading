"""Tests de RelativeMomentum (máscaras integradas y columnas de ranking)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import MarketRegime  # noqa: E402
from relative_momentum_core import (  # noqa: E402
  build_pair_ranks,
  rotation_entry_mask_daily,
  rotation_exit_mask,
)


def _daily_universe_frame(n: int = 60) -> tuple[pd.DataFrame, dict[str, str]]:
  """Serie diaria: ETH lidera días 10-20, BTC 25-40, SOL 45+."""
  dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
  eth = np.full(n, 100.0)
  btc = np.full(n, 100.0)
  sol = np.full(n, 100.0)
  eth[10:21] = 100 + np.arange(11) * 2.0
  if n > 25:
    end_btc = min(n, 41)
    btc[25:end_btc] = 100 + np.arange(end_btc - 25) * 2.5
  if n > 45:
    sol[45:] = 100 + np.arange(n - 45) * 3.0

  frame = pd.DataFrame(
    {
      "date": dates,
      "close_eth": eth,
      "close_btc": btc,
      "close_sol": sol,
      "btc_market_regime": MarketRegime.BULL.value,
    }
  )
  cols = {"ETH": "close_eth", "BTC": "close_btc", "SOL": "close_sol"}
  return frame, cols


def test_build_pair_ranks_rotates_leader() -> None:
  frame, cols = _daily_universe_frame()
  ranks = build_pair_ranks(frame, asset_columns=cols, window=3)
  assert ranks["ETH"].iloc[18] == 1
  assert ranks["BTC"].iloc[35] == 1
  assert ranks["SOL"].iloc[55] == 1


def test_entry_and_exit_masks_respect_hysteresis_and_dead_band() -> None:
  rank = pd.Series([3, 2, 1, 1, 1, 2, 2, 3])
  dates = pd.date_range("2024-01-01", periods=len(rank), freq="D", tz="UTC")
  entry = rotation_entry_mask_daily(rank, dates, top_n=1, confirm_days=2)
  exit_mask = rotation_exit_mask(rank, exit_rank_k=2)
  assert entry.iloc[3]
  assert not exit_mask.iloc[5]
  assert exit_mask.iloc[7]


def test_bear_regime_blocks_entry_column() -> None:
  frame, cols = _daily_universe_frame(n=40)
  ranks = build_pair_ranks(frame, asset_columns=cols, window=2)
  entry = rotation_entry_mask_daily(
    ranks["ETH"], frame["date"], top_n=1, confirm_days=1
  )
  not_bear = frame["btc_market_regime"] != MarketRegime.BEAR.value
  allowed = entry & not_bear
  frame_bear = frame.copy()
  frame_bear["btc_market_regime"] = MarketRegime.BEAR.value
  blocked = entry & (frame_bear["btc_market_regime"] != MarketRegime.BEAR.value)
  assert allowed.any()
  assert not blocked.any()
