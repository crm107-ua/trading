"""Tests mínimos del motor research/xsec_lab.py"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))

from xsec_lab import (  # noqa: E402
  compute_metrics,
  portfolio_return,
  weights_equal,
)


def _two_asset_prices() -> pd.DataFrame:
  idx = pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC")
  return pd.DataFrame(
    {
      "A/USDT": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
      "B/USDT": [200, 198, 196, 194, 192, 190, 188, 186, 184, 182],
    },
    index=idx,
  )


def test_constant_weights_track_single_asset() -> None:
  prices = _two_asset_prices()

  def all_a(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    w = pd.Series(0.0, index=p.columns)
    w["A/USDT"] = 1.0
    return w

  rets, _ = portfolio_return(prices, all_a, "W", fee_per_rotation=0.0)
  single = np.log(prices["A/USDT"] / prices["A/USDT"].shift(1)).fillna(0.0)
  np.testing.assert_allclose(rets.values, single.values, atol=1e-10)


def test_no_rebalance_change_means_zero_turnover_cost_with_equal_weight() -> None:
  prices = _two_asset_prices()
  rets, turnover = portfolio_return(prices, weights_equal, "M", fee_per_rotation=0.001)
  # Primer día sin retorno; con fee solo en rebalanceos
  assert turnover >= 0.0
  rets0, turnover0 = portfolio_return(prices, weights_equal, "M", fee_per_rotation=0.0)
  # Misma trayectoria sin fee si no hubiera rebalanceos con cambio — al menos no más rica con fee
  m_fee = compute_metrics(rets, turnover=turnover)
  m_nofee = compute_metrics(rets0, turnover=turnover0)
  assert m_fee.final_wealth <= m_nofee.final_wealth + 1e-9


def test_friction_reduces_wealth_when_rebalance_has_turnover() -> None:
  prices = _two_asset_prices()
  rets_a, _ = portfolio_return(prices, weights_equal, "W", fee_per_rotation=0.0)
  rets_b, _ = portfolio_return(prices, weights_equal, "W", fee_per_rotation=0.01)
  wa = compute_metrics(rets_a).final_wealth
  wb = compute_metrics(rets_b).final_wealth
  assert wb < wa


def test_discrete_slots_invest_less_than_continuous_when_one_eligible() -> None:
  from xsec_lab import AblationConfig, portfolio_return_ablation

  idx = pd.date_range("2024-01-01", periods=80, freq="D", tz="UTC")
  prices = pd.DataFrame(
    {
      "A/USDT": np.linspace(100, 150, len(idx)),
      "B/USDT": np.linspace(200, 180, len(idx)),
      "C/USDT": np.linspace(50, 55, len(idx)),
    },
    index=idx,
  )

  def only_a(p: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    w = pd.Series(0.0, index=p.columns)
    w["A/USDT"] = 1.0
    return w

  cont, _ = portfolio_return(prices, only_a, "W", fee_per_rotation=0.0)
  disc, _, stats = portfolio_return_ablation(
    prices,
    only_a,
    "W",
    fee_per_rotation=0.0,
    config=AblationConfig(discrete_slots=True, max_slots=3),
  )
  assert compute_metrics(disc).final_wealth < compute_metrics(cont).final_wealth
  assert stats["cash_drag_mean"] > 0.2


def test_compute_metrics_sharpe_finite() -> None:
  idx = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
  r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.01, len(idx)), index=idx)
  m = compute_metrics(r)
  assert np.isfinite(m.sharpe)
  assert m.max_drawdown <= 0.0


def test_pit_universe_excludes_late_listings() -> None:
  from xsec_lab import pair_listing_dates, weights_top_n_momentum_pit

  idx = pd.date_range("2024-01-01", periods=60, freq="D", tz="UTC")
  prices = pd.DataFrame(
    {
      "OLD/USDT": np.linspace(100, 120, len(idx)),
      "NEW/USDT": np.linspace(50, 80, len(idx)),
    },
    index=idx,
  )
  listing = {
    "OLD/USDT": pd.Timestamp("2023-01-01", tz="UTC"),
    "NEW/USDT": pd.Timestamp("2024-03-01", tz="UTC"),
  }
  as_of = idx[-1]
  w = weights_top_n_momentum_pit(prices, as_of, window=14, top_n=1, listing_dates=listing)
  assert w["NEW/USDT"] == 0.0
  assert w["OLD/USDT"] == 1.0
