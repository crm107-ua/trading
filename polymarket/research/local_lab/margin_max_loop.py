#!/usr/bin/env python3
"""
Research loop: maximize margin on $100 while WR>=75%.
Targets from fill study: avg_net >= $15/sesión and prefer high notional margin.
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
INCOME_TARGET = 12.0  # $/sesión media sobre $100 (superior a +8.88 previo)
MAX_TRIALS = 6


def _base() -> dict:
    return json.loads((CFG_DIR / "maker_demo_100_usd_margin.json").read_text(encoding="utf-8"))


def mutate(cfg: dict, rng: random.Random, gen: int) -> dict:
    c = deepcopy(cfg)
    c["quote_size_shares"] = rng.choice([32, 40, 48, 55, 65])
    c["max_inventory_shares"] = int(c["quote_size_shares"] * rng.choice([1.2, 1.4, 1.6]))
    c["max_notional_per_side_usdc"] = rng.choice([40, 45, 48, 52, 58])
    c["max_inventory_usdc"] = rng.choice([50, 55, 60, 65])
    c["max_size_mult"] = round(rng.choice([2.2, 2.5, 2.8, 3.2]), 1)
    c["min_edge"] = round(rng.choice([0.028, 0.03, 0.035, 0.04, 0.045]), 3)
    c["soft_edge"] = round(c["min_edge"] + rng.choice([0.01, 0.015, 0.02]), 3)
    c["hard_edge"] = round(c["soft_edge"] + rng.choice([0.02, 0.025, 0.03]), 3)
    c["min_expected_pnl_usdc"] = round(rng.choice([0.4, 0.6, 0.75, 1.0, 1.25]), 2)
    c["min_take_profit"] = round(rng.choice([0.02, 0.025, 0.03, 0.035]), 3)
    c["max_take_profit"] = round(rng.choice([0.08, 0.10, 0.12]), 3)
    c["tp_capture_frac"] = round(rng.choice([0.5, 0.55, 0.6, 0.7]), 2)
    c["stop_loss_mid"] = round(rng.choice([0.022, 0.028, 0.032]), 3)
    c["max_entry_fills"] = rng.choice([5, 6, 8, 10])
    c["cooldown_after_fill_s"] = rng.choice([5, 8, 12, 15])
    c["quote_time_min_s"] = rng.choice([45, 55, 70])
    c["quote_time_max_s"] = rng.choice([240, 260, 280])
    c["flatten_after_fill"] = False
    c["paper_touch_fill_every_n"] = 0
    c["exit_hazard_per_s"] = 0
    c["demo_label"] = f"margin_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


async def main() -> int:
    rng = random.Random(20260716)
    base = _base()
    history: list[dict] = []
    best: dict | None = None
    seeds = [
        deepcopy(base),
        mutate(
            {
                **base,
                "quote_size_shares": 50,
                "max_size_mult": 3.2,
                "min_edge": 0.028,
                "min_expected_pnl_usdc": 0.25,
                "max_loss_usdc": 5.0,
                "stop_loss_mid": 0.016,
            },
            rng,
            0,
        ),
        mutate(
            {
                **base,
                "quote_size_shares": 55,
                "min_edge": 0.03,
                "tp_capture_frac": 0.65,
                "max_take_profit": 0.10,
                "max_loss_usdc": 7.0,
            },
            rng,
            0,
        ),
        mutate(
            {
                **base,
                "quote_size_shares": 48,
                "min_edge": 0.032,
                "hard_edge": 0.07,
                "cooldown_after_fill_s": 2,
                "max_entry_fills": 16,
            },
            rng,
            0,
        ),
    ]

    for i in range(MAX_TRIALS):
        if i < len(seeds):
            cfg = seeds[i]
        elif best:
            cfg = mutate(best["cfg"], rng, i)
        else:
            cfg = mutate(base, rng, i)

        path = OUT / f"margin_cfg_{i+1:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"\n######## MARGIN TRIAL {i+1}/{MAX_TRIALS} {cfg['demo_label']} ########", flush=True)
        print(
            f"params size={cfg['quote_size_shares']} edge={cfg['min_edge']}/{cfg['hard_edge']} "
            f"minEV={cfg['min_expected_pnl_usdc']} tp={cfg['min_take_profit']}-{cfg['max_take_profit']} "
            f"entries={cfg['max_entry_fills']} cd={cfg['cooldown_after_fill_s']}s",
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
            "total_net": round(sum(r["net"] for r in summary["results"]), 2),
        }
        wr_pen = 0.0 if summary["win_rate"] >= WR_TARGET else -80.0
        # Emphasize total/avg income on $100 + WR
        score = (
            summary["avg_net_usdc"] * 10
            + row["total_net"] * 0.5
            + summary["win_rate"] * 50
            + (10 if summary["sessions_with_fills"] >= 4 else -30)
            - summary["losses"] * 6
            + wr_pen
        )
        row["score"] = score
        history.append(row)
        (OUT / "margin_max_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(
            f"-> WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
            f"total={row['total_net']:+.2f} traded={summary['sessions_with_fills']} "
            f"losses={summary['losses']} score={score:.2f}",
            flush=True,
        )
        if best is None or score > best["score"]:
            best = row
            (OUT / "margin_max_best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
            (CFG_DIR / "maker_demo_100_usd_margin_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )
        if (
            summary["win_rate"] >= WR_TARGET
            and summary["sessions_with_fills"] >= 4
            and summary["avg_net_usdc"] >= INCOME_TARGET
            and summary["losses"] <= 1
        ):
            print(
                f"\n*** MARGIN TARGET HIT: avg>=${INCOME_TARGET:.0f}/sesion & WR>=75% on $100 ***",
                flush=True,
            )
            return 0

    if best:
        print(
            f"\nBest after {MAX_TRIALS}: WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f} "
            f"total={best['total_net']:+.2f}",
            flush=True,
        )
        return 0 if best["win_rate"] >= WR_TARGET and best["avg_net_usdc"] >= INCOME_TARGET else 1
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
