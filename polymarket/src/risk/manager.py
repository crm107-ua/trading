"""Risk limits (frozen from config/paper.json + PREREG_15)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from polymarket.src.execution.plan import OrderPlan

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "paper.json"


@dataclass
class RiskState:
    bankroll_usdc: float
    inventory_up_usdc: float
    last_feed_ts_ms: int


def load_limits() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def risk_manager_approves(
    market_state: dict,
    order_plan: OrderPlan,
    state: RiskState,
    now_ms: int,
) -> bool:
    limits = load_limits()
    stale_ms = limits["kill_switch_feed_stale_ms"]
    feed_ts = int(market_state.get("feed_ts_ms", now_ms))
    if now_ms - feed_ts > stale_ms:
        return False
    if order_plan.notional_usdc > limits["max_usd_per_window"]:
        return False
    if state.bankroll_usdc <= 0:
        return False
    skew = state.inventory_up_usdc / state.bankroll_usdc
    if skew + order_plan.notional_usdc / state.bankroll_usdc > limits["max_inventory_skew"]:
        return False
    return True
