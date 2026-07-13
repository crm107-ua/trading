"""CLOB book normalization — Polymarket WS order is not guaranteed best-first."""

from __future__ import annotations

from typing import Any


def _price(level: dict[str, Any]) -> float:
    return float(level["price"])


def best_bid_ask(bids: list[dict], asks: list[dict]) -> tuple[float | None, float | None]:
    best_bid = max((_price(b) for b in bids), default=None)
    best_ask = min((_price(a) for a in asks), default=None)
    return best_bid, best_ask


def top_levels(bids: list[dict], asks: list[dict], n: int = 10) -> tuple[list[dict], list[dict]]:
    """Return top-n bids (desc price) and asks (asc price) near touch."""
    sb = sorted(bids, key=_price, reverse=True)[:n]
    sa = sorted(asks, key=_price)[:n]
    return sb, sa


def truncate_book(levels: list[dict], n: int, *, side: str) -> list[dict]:
    """Top-n levels near touch for storage."""
    if not levels:
        return []
    reverse = side == "bid"
    return sorted(levels, key=_price, reverse=reverse)[:n]
