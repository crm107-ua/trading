"""
Context Engineering pipeline for the Polymarket NIM decision engine.

Stages (ingest → rank → route → compress) decide what the model is allowed
to know on each request — not how cleverly the prompt is phrased.

Adapted from the Context Engineering discipline notes (wast3 / 0xWast3).
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

import numpy as np

from polymarket.src.ai.env_loader import load_repo_dotenv


class SourceType(Enum):
    DOCUMENT = "document"
    API_RESPONSE = "api_response"
    DATABASE_ROW = "database_row"
    CONVERSATION = "conversation"
    CODE = "code"
    MARKET_SNAPSHOT = "market_snapshot"
    SESSION_STATS = "session_stats"
    DECISION_TRACE = "decision_trace"
    RISK_LIMIT = "risk_limit"


@dataclass
class IngestedChunk:
    """Atomic unit after ingestion. Downstream stages operate only on this shape."""

    content: str
    source_type: SourceType
    source_id: str
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def token_estimate(self) -> int:
        return max(1, len(self.content) // 4)


@dataclass
class RankedChunk:
    chunk: IngestedChunk
    semantic_score: float
    recency_score: float
    authority_score: float

    @property
    def final_score(self) -> float:
        return (
            0.55 * self.semantic_score
            + 0.25 * self.recency_score
            + 0.20 * self.authority_score
        )


class RouteDecision(Enum):
    MINIMAL = "minimal"  # top 3 chunks, fast/cheap model
    STANDARD = "standard"  # top 15 chunks, mid-tier model
    DEEP = "deep"  # full ranked set, frontier model
    TOOL_ONLY = "tool_only"  # no retrieved context, direct tool/rule path


# Default authority priors for maker sources (tune per domain).
DEFAULT_SOURCE_AUTHORITY: dict[str, float] = {
    SourceType.MARKET_SNAPSHOT.value: 0.95,
    SourceType.API_RESPONSE.value: 0.90,
    SourceType.RISK_LIMIT.value: 0.92,
    SourceType.SESSION_STATS.value: 0.75,
    SourceType.DECISION_TRACE.value: 0.65,
    SourceType.DATABASE_ROW.value: 0.85,
    SourceType.CODE.value: 0.85,
    SourceType.DOCUMENT.value: 0.70,
    SourceType.CONVERSATION.value: 0.55,
}

MODEL_BY_ROUTE = {
    RouteDecision.MINIMAL: "meta/llama-3.2-1b-instruct",
    RouteDecision.STANDARD: "meta/llama-3.2-1b-instruct",
    RouteDecision.DEEP: "meta/llama-3.2-1b-instruct",
    RouteDecision.TOOL_ONLY: "meta/llama-3.2-1b-instruct",
}

EMBED_DIM = 64


def context_engineering_enabled() -> bool:
    load_repo_dotenv()
    raw = os.environ.get("NVIDIA_NIM_CONTEXT_ENGINEERING", "1").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def strip_boilerplate(text: str) -> str:
    """Remove headers, footers, nav chrome, repeated page artifacts."""
    text = re.sub(r"Page \d+ of \d+", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_paragraphs(text: str) -> list[str]:
    return [p for p in text.split("\n\n") if p.strip()]


def ingest_document(raw_text: str, source_id: str) -> list[IngestedChunk]:
    """Normalize a raw document into clean, provenance-tagged chunks."""
    cleaned = strip_boilerplate(raw_text)
    paragraphs = split_into_paragraphs(cleaned)
    return [
        IngestedChunk(
            content=para,
            source_type=SourceType.DOCUMENT,
            source_id=source_id,
            metadata={"paragraph_index": i, "char_count": len(para)},
        )
        for i, para in enumerate(paragraphs)
        if len(para.strip()) > 20
    ]


def ingest_kv(
    *,
    label: str,
    payload: dict[str, Any],
    source_type: SourceType,
    source_id: str,
) -> IngestedChunk:
    """Ingest a structured key/value block as one attributable chunk."""
    lines = [f"{label}:"]
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, float):
            lines.append(f"  {key}={value:.6g}")
        else:
            lines.append(f"  {key}={value}")
    return IngestedChunk(
        content="\n".join(lines),
        source_type=source_type,
        source_id=source_id,
        metadata={"keys": [k for k, v in payload.items() if v is not None]},
    )


def ingest_market_snapshot(snapshot: dict[str, Any]) -> list[IngestedChunk]:
    """
    Split a maker snapshot into heterogeneous, provenance-tagged chunks
    so ranking can keep signal and drop noise per request.
    """
    chunks: list[IngestedChunk] = []

    book = {
        "spot_usd": snapshot.get("spot"),
        "strike_usd": snapshot.get("strike"),
        "best_bid": snapshot.get("best_bid"),
        "best_ask": snapshot.get("best_ask"),
        "mark_mid": snapshot.get("mark_price"),
        "last_trade": snapshot.get("last_trade"),
        "feed_age_ms": snapshot.get("feed_age_ms"),
        "time_remaining_s": snapshot.get("time_remaining_s"),
    }
    chunks.append(
        ingest_kv(
            label="market_book",
            payload=book,
            source_type=SourceType.MARKET_SNAPSHOT,
            source_id="snapshot:book",
        )
    )

    edge = {
        "edge_abs": snapshot.get("edge_abs"),
        "min_edge": snapshot.get("min_edge"),
        "proposed_bid": snapshot.get("quote_bid"),
        "proposed_ask": snapshot.get("quote_ask"),
        "quote_size_shares": snapshot.get("quote_size"),
        "spot_move_since_last_quote_usd": _spot_move(snapshot),
        "requote_threshold_usd": snapshot.get("requote_spot_move_usd"),
    }
    chunks.append(
        ingest_kv(
            label="edge_and_quote",
            payload=edge,
            source_type=SourceType.API_RESPONSE,
            source_id="snapshot:edge",
        )
    )

    risk = {
        "inventory_shares": snapshot.get("inventory_shares"),
        "max_inventory_usdc": snapshot.get("max_inventory_usdc"),
        "unrealized_pnl_usdc": snapshot.get("unrealized_pnl_usdc"),
        "avg_entry": snapshot.get("avg_entry"),
        "fair_up": snapshot.get("fair_up"),
        "lock_profit_usdc": snapshot.get("lock_profit_usdc"),
        "max_loss_usdc": snapshot.get("max_loss_usdc"),
    }
    chunks.append(
        ingest_kv(
            label="risk_and_inventory",
            payload=risk,
            source_type=SourceType.RISK_LIMIT,
            source_id="snapshot:risk",
        )
    )

    session = snapshot.get("session_context")
    if isinstance(session, dict) and session:
        chunks.append(
            ingest_kv(
                label="session_stats",
                payload=session,
                source_type=SourceType.SESSION_STATS,
                source_id="session:stats",
            )
        )

    for i, trace in enumerate(snapshot.get("recent_decisions") or []):
        if not isinstance(trace, dict):
            continue
        chunks.append(
            ingest_kv(
                label=f"recent_decision_{i}",
                payload=trace,
                source_type=SourceType.DECISION_TRACE,
                source_id=f"decision:{i}",
            )
        )

    notes = snapshot.get("context_notes")
    if isinstance(notes, str) and notes.strip():
        chunks.extend(ingest_document(notes, source_id="notes:operator"))

    return [c for c in chunks if c.content.strip()]


def _spot_move(snapshot: dict[str, Any]) -> float | None:
    spot = snapshot.get("spot")
    last = snapshot.get("last_quote_spot")
    if spot is None or last is None:
        return None
    return abs(float(spot) - float(last))


def embed(text: str, *, dim: int = EMBED_DIM) -> np.ndarray:
    """
    Lightweight deterministic embedding (hashed char/word n-grams).
    Good enough for intra-snapshot ranking without an external embed API.
    """
    vec = np.zeros(dim, dtype=np.float64)
    normalized = text.lower()
    tokens = re.findall(r"[a-z0-9_./:-]+", normalized)
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        weight = 1.0 + min(3.0, len(token) / 8.0)
        vec[idx] += sign * weight
    # char trigrams for numeric/dense fields
    compact = re.sub(r"\s+", "", normalized)
    for i in range(max(0, len(compact) - 2)):
        tri = compact[i : i + 3]
        digest = hashlib.blake2b(tri.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if digest[5] % 2 == 0 else -1.0
        vec[idx] += 0.35 * sign
    norm = np.linalg.norm(vec)
    if norm < 1e-12:
        return vec
    return vec / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(a, b) / denom)


def rank_chunks(
    query_embedding: np.ndarray,
    chunks: list[IngestedChunk],
    chunk_embeddings: list[np.ndarray],
    source_authority: dict[str, float] | None = None,
    *,
    now: datetime | None = None,
) -> list[RankedChunk]:
    """Rank with semantic + recency + authority (not semantic alone)."""
    authority = {**DEFAULT_SOURCE_AUTHORITY, **(source_authority or {})}
    now = now or datetime.now(timezone.utc)
    ranked: list[RankedChunk] = []

    for chunk, embedding in zip(chunks, chunk_embeddings, strict=True):
        semantic = cosine_similarity(query_embedding, embedding)
        ingested = chunk.ingested_at
        if ingested.tzinfo is None:
            ingested = ingested.replace(tzinfo=timezone.utc)
        age_days = max(0.0, (now - ingested).total_seconds() / 86400.0)
        recency = 1.0 / (1.0 + age_days / 30.0)
        auth = float(authority.get(chunk.source_type.value, 0.5))
        ranked.append(
            RankedChunk(
                chunk=chunk,
                semantic_score=semantic,
                recency_score=recency,
                authority_score=auth,
            )
        )
    return sorted(ranked, key=lambda r: r.final_score, reverse=True)


def estimate_query_complexity(query: str, snapshot: dict[str, Any] | None = None) -> float:
    """Lightweight 0..1 complexity classifier for routing."""
    q = query.lower()
    score = 0.2
    if any(w in q for w in ("inventory", "flatten", "exit", "pnl", "loss", "lock")):
        score += 0.25
    if any(w in q for w in ("ambiguous", "multi", "deep", "regime", "adverse")):
        score += 0.2
    if snapshot:
        edge = snapshot.get("edge_abs")
        min_edge = float(snapshot.get("min_edge") or 0.03)
        if edge is not None:
            ratio = float(edge) / max(min_edge, 1e-9)
            if 0.45 <= ratio <= 1.4:
                score += 0.25  # ambiguous edge band
            elif ratio > 2.0:
                score += 0.05
        if abs(float(snapshot.get("inventory_shares") or 0)) > 1e-9:
            score += 0.15
        if len(snapshot.get("recent_decisions") or []) >= 3:
            score += 0.1
    return max(0.0, min(1.0, score))


def route_request(
    query: str,
    ranked_chunks: list[RankedChunk],
    query_complexity: float,
) -> tuple[RouteDecision, list[RankedChunk]]:
    """Decide how much context this request earns."""
    del query  # reserved for future query-shape heuristics
    top_score = ranked_chunks[0].final_score if ranked_chunks else 0.0

    if top_score > 0.85 and query_complexity < 0.3:
        return RouteDecision.MINIMAL, ranked_chunks[:3]

    if top_score < 0.20 and query_complexity < 0.15:
        # Extremely weak match + trivial query → no retrieval (rules/tools)
        return RouteDecision.TOOL_ONLY, []

    if query_complexity > 0.7 or len(ranked_chunks) > 40:
        return RouteDecision.DEEP, ranked_chunks[:60]

    return RouteDecision.STANDARD, ranked_chunks[:15]


def _information_density(sentence: str) -> float:
    numbers = len(re.findall(r"\d+", sentence))
    capitalized = len(re.findall(r"\b[A-Z][a-z]+", sentence))
    length_penalty = 1.0 / (1.0 + len(sentence) / 100.0)
    return (numbers * 2 + capitalized) * length_penalty


def _has_dense_factual_structure(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    kv_like = sum(1 for ln in lines if "=" in ln or ":" in ln)
    return kv_like >= max(2, len(lines) // 2)


def _detect_best_strategy(chunk: IngestedChunk) -> str:
    if chunk.source_type in {
        SourceType.DATABASE_ROW,
        SourceType.MARKET_SNAPSHOT,
        SourceType.API_RESPONSE,
        SourceType.RISK_LIMIT,
        SourceType.SESSION_STATS,
        SourceType.DECISION_TRACE,
    }:
        return "structural"
    if _has_dense_factual_structure(chunk.content):
        return "extractive"
    return "abstractive"


def _extractive_compress(text: str, target_tokens: int) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not sentences:
        return text[: target_tokens * 4]
    scored = [(s, _information_density(s)) for s in sentences]
    scored.sort(key=lambda x: x[1], reverse=True)
    kept: list[str] = []
    token_count = 0
    for sentence, _ in scored:
        sentence_tokens = max(1, len(sentence) // 4)
        if token_count + sentence_tokens > target_tokens and kept:
            break
        kept.append(sentence)
        token_count += sentence_tokens
    # Preserve original order for readability
    order = {s: i for i, s in enumerate(sentences)}
    kept.sort(key=lambda s: order.get(s, 0))
    return "\n".join(kept)


def _structural_compress(text: str, target_tokens: int) -> str:
    """Keep high-signal key=value lines within budget; drop empty/noise lines."""
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text
    header = lines[0]
    body = lines[1:] if len(lines) > 1 else []
    scored = sorted(
        body,
        key=lambda ln: _information_density(ln),
        reverse=True,
    )
    kept = [header]
    tokens = max(1, len(header) // 4)
    for ln in scored:
        t = max(1, len(ln) // 4)
        if tokens + t > target_tokens and len(kept) > 1:
            break
        kept.append(ln)
        tokens += t
    # Restore original relative order for body lines kept
    body_order = {ln: i for i, ln in enumerate(body)}
    head, rest = kept[0], kept[1:]
    rest.sort(key=lambda ln: body_order.get(ln, 0))
    return "\n".join([head, *rest])


def _abstractive_compress(text: str, target_tokens: int) -> str:
    """
    Dense rewrite without a hard dependency on an LLM SDK.
    Falls back to extractive compression (facts preserved, connective tissue cut).
    """
    load_repo_dotenv()
    if os.environ.get("CONTEXT_ENGINEERING_ABSTRACTIVE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        try:
            import anthropic  # type: ignore

            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=max(32, target_tokens),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Compress this to roughly {target_tokens} tokens.\n"
                            "Preserve every fact, number, and named entity.\n"
                            "Remove only redundancy and connective prose.\n\n"
                            f"Text: {text}"
                        ),
                    }
                ],
            )
            return response.content[0].text
        except Exception:
            pass
    return _extractive_compress(text, target_tokens)


def compress_chunk(
    chunk: IngestedChunk,
    target_tokens: int,
    strategy: str = "auto",
) -> str:
    """Compress toward a token budget without naive truncation."""
    current_tokens = chunk.token_estimate()
    if current_tokens <= target_tokens:
        return chunk.content

    if strategy == "auto":
        strategy = _detect_best_strategy(chunk)

    if strategy == "extractive":
        return _extractive_compress(chunk.content, target_tokens)
    if strategy == "structural":
        return _structural_compress(chunk.content, target_tokens)
    return _abstractive_compress(chunk.content, target_tokens)


@dataclass(frozen=True)
class AssembledContext:
    text: str
    route: RouteDecision
    model_hint: str
    selected_source_ids: list[str]
    chunk_count: int
    token_estimate: int


def build_context_from_chunks(
    query: str,
    chunks: list[IngestedChunk],
    *,
    snapshot: dict[str, Any] | None = None,
    source_authority: dict[str, float] | None = None,
) -> AssembledContext:
    """Full pipeline: ingest(already done) → rank → route → compress → assemble."""
    if not chunks:
        return AssembledContext(
            text="",
            route=RouteDecision.TOOL_ONLY,
            model_hint=MODEL_BY_ROUTE[RouteDecision.TOOL_ONLY],
            selected_source_ids=[],
            chunk_count=0,
            token_estimate=0,
        )

    query_embedding = embed(query)
    chunk_embeddings = [embed(c.content) for c in chunks]
    ranked = rank_chunks(
        query_embedding,
        chunks,
        chunk_embeddings,
        source_authority=source_authority,
    )
    complexity = estimate_query_complexity(query, snapshot)
    decision, selected = route_request(query, ranked, complexity)

    if decision == RouteDecision.TOOL_ONLY:
        return AssembledContext(
            text="",
            route=decision,
            model_hint=MODEL_BY_ROUTE[decision],
            selected_source_ids=[],
            chunk_count=0,
            token_estimate=0,
        )

    budget_per_chunk = {
        RouteDecision.MINIMAL: 120,
        RouteDecision.STANDARD: 180,
        RouteDecision.DEEP: 260,
    }[decision]

    compressed = [compress_chunk(r.chunk, budget_per_chunk) for r in selected]
    text = "\n\n---\n\n".join(c for c in compressed if c.strip())
    return AssembledContext(
        text=text,
        route=decision,
        model_hint=MODEL_BY_ROUTE[decision],
        selected_source_ids=[r.chunk.source_id for r in selected],
        chunk_count=len(selected),
        token_estimate=max(1, len(text) // 4),
    )


def build_maker_context(
    snapshot: dict[str, Any],
    *,
    query: str | None = None,
) -> AssembledContext:
    """
    Context engineering entrypoint for the maker decision engine.
    Ingests snapshot heterogeneity, then ranks/routes/compresses.
    """
    q = query or (
        "Decide quote, cancel_replace, or hold for this Polymarket BTC-5m maker snapshot. "
        "Prioritize edge quality, book stability, inventory risk, and feed freshness."
    )
    chunks = ingest_market_snapshot(snapshot)
    return build_context_from_chunks(q, chunks, snapshot=snapshot)


def iter_provenance(assembled: AssembledContext) -> Iterable[str]:
    for sid in assembled.selected_source_ids:
        yield sid
