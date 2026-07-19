"""Tests desk_risk: correlación, EV, ladder."""

from __future__ import annotations

from polymarket.research.local_lab.desk_risk import (
    build_risk_budget,
    collision_rate,
    effective_lines,
    ev_per_filled_session,
    forecast_pnl,
    ladder_stage,
)


def test_effective_lines_haircut():
    assert effective_lines(1, 0.85) == 1.0
    assert abs(effective_lines(2, 0.85) - 1.15) < 1e-9
    assert effective_lines(4, 0.85) < 4.0


def test_ev_positive_high_wr():
    ev = ev_per_filled_session(wr=0.83, avg_win=0.094, avg_loss=-0.087)
    assert ev > 0.05


def test_forecast_corr_less_than_naive():
    fc = forecast_pnl(hours=1.0, lines=4, wr=0.83, rho=0.85)
    assert fc["pnl_corr_adjusted_usdc"] < fc["pnl_naive_n_times_usdc"]
    assert fc["effective_lines"] < 4


def test_risk_budget_caps_desk():
    b = build_risk_budget(lines=4, capital_per_line=1.5, rho=0.85)
    assert b.max_desk_notional_usdc <= 1.5 * 4
    assert b.effective_independent_lines < 4


def test_ladder_next():
    s = ladder_stage(1.5)
    assert s["next_stage"] == 2.0
    assert 1.5 in s["ladder_usdc"]


def test_collision_rate():
    c = collision_rate([["m1", "m2"], ["m1", "m3"]])
    assert c["collided_markets"] == 1
    assert c["collision_rate"] > 0
