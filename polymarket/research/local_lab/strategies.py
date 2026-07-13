"""Paper-maker strategies for local lab (non-binding)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QuoteIntent:
    bid: float
    ask: float
    size_shares: float
    strategy_id: str
    note: str = ""


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def maker_16(fair_up: float, cfg: dict[str, Any]) -> QuoteIntent:
    """Frozen #16 — PREREG_16 params only."""
    hs = float(cfg["half_spread"])
    buf = float(cfg["safety_buffer"])
    size = float(cfg["quote_size_shares"])
    bid = _clip(fair_up - hs - buf, 0.01, 0.98)
    ask = _clip(fair_up + hs + buf, 0.02, 0.99)
    return QuoteIntent(bid, ask, size, "maker_16", "pre-reg frozen")


def wide_spread_only(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    cfg: dict[str, Any],
    min_spread: float = 0.05,
) -> QuoteIntent | None:
    """Probe #17-local: quote solo si el libro retail está muy ancho."""
    if best_bid is None or best_ask is None:
        return None
    if best_ask - best_bid < min_spread:
        return None
    q = maker_16(fair_up, cfg)
    return QuoteIntent(q.bid, q.ask, q.size_shares, "wide_spread_probe", f"market_spread>={min_spread}")


def tight_mid_fade(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """Probe #18-local: solo ask cuando spot>strike y mid está barato vs fair."""
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2
    if spot <= strike or fair_up - mid < 0.03:
        return None
    size = float(cfg["quote_size_shares"])
    ask = _clip(fair_up + float(cfg["half_spread"]), 0.02, 0.99)
    bid = _clip(fair_up - float(cfg["half_spread"]) - 0.02, 0.01, 0.98)
    return QuoteIntent(bid, ask, size, "tight_mid_fade", "spot>strike & mid stale")


STRATEGIES = {
    "maker_16": maker_16,
    "wide_spread_probe": wide_spread_only,
    "tight_mid_fade": tight_mid_fade,
}
