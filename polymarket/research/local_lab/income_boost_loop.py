#!/usr/bin/env python3
"""
Maximiza ingresos paper manteniendo WR>=75%.
Sin fills/exits sintéticos (no touch_fill, no locked_spread, no hazard).
Target: avg_net_usdc >= INCOME_TARGET con WR>=75% y <=1 loss.
"""

from __future__ import annotations

import asyncio
import json
import random
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab"
CFG_DIR = POLY / "config"
WR_TARGET = 0.75
INCOME_TARGET = 4.0  # $/sesión media sobre $100
MAX_TRIALS = 8


def _base() -> dict:
    return json.loads((CFG_DIR / "maker_demo_100_usd_income.json").read_text(encoding="utf-8"))


def mutate(cfg: dict, rng: random.Random, gen: int) -> dict:
    c = deepcopy(cfg)
    c["quote_size_shares"] = rng.choice([18, 22, 25, 30, 35, 40])
    c["max_inventory_shares"] = int(c["quote_size_shares"] * rng.choice([1.2, 1.5, 1.8]))
    c["max_notional_per_side_usdc"] = rng.choice([28, 32, 35, 40, 45])
    c["max_inventory_usdc"] = rng.choice([40, 45, 50, 55])
    c["max_size_mult"] = round(rng.choice([2.0, 2.5, 3.0, 3.5]), 1)
    c["min_edge"] = round(rng.choice([0.025, 0.03, 0.035, 0.04]), 3)
    c["min_z"] = round(rng.choice([0.9, 1.0, 1.15, 1.3]), 2)
    c["min_take_profit"] = round(rng.choice([0.015, 0.018, 0.022, 0.028]), 3)
    c["max_take_profit"] = round(rng.choice([0.05, 0.06, 0.07, 0.08]), 3)
    c["tp_edge_scale"] = round(rng.choice([0.5, 0.65, 0.8, 1.0]), 2)
    c["stop_loss_mid"] = round(rng.choice([0.02, 0.025, 0.03, 0.035]), 3)
    c["min_market_spread"] = round(rng.choice([0.008, 0.01, 0.012]), 3)
    c["kelly_sizing"] = True
    c["flatten_after_fill"] = False
    c["paper_touch_fill_every_n"] = 0
    c["exit_hazard_per_s"] = 0
    c["demo_label"] = f"income_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


async def main() -> int:
    rng = random.Random(20260716)
    base = _base()
    history: list[dict] = []
    best: dict | None = None
    seeds = [
        deepcopy(base),
        mutate({**base, "quote_size_shares": 35, "min_edge": 0.035, "min_take_profit": 0.022}, rng, 0),
        mutate({**base, "quote_size_shares": 40, "max_size_mult": 3.5, "min_edge": 0.04}, rng, 0),
        mutate({**base, "quote_size_shares": 30, "tp_edge_scale": 1.0, "max_take_profit": 0.08}, rng, 0),
    ]

    for i in range(MAX_TRIALS):
        if i < len(seeds):
            cfg = seeds[i]
        elif best:
            cfg = mutate(best["cfg"], rng, i)
            # Bias: push size/income from best while keeping risk knobs
            cfg["quote_size_shares"] = max(cfg["quote_size_shares"], int(best["cfg"]["quote_size_shares"] * 0.9))
        else:
            cfg = mutate(base, rng, i)

        path = OUT / f"income_cfg_{i+1:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n######## INCOME TRIAL {i+1}/{MAX_TRIALS} {cfg['demo_label']} ########", flush=True)
        print(
            f"params size={cfg['quote_size_shares']} mult={cfg['max_size_mult']} "
            f"edge={cfg['min_edge']} tp={cfg['min_take_profit']}-{cfg['max_take_profit']} "
            f"stop={cfg['stop_loss_mid']} notional={cfg['max_notional_per_side_usdc']}",
            flush=True,
        )
        summary = await run_batch(
            strategy="maker_edge",
            config=str(path),
            sessions=6,
            minutes=3.5,
        )
        row = {
            "trial": i + 1,
            "cfg": cfg,
            "win_rate": summary["win_rate"],
            "avg_net_usdc": summary["avg_net_usdc"],
            "sessions_with_fills": summary["sessions_with_fills"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "results": summary["results"],
        }
        # Score prioritizes income, but heavily penalizes WR < 75%
        wr_pen = 0.0 if summary["win_rate"] >= WR_TARGET else -50.0
        score = (
            summary["avg_net_usdc"] * 12
            + summary["win_rate"] * 40
            + (8 if summary["sessions_with_fills"] >= 4 else -25)
            - summary["losses"] * 4
            + wr_pen
        )
        row["score"] = score
        history.append(row)
        (OUT / "income_boost_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(
            f"-> WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
            f"traded={summary['sessions_with_fills']} losses={summary['losses']} score={score:.2f}",
            flush=True,
        )
        if best is None or score > best["score"]:
            best = row
            (OUT / "income_boost_best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
            (CFG_DIR / "maker_demo_100_usd_income_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )
        if (
            summary["win_rate"] >= WR_TARGET
            and summary["sessions_with_fills"] >= 4
            and summary["avg_net_usdc"] >= INCOME_TARGET
            and summary["losses"] <= 1
        ):
            print(
                f"\n*** INCOME TARGET HIT: avg>=${INCOME_TARGET:.0f}/sesion & WR>=75% ***",
                flush=True,
            )
            return 0

    if best:
        print(
            f"\nBest after {MAX_TRIALS}: WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f}",
            flush=True,
        )
        return 0 if best["win_rate"] >= WR_TARGET and best["avg_net_usdc"] >= INCOME_TARGET else 1
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
