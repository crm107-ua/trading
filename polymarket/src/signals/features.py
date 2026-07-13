"""Feature engineering from market state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from polymarket.src.data.book_utils import best_bid_ask


@dataclass
class MarketFeatures:
    spot: float
    strike: float
    time_remaining_s: float
    best_bid: float | None
    best_ask: float | None
    mid: float | None
    spread: float | None
    momentum_1m: float


def build_market_features(market_state: dict[str, Any]) -> MarketFeatures:
    spot = float(market_state["spot"])
    strike = float(market_state["strike"])
    time_remaining_s = float(market_state.get("time_remaining_s", 300.0))
    bids = market_state.get("bids") or []
    asks = market_state.get("asks") or []
    best_bid, best_ask = best_bid_ask(bids, asks)
    mid = None
    spread = None
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
    elif best_ask is not None:
        mid = best_ask
    elif best_bid is not None:
        mid = best_bid
    momentum_1m = float(market_state.get("momentum_1m", 0.0))
    return MarketFeatures(
        spot=spot,
        strike=strike,
        time_remaining_s=time_remaining_s,
        best_bid=best_bid,
        best_ask=best_ask,
        mid=mid,
        spread=spread,
        momentum_1m=momentum_1m,
    )
