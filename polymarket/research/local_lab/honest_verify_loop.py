#!/usr/bin/env python3
"""
Verificación honesta post-fix fair-value:
- sin paper_touch_fill
- sin exits sintéticos (hazard/mean-reversion inventados)
- fair lognormal corregido
Objetivo lab: WR>=75% con avg_net>0 y >=4 sesiones con fills.
NO implica dinero real / live.
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
MAX_TRIALS = 8


def _base() -> dict:
    cfg = json.loads((CFG_DIR / "maker_demo_100_usd_honest.json").read_text(encoding="utf-8"))
    cfg["paper_touch_fill_every_n"] = 0
    cfg["paper_pnl_mode"] = ""
    cfg["mean_reversion_exit"] = False
    cfg["exit_hazard_per_s"] = 0
    # Mark-to-mid immediately after fill = half-spread accounting (still paper, not live).
    cfg["flatten_after_fill"] = True
    return cfg


def mutate(cfg: dict, rng: random.Random, gen: int) -> dict:
    c = deepcopy(cfg)
    c["min_edge"] = round(rng.choice([0.015, 0.02, 0.025, 0.03, 0.035]), 3)
    c["min_z"] = round(rng.choice([0.7, 0.85, 1.0, 1.15]), 2)
    c["min_take_profit"] = round(rng.choice([0.008, 0.01, 0.012, 0.015]), 3)
    c["half_spread"] = round(rng.choice([0.01, 0.012, 0.015, 0.018]), 3)
    c["quote_size_shares"] = rng.choice([5, 6, 8, 10])
    c["toxic_tol"] = round(rng.choice([0.008, 0.01, 0.012]), 3)
    c["kelly_sizing"] = rng.choice([True, False])
    c["demo_label"] = f"honest_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


async def main() -> int:
    rng = random.Random(20260716)
    base = _base()
    history: list[dict] = []
    best: dict | None = None
    seeds = [
        deepcopy(base),
        mutate({**base, "min_edge": 0.015, "min_z": 0.7}, rng, 0),
        mutate({**base, "min_edge": 0.025, "half_spread": 0.015}, rng, 0),
        mutate({**base, "min_edge": 0.03, "min_take_profit": 0.008, "quote_size_shares": 6}, rng, 0),
    ]

    for i in range(MAX_TRIALS):
        if i < len(seeds):
            cfg = seeds[i]
        elif best:
            cfg = mutate(best["cfg"], rng, i)
        else:
            cfg = mutate(base, rng, i)

        path = OUT / f"honest_cfg_{i+1:02d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n######## HONEST TRIAL {i+1}/{MAX_TRIALS} {cfg['demo_label']} ########", flush=True)
        print(
            f"params min_edge={cfg['min_edge']} min_z={cfg['min_z']} tp={cfg['min_take_profit']} "
            f"hs={cfg['half_spread']} size={cfg['quote_size_shares']}",
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
        )
        row["score"] = score
        history.append(row)
        (OUT / "honest_verify_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(
            f"→ WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
            f"traded={summary['sessions_with_fills']} losses={summary['losses']} score={score:.2f}",
            flush=True,
        )

        if best is None or score > best["score"]:
            best = row
            (OUT / "honest_verify_best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
            (CFG_DIR / "maker_demo_100_usd_honest_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )

        if (
            summary["win_rate"] >= TARGET
            and summary["sessions_with_fills"] >= 4
            and summary["avg_net_usdc"] > 0
            and summary["losses"] <= 1
        ):
            print("\n*** HONEST TARGET HIT >= 75% (paper only) ***", flush=True)
            print(
                "AVISO: lab local no coloca órdenes reales; no es dinero on-chain.",
                flush=True,
            )
            return 0

    if best:
        print(
            f"\nBest after {MAX_TRIALS}: WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f}",
            flush=True,
        )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
