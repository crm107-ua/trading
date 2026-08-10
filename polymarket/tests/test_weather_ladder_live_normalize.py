"""Unit tests for ladder live floor normalization (no network)."""

from __future__ import annotations

from polymarket.research.local_lab.weather_ladder_live import _live_normalize_legs
from polymarket.src.execution.clob_live import MIN_ORDER_SHARES
from polymarket.src.weather.ladder import LadderLeg, LadderPlan


def _plan(shares: list[float], prices: list[float] | None = None) -> LadderPlan:
    prices = prices or [0.20, 0.25, 0.30]
    legs = [
        LadderLeg(
            name=f"{30+i}°C",
            my_prob=0.3,
            price=prices[i],
            dollars=round(shares[i] * prices[i], 4),
            shares=shares[i],
            ev=0.05,
            token_id=f"tok{i}",
        )
        for i in range(3)
    ]
    return LadderPlan(legs, sum(prices), 0.1, 31, True, True, "take")


def test_live_floors_bump_thin_legs():
    plan, reason = _live_normalize_legs(_plan([2.0, 2.0, 2.0]), slip_cents=0.01, max_capital=25.0)
    assert reason == "ok"
    assert plan is not None
    assert all(l.shares >= MIN_ORDER_SHARES for l in plan.legs)
    assert sum(l.dollars for l in plan.legs) <= 25.0


def test_live_floors_abort_over_capital():
    # High prices + min shares → notional > tiny capital
    plan, reason = _live_normalize_legs(
        _plan([5.0, 5.0, 5.0], prices=[0.35, 0.36, 0.37]),
        slip_cents=0.02,
        max_capital=3.0,
    )
    assert plan is None
    assert "max_capital" in reason
