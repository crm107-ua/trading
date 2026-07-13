#!/usr/bin/env python3
"""
Exploratory edge analysis on real phase-A / smoke panels.

NOT a binding screen — labels EXPLORATORY. Requires >=30d for #16 verdict.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from polymarket.research.poly_lab.replay_panel import ReplayPanel, build_replay_panel
from polymarket.src.data.book_utils import best_bid_ask, top_levels
from polymarket.src.pricing.fair_value import (
    MIN_NET_EDGE,
    estimate_fair_values,
    find_executable_edge,
    slippage_est,
    TAKER_FEE,
    SAFETY_BUFFER,
)
from polymarket.src.signals.features import build_market_features

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "research" / "output" / "poly_explore"
INITIAL_CAPITAL = 10_000.0

# Frozen #16 params
HALF_SPREAD = 0.015
SAFETY_BUFFER = 0.005
QUOTE_SIZE = 100.0
REQUOTE_SPOT_USD = 25.0
ADVERSE_WINDOW_NS = 500_000_000
ADVERSE_SPOT_USD = 10.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _maker_quotes(fair_up: float) -> tuple[float, float]:
    bid = _clip(fair_up - HALF_SPREAD - SAFETY_BUFFER, 0.01, 0.98)
    ask = _clip(fair_up + HALF_SPREAD + SAFETY_BUFFER, 0.02, 0.99)
    return bid, ask


@dataclass
class MakerFill:
    ts_ns: int
    side: str
    price: float
    fair: float
    spot: float
    spread_captured: float
    adverse: bool
    adverse_cost: float


@dataclass
class MakerResult:
    fills: list[MakerFill] = field(default_factory=list)
    spread_captured_total: float = 0.0
    adverse_cost_total: float = 0.0
    inventory_pnl: float = 0.0
    net_pnl: float = 0.0
    adverse_rate: float = 0.0
    fill_count: int = 0
    cost_basis: dict[str, float] = field(default_factory=dict)
    inventory_shares: dict[str, float] = field(default_factory=dict)


def simulate_maker(panel: ReplayPanel, btc_ts: list[int], btc_prices: list[float]) -> MakerResult:
    result = MakerResult()
    inventory_shares: dict[str, float] = {}
    last_quote_spot: dict[str, float] = {}
    our_bid: dict[str, float] = {}
    our_ask: dict[str, float] = {}
    last_trade_seen: dict[str, float | None] = {}

    for tick in panel.ticks:
        mid = tick.market_id
        feats = build_market_features(
            {
                "spot": tick.spot,
                "strike": tick.strike,
                "time_remaining_s": tick.time_remaining_s,
                "bids": tick.bids,
                "asks": tick.asks,
            }
        )
        fair = estimate_fair_values(feats)["up"]
        prev_spot = last_quote_spot.get(mid)
        if prev_spot is None or abs(tick.spot - prev_spot) >= REQUOTE_SPOT_USD:
            bid, ask = _maker_quotes(fair)
            our_bid[mid] = bid
            our_ask[mid] = ask
            last_quote_spot[mid] = tick.spot

        if tick.last_trade is None:
            continue
        prev_lt = last_trade_seen.get(mid)
        if prev_lt is not None and abs(tick.last_trade - prev_lt) < 1e-9:
            continue
        last_trade_seen[mid] = tick.last_trade

        fill_side = None
        fill_price = None
        ob = our_bid.get(mid)
        oa = our_ask.get(mid)
        lt = tick.last_trade
        # Fill only if trade prints through our quote (not unrelated deep-book trades)
        if ob is not None and lt <= ob + 1e-6 and abs(lt - ob) <= 0.02:
            fill_side = "bid"
            fill_price = ob
        elif oa is not None and lt >= oa - 1e-6 and abs(lt - oa) <= 0.02:
            fill_side = "ask"
            fill_price = oa

        if fill_side is None:
            continue

        spread_cap = (HALF_SPREAD + SAFETY_BUFFER) * QUOTE_SIZE

        # Spot 500ms later
        target_ns = tick.recv_ts_ns + ADVERSE_WINDOW_NS
        bi = max(__import__("bisect").bisect_right(btc_ts, target_ns) - 1, 0)
        spot_later = btc_prices[bi]
        adverse = False
        adverse_cost = 0.0
        if fill_side == "bid" and spot_later < tick.spot - ADVERSE_SPOT_USD:
            adverse = True
            adverse_cost = (tick.spot - spot_later) / tick.spot * QUOTE_SIZE * fill_price
        elif fill_side == "ask" and spot_later > tick.spot + ADVERSE_SPOT_USD:
            adverse = True
            adverse_cost = (spot_later - tick.spot) / tick.spot * QUOTE_SIZE * fill_price

        result.fills.append(
            MakerFill(
                ts_ns=tick.recv_ts_ns,
                side=fill_side,
                price=fill_price,
                fair=fair,
                spot=tick.spot,
                spread_captured=spread_cap,
                adverse=adverse,
                adverse_cost=adverse_cost,
            )
        )
        result.spread_captured_total += spread_cap
        result.adverse_cost_total += adverse_cost
        result.fill_count += 1
        if fill_side == "bid":
            result.inventory_shares[mid] = result.inventory_shares.get(mid, 0.0) + QUOTE_SIZE
            result.cost_basis[mid] = result.cost_basis.get(mid, 0.0) + fill_price * QUOTE_SIZE
        else:
            result.inventory_shares[mid] = result.inventory_shares.get(mid, 0.0) - QUOTE_SIZE
            result.cost_basis[mid] = result.cost_basis.get(mid, 0.0) - fill_price * QUOTE_SIZE

    # Resolution PnL
    for mid, winfo in panel.windows.items():
        shares = result.inventory_shares.get(mid, 0.0)
        if abs(shares) < 1e-6:
            continue
        payout = shares * float(winfo["resolved_up"])
        result.inventory_pnl += payout - result.cost_basis.get(mid, 0.0)

    result.net_pnl = result.spread_captured_total - result.adverse_cost_total + result.inventory_pnl
    if result.fill_count:
        result.adverse_rate = sum(1 for f in result.fills if f.adverse) / result.fill_count
    return result


@dataclass
class TakerResult:
    opportunities: int = 0
    windows_with_edge: int = 0
    edge_sum: float = 0.0
    friction_sum: float = 0.0
    hypothetical_pnl: float = 0.0
    stale_mid_avg: float = 0.0
    market_spread_avg: float = 0.0


def simulate_taker(panel: ReplayPanel) -> TakerResult:
    result = TakerResult()
    stale_samples: list[float] = []
    spread_samples: list[float] = []
    seen_windows: set[str] = set()
    edge_windows: set[str] = set()

    for tick in panel.ticks:
        state = {
            "spot": tick.spot,
            "strike": tick.strike,
            "time_remaining_s": tick.time_remaining_s,
            "bids": tick.bids,
            "asks": tick.asks,
        }
        feats = build_market_features(state)
        fair = estimate_fair_values(feats)["up"]
        if tick.best_bid is not None and tick.best_ask is not None:
            mid = (tick.best_bid + tick.best_ask) / 2
            stale_samples.append(abs(mid - fair))
            spread_samples.append(tick.best_ask - tick.best_bid)

        opp = find_executable_edge(state, {"up": fair}, size_shares=QUOTE_SIZE)
        if opp is None:
            continue
        result.opportunities += 1
        edge_windows.add(tick.market_id)
        friction = (
            TAKER_FEE * opp.vwap * opp.size_shares
            + slippage_est(opp.size_shares) * opp.size_shares
            + SAFETY_BUFFER * opp.size_shares
        )
        result.edge_sum += opp.net_edge * opp.size_shares
        result.friction_sum += friction
        if tick.market_id not in seen_windows:
            seen_windows.add(tick.market_id)
            winfo = panel.windows.get(tick.market_id, {})
            resolved = float(winfo.get("resolved_up", 0))
            payout = opp.size_shares * resolved
            cost = opp.vwap * opp.size_shares + friction
            result.hypothetical_pnl += payout - cost

    result.windows_with_edge = len(edge_windows)
    if stale_samples:
        result.stale_mid_avg = sum(stale_samples) / len(stale_samples)
    if spread_samples:
        result.market_spread_avg = sum(spread_samples) / len(spread_samples)
    return result


def conservative_annual_estimate(adverse_rate: float) -> dict[str, Any]:
    """Scenario bands from PREREG_16 table only — not scaled from short samples."""
    spr_low, spr_high = 0.50, 1.50  # USDC/fill (0.5-1.5¢ × 100 shares)
    fills_low, fills_high = 10, 40
    adv_mult = 1.0 + adverse_rate
    return {
        "assumption_source": "PREREG_16 techo económico",
        "fills_per_day_range": [fills_low, fills_high],
        "spread_per_fill_usdc_range": [spr_low, spr_high],
        "low_usdc_year": round(fills_low * spr_low / adv_mult * 365.25, 0),
        "mid_usdc_year": round(25 * 1.0 / adv_mult * 365.25, 0),
        "high_usdc_year": round(fills_high * spr_high / adv_mult * 365.25, 0),
        "prereg_ceiling_usdc_year": "300-1200",
    }


def extrapolate_annual(
    net_pnl: float,
    duration_hours: float,
    windows: int,
) -> dict[str, float]:
    if duration_hours <= 0:
        return {}
    hours_per_year = 365.25 * 24
    windows_per_day = (windows / duration_hours) * 24 if duration_hours else 0
    pnl_per_day = (net_pnl / duration_hours) * 24 if duration_hours else 0
    pnl_per_year = pnl_per_day * 365.25
    return {
        "duration_hours": round(duration_hours, 3),
        "windows_observed": windows,
        "windows_per_day_extrap": round(windows_per_day, 1),
        "pnl_observed_usdc": round(net_pnl, 2),
        "pnl_per_day_extrap_usdc": round(pnl_per_day, 2),
        "pnl_per_year_extrap_usdc": round(pnl_per_year, 2),
        "return_on_10k_annual_pct": round(pnl_per_year / INITIAL_CAPITAL * 100, 2),
    }


def microstructure_scan(panel: ReplayPanel) -> dict[str, Any]:
    """Scan how often the book shows exploitable dislocations vs fair value."""
    taker_ticks = 0
    wide_spread_ticks = 0
    competitive_bid_ticks = 0
    competitive_ask_ticks = 0
    n = 0
    for tick in panel.ticks:
        if tick.best_bid is None or tick.best_ask is None:
            continue
        n += 1
        feats = build_market_features(
            {
                "spot": tick.spot,
                "strike": tick.strike,
                "time_remaining_s": tick.time_remaining_s,
                "bids": tick.bids,
                "asks": tick.asks,
            }
        )
        fair = estimate_fair_values(feats)["up"]
        tb, ta = top_levels(tick.bids, tick.asks, 10)
        state = {
            "spot": tick.spot,
            "strike": tick.strike,
            "time_remaining_s": tick.time_remaining_s,
            "bids": tick.bids,
            "asks": tick.asks,
        }
        if find_executable_edge(state, {"up": fair}, size_shares=QUOTE_SIZE):
            taker_ticks += 1
        if tick.best_ask - tick.best_bid > 0.03:
            wide_spread_ticks += 1
        bid_q, ask_q = _maker_quotes(fair)
        if bid_q >= tick.best_bid:
            competitive_bid_ticks += 1
        if ask_q <= tick.best_ask:
            competitive_ask_ticks += 1
    return {
        "ticks_with_book": n,
        "pct_taker_edge_visible": round(100 * taker_ticks / max(n, 1), 2),
        "pct_wide_spread_gt_3c": round(100 * wide_spread_ticks / max(n, 1), 2),
        "pct_our_bid_competitive": round(100 * competitive_bid_ticks / max(n, 1), 2),
        "pct_our_ask_competitive": round(100 * competitive_ask_ticks / max(n, 1), 2),
    }


def run_explore(data_root: Path, run_id: str = "latest") -> dict[str, Any]:
    panel = build_replay_panel(data_root)
    btc_rows, _ = __import__(
        "polymarket.research.poly_lab.replay_panel", fromlist=["load_panel"]
    ).load_panel(data_root)
    btc_ts = [r["recv_ts_ns"] for r in btc_rows]
    btc_prices = [float(r["price"]) for r in btc_rows]

    maker = simulate_maker(panel, btc_ts, btc_prices)
    taker = simulate_taker(panel)
    micro = microstructure_scan(panel)

    maker_extrap = extrapolate_annual(
        maker.net_pnl, panel.duration_hours, len(panel.windows)
    )
    maker_scenarios = conservative_annual_estimate(maker.adverse_rate)
    taker_extrap = extrapolate_annual(
        taker.hypothetical_pnl, panel.duration_hours, len(panel.windows)
    )

    report: dict[str, Any] = {
        "verdict": "EXPLORATORY",
        "verdict_binding": False,
        "warning": "No usar para registry. Requiere >=30d fase A + paper 14d para #16.",
        "data_root": str(data_root),
        "panel": {
            "btc_rows": panel.btc_count,
            "clob_rows": panel.clob_count,
            "aligned_ticks": len(panel.ticks),
            "windows": len(panel.windows),
            "duration_hours": round(panel.duration_hours, 4),
        },
        "maker_16_exploratory": {
            "fills": maker.fill_count,
            "adverse_rate": round(maker.adverse_rate, 4),
            "spread_captured_usdc": round(maker.spread_captured_total, 2),
            "adverse_cost_usdc": round(maker.adverse_cost_total, 2),
            "inventory_pnl_usdc": round(maker.inventory_pnl, 2),
            "net_pnl_usdc": round(maker.net_pnl, 2),
            "p2_ratio": round(
                maker.spread_captured_total / max(maker.adverse_cost_total, 0.01), 3
            ),
            "death_p1_would_fire": maker.adverse_rate > 0.55,
            "death_p2_would_fire": maker.spread_captured_total < 2 * maker.adverse_cost_total,
            "extrapolation": maker_extrap,
            "annual_scenarios_conservative": maker_scenarios,
        },
        "taker_15_exploratory": {
            "opportunities": taker.opportunities,
            "windows_with_edge": taker.windows_with_edge,
            "edge_sum_usdc": round(taker.edge_sum, 2),
            "friction_sum_usdc": round(taker.friction_sum, 2),
            "hypothetical_pnl_usdc": round(taker.hypothetical_pnl, 2),
            "stale_mid_vs_fair_avg": round(taker.stale_mid_avg, 4),
            "market_spread_avg": round(taker.market_spread_avg, 4),
            "extrapolation": taker_extrap,
        },
        "microstructure": micro,
        "prereg_16_ceiling_annual_usdc": "300-1200 (pre-reg techo optimista)",
        "windows_detail": [
            {
                "market_id": w["market_id"],
                "question": w["question"][:60],
                "strike": round(w["strike"], 2),
                "spot_end": round(w["spot_end"], 2),
                "resolved_up": w["resolved_up"],
                "clob_updates": w["clob_updates"],
            }
            for w in panel.windows.values()
        ],
    }

    out_dir = OUTPUT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "explore_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Exploratory Polymarket edge analysis")
    p.add_argument("--data-root", type=Path, default=ROOT / "data_local" / "smoke_test")
    p.add_argument("--run-id", default="latest")
    args = p.parse_args()
    r = run_explore(args.data_root, args.run_id)
    print(json.dumps(r, indent=2))
