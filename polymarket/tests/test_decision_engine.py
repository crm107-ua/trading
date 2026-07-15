from __future__ import annotations

import pytest

from polymarket.src.ai.decision_engine import decide_quote_action, rule_guard


def _base_snapshot(**overrides) -> dict:
    snap = {
        "spot": 95000.0,
        "strike": 94900.0,
        "time_remaining_s": 180.0,
        "best_bid": 0.48,
        "best_ask": 0.52,
        "last_trade": 0.50,
        "last_quote_spot": 94990.0,
        "requote_spot_move_usd": 25.0,
        "inventory_shares": 0.0,
        "max_inventory_usdc": 300.0,
        "kill_switch_feed_stale_ms": 2000.0,
        "feed_age_ms": 100.0,
        "quote_bid": 0.47,
        "quote_ask": 0.53,
        "quote_size": 5.0,
    }
    snap.update(overrides)
    return snap


def test_rule_missing_book():
    d = rule_guard(_base_snapshot(best_bid=None))
    assert d is not None
    assert d.action == "hold"
    assert d.source == "rule"


def test_rule_spot_moved_cancel_replace():
    d = rule_guard(_base_snapshot(spot=95030.0, last_quote_spot=95000.0, requote_spot_move_usd=25.0))
    assert d is not None
    assert d.action == "cancel_replace"


def test_rule_stale_feed():
    d = rule_guard(_base_snapshot(feed_age_ms=5000.0, kill_switch_feed_stale_ms=2000.0))
    assert d is not None
    assert d.action == "hold"
    assert d.reason == "rule_stale_feed"


def test_rule_window_closing():
    d = rule_guard(_base_snapshot(time_remaining_s=5.0))
    assert d is not None
    assert d.action == "hold"


def test_decide_uses_rules_without_network(monkeypatch):
    snap = _base_snapshot(best_ask=None)
    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "hold"
    assert decision.source == "rule"
    assert nim is None
