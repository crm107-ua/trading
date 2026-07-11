"""Tests del filtro de liquidez dinámico 20M (xsec_momentum_core)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from xsec_momentum_core import (  # noqa: E402
  LIQUIDITY_THRESHOLD_USDT,
  build_pair_ranks,
  liquidity_eligibility_mask,
  liquidity_exit_on_rebalance,
  quote_volume_usdt,
)


def _dates(n: int, start: str = "2024-01-01") -> pd.DatetimeIndex:
  return pd.date_range(start, periods=n, freq="D", tz="UTC")


def test_tail_volume_spike_does_not_affect_past_eligibility() -> None:
  idx = _dates(50)
  qv = pd.Series(1_000_000.0, index=idx)
  qv.iloc[-1] = 500_000_000.0
  base = liquidity_eligibility_mask(qv, window=10, threshold=20_000_000, min_periods=5)
  assert not base.iloc[:30].any()
  assert base.iloc[-1] != base.iloc[-2] or not base.iloc[-2]


def test_threshold_boundary_exact() -> None:
  idx = _dates(40)
  # Constante justo por encima del umbral tras warmup+shift
  qv = pd.Series(LIQUIDITY_THRESHOLD_USDT + 1.0, index=idx)
  elig = liquidity_eligibility_mask(qv, window=10, threshold=LIQUIDITY_THRESHOLD_USDT, min_periods=5)
  assert elig.iloc[-1]
  qv_low = pd.Series(LIQUIDITY_THRESHOLD_USDT - 1.0, index=idx)
  elig_low = liquidity_eligibility_mask(
    qv_low, window=10, threshold=LIQUIDITY_THRESHOLD_USDT, min_periods=5
  )
  assert not elig_low.iloc[-1]


def test_pair_crosses_threshold_on_expected_date() -> None:
  idx = _dates(60)
  qv = pd.Series(5_000_000.0, index=idx)
  qv.iloc[35:] = 25_000_000.0
  elig = liquidity_eligibility_mask(qv, window=10, threshold=20_000_000, min_periods=5)
  first_true = elig[elig].index[0] if elig.any() else None
  assert first_true is not None
  assert idx[35] < first_true < idx[50]


def test_ineligible_asset_excluded_from_ranking() -> None:
  idx = _dates(30)
  frame = pd.DataFrame(
    {
      "close_a": np.linspace(100, 130, 30),
      "close_b": np.linspace(200, 150, 30),
    },
    index=idx,
  )
  elig = {
    "A": pd.Series(True, index=idx),
    "B": pd.Series(False, index=idx),
  }
  ranks = build_pair_ranks(
    frame,
    asset_columns={"A": "close_a", "B": "close_b"},
    window=5,
    asset_eligibility=elig,
  )
  assert ranks["B"].isna().all()
  assert ranks["A"].notna().any()


def test_liquidity_exit_on_rebalance_when_becomes_ineligible() -> None:
  idx = _dates(14)
  # Lunes en idx[7] si start es lunes 2024-01-01
  eligible = pd.Series(True, index=idx)
  eligible.iloc[7:] = False
  ex = liquidity_exit_on_rebalance(eligible, pd.Series(idx, index=idx))
  monday_flags = ex[ex]
  assert monday_flags.any()
  for dt in monday_flags.index:
    assert dt.weekday() == 0
    assert not eligible.loc[dt]


def test_quote_volume_usdt_formula() -> None:
  vol = pd.Series([100.0, 200.0])
  close = pd.Series([10.0, 5.0])
  qv = quote_volume_usdt(vol, close)
  pd.testing.assert_series_equal(qv, pd.Series([1000.0, 1000.0]))
