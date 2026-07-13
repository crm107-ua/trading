"""Market metadata types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketInfo:
    market_id: str
    question: str
    token_id_up: str
    token_id_down: str | None
    end_time: str
    accepting_orders: bool
    event_title: str
