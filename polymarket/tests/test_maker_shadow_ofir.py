"""Unit tests Shadow OFIR — lead + toxicity + mid-lag guard."""

from __future__ import annotations

from polymarket.research.local_lab.strategies import maker_fusion, maker_shadow_ofir


def _cfg(**kw):
    base = {
        "quote_size_shares": 3,
        "max_quote_size_shares": 3,
        "quote_join_touch": True,
        "_strike_trusted": True,
        "_window_open": True,
        "_time_remaining_s": 180,
        "_roll_lead_usd": 4.0,
        "_spot_velocity_usd": 1.2,
        "_mid_delta": 0.005,
        "_book_imbalance": 0.62,
        "_pulse_streak": 2,
        "shadow_min_lead_usd": 2.0,
        "shadow_min_vel_usd": 0.5,
        "shadow_min_edge": 0.01,
        "shadow_max_mid_catchup": 0.02,
        "shadow_min_imbalance": 0.55,
        "shadow_persist_polls": 2,
        "min_edge": 0.01,
        "pulse_fair_scale_usd": 28,
        "pulse_blend_bs_fair": False,
        "fusion_enable_shadow": True,
        "fusion_enable_pulse": False,
        "fusion_enable_follow": False,
        "fusion_enable_edge": False,
    }
    base.update(kw)
    return base


def test_shadow_quotes_up_on_lead_and_imbalance():
    q = maker_shadow_ofir(0.55, 0.48, 0.52, spot=65010, strike=65000, cfg=_cfg())
    assert q is not None
    assert q.strategy_id == "maker_shadow_ofir"
    assert q.bid is not None and q.bid < 0.5


def test_shadow_blocks_toxic_imbalance():
    q = maker_shadow_ofir(
        0.55, 0.48, 0.52, spot=65010, strike=65000, cfg=_cfg(_book_imbalance=0.35)
    )
    assert q is None


def test_shadow_blocks_mid_already_caught_up():
    q = maker_shadow_ofir(
        0.55, 0.48, 0.52, spot=65010, strike=65000, cfg=_cfg(_mid_delta=0.05)
    )
    assert q is None


def test_fusion_routes_via_shadow_when_enabled():
    q = maker_fusion(0.55, 0.48, 0.52, spot=65010, strike=65000, cfg=_cfg())
    assert q is not None
    assert "via_shadow" in (q.note or "")
