#!/usr/bin/env python3
"""Async Polymarket bot skeleton — paper mode only until screen PASS."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from polymarket.research.collectors.market_discovery import discover_btc_updown
from polymarket.src.execution.plan import build_execution_plan, choose_position_structure
from polymarket.src.pricing.fair_value import estimate_fair_values, find_executable_edge
from polymarket.src.risk.manager import RiskState, risk_manager_approves
from polymarket.src.signals.features import build_market_features

SCREEN_REPORT = (
    Path(__file__).resolve().parents[1]
    / "research"
    / "output"
    / "poly_15"
    / "20260713_screen"
    / "report.json"
)


def screen_passed() -> bool:
    if not SCREEN_REPORT.exists():
        return False
    data = json.loads(SCREEN_REPORT.read_text(encoding="utf-8"))
    return data.get("verdict") == "PASA" and data.get("hypothesis_judged") is True


async def fetch_market_state(token_id: str) -> dict | None:
    import httpx

    from polymarket.src.data.btc_spot import fetch_btc_spot_async

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            spot, _src = await fetch_btc_spot_async(client)
        except RuntimeError:
            return None
        cr = await client.get(
            "https://clob.polymarket.com/book",
            params={"token_id": token_id},
        )
    if cr.status_code != 200:
        return None
    book = cr.json()
    return {
        "spot": spot,
        "strike": spot,  # placeholder — real strike from Gamma metadata
        "time_remaining_s": 300.0,
        "bids": book.get("bids") or [],
        "asks": book.get("asks") or [],
        "feed_ts_ms": int(time.time() * 1000),
        "momentum_1m": 0.0,
    }


async def submit_orders_paper(order_plan, log: list) -> None:
    log.append(
        {
            "ts": time.time(),
            "type": order_plan.order_type,
            "side": order_plan.token_side,
            "price": order_plan.price,
            "size": order_plan.size_shares,
            "notional": order_plan.notional_usdc,
        }
    )


async def run_paper_maker(cycles: int = 3) -> None:
    """#16 paper maker — lab local (sin on-chain)."""
    from polymarket.research.local_lab.paper_maker import run_paper_session

    minutes = max(cycles * 2, 10)  # cycles arg ~ proxy minutes for CLI compat
    report = await run_paper_session("maker_16", minutes=float(minutes))
    print(json.dumps(report, indent=2, ensure_ascii=False))


async def run_polymarket_bot(mode: str = "paper", cycles: int = 3) -> None:
    if mode == "paper-maker":
        await run_paper_maker(cycles)
        return
    if mode == "live":
        raise SystemExit("Live mode disabled until screen PASS + 30d depth")
    if not screen_passed():
        print("Paper bot blocked: screen verdict != PASA (see report.json)")
        return

    markets = discover_btc_updown()
    if not markets:
        print("No markets found")
        return
    token_id = markets[0].token_id_up
    state = RiskState(bankroll_usdc=10_000.0, inventory_up_usdc=0.0, last_feed_ts_ms=0)
    paper_log: list = []

    for _ in range(cycles):
        market_state = await fetch_market_state(token_id)
        if market_state is None:
            await asyncio.sleep(1.0)
            continue
        features = build_market_features(market_state)
        fair_values = estimate_fair_values(features)
        opportunity = find_executable_edge(market_state, fair_values)
        if opportunity is None:
            await asyncio.sleep(2.0)
            continue
        position_plan = choose_position_structure(market_state, opportunity)
        order_plan = build_execution_plan(market_state, position_plan)
        now_ms = int(time.time() * 1000)
        if risk_manager_approves(market_state, order_plan, state, now_ms):
            await submit_orders_paper(order_plan, paper_log)
        await asyncio.sleep(2.0)

    out = Path(__file__).resolve().parents[1] / "data_local" / "paper_log.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(paper_log, indent=2), encoding="utf-8")
    print(f"Paper cycles done; {len(paper_log)} orders logged -> {out}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="paper", choices=["paper", "paper-maker", "live"])
    p.add_argument("--cycles", type=int, default=3)
    p.add_argument("--minutes", type=float, default=None, help="Paper-maker duration (min)")
    args = p.parse_args()
    if args.mode == "paper-maker":
        from polymarket.research.local_lab.paper_maker import run_paper_session

        mins = args.minutes if args.minutes is not None else float(max(args.cycles * 2, 10))
        report = asyncio.run(run_paper_session("maker_16", minutes=mins))
        print(json.dumps(report, indent=2))
        return
    asyncio.run(run_polymarket_bot(mode=args.mode, cycles=args.cycles))


if __name__ == "__main__":
    main()
