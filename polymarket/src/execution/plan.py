"""Execution plan builder."""

from __future__ import annotations

from dataclasses import dataclass

from polymarket.src.pricing.fair_value import Opportunity


@dataclass
class OrderPlan:
    token_side: str
    order_type: str
    price: float
    size_shares: float
    notional_usdc: float


@dataclass
class PositionPlan:
    action: str
    opportunity: Opportunity


def choose_position_structure(_market_state: dict, opportunity: Opportunity) -> PositionPlan:
    return PositionPlan(action="open_long_up", opportunity=opportunity)


def build_execution_plan(_market_state: dict, position: PositionPlan) -> OrderPlan:
    opp = position.opportunity
    return OrderPlan(
        token_side="up",
        order_type="FAK",
        price=opp.vwap,
        size_shares=opp.size_shares,
        notional_usdc=opp.vwap * opp.size_shares,
    )
