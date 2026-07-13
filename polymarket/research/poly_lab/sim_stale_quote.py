#!/usr/bin/env python3
"""
#15 Stale-quote simulator — honest friction, VWAP, account PnL.

Frozen: polymarket/docs/PREREG_15_POLY_STALE_QUOTE.md
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from polymarket.src.pricing.fair_value import (
    MIN_NET_EDGE,
    SAFETY_BUFFER,
    TAKER_FEE,
    estimate_fair_values,
    find_executable_edge,
    slippage_est,
)
from polymarket.src.signals.features import build_market_features

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_BASE = ROOT / "research" / "output" / "poly_15"

INITIAL_CAPITAL = 10_000.0
LATENCY_MS_ASSUMED = 250.0  # retail spot feed delay for D-2 proxy


@dataclass
class SimConfig:
    initial_capital: float = INITIAL_CAPITAL
    size_shares: float = 100.0
    seed: int = 15


@dataclass
class TradeRecord:
    ts_ms: int
    fair_up: float
    vwap: float
    net_edge: float
    notional: float
    friction: float
    filled: bool
    resolution_pnl: float = 0.0


@dataclass
class SimResult:
    run_id: str
    trades: list[TradeRecord] = field(default_factory=list)
    bankroll_end: float = INITIAL_CAPITAL
    edge_sum: float = 0.0
    friction_sum: float = 0.0
    fill_count: int = 0
    order_count: int = 0
    latency_samples_ms: list[float] = field(default_factory=list)
    pnl_by_market: dict[str, float] = field(default_factory=dict)


def generate_synthetic_replay(n_windows: int = 120, seed: int = 15) -> list[dict[str, Any]]:
    """
    Synthetic 5m windows — DEV ONLY. No emitir veredicto vinculante desde estos datos.

    Resolución path-dependent: Up gana si spot_final > strike (regla mercado real).
    Requiere depth WS grabado para screen honesto (pre-reg #15).
    """
    rng = np.random.default_rng(seed)
    spot = 62_000.0
    rows: list[dict[str, Any]] = []
    for w in range(n_windows):
        strike = spot
        window_end_spot = spot
        for step in range(30):
            ts = w * 300_000 + step * 10_000
            spot += rng.normal(0, 15)
            window_end_spot = spot
            time_remaining = max(300 - step * 10, 10)
            fair = 0.5 + (spot - strike) / 800.0
            fair = float(np.clip(fair, 0.05, 0.95))
            stale = fair - rng.uniform(0, 0.04) * (1 if spot > strike else -1)
            mid = float(np.clip(stale + rng.normal(0, 0.01), 0.02, 0.98))
            spread = rng.uniform(0.01, 0.03)
            bid = max(0.01, mid - spread / 2)
            ask = min(0.99, mid + spread / 2)
            depth = rng.uniform(500, 5000)
            resolved = None
            if step == 29:
                resolved = int(window_end_spot > strike)
            rows.append(
                {
                    "market_id": f"win_{w}",
                    "ts_ms": ts,
                    "spot": spot,
                    "strike": strike,
                    "time_remaining_s": time_remaining,
                    "bids": [{"price": f"{bid:.4f}", "size": f"{depth:.2f}"}],
                    "asks": [{"price": f"{ask:.4f}", "size": f"{depth:.2f}"}],
                    "feed_ts_ms": ts,
                    "resolved_up": resolved,
                    "latency_ms": LATENCY_MS_ASSUMED + rng.uniform(-20, 80),
                }
            )
        spot = window_end_spot + rng.normal(0, 50)
    return rows


def simulate_replay(replay: list[dict[str, Any]], cfg: SimConfig) -> SimResult:
    result = SimResult(run_id="")
    bankroll = cfg.initial_capital
    open_positions: dict[str, dict] = {}
    traded_markets: set[str] = set()

    for row in replay:
        features = build_market_features(row)
        fair_values = estimate_fair_values(features)
        opp = find_executable_edge(row, fair_values, size_shares=cfg.size_shares)
        result.latency_samples_ms.append(float(row.get("latency_ms", LATENCY_MS_ASSUMED)))

        if opp is None:
            continue

        mid = row["market_id"]
        if mid in traded_markets:
            continue

        result.order_count += 1
        friction = (
            TAKER_FEE * opp.vwap * opp.size_shares
            + slippage_est(opp.size_shares) * opp.size_shares
            + SAFETY_BUFFER * opp.size_shares
        )
        notional = opp.vwap * opp.size_shares
        if notional + friction > bankroll * 0.05:
            continue

        result.fill_count += 1
        result.edge_sum += opp.net_edge * opp.size_shares
        result.friction_sum += friction
        bankroll -= notional + friction
        traded_markets.add(mid)

        open_positions[mid] = {
            "shares": opp.size_shares,
            "cost": notional + friction,
        }

        result.trades.append(
            TradeRecord(
                ts_ms=int(row["ts_ms"]),
                fair_up=fair_values["up"],
                vwap=opp.vwap,
                net_edge=opp.net_edge,
                notional=notional,
                friction=friction,
                filled=True,
            )
        )

        if row.get("resolved_up") is not None and mid in open_positions:
            pos = open_positions[mid]
            payout = pos["shares"] * float(row["resolved_up"])
            pnl = payout - pos["cost"]
            bankroll += payout
            result.pnl_by_market[mid] = pnl
            result.trades[-1].resolution_pnl = pnl
            del open_positions[mid]

    result.bankroll_end = bankroll
    return result


def split_halves(replay: list[dict]) -> tuple[list[dict], list[dict]]:
    markets = sorted({r["market_id"] for r in replay})
    mid = len(markets) // 2
    is_m = set(markets[:mid])
    oos_m = set(markets[mid:])
    is_rows = [r for r in replay if r["market_id"] in is_m]
    oos_rows = [r for r in replay if r["market_id"] in oos_m]
    return is_rows, oos_rows


def sharpe_from_pnls(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    arr = np.array(pnls)
    if arr.std() < 1e-9:
        return 0.0
    return float(arr.mean() / arr.std() * math.sqrt(len(arr)))


def evaluate_deaths(full: SimResult, oos: SimResult) -> dict[str, Any]:
    deaths: dict[str, bool] = {}
    deaths["D-1"] = full.edge_sum < 2 * full.friction_sum
    lat = sorted(full.latency_samples_ms)
    p95 = lat[int(0.95 * len(lat)) - 1] if lat else 9999
    deaths["D-2"] = p95 > 3000
    total_pnl = full.bankroll_end - INITIAL_CAPITAL
    if full.pnl_by_market and total_pnl != 0:
        max_share = max(abs(v) for v in full.pnl_by_market.values()) / abs(total_pnl) if total_pnl else 1
        deaths["D-3"] = max_share > 0.40
    else:
        deaths["D-3"] = False
    fill_rate = full.fill_count / max(full.order_count, 1)
    deaths["D-4"] = fill_rate < 0.50
    oos_pnls = [t.resolution_pnl for t in oos.trades if t.filled]
    deaths["D-5"] = sharpe_from_pnls(oos_pnls) < 0.5
    return {
        "deaths": deaths,
        "latency_p95_ms": round(p95, 1),
        "fill_rate": round(fill_rate, 4),
        "edge_sum": round(full.edge_sum, 2),
        "friction_sum": round(full.friction_sum, 2),
        "oos_sharpe": round(sharpe_from_pnls(oos_pnls), 3),
    }


def run_screen(
    run_id: str,
    seed: int = 15,
    replay_dir: Path | None = None,
    allow_synthetic_dev: bool = False,
) -> dict[str, Any]:
    """
    Screen #15. Veredicto vinculante solo con replay de depth WS real.

    Sin replay_dir: emite SCREEN_INVALIDO (hipótesis no juzgada).
    allow_synthetic_dev: solo para pruebas unitarias; nunca escribe MUERTA/PASA vinculante.
    """
    if replay_dir is None and not allow_synthetic_dev:
        report = {
            "hypothesis": 15,
            "run_id": run_id,
            "prereg": "polymarket/docs/PREREG_15_POLY_STALE_QUOTE.md",
            "invalidation_doc": "polymarket/docs/SCREEN_15_INVALIDATION.md",
            "verdict": "SCREEN_INVALIDO",
            "verdict_binding": True,
            "hypothesis_judged": False,
            "market_verdict": None,
            "death_codes": [],
            "invalidated_runs": [
                {"order": 1, "reported": "MUERTA (D-4)", "bug": "order_count incluía todos los ticks"},
                {"order": 2, "reported": "MUERTA (D-5), PnL ~-9097", "bug": "múltiples fills por ventana"},
                {"order": 3, "reported": "MUERTA (D-5), PnL ~-5713", "bug": "fix parcial contabilidad"},
                {
                    "order": 4,
                    "reported": "MUERTA (D-5), PnL ~-5628",
                    "bug": "resolved_up coin flip independiente del spot",
                },
            ],
            "reason": "Sin depth WS >=30d; synthetic no informativo; runs intermedios invalidados",
            "required_for_honest_screen": "polymarket/data_local/ clob_recorder >=30d + replay",
            "branch_status": "PAUSA",
            "open_hypothesis_16": False,
            "note": "Único veredicto vinculante. No re-ejecutar sin datos reales.",
        }
        out_dir = OUTPUT_BASE / run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    if replay_dir is not None:
        replay_path = replay_dir / "book_snapshots.json"
        if not replay_path.exists():
            raise FileNotFoundError(f"Missing replay: {replay_path}")
        replay = json.loads(replay_path.read_text(encoding="utf-8"))
        # TODO: map WS snapshots -> market_state rows when >=30d panel exists
        raise NotImplementedError("Replay screen requires full session mapper (not yet implemented)")

    # Dev-only synthetic path (no binding verdict)
    cfg = SimConfig(seed=seed)
    replay = generate_synthetic_replay(n_windows=120, seed=seed)
    is_rows, oos_rows = split_halves(replay)
    full = simulate_replay(replay, cfg)
    oos = simulate_replay(oos_rows, cfg)
    deaths = evaluate_deaths(full, oos)
    return {
        "hypothesis": 15,
        "run_id": run_id,
        "verdict": "DEV_ONLY_SYNTHETIC",
        "verdict_binding": False,
        "hypothesis_judged": False,
        "evaluation": deaths,
        "warning": "No usar para registry; ver SCREEN_15_INVALIDATION.md",
    }


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="20260713_screen")
    args = p.parse_args()
    r = run_screen(args.run_id)
    print(json.dumps(r, indent=2))
