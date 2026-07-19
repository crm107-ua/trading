"""Tests for FollowGate and Fusion router."""

from __future__ import annotations

from polymarket.research.local_lab.strategies import maker_follow, maker_fusion


def test_follow_bids_when_mid_and_spot_agree_up():
    cfg = {
        "quote_size_shares": 5,
        "max_quote_size_shares": 5,
        "quote_join_touch": True,
        "_window_open": True,
        "_time_remaining_s": 180,
        "_roll_lead_usd": 3.0,
        "_spot_velocity_usd": 1.0,
        "follow_min_roll_usd": 1.0,
        "follow_min_vel_usd": 0.2,
        "follow_up_lo": 0.52,
        "follow_up_hi": 0.72,
        "follow_fair_oppose_max": 0.05,
        "follow_persist_polls": 1,
    }
    q = maker_follow(0.58, 0.59, 0.61, 100_010.0, 100_000.0, cfg)
    assert q is not None
    assert q.strategy_id == "maker_follow"
    assert q.bid > 0.02


def test_follow_rejects_extreme_mid():
    cfg = {
        "quote_size_shares": 5,
        "quote_join_touch": True,
        "_window_open": True,
        "_time_remaining_s": 180,
        "_roll_lead_usd": 5.0,
        "_spot_velocity_usd": 2.0,
        "follow_extreme_hi": 0.78,
    }
    assert maker_follow(0.90, 0.88, 0.92, 100_020.0, 100_000.0, cfg) is None


def test_fusion_edge_requires_momentum():
    cfg = {
        "quote_size_shares": 5,
        "max_quote_size_shares": 5,
        "quote_join_touch": True,
        "half_spread": 0.012,
        "safety_buffer": 0.002,
        "kelly_sizing": False,
        "min_edge": 0.03,
        "min_z": 1.0,
        "sigma_mid": 0.03,
        "cheap_side_only": True,
        "fusion_enable_pulse": False,
        "fusion_enable_follow": False,
        "fusion_enable_edge": True,
        "edge_require_momentum": True,
        "edge_min_quote_mid": 0.28,
        "edge_max_quote_mid": 0.72,
        "edge_min_edge": 0.03,
        "edge_cheap_side_only": True,
        "min_spot_lead_usd": 2.0,
        "_strike_trusted": False,
        "_window_open": True,
        "_time_remaining_s": 180,
        "_roll_lead_usd": 0.0,
        "_spot_velocity_usd": 0.0,
        "_pulse_streak": 0,
    }
    # sin roll → bloqueado
    assert maker_fusion(0.55, 0.48, 0.50, 100_000.0, 100_000.0, cfg) is None
    cfg["_roll_lead_usd"] = 3.0
    q = maker_fusion(0.55, 0.48, 0.50, 100_010.0, 100_000.0, cfg)
    assert q is not None
    assert "via_edge" in q.note


def test_fusion_can_disable_pulse():
    cfg = {
        "quote_size_shares": 5,
        "max_quote_size_shares": 5,
        "quote_join_touch": True,
        "fusion_enable_pulse": False,
        "fusion_enable_follow": True,
        "fusion_enable_edge": False,
        "_window_open": True,
        "_time_remaining_s": 180,
        "_roll_lead_usd": 3.0,
        "_spot_velocity_usd": 1.0,
        "_pulse_streak": 2,
        "_strike_trusted": True,
        "follow_min_roll_usd": 1.0,
        "follow_min_vel_usd": 0.2,
        "follow_up_lo": 0.52,
        "follow_up_hi": 0.72,
        "follow_fair_oppose_max": 0.05,
        "follow_persist_polls": 1,
        "min_spot_lead_usd": 1.0,
        "min_spot_velocity_usd": 0.2,
    }
    q = maker_fusion(0.58, 0.59, 0.61, 100_010.0, 100_000.0, cfg)
    assert q is not None
    assert "via_follow" in q.note
    assert "via_pulse" not in q.note


def test_follow_optional_fair_veto():
    cfg = {
        "quote_size_shares": 5,
        "quote_join_touch": True,
        "_window_open": True,
        "_time_remaining_s": 180,
        "_roll_lead_usd": 3.0,
        "_spot_velocity_usd": 1.0,
        "follow_min_roll_usd": 1.0,
        "follow_min_vel_usd": 0.2,
        "follow_up_lo": 0.52,
        "follow_up_hi": 0.72,
        "follow_use_fair_veto": True,
        "follow_fair_oppose_max": 0.04,
        "follow_persist_polls": 1,
    }
    assert maker_follow(0.50, 0.59, 0.61, 100_010.0, 100_000.0, cfg) is None
    cfg["follow_use_fair_veto"] = False
    q = maker_follow(0.50, 0.59, 0.61, 100_010.0, 100_000.0, cfg)
    assert q is not None
