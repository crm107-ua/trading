"""Tests unitarios de xsec_momentum_core.py (XSecMomentum #10)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from xsec_momentum_core import (  # noqa: E402
  bear_flat_on_rebalance,
  momentum_score,
  rank_universe,
  rebalance_day_mask,
  rebalance_entry_mask,
  rotation_exit_on_rebalance,
  top_n_mask,
)


def _dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
  return pd.date_range(start, periods=n, freq="D", tz="UTC")


def test_momentum_tail_perturbation_does_not_change_past_scores() -> None:
  close = pd.Series(np.linspace(100, 120, 40), index=_dates(40))
  base = momentum_score(close, window=7)
  close_alt = close.copy()
  close_alt.iloc[-1] = 999.0
  alt = momentum_score(close_alt, window=7)
  pd.testing.assert_series_equal(base.iloc[:-1], alt.iloc[:-1])


def test_pit_pair_without_history_not_ranked() -> None:
  idx = _dates(20)
  scores = {
    "A": momentum_score(pd.Series(np.linspace(100, 110, 20), index=idx), window=14),
    "B": momentum_score(pd.Series([np.nan] * 20, index=idx), window=14),
  }
  ranks = rank_universe(scores)
  assert ranks["B"].isna().all()
  assert ranks["A"].notna().any()


def test_rebalance_entry_only_on_monday() -> None:
  idx = _dates(14)
  rank = pd.Series([1.0, 2.0, 1.0, 3.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 1.0, 2.0, 1.0, 1.0], index=idx)
  entry = rebalance_entry_mask(rank, pd.Series(idx, index=idx), top_n=2)
  mondays = rebalance_day_mask(pd.Series(idx, index=idx))
  assert entry.sum() == (top_n_mask(rank, 2) & mondays).sum()
  if entry.any():
    assert all(d.weekday() == 0 for d in entry[entry].index)


def test_dead_band_exit_only_when_rank_above_k_on_rebalance() -> None:
  idx = _dates(7)
  rank = pd.Series([1, 2, 5, 1, 3, 2, 4], index=idx, dtype=float)
  ex = rotation_exit_on_rebalance(rank, pd.Series(idx, index=idx), exit_rank_k=3)
  assert ex.sum() >= 0
  assert ex.iloc[2] == bool(rebalance_day_mask(pd.Series(idx, index=idx)).iloc[2] and rank.iloc[2] > 3)


def test_bear_flat_on_rebalance_monday() -> None:
  idx = _dates(7)
  regime = pd.Series(["BULL", "BEAR", "RANGE", "BEAR", "BULL", "BEAR", "RANGE"], index=idx)
  flat = bear_flat_on_rebalance(regime, pd.Series(idx, index=idx), bear_value="BEAR")
  for i, flag in enumerate(flat):
    if flag:
      assert regime.iloc[i] == "BEAR"
      assert idx[i].weekday() == 0


def test_top_n_requires_valid_rank() -> None:
  rank = pd.Series([1.0, np.nan, 2.0])
  mask = top_n_mask(rank, 1)
  assert mask.iloc[0]
  assert not mask.iloc[1]
  assert not mask.iloc[2]
