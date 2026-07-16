from __future__ import annotations

from polymarket.research.local_lab.edge_math import EdgeParams, expected_pnl_bid, p_win_bid, monte_carlo_session
from polymarket.research.local_lab.strategies import maker_edge


def test_p_win_increases_with_edge():
    tight = EdgeParams(0.01, 0.01, 0.01, 6, 0.03)
    wide = EdgeParams(0.01, 0.05, 0.01, 6, 0.03)
    assert p_win_bid(wide) >= p_win_bid(tight)


def test_expected_pnl_positive():
    p = EdgeParams(0.02, 0.03, 0.01, 6, 0.03)
    assert expected_pnl_bid(p) > 0


def test_mc_selective_beats_random_seed():
    p = EdgeParams(0.015, 0.04, 0.01, 6, 0.03)
    r = monte_carlo_session(p, n_fills=10, n_sims=1000, seed=1)
    assert r["win_rate"] > 0.55


def test_maker_edge_requires_divergence():
    cfg = {
        "min_edge": 0.03,
        "min_z": 1.0,
        "sigma_mid": 0.03,
        "half_spread": 0.015,
        "safety_buffer": 0.002,
        "quote_size_shares": 8,
        "quote_join_touch": True,
        "kelly_sizing": False,
    }
    assert maker_edge(0.5, 0.49, 0.51, 100.0, 100.0, cfg) is None  # edge 0
    q = maker_edge(0.55, 0.48, 0.50, 100.0, 100.0, cfg)  # cheap market
    assert q is not None
    assert q.strategy_id == "maker_edge"
    assert q.bid > 0.02
    assert q.ask == 0.99


def test_maker_edge_rejects_lottery_mid():
    cfg = {
        "min_edge": 0.03,
        "min_z": 1.0,
        "sigma_mid": 0.03,
        "half_spread": 0.015,
        "safety_buffer": 0.002,
        "quote_size_shares": 8,
        "quote_join_touch": True,
        "kelly_sizing": False,
        "min_quote_mid": 0.28,
        "max_quote_mid": 0.72,
    }
    assert maker_edge(0.40, 0.08, 0.12, 100.0, 100.0, cfg) is None
    q = maker_edge(0.55, 0.48, 0.50, 100.0, 100.0, cfg)
    assert q is not None
