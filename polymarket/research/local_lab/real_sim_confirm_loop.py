#!/usr/bin/env python3
"""
Simulación real-feed (OOS) — siguiente paso tras el hito margin_max_v3.

- Feeds live Binance + CLOB (no synthetic fills / locked_spread).
- Params anclados al hito; mutaciones solo si hace falta subir target.
- Target: WR>=75%, avg_net >= RAISED_TARGET, losses<=2, traded>=5.
- NO es live on-chain. NO es screen vinculante.
"""

from __future__ import annotations

import asyncio
import json
import os
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
RAISED_TARGET = float(os.getenv("REAL_SIM_AVG_TARGET", "20"))
MAX_TRIALS = int(os.getenv("REAL_SIM_MAX_TRIALS", "6"))
SESSIONS = int(os.getenv("REAL_SIM_SESSIONS", "8"))
MINUTES = float(os.getenv("REAL_SIM_MINUTES", "5"))


def _hito_cfg() -> dict:
    p = CFG_DIR / "maker_demo_100_usd_margin_best.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg.update(
        {
            "demo_label": "real_sim_oos_v1",
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "flatten_after_fill": False,
            "mean_reversion_exit": False,
            "exit_hazard_per_s": 0,
            "initial_capital_usdc": 100.0,
        }
    )
    return cfg


def mutate(cfg: dict, rng: random.Random, gen: int) -> dict:
    c = deepcopy(cfg)
    # Conservador: no romper el hito; solo empujar tamaño/TP si WR aguanta
    c["quote_size_shares"] = rng.choice(
        [int(cfg["quote_size_shares"]), 45, 48, 52, 55]
    )
    c["max_inventory_shares"] = max(
        c["quote_size_shares"], int(c["quote_size_shares"] * 1.3)
    )
    c["max_notional_per_side_usdc"] = rng.choice([48, 50, 52, 55])
    c["max_inventory_usdc"] = rng.choice([55, 58, 60])
    c["max_size_mult"] = round(rng.choice([2.8, 3.0, 3.2]), 1)
    c["min_take_profit"] = round(rng.choice([0.02, 0.022, 0.025]), 3)
    c["max_take_profit"] = round(rng.choice([0.09, 0.10, 0.11]), 3)
    c["tp_capture_frac"] = round(rng.choice([0.55, 0.6, 0.65]), 2)
    c["max_loss_usdc"] = round(rng.choice([5.0, 6.0, 7.0]), 1)
    c["stop_loss_mid"] = round(rng.choice([0.016, 0.018, 0.02]), 3)
    c["demo_label"] = f"real_sim_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


async def main() -> int:
    rng = random.Random(20260716)
    base = _hito_cfg()
    history: list[dict] = []
    best: dict | None = None

    # Trial 0 = hito congelado (confirmación OOS pura)
    seeds = [
        deepcopy(base),
        mutate(base, rng, 0),
        mutate({**base, "quote_size_shares": 52, "tp_capture_frac": 0.65}, rng, 0),
    ]

    meta = {
        "milestone_doc": "polymarket/docs/MILESTONE_2026-07-16_MAKER_EDGE_LAB.md",
        "mode": "real_feed_simulation_oos",
        "live_onchain": False,
        "raised_target_usdc": RAISED_TARGET,
        "sessions": SESSIONS,
        "minutes": MINUTES,
    }
    (OUT / "real_sim_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)

    for i in range(MAX_TRIALS):
        cfg = seeds[i] if i < len(seeds) else mutate(best["cfg"] if best else base, rng, i)
        path = OUT / f"real_sim_cfg_{i+1:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(
            f"\n######## REAL-SIM TRIAL {i+1}/{MAX_TRIALS} {cfg['demo_label']} ########",
            flush=True,
        )
        print(
            f"params size={cfg['quote_size_shares']} edge={cfg['min_edge']} "
            f"tp={cfg['min_take_profit']}-{cfg['max_take_profit']} "
            f"max_loss={cfg.get('max_loss_usdc')} sessions={SESSIONS}x{MINUTES}m",
            flush=True,
        )
        summary = await run_batch(
            strategy="maker_edge",
            config=str(path),
            sessions=SESSIONS,
            minutes=MINUTES,
        )
        total = round(sum(r["net"] for r in summary["results"]), 2)
        row = {
            "trial": i + 1,
            "cfg": cfg,
            "win_rate": summary["win_rate"],
            "avg_net_usdc": summary["avg_net_usdc"],
            "total_net": total,
            "sessions_with_fills": summary["sessions_with_fills"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "results": summary["results"],
        }
        wr_ok = summary["win_rate"] >= WR_TARGET
        score = (
            summary["avg_net_usdc"] * 8
            + total * 0.4
            + summary["win_rate"] * 60
            + (12 if summary["sessions_with_fills"] >= 5 else -40)
            - summary["losses"] * 8
            + (0 if wr_ok else -100)
        )
        row["score"] = score
        history.append(row)
        (OUT / "real_sim_history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
        print(
            f"-> WR={summary['win_rate']:.1%} avg={summary['avg_net_usdc']:+.2f} "
            f"total={total:+.2f} traded={summary['sessions_with_fills']} "
            f"losses={summary['losses']} score={score:.2f}",
            flush=True,
        )
        if best is None or score > best["score"]:
            best = row
            (OUT / "real_sim_best.json").write_text(json.dumps(best, indent=2), encoding="utf-8")
            (CFG_DIR / "maker_demo_100_usd_real_sim_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )
        if (
            summary["win_rate"] >= WR_TARGET
            and summary["sessions_with_fills"] >= 5
            and summary["avg_net_usdc"] >= RAISED_TARGET
            and summary["losses"] <= 2
        ):
            print(
                f"\n*** REAL-SIM TARGET HIT: avg>=${RAISED_TARGET:.0f} & WR>=75% (feeds reales, no on-chain) ***",
                flush=True,
            )
            return 0

    if best:
        print(
            f"\nBest after {MAX_TRIALS}: WR={best['win_rate']:.1%} avg={best['avg_net_usdc']:+.2f} "
            f"total={best['total_net']:+.2f}",
            flush=True,
        )
        return (
            0
            if best["win_rate"] >= WR_TARGET and best["avg_net_usdc"] >= RAISED_TARGET
            else 1
        )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
