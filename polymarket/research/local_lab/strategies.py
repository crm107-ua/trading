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


def maker_16(
    fair_up: float,
    cfg: dict[str, Any],
    best_bid: float | None = None,
    best_ask: float | None = None,
) -> QuoteIntent:
    """Frozen #16 — PREREG_16 params; optional join-touch for paper liquidity."""
    hs = float(cfg["half_spread"])
    buf = float(cfg["safety_buffer"])
    size = float(cfg["quote_size_shares"])
    bid = _clip(fair_up - hs - buf, 0.01, 0.98)
    ask = _clip(fair_up + hs + buf, 0.02, 0.99)
    if cfg.get("quote_join_touch") and best_bid is not None and best_ask is not None:
        # Join touch only when still on the safe side of fair
        if best_bid <= fair_up - buf:
            bid = _clip(best_bid, 0.01, 0.98)
        if best_ask >= fair_up + buf:
            ask = _clip(best_ask, 0.02, 0.99)
        if ask <= bid:
            ask = _clip(bid + 0.02, 0.02, 0.99)
    return QuoteIntent(bid, ask, size, "maker_16", "pre-reg frozen")


def apply_inventory_skew(
    quote: QuoteIntent,
    *,
    inventory_shares: float,
    cfg: dict[str, Any],
    mid: float | None = None,
) -> QuoteIntent | None:
    """
    Inventory control:
    - any long → only ask (reduce); any short → only bid
    - at/over cap → still quote reducing side (never mute exits)
    """
    size = float(cfg["quote_size_shares"])
    max_inv_shares = float(cfg.get("max_inventory_shares", size * 2))
    skew_shares = float(cfg.get("inventory_skew_shares", size))
    bid, ask = quote.bid, quote.ask
    note = quote.note
    tick = 0.01
    exit_size = min(size, abs(inventory_shares)) if abs(inventory_shares) > 1e-9 else size

    if inventory_shares > 1e-9:
        # Reduce long — join ask touch / mid+tick
        bid = 0.01
        if mid is not None:
            ask = _clip(mid + tick, 0.02, 0.99)
        elif ask >= 0.98:
            return None
        note = f"{note}|exit_long".strip("|")
        return QuoteIntent(bid, ask, exit_size, quote.strategy_id, note)
    if inventory_shares < -1e-9:
        ask = 0.99
        if mid is not None:
            bid = _clip(mid - tick, 0.01, 0.98)
        elif bid <= 0.02:
            return None
        note = f"{note}|exit_short".strip("|")
        return QuoteIntent(bid, ask, exit_size, quote.strategy_id, note)

    # Flat book: refuse to open if quote would breach caps later; keep entry quote
    if abs(inventory_shares) >= max_inv_shares - 1e-9:
        return None
    if ask - bid < 0.01:
        return None
    # Optional soft skew unused when flat
    _ = skew_shares
    return QuoteIntent(bid, ask, quote.size_shares, quote.strategy_id, note)


def wide_spread_only(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """Probe #17-local: quote solo si el libro retail está muy ancho."""
    min_spread = float(cfg.get("min_market_spread", 0.04))
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


def maker_edge(
    fair_up: float,
    best_bid: float | None,
    best_ask: float | None,
    spot: float,
    strike: float,
    cfg: dict[str, Any],
) -> QuoteIntent | None:
    """
    Selective maker: quote only when |fair - mid| >= min_edge.
    Cheap market → bid at touch; rich market → ask at touch.
    High-margin mode: tiered size + min expected pnl filter.
    """
    if best_bid is None or best_ask is None:
        return None
    mid = (best_bid + best_ask) / 2.0
    min_edge = float(cfg.get("min_edge", 0.03))
    sigma = float(cfg.get("sigma_mid", 0.03))
    edge = fair_up - mid
    abs_edge = abs(edge)
    z = abs_edge / max(sigma, 1e-6)
    min_z = float(cfg.get("min_z", 1.0))
    if abs_edge < min_edge or z < min_z:
        return None

    # Evita lotería (YES a 0.09 / 0.90): ahí el "edge" vs fair suele ser ruido de cola.
    mid_lo = float(cfg.get("min_quote_mid", 0.0) or 0.0)
    mid_hi = float(cfg.get("max_quote_mid", 1.0) or 1.0)
    if mid_lo > 0 and mid < mid_lo:
        return None
    if mid_hi < 1 and mid > mid_hi:
        return None

    # Optional time window (seconds remaining) — avoid open chaos / last-second junk.
    t_rem = cfg.get("_time_remaining_s")
    t_min = float(cfg.get("quote_time_min_s", 0) or 0)
    t_max = float(cfg.get("quote_time_max_s", 0) or 0)
    if t_rem is not None:
        if t_min > 0 and float(t_rem) < t_min:
            return None
        if t_max > 0 and float(t_rem) > t_max:
            return None

    hs = float(cfg["half_spread"])
    buf = float(cfg["safety_buffer"])
    base_size = float(cfg["quote_size_shares"])
    max_mult = float(cfg.get("max_size_mult", 2.5))
    # Tiered sizing: mediocre edge → small; premium edge → full throttle.
    soft = float(cfg.get("soft_edge", min_edge * 1.4))
    hard = float(cfg.get("hard_edge", min_edge * 2.2))
    if cfg.get("kelly_sizing", True):
        if abs_edge >= hard:
            f = max_mult
        elif abs_edge >= soft:
            f = 1.0 + (max_mult - 1.0) * (abs_edge - soft) / max(hard - soft, 1e-6)
        else:
            f = float(cfg.get("soft_size_frac", 0.55))
        size = max(1.0, round(base_size * f, 2))
    else:
        size = base_size
    size = max(1.0, round(size * float(cfg.get("_runtime_size_scale", 1.0) or 1.0), 2))
    # Hard cap — evita size 42×3.0=126 que tumba la sesión de 100€
    hard_cap = float(cfg.get("max_quote_size_shares", 0) or 0)
    if hard_cap > 0:
        size = min(size, hard_cap)

    # Skip unless expected capture (edge * size * capture_frac) clears hurdle on $100 book.
    capture = float(cfg.get("expected_capture_frac", 0.45))
    min_ev = float(cfg.get("min_expected_pnl_usdc", 0.0) or 0.0)
    if min_ev > 0 and abs_edge * size * capture < min_ev:
        return None

    mkt_spread = best_ask - best_bid
    if mkt_spread < float(cfg.get("min_market_spread", 0.0)):
        return None

    if edge >= min_edge:
        bid = _clip(best_bid if cfg.get("quote_join_touch", True) else fair_up - hs - buf, 0.01, 0.98)
        if bid >= mid - 1e-9:
            return None
        # No bids en colas extremas aunque el mid pase el filtro por un tick.
        if mid_lo > 0 and bid < mid_lo:
            return None
        ask = 0.99
        return QuoteIntent(bid, ask, size, "maker_edge", f"cheap e={abs_edge:.3f} sz={size}")
    ask = _clip(best_ask if cfg.get("quote_join_touch", True) else fair_up + hs + buf, 0.02, 0.99)
    if ask <= mid + 1e-9:
        return None
    if mid_hi < 1 and ask > mid_hi:
        return None
    bid = 0.01
    return QuoteIntent(bid, ask, size, "maker_edge", f"rich e={abs_edge:.3f} sz={size}")


STRATEGIES = {
    "maker_16": maker_16,
    "wide_spread_probe": wide_spread_only,
    "tight_mid_fade": tight_mid_fade,
    "maker_edge": maker_edge,
}
