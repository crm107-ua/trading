from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from polymarket.src.ai.context_engineering import (
    RouteDecision,
    SourceType,
    build_context_from_chunks,
    build_maker_context,
    compress_chunk,
    embed,
    estimate_query_complexity,
    ingest_document,
    ingest_market_snapshot,
    rank_chunks,
    route_request,
    strip_boilerplate,
)


def test_strip_boilerplate_and_ingest_document():
    raw = "Page 1 of 3\n\nAlpha edge is 3.5 percent on BTC.\n\n\n\nNav junk\n\nBeta risk cap is 2 USDC."
    chunks = ingest_document(raw, source_id="doc:1")
    assert all(c.source_type == SourceType.DOCUMENT for c in chunks)
    assert all(c.source_id == "doc:1" for c in chunks)
    assert all("Page " not in c.content for c in chunks)
    assert len(chunks) >= 1


def test_ingest_market_snapshot_splits_provenance():
    snap = {
        "spot": 95000.0,
        "strike": 94950.0,
        "best_bid": 0.48,
        "best_ask": 0.52,
        "mark_price": 0.50,
        "edge_abs": 0.04,
        "min_edge": 0.03,
        "inventory_shares": 2.0,
        "max_inventory_usdc": 5.0,
        "session_context": {"fills": 1, "demo_label": "grind_nim_v2_ultra"},
        "recent_decisions": [{"action": "hold", "reason": "rule_weak_edge"}],
        "context_notes": "Operator note: prefer fewer high-quality posts over spam quotes.",
    }
    chunks = ingest_market_snapshot(snap)
    types = {c.source_type for c in chunks}
    ids = {c.source_id for c in chunks}
    assert SourceType.MARKET_SNAPSHOT in types
    assert SourceType.RISK_LIMIT in types
    assert SourceType.SESSION_STATS in types
    assert SourceType.DECISION_TRACE in types
    assert "snapshot:book" in ids
    assert "session:stats" in ids


def test_rank_prefers_authority_when_semantic_ties():
    query = embed("edge quote market book")
    now = datetime.now(timezone.utc)
    from polymarket.src.ai.context_engineering import IngestedChunk

    stale_forum = IngestedChunk(
        content="edge quote market book discussion from forum",
        source_type=SourceType.CONVERSATION,
        source_id="forum",
        ingested_at=now - timedelta(days=400),
    )
    live_book = IngestedChunk(
        content="edge quote market book live api",
        source_type=SourceType.API_RESPONSE,
        source_id="api",
        ingested_at=now,
    )
    ranked = rank_chunks(
        query,
        [stale_forum, live_book],
        [embed(stale_forum.content), embed(live_book.content)],
        now=now,
    )
    assert ranked[0].chunk.source_id == "api"
    assert ranked[0].final_score >= ranked[1].final_score


def test_route_minimal_on_simple_high_confidence():
    from polymarket.src.ai.context_engineering import IngestedChunk, RankedChunk

    chunk = IngestedChunk(
        content="market_book:\n  spot_usd=95000",
        source_type=SourceType.MARKET_SNAPSHOT,
        source_id="snapshot:book",
    )
    ranked = [
        RankedChunk(chunk=chunk, semantic_score=0.95, recency_score=1.0, authority_score=0.95)
    ]
    decision, selected = route_request("simple quote", ranked, query_complexity=0.1)
    assert decision == RouteDecision.MINIMAL
    assert len(selected) == 1


def test_compress_structural_keeps_budget():
    from polymarket.src.ai.context_engineering import IngestedChunk

    body = "edge_and_quote:\n" + "\n".join(
        [f"  field_{i}={i * 1.23456789}" for i in range(40)]
    )
    chunk = IngestedChunk(
        content=body,
        source_type=SourceType.API_RESPONSE,
        source_id="snapshot:edge",
    )
    out = compress_chunk(chunk, target_tokens=40, strategy="structural")
    assert chunk.token_estimate() > 40
    assert max(1, len(out) // 4) <= 55  # small slack for headers
    assert "edge_and_quote" in out


def test_build_maker_context_assembles_nonempty():
    snap = {
        "spot": 95000.0,
        "strike": 94980.0,
        "best_bid": 0.45,
        "best_ask": 0.55,
        "mark_price": 0.50,
        "edge_abs": 0.05,
        "min_edge": 0.036,
        "quote_bid": 0.44,
        "quote_ask": 0.56,
        "quote_size": 5,
        "inventory_shares": 0,
        "max_inventory_usdc": 2.5,
        "feed_age_ms": 80,
        "time_remaining_s": 200,
        "session_context": {"demo_label": "grind_nim_v2_ultra", "fills": 0},
    }
    assembled = build_maker_context(snap)
    assert assembled.route in {
        RouteDecision.MINIMAL,
        RouteDecision.STANDARD,
        RouteDecision.DEEP,
    }
    assert assembled.chunk_count >= 1
    assert "market_book" in assembled.text or "edge_and_quote" in assembled.text
    assert assembled.token_estimate > 0


def test_estimate_complexity_rises_with_inventory_and_ambiguous_edge():
    low = estimate_query_complexity("quote now", {"edge_abs": 0.10, "min_edge": 0.03})
    high = estimate_query_complexity(
        "ambiguous inventory exit pnl",
        {
            "edge_abs": 0.035,
            "min_edge": 0.03,
            "inventory_shares": 3.0,
            "recent_decisions": [{}, {}, {}],
        },
    )
    assert high > low


def test_embed_is_deterministic_and_normalized():
    a = embed("edge_abs=0.04 min_edge=0.03")
    b = embed("edge_abs=0.04 min_edge=0.03")
    assert np.allclose(a, b)
    assert abs(float(np.linalg.norm(a)) - 1.0) < 1e-6


def test_strip_boilerplate_collapses_blank_lines():
    assert "\n\n\n" not in strip_boilerplate("a\n\n\n\nb")


def test_build_context_from_empty_chunks_is_tool_only():
    assembled = build_context_from_chunks("anything", [])
    assert assembled.route == RouteDecision.TOOL_ONLY
    assert assembled.text == ""
