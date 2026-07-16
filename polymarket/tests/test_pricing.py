"""Unit tests — pricing and risk (frozen params)."""

import math

from polymarket.src.pricing.fair_value import estimate_fair_values, find_executable_edge
from polymarket.src.risk.manager import RiskState, risk_manager_approves
from polymarket.src.signals.features import build_market_features
from polymarket.src.execution.plan import build_execution_plan, choose_position_structure


def test_fair_value_above_strike():
    features = build_market_features(
        {
            "spot": 63_000,
            "strike": 62_000,
            "time_remaining_s": 300,
            "bids": [{"price": "0.55", "size": "1000"}],
            "asks": [{"price": "0.57", "size": "1000"}],
        }
    )
    fv = estimate_fair_values(features)
    assert fv["up"] > 0.5
    assert abs(fv["up"] + fv["down"] - 1.0) < 1e-6


def test_fair_value_small_move_not_collapsed():
    """$1 under strike in a 2m window must not floor to 0.001 (old dollar-vol bug)."""
    features = build_market_features(
        {
            "spot": 64_214,
            "strike": 64_215,
            "time_remaining_s": 120,
            "bids": [{"price": "0.34", "size": "10"}],
            "asks": [{"price": "0.36", "size": "10"}],
        }
    )
    fv = estimate_fair_values(features)
    assert 0.35 < fv["up"] < 0.65


def test_no_edge_when_ask_too_high():
    state = {
        "spot": 62_000,
        "strike": 62_000,
        "time_remaining_s": 300,
        "bids": [{"price": "0.48", "size": "1000"}],
        "asks": [{"price": "0.95", "size": "1000"}],
    }
    features = build_market_features(state)
    fv = estimate_fair_values(features)
    assert find_executable_edge(state, fv, size_shares=50) is None


def test_risk_blocks_stale_feed():
    from polymarket.src.execution.plan import OrderPlan

    plan = OrderPlan("up", "FAK", 0.5, 100, 50)
    state = RiskState(10_000, 0, 0)
    market = {"feed_ts_ms": 0}
    assert risk_manager_approves(market, plan, state, now_ms=10_000) is False
