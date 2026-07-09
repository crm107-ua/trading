"""Tests de correlación entre posiciones (quant_core)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "user_data" / "strategies"))

from quant_core import (  # noqa: E402
  count_high_correlations,
  evaluate_correlation_entry,
  extract_daily_returns,
  pearson_correlation,
)


def _daily_returns_from_seed(seed: int, n: int = 40) -> pd.Series:
  rng = np.random.default_rng(seed)
  dates = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
  prices = 100 * np.cumprod(1 + rng.normal(0, 0.01, n))
  return pd.Series(prices, index=dates).pct_change().dropna()


class TestPearsonCorrelation:
  def test_high_correlation_detected(self) -> None:
    a = _daily_returns_from_seed(1)
    b = a * 0.9 + 0.0001
    corr, sufficient = pearson_correlation(a, b)
    assert sufficient
    assert corr is not None and corr > 0.8

  def test_insufficient_history(self) -> None:
    a = _daily_returns_from_seed(1, n=10)
    b = _daily_returns_from_seed(2, n=10)
    corr, sufficient = pearson_correlation(a, b, min_observations=20)
    assert not sufficient
    assert corr is None


class TestCorrelationEntryPolicy:
  def test_rejects_when_two_open_pairs_correlated(self) -> None:
    base = _daily_returns_from_seed(1)
    candidate = base
    open_a = base * 0.95 + 0.0001
    open_b = base * 0.92 + 0.0002
    count, _, _ = count_high_correlations(
      candidate,
      {"AAA/USDT": open_a, "BBB/USDT": open_b},
      threshold=0.8,
    )
    assert count >= 2
    allowed, reason = evaluate_correlation_entry(count, 2, [], insufficient_policy="allow")
    assert not allowed
    assert "correlacion_alta" in reason

  def test_allow_when_insufficient_history_policy_allow(self) -> None:
    allowed, reason = evaluate_correlation_entry(
      0,
      2,
      ["ETH/USDT"],
      insufficient_policy="allow",
    )
    assert allowed
    assert "insuficiente_allow" in reason

  def test_reject_when_insufficient_history_policy_reject(self) -> None:
    allowed, reason = evaluate_correlation_entry(
      0,
      2,
      ["ETH/USDT"],
      insufficient_policy="reject",
    )
    assert not allowed
    assert "historial_insuficiente" in reason


class TestExtractDailyReturns:
  def test_resamples_intraday_to_daily(self) -> None:
    n = 7 * 96
    dates = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    closes = pd.Series(range(100, 100 + n), index=dates, dtype=float)
    daily = extract_daily_returns(closes, lookback_days=30)
    assert len(daily) >= 1
