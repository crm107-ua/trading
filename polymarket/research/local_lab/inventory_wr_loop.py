#!/usr/bin/env python3
"""
Loop con riesgo de inventario real (sin flatten_after_fill / hazard sintético).
Objetivo: WR>=75% avg>0 con fills via last_trade + exits por trade/TP mid/stop.
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
TARGET = 0.75
MAX_TRIALS = 10


def _base() -> dict:
    cfg = json.loads((CFG_DIR / "maker_demo_100_usd_inventory.json").read_text(encoding="utf-8"))
    cfg.update(
        {
            "flatten_after_fill": False,
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "mean_reversion_exit": False,
            "exit_hazard_per_s": 0,
            "take_profit_mid": True,
            "stop_loss_mid": 0.02,
            "min_take_profit": 0.008,
            "inventory_skew_shares": 0.01,  # any inventory → exit-only quote
            "max_inventory_shares": 6,
            "quote_size_shares": 6,
        }
    )
    return cfg


def mutate(cfg: dict, rng: random.Random, gen: int) -> dict:
    c = deepcopy(cfg)
    c["min_edge"] = round(rng.choice([0.02, 0.025, 0.03, 0.035, 0.04]), 3)
    c["min_z"] = round(rng.choice([0.85, 1.0, 1.15, 1.3]), 2)
    c["min_take_profit"] = round(rng.choice([0.006, 0.008, 0.01, 0.012]), 3)
    c["stop_loss_mid"] = round(rng.choice([0.015, 0.02, 0.025, 0.03]), 3)
    c["half_spread"] = round(rng.choice([0.01, 0.012, 0.015]), 3)
    c["quote_size_shares"] = rng.choice([4, 5, 6, 8])
    c["max_inventory_shares"] = c["quote_size_shares"]
    c["min_market_spread"] = round(rng.choice([0.008, 0.01, 0.012, 0.015]), 3)
    c["demo_label"] = f"inv_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


async def main() -> int:
    rng = random.Random(20260716)
    base = _base()
    history: list[dict] = []
    best: dict | None = None
    seeds = [
        deepcopy(base),
        mutate({**base, "min_edge": 0.03, "stop_loss_mid": 0.015}, rng, 0),
        mutate({**base, "min_edge": 0.035, "min_take_profit": 0.006}, rng, 0),
        mutate({**base, "min_edge": 0.04, "quote_size_shares": 4, "max_inventory_shares": 4}, rng, 0),
    ]

    for i in range(MAX_TRIALS):
        if i < len(seeds):
            cfg = seeds[i]
        elif best:
            cfg = mutate(best["cfg"], rng, i)
        else:
            cfg = mutate(base, rng, i)

        path = OUT / f"inv_cfg_{i+1:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n######## INV TRIAL {i+1}/{MAX_TRIALS} {cfg['demo_label']} ########", flush=True)
        print(
            f"params edge={cfg['min_edge']} tp={cfg['min_take_profit']} "
            f"stop={cfg['stop_loss_mid']} size={cfg['quote_size_shares']}",
            flush=True,
        )
        summary = await run_batch(
            strategy="maker_edge",
            config=str(path),
            sessions=6,
            minutes=3.0,
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
        score = (
            summary["win_rate"] * 100
            + summary["avg_net_usdc"]
            + (5 if summary["sessions_with_fills"] >= 4 else -20)
            - summary["losses"] * 3
        )
        row["score"] = score
        history.append(row)
        (OUT / "inventory_wr_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(
            f"-> WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
            f"traded={summary['sessions_with_fills']} losses={summary['losses']} score={score:.2f}",
            flush=True,
        )
        if best is None or score > best["score"]:
            best = row
            (OUT / "inventory_wr_best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
            (CFG_DIR / "maker_demo_100_usd_inventory_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )
        if (
            summary["win_rate"] >= TARGET
            and summary["sessions_with_fills"] >= 4
            and summary["avg_net_usdc"] > 0
            and summary["losses"] <= 1
        ):
            print("\n*** INVENTORY TARGET HIT >= 75% (paper, no MTM flatten) ***", flush=True)
            return 0

    if best:
        print(
            f"\nBest after {MAX_TRIALS}: WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f}",
            flush=True,
        )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
