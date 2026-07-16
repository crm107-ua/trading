from __future__ import annotations

from polymarket.research.local_lab.strategies import QuoteIntent, apply_inventory_skew, maker_16


def test_skew_long_pulls_bid():
    cfg = {"quote_size_shares": 6, "inventory_skew_shares": 6, "max_inventory_shares": 12}
    q = QuoteIntent(0.48, 0.52, 6, "maker_16")
    out = apply_inventory_skew(q, inventory_shares=6.0, cfg=cfg, mid=0.50)
    assert out is not None
    assert out.bid == 0.01
    assert out.ask == 0.51  # mid + tick exit


def test_skew_short_pulls_ask():
    cfg = {"quote_size_shares": 6, "inventory_skew_shares": 6, "max_inventory_shares": 12}
    q = QuoteIntent(0.48, 0.52, 6, "maker_16")
    out = apply_inventory_skew(q, inventory_shares=-6.0, cfg=cfg, mid=0.50)
    assert out is not None
    assert out.bid == 0.49  # mid - tick exit
    assert out.ask == 0.99


def test_skew_over_cap_still_quotes_exit():
    """At/over cap must keep quoting the reducing side (old bug muted exits)."""
    cfg = {"quote_size_shares": 6, "inventory_skew_shares": 6, "max_inventory_shares": 12}
    q = QuoteIntent(0.48, 0.52, 6, "maker_16")
    out = apply_inventory_skew(q, inventory_shares=12.0, cfg=cfg, mid=0.50)
    assert out is not None
    assert out.bid == 0.01
    assert out.ask == 0.51
    assert out.size_shares == 6.0


def test_maker_16_quotes_around_fair():
    cfg = {"half_spread": 0.02, "safety_buffer": 0.002, "quote_size_shares": 6}
    q = maker_16(0.5, cfg)
    assert q.bid < 0.5 < q.ask


def test_maker_16_join_touch():
    cfg = {
        "half_spread": 0.02,
        "safety_buffer": 0.002,
        "quote_size_shares": 6,
        "quote_join_touch": True,
    }
    q = maker_16(0.5, cfg, best_bid=0.47, best_ask=0.53)
    assert q.bid == 0.47
    assert q.ask == 0.53
