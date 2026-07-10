"""Tests unitarios de relative_momentum_core.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from relative_momentum_core import (  # noqa: E402
  momentum_score,
  rank_universe,
  rotation_entry_mask,
  rotation_entry_mask_daily,
  rotation_exit_mask,
  top_n_mask,
)


def test_momentum_score_uses_shift_not_current_close() -> None:
  close = pd.Series([100.0, 102.0, 104.0, 106.0, 108.0, 999.0])
  scores = momentum_score(close, window=2)
  # t=3: close[2]/close[0]-1 = 0.04 — no usa el 999 final
  assert scores.iloc[3] == pytest.approx(0.04)
  assert scores.iloc[3] == scores.iloc[3]


def test_absurd_tail_does_not_change_prior_score() -> None:
  base = pd.Series([100.0, 102.0, 104.0, 106.0, 108.0, 110.0])
  mutated = base.copy()
  mutated.iloc[-1] = 50_000.0
  s1 = momentum_score(base, window=2)
  s2 = momentum_score(mutated, window=2)
  pd.testing.assert_series_equal(s1.iloc[:-1], s2.iloc[:-1])


def test_rank_universe_nan_excluded_not_zero() -> None:
  scores = {
    "BTC": pd.Series([0.10, float("nan")]),
    "ETH": pd.Series([0.05, 0.08]),
    "SOL": pd.Series([0.20, 0.02]),
  }
  ranks = rank_universe(scores)
  assert ranks.loc[0, "SOL"] == 1
  assert ranks.loc[0, "BTC"] == 2
  assert ranks.loc[0, "ETH"] == 3
  assert pd.isna(ranks.loc[1, "BTC"])
  assert ranks.loc[1, "ETH"] == 1


def test_top_n_mask() -> None:
  rank = pd.Series([1.0, 2.0, 3.0, float("nan")])
  mask = top_n_mask(rank, 2)
  assert mask.tolist() == [True, True, False, False]


def test_rotation_entry_mask_daily_requires_consecutive_days() -> None:
  dates = pd.date_range("2024-01-01", periods=5 * 24, freq="h", tz="UTC")
  rank = pd.Series(2, index=dates)
  rank[dates.floor("D") == pd.Timestamp("2024-01-03", tz="UTC")] = 1
  rank[dates.floor("D") == pd.Timestamp("2024-01-04", tz="UTC")] = 1
  entry = rotation_entry_mask_daily(rank, dates, top_n=1, confirm_days=2)
  assert not entry.loc[dates.floor("D") == pd.Timestamp("2024-01-03", tz="UTC")].any()
  assert entry.loc[dates.floor("D") == pd.Timestamp("2024-01-04", tz="UTC")].any()


def test_rotation_entry_requires_consecutive_bars() -> None:
  rank = pd.Series([2, 1, 1, 1, 2, 1, 1])
  entry = rotation_entry_mask(rank, top_n=1, confirm_bars=2)
  assert not entry.iloc[1]
  assert entry.iloc[2]
  assert entry.iloc[6]


def test_rotation_exit_dead_band() -> None:
  rank = pd.Series([1, 2, 2, 3])
  exit_mask = rotation_exit_mask(rank, exit_rank_k=2)
  assert not exit_mask.iloc[1]
  assert not exit_mask.iloc[2]
  assert exit_mask.iloc[3]


def test_ranking_causality_identical_until_divergence() -> None:
  idx = pd.date_range("2024-01-01", periods=8, freq="D", tz="UTC")
  a = pd.Series([1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7], index=idx)
  b_left = pd.Series([1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35], index=idx)
  b_right = b_left.copy()
  b_right.iloc[6] = 4.0

  scores_left = {"A": momentum_score(a, 1), "B": momentum_score(b_left, 1)}
  scores_right = {"A": momentum_score(a, 1), "B": momentum_score(b_right, 1)}
  ranks_left = rank_universe(scores_left)
  ranks_right = rank_universe(scores_right)

  pd.testing.assert_frame_equal(ranks_left.iloc[:6], ranks_right.iloc[:6])
  assert not ranks_left.iloc[7].equals(ranks_right.iloc[7])
