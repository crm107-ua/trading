"""Fair value and executable edge (frozen params from PREREG_15)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from polymarket.src.data.book_utils import best_bid_ask, top_levels
from polymarket.src.signals.features import MarketFeatures

SIGMA_ANNUAL = 0.55
MIN_NET_EDGE = 0.02
SAFETY_BUFFER = 0.005
TAKER_FEE = 0.02
SLIPPAGE_PER_100 = 0.003


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def estimate_fair_values(features: MarketFeatures) -> dict[str, float]:
    t_years = max(features.time_remaining_s / (365.25 * 24 * 3600), 1e-8)
    denom = SIGMA_ANNUAL * math.sqrt(t_years)
    z = (features.spot - features.strike) / denom if denom > 0 else 0.0
    p_up = max(0.001, min(0.999, _norm_cdf(z)))
    return {"up": p_up, "down": 1.0 - p_up}


def vwap_ask(asks: list[dict], size_shares: float) -> float | None:
    if not asks or size_shares <= 0:
        return None
    remaining = size_shares
    cost = 0.0
    filled = 0.0
    for level in sorted(asks, key=lambda x: float(x["price"])):
        price = float(level["price"])
        avail = float(level["size"])
        take = min(remaining, avail)
        cost += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-9:
            break
    if filled <= 0:
        return None
    if remaining > 1e-6:
        return None  # insufficient depth
    return cost / filled


def slippage_est(size_shares: float) -> float:
    return SLIPPAGE_PER_100 * (size_shares / 100.0)


@dataclass
class Opportunity:
    side: str
    fair: float
    vwap: float
    edge_bruto: float
    net_edge: float
    size_shares: float


def find_executable_edge(
    market_state: dict[str, Any],
    fair_values: dict[str, float],
    size_shares: float = 100.0,
) -> Opportunity | None:
    bids = market_state.get("bids") or []
    asks = market_state.get("asks") or []
    tb, ta = top_levels(bids, asks, 10)
    vwap = vwap_ask(ta, size_shares)
    if vwap is None:
        return None
    fair_up = fair_values["up"]
    bb, ba = best_bid_ask(bids, asks)
    spread_half = 0.0
    if bb is not None and ba is not None:
        spread_half = (ba - bb) / 2
    edge_bruto = fair_up - vwap
    friction = TAKER_FEE * vwap + spread_half + slippage_est(size_shares) + SAFETY_BUFFER
    net_edge = edge_bruto - friction
    if net_edge <= MIN_NET_EDGE:
        return None
    return Opportunity(
        side="buy_up",
        fair=fair_up,
        vwap=vwap,
        edge_bruto=edge_bruto,
        net_edge=net_edge,
        size_shares=size_shares,
    )
