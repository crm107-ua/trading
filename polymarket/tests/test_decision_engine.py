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
        "mark_price": 0.50,
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


def test_rule_inventory_uses_mark_not_btc_spot():
    # 5 shares * BTC spot 65000 would wrongly trip; mark 0.5 → 2.5 USDC under cap 8
    d = rule_guard(
        _base_snapshot(
            inventory_shares=5.0,
            spot=65000.0,
            last_quote_spot=65000.0,
            mark_price=0.5,
            max_inventory_usdc=8.0,
        )
    )
    assert d is None
    d2 = rule_guard(_base_snapshot(inventory_shares=20.0, spot=65000.0, mark_price=0.5, max_inventory_usdc=8.0))
    assert d2 is not None
    assert d2.reason == "rule_inventory_cap"


def test_coerce_hold_to_quote_when_reason_says_capturing():
    from polymarket.src.ai.decision_engine import _coerce_action

    assert _coerce_action("hold", "spread is worth capturing", 0.8, 0.55) == "quote"
    assert _coerce_action("hold", "uncertain book", 0.8, 0.55) == "hold"


def test_fast_path_quotes_without_nim(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_MODE", "fast")
    snap = _base_snapshot()
    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "quote"
    assert decision.reason == "rule_fast_path"
    assert decision.source == "rule"
    assert nim is None


def test_rule_guard_respects_min_spread_cents():
    # 0.5¢ book allowed when snapshot umbral=0.5
    d = rule_guard(
        _base_snapshot(
            best_bid=0.48,
            best_ask=0.485,
            fast_path_min_spread_cents=0.5,
        )
    )
    assert d is None
    d2 = rule_guard(
        _base_snapshot(
            best_bid=0.48,
            best_ask=0.485,
            fast_path_min_spread_cents=1.0,
        )
    )
    assert d2 is not None
    assert d2.reason == "rule_tight_market_spread"


def test_nim_error_falls_back_to_quote_on_edge(monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_MODE", "hybrid")
    monkeypatch.setenv("NVIDIA_NIM_GRIND", "1")
    monkeypatch.setenv("NVIDIA_NIM_PROFIT_ASSIST", "0")

    def _boom(*_a, **_k):
        raise TimeoutError("nim down")

    monkeypatch.setattr(
        "polymarket.src.ai.decision_engine.robust_chat_completion",
        _boom,
    )
    snap = _base_snapshot(
        edge_abs=0.05,
        min_edge=0.02,
        fast_path_min_spread_cents=1.0,
        best_bid=0.48,
        best_ask=0.52,
    )
    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "quote"
    assert decision.reason == "rule_nim_fallback_edge"
    assert nim is None


def test_decide_uses_rules_without_network(monkeypatch):
    snap = _base_snapshot(best_ask=None)
    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "hold"
    assert decision.source == "rule"
    assert nim is None
