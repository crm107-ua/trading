"""Tests del scoring del torneo sim live-exact."""

from __future__ import annotations

from polymarket.research.local_lab.sim_live_tournament import score_row


def test_score_prefers_positive_pnl_and_wr():
    weak = {
        "total": -1.0,
        "wr": 0.0,
        "worst": -1.0,
        "sessions_with_fills": 1,
        "fills_total": 2,
        "capital": 10,
    }
    strong = {
        "total": 1.5,
        "wr": 0.75,
        "worst": -0.2,
        "sessions_with_fills": 2,
        "fills_total": 6,
        "capital": 10,
    }
    assert score_row(strong) > score_row(weak)


def test_score_penalizes_starve():
    starve = {
        "total": 0.0,
        "wr": 0.0,
        "worst": 0.0,
        "sessions_with_fills": 0,
        "fills_total": 0,
        "capital": 10,
    }
    traded = {
        "total": 0.0,
        "wr": 0.5,
        "worst": -0.1,
        "sessions_with_fills": 2,
        "fills_total": 4,
        "capital": 10,
    }
    assert score_row(traded) > score_row(starve)
