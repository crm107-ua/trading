"""Paper-ultra shaped integration: grind_nim_v2_ultra + Context Engineering."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket.research.local_lab.paper_maker import PaperSession
from polymarket.src.ai.decision_engine import assemble_quote_context, decide_quote_action


ROOT = Path(__file__).resolve().parents[1]
ULTRA_CFG = ROOT / "config" / "maker_demo_grind_nim_v2.json"


def test_ultra_config_label():
    cfg = json.loads(ULTRA_CFG.read_text(encoding="utf-8"))
    assert cfg["demo_label"] == "grind_nim_v2_ultra"
    assert cfg["min_edge"] == 0.036


def test_paper_session_context_extras_and_decisions(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_NIM_MODE", "fast")
    monkeypatch.setenv("NVIDIA_NIM_CONTEXT_ENGINEERING", "1")
    cfg = json.loads(ULTRA_CFG.read_text(encoding="utf-8"))
    session = PaperSession(
        strategy_id="maker_16",
        cfg=cfg,
        out_dir=tmp_path,
        bankroll=float(cfg["initial_capital_usdc"]),
    )
    extras = session._context_extras()
    assert extras["session_context"]["demo_label"] == "grind_nim_v2_ultra"
    assert extras["recent_decisions"] == []

    snap = {
        "spot": 95000.0,
        "strike": 94990.0,
        "time_remaining_s": 200.0,
        "best_bid": 0.48,
        "best_ask": 0.52,
        "last_trade": 0.50,
        "last_quote_spot": 95000.0,
        "requote_spot_move_usd": cfg["requote_spot_move_usd"],
        "inventory_shares": 0.0,
        "mark_price": 0.50,
        "max_inventory_usdc": cfg["max_inventory_usdc"],
        "kill_switch_feed_stale_ms": cfg["kill_switch_feed_stale_ms"],
        "feed_age_ms": 80.0,
        "quote_bid": 0.47,
        "quote_ask": 0.53,
        "quote_size": cfg["quote_size_shares"],
        "fast_path_min_spread_cents": cfg["fast_path_min_spread_cents"],
        "edge_abs": 0.045,
        "min_edge": cfg["min_edge"],
        **extras,
    }
    assembled = assemble_quote_context(snap)
    assert assembled is not None
    assert assembled.chunk_count >= 3
    assert "session:stats" in assembled.selected_source_ids or "snapshot:edge" in assembled.selected_source_ids

    decision, nim = decide_quote_action(snapshot=snap, use_cache=False)
    assert decision.action == "quote"
    assert decision.source == "rule"
    assert nim is None
    session._remember_decision(decision, kind="quote")
    assert len(session._recent_decisions) == 1
    assert session._recent_decisions[0]["action"] == "quote"
