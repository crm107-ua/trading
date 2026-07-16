#!/usr/bin/env python3
"""
Confirmación rápida WR≥75% con feeds reales (paper, no on-chain).

Batch corto: N sesiones × M minutos. Mutación agresiva hacia selectividad
(más edge, menos size/entries, cola de pérdidas acotada).
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

WR_TARGET = float(os.getenv("WR_FAST_TARGET", "0.75"))
AVG_FLOOR = float(os.getenv("WR_FAST_AVG", "1.0"))
MAX_LOSSES = int(os.getenv("WR_FAST_MAX_LOSSES", "1"))
MIN_TRADED = int(os.getenv("WR_FAST_MIN_TRADED", "3"))
SESSIONS = int(os.getenv("WR_FAST_SESSIONS", "4"))
MINUTES = float(os.getenv("WR_FAST_MINUTES", "2.0"))
MAX_TRIALS = int(os.getenv("WR_FAST_MAX_TRIALS", "8"))


def _load_base() -> dict:
    for name in (
        "maker_demo_100_usd_wr_hunt.json",
        "maker_demo_100_usd_risk_pack.json",
    ):
        p = CFG_DIR / name
        if p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            break
    else:
        raise FileNotFoundError("no wr hunt / risk pack config")
    # Prefer best mini if present
    best = OUT / "calibrate_best_mini.json"
    if best.exists():
        packed = json.loads(best.read_text(encoding="utf-8"))
        if isinstance(packed.get("cfg"), dict):
            cfg = packed["cfg"]
    cfg.update(
        {
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "flatten_after_fill": False,
            "mean_reversion_exit": False,
            "exit_hazard_per_s": 0,
            "fair_fade_exit": True,
            "initial_capital_usdc": 100.0,
        }
    )
    return cfg


def mutate_wr(cfg: dict, rng: random.Random, gen: int) -> dict:
    c = deepcopy(cfg)
    c["min_edge"] = round(min(0.06, float(c.get("min_edge", 0.035)) + rng.choice([0.0, 0.005, 0.01])), 3)
    c["soft_edge"] = round(c["min_edge"] * 1.4, 3)
    c["hard_edge"] = round(c["min_edge"] * 2.2, 3)
    c["min_z"] = round(min(1.5, float(c.get("min_z", 1.0)) + rng.choice([0.0, 0.05, 0.1])), 2)
    c["quote_size_shares"] = max(14, int(c.get("quote_size_shares", 22)) + rng.choice([-4, -2, 0]))
    c["max_size_mult"] = round(max(1.2, float(c.get("max_size_mult", 1.6)) - rng.choice([0.0, 0.1, 0.2])), 1)
    c["max_entry_fills"] = max(3, int(c.get("max_entry_fills", 5)) + rng.choice([-2, -1, 0]))
    c["max_loss_usdc"] = round(max(1.5, float(c.get("max_loss_usdc", 2.5)) - rng.choice([0.0, 0.3, 0.5])), 1)
    c["stop_loss_mid"] = round(max(0.008, float(c.get("stop_loss_mid", 0.012)) - rng.choice([0.0, 0.001, 0.002])), 3)
    c["session_kill_net_usdc"] = round(max(3.0, float(c.get("session_kill_net_usdc", 5)) - rng.choice([0.0, 0.5, 1.0])), 1)
    c["min_expected_pnl_usdc"] = round(float(c.get("min_expected_pnl_usdc", 0.4)) + rng.choice([0.0, 0.05, 0.1]), 2)
    c["cooldown_after_fill_s"] = max(4, int(c.get("cooldown_after_fill_s", 6)) + rng.choice([0, 1, 2]))
    c["max_inventory_shares"] = max(c["quote_size_shares"], int(c["quote_size_shares"] * 1.2))
    c["max_notional_per_side_usdc"] = round(c["quote_size_shares"] * 1.15, 1)
    c["max_inventory_usdc"] = round(c["max_inventory_shares"] * 1.05, 1)
    c["fair_fade_exit"] = True
    c["demo_label"] = f"wr_fast_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    return c


def _ok(summary: dict) -> bool:
    wr = float(summary.get("win_rate") or 0)
    avg = float(summary.get("avg_net_usdc") or 0)
    losses = int(summary.get("losses") or 99)
    traded = int(summary.get("sessions_with_fills") or 0)
    return wr >= WR_TARGET and avg >= AVG_FLOOR and losses <= MAX_LOSSES and traded >= MIN_TRADED


async def _batch_retry(path: Path, attempts: int = 3) -> dict:
    last: Exception | None = None
    for a in range(1, attempts + 1):
        try:
            return await run_batch(
                strategy="maker_edge",
                config=str(path),
                sessions=SESSIONS,
                minutes=MINUTES,
            )
        except Exception as e:
            last = e
            wait = min(45, 5 * a)
            print(f"WARN batch fail {a}/{attempts}: {e!r} retry {wait}s", flush=True)
            await asyncio.sleep(wait)
    assert last is not None
    raise last


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "STOP_AUTONOMOUS_OOS").write_text("confirm_wr_fast owns the machine\n", encoding="utf-8")
    rng = random.Random(20260716)
    base = _load_base()
    # Seed: wr_hunt + best-mini + one tighter
    hunt = json.loads((CFG_DIR / "maker_demo_100_usd_wr_hunt.json").read_text(encoding="utf-8"))
    seeds = [deepcopy(base), deepcopy(hunt), mutate_wr(hunt, rng, 0)]
    history: list[dict] = []
    best: dict | None = None

    meta = {
        "mode": "confirm_wr_fast",
        "live_onchain": False,
        "wr_target": WR_TARGET,
        "sessions": SESSIONS,
        "minutes": MINUTES,
        "max_trials": MAX_TRIALS,
    }
    (OUT / "confirm_wr_fast_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)

    for i in range(1, MAX_TRIALS + 1):
        cfg = seeds[i - 1] if i <= len(seeds) else mutate_wr(best["cfg"] if best else base, rng, i)
        path = OUT / f"confirm_wr_fast_{i:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(
            f"\n######## WR-FAST TRIAL {i}/{MAX_TRIALS} {cfg['demo_label']} "
            f"{SESSIONS}x{MINUTES}m ########",
            flush=True,
        )
        print(
            f"size={cfg['quote_size_shares']} edge={cfg['min_edge']} "
            f"max_loss={cfg.get('max_loss_usdc')} entries={cfg.get('max_entry_fills')}",
            flush=True,
        )
        summary = await _batch_retry(path)
        total = round(sum(r["net"] for r in summary["results"]), 2)
        row = {
            "trial": i,
            "label": cfg["demo_label"],
            "wr": summary.get("win_rate"),
            "avg": summary.get("avg_net_usdc"),
            "losses": summary.get("losses"),
            "traded": summary.get("sessions_with_fills"),
            "total": total,
            "size": cfg["quote_size_shares"],
            "min_edge": cfg["min_edge"],
            "results": summary["results"],
            "hit": _ok(summary),
        }
        history.append(row)
        (OUT / "confirm_wr_fast_history.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )
        print(
            f"-> WR={100*(row['wr'] or 0):.1f}% avg={row['avg']:+.2f} total={total:+.2f} "
            f"traded={row['traded']} losses={row['losses']} HIT={row['hit']}",
            flush=True,
        )
        score = (float(row["wr"] or 0), float(row["avg"] or 0), -int(row["losses"] or 0))
        if best is None or score > best["score"]:
            best = {"score": score, "cfg": deepcopy(cfg), "row": row}
            (OUT / "confirm_wr_fast_best.json").write_text(
                json.dumps({"cfg": cfg, "row": row}, indent=2), encoding="utf-8"
            )

        if row["hit"]:
            freeze = CFG_DIR / "maker_demo_100_usd_wr75_confirmed.json"
            freeze.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            (OUT / "confirm_wr_fast_hit.json").write_text(
                json.dumps({"cfg": cfg, "row": row}, indent=2), encoding="utf-8"
            )
            print(f"\n*** WR>=75% CONFIRMED (fast real-feed) *** → {freeze}", flush=True)
            return 0

    print("\n*** WR-FAST EXHAUSTED — no confirmation ***", flush=True)
    if best:
        print(json.dumps(best["row"], indent=2), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
