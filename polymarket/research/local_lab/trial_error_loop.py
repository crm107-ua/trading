#!/usr/bin/env python3
"""
Prueba-error iterativo: $100 paper, feeds reales, NIM hybrid (free endpoints).
Mutación de parámetros hasta win_rate >= 75% con net medio > 0.
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
MAX_TRIALS = 6


def _base_cfg() -> dict:
    p = CFG_DIR / "maker_demo_100_eur_best.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg.update(
        {
            "demo_label": "trial_error_100usd",
            "initial_capital_usdc": 100.0,
            "currency_label": "USD",
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "mean_reversion_exit": True,
            "exit_hazard_per_s": 0.3,
            "reject_adverse_fills": True,
            "take_profit_mid": True,
            "quote_join_touch": True,
        }
    )
    return cfg


def mutate(cfg: dict, rng: random.Random, generation: int) -> dict:
    c = deepcopy(cfg)
    c["min_edge"] = round(rng.choice([0.02, 0.025, 0.03, 0.035, 0.04]), 3)
    c["min_z"] = round(rng.choice([0.7, 0.85, 1.0, 1.15]), 2)
    c["min_take_profit"] = round(rng.choice([0.008, 0.01, 0.012, 0.015]), 3)
    c["half_spread"] = round(rng.choice([0.01, 0.012, 0.015, 0.018]), 3)
    c["quote_size_shares"] = rng.choice([6, 8, 10])
    c["sigma_mid"] = round(rng.choice([0.025, 0.03, 0.035]), 3)
    c["exit_hazard_per_s"] = round(rng.choice([0.2, 0.3, 0.4, 0.5]), 2)
    c["toxic_tol"] = round(rng.choice([0.008, 0.01, 0.012]), 3)
    c["kelly_sizing"] = rng.choice([True, False])
    c["demo_label"] = f"trial_g{generation}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


async def main() -> int:
    rng = random.Random(20260716)
    base = _base_cfg()
    history: list[dict] = []
    best: dict | None = None

    # Seeded candidates first (informed by MC + prior runs)
    seeds = [
        deepcopy(base),
        mutate({**base, "min_edge": 0.02, "min_z": 0.7, "exit_hazard_per_s": 0.45}, rng, 0),
        mutate({**base, "min_edge": 0.035, "min_take_profit": 0.015, "quote_size_shares": 10}, rng, 0),
    ]

    for i in range(MAX_TRIALS):
        cfg = seeds[i] if i < len(seeds) else mutate(best["cfg"] if best else base, rng, i)
        # Bias mutation toward previous best
        if best and i >= len(seeds):
            cfg = mutate(best["cfg"], rng, i)
            # keep some winning knobs
            cfg["mean_reversion_exit"] = True
            cfg["paper_touch_fill_every_n"] = 0

        path = OUT / f"trial_cfg_{i+1:02d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n######## TRIAL {i+1}/{MAX_TRIALS} {cfg['demo_label']} ########", flush=True)
        print(
            f"params min_edge={cfg['min_edge']} min_z={cfg['min_z']} tp={cfg['min_take_profit']} "
            f"hazard={cfg['exit_hazard_per_s']} size={cfg['quote_size_shares']}",
            flush=True,
        )

        summary = await run_batch(
            strategy="maker_edge",
            config=str(path),
            sessions=6,
            minutes=2.5,
        )
        row = {
            "trial": i + 1,
            "cfg": cfg,
            "win_rate": summary["win_rate"],
            "avg_net_usdc": summary["avg_net_usdc"],
            "sessions_with_fills": summary["sessions_with_fills"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "no_loss_rate": summary["no_loss_rate"],
            "results": summary["results"],
        }
        history.append(row)
        (OUT / "trial_error_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")

        score = (
            summary["win_rate"] * 100
            + summary["avg_net_usdc"]
            + (5 if summary["sessions_with_fills"] >= 4 else -20)
        )
        row["score"] = score
        print(
            f"→ WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
            f"traded={summary['sessions_with_fills']} losses={summary['losses']} score={score:.2f}",
            flush=True,
        )

        if best is None or score > best["score"]:
            best = row
            (OUT / "trial_error_best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
            (CFG_DIR / "maker_demo_100_usd_trial_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )

        if (
            summary["win_rate"] >= TARGET
            and summary["sessions_with_fills"] >= 4
            and summary["avg_net_usdc"] > 0
            and summary["losses"] <= 1
        ):
            print("\n*** TARGET HIT >= 75% ***", flush=True)
            return 0

    print(
        f"\nBest after {MAX_TRIALS}: WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f}",
        flush=True,
    )
    return 0 if best and best["win_rate"] >= TARGET else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
