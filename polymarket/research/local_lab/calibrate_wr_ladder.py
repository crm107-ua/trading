#!/usr/bin/env python3
"""
Calibración escalonada maker_edge (paper, real-feed):

  Fase A (mini):  pocas sesiones × minutos cortos → adaptar poco a poco.
  Fase B (largo): si pasa A, promover a sesiones ≥10 min y exigir WR≥75%.

Sin fills sintéticos. No es live on-chain. No es screen vinculante.
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

WR_MINI = float(os.getenv("CAL_WR_MINI", "0.67"))
WR_PROMOTE = float(os.getenv("CAL_WR_PROMOTE", "0.75"))
AVG_MINI = float(os.getenv("CAL_AVG_MINI", "2.0"))
AVG_PROMOTE = float(os.getenv("CAL_AVG_PROMOTE", "8.0"))
MAX_LOSS_MINI = int(os.getenv("CAL_MAX_LOSS_MINI", "1"))
MAX_LOSS_PROMOTE = int(os.getenv("CAL_MAX_LOSS_PROMOTE", "1"))
MIN_TRADED_MINI = int(os.getenv("CAL_MIN_TRADED_MINI", "2"))
MIN_TRADED_PROMOTE = int(os.getenv("CAL_MIN_TRADED_PROMOTE", "3"))

MINI_SESSIONS = int(os.getenv("CAL_MINI_SESSIONS", "3"))
MINI_MINUTES = float(os.getenv("CAL_MINI_MINUTES", "2.5"))
PROMOTE_SESSIONS = int(os.getenv("CAL_PROMOTE_SESSIONS", "4"))
PROMOTE_MINUTES = float(os.getenv("CAL_PROMOTE_MINUTES", "12"))
MAX_ROUNDS = int(os.getenv("CAL_MAX_ROUNDS", "10"))


def _base_cfg() -> dict:
    p = CFG_DIR / "maker_demo_100_usd_risk_pack.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
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


def mutate_gentle(cfg: dict, rng: random.Random, gen: int, *, reason: str) -> dict:
    """Mutación pequeña según fallo (cola / WR / flat)."""
    c = deepcopy(cfg)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    if "loss" in reason or "tail" in reason:
        c["quote_size_shares"] = max(18, int(c["quote_size_shares"] * rng.choice([0.85, 0.9])))
        c["max_size_mult"] = round(max(1.4, float(c["max_size_mult"]) - 0.2), 1)
        c["max_loss_usdc"] = round(max(2.0, float(c["max_loss_usdc"]) - 0.5), 1)
        c["stop_loss_mid"] = round(max(0.01, float(c["stop_loss_mid"]) - 0.002), 3)
        c["session_kill_net_usdc"] = round(max(5.0, float(c.get("session_kill_net_usdc", 8)) - 1.0), 1)
        c["max_entry_fills"] = max(4, int(c["max_entry_fills"]) - 1)
    elif "wr" in reason:
        c["min_edge"] = round(min(0.055, float(c["min_edge"]) + 0.005), 3)
        c["soft_edge"] = round(c["min_edge"] * 1.4, 3)
        c["hard_edge"] = round(c["min_edge"] * 2.2, 3)
        c["min_z"] = round(min(1.4, float(c["min_z"]) + 0.05), 2)
        c["min_expected_pnl_usdc"] = round(float(c["min_expected_pnl_usdc"]) + 0.05, 2)
    elif "flat" in reason or "trade" in reason:
        c["min_edge"] = round(max(0.025, float(c["min_edge"]) - 0.005), 3)
        c["soft_edge"] = round(c["min_edge"] * 1.4, 3)
        c["hard_edge"] = round(c["min_edge"] * 2.2, 3)
        c["quote_size_shares"] = min(40, int(c["quote_size_shares"]) + 2)
        c["max_entry_fills"] = min(12, int(c["max_entry_fills"]) + 1)
        c["cooldown_after_fill_s"] = max(2, int(c["cooldown_after_fill_s"]) - 1)
    else:
        # Empuje leve mixto
        c["quote_size_shares"] = int(
            rng.choice(
                [
                    max(18, int(c["quote_size_shares"]) - 2),
                    int(c["quote_size_shares"]),
                    min(38, int(c["quote_size_shares"]) + 2),
                ]
            )
        )
        c["max_loss_usdc"] = round(rng.choice([2.5, 3.0, 3.5, 4.0]), 1)
        c["min_edge"] = round(rng.choice([0.03, 0.032, 0.035, 0.038]), 3)
        c["soft_edge"] = round(c["min_edge"] * 1.4, 3)
        c["hard_edge"] = round(c["min_edge"] * 2.2, 3)

    c["max_inventory_shares"] = max(c["quote_size_shares"], int(c["quote_size_shares"] * 1.25))
    c["max_notional_per_side_usdc"] = round(c["quote_size_shares"] * 1.2, 1)
    c["max_inventory_usdc"] = round(c["max_inventory_shares"] * 1.05, 1)
    c["demo_label"] = f"cal_g{gen}_{stamp}"
    return c


def _fail_reason(summary: dict, *, phase: str) -> str | None:
    wr = float(summary.get("win_rate") or 0)
    avg = float(summary.get("avg_net_usdc") or 0)
    losses = int(summary.get("losses") or 0)
    traded = int(summary.get("sessions_with_fills") or 0)
    if phase == "mini":
        if traded < MIN_TRADED_MINI:
            return "flat_trade"
        if losses > MAX_LOSS_MINI:
            return "loss_tail"
        if wr < WR_MINI:
            return "wr"
        if avg < AVG_MINI:
            return "wr_avg"
        return None
    if traded < MIN_TRADED_PROMOTE:
        return "flat_trade"
    if losses > MAX_LOSS_PROMOTE:
        return "loss_tail"
    if wr < WR_PROMOTE:
        return "wr"
    if avg < AVG_PROMOTE:
        return "wr_avg"
    return None


def _row(phase: str, round_i: int, cfg: dict, summary: dict, reason: str | None) -> dict:
    return {
        "phase": phase,
        "round": round_i,
        "label": cfg.get("demo_label"),
        "wr": summary.get("win_rate"),
        "avg_net": summary.get("avg_net_usdc"),
        "losses": summary.get("losses"),
        "traded": summary.get("sessions_with_fills"),
        "total": round(sum(r["net"] for r in summary["results"]), 2),
        "fail_reason": reason,
        "size": cfg.get("quote_size_shares"),
        "min_edge": cfg.get("min_edge"),
        "max_loss": cfg.get("max_loss_usdc"),
        "kill": cfg.get("session_kill_net_usdc"),
        "results": summary.get("results"),
    }


async def _run_batch_retry(
    *,
    strategy: str,
    config: str,
    sessions: int,
    minutes: float,
    attempts: int = 4,
) -> dict:
    last: Exception | None = None
    for a in range(1, attempts + 1):
        try:
            return await run_batch(
                strategy=strategy,
                config=config,
                sessions=sessions,
                minutes=minutes,
            )
        except Exception as e:  # network / gamma flakes
            last = e
            wait = min(60, 5 * a)
            print(f"WARN batch failed attempt {a}/{attempts}: {e!r} — retry in {wait}s", flush=True)
            await asyncio.sleep(wait)
    assert last is not None
    raise last


async def main() -> int:
    rng = random.Random(20260716)
    cfg = _base_cfg()
    history: list[dict] = []
    promoted: dict | None = None
    best_mini: dict | None = None
    best_long: dict | None = None

    meta = {
        "mode": "calibrate_wr_ladder",
        "live_onchain": False,
        "mini": {"sessions": MINI_SESSIONS, "minutes": MINI_MINUTES, "wr": WR_MINI, "avg": AVG_MINI},
        "promote": {
            "sessions": PROMOTE_SESSIONS,
            "minutes": PROMOTE_MINUTES,
            "wr": WR_PROMOTE,
            "avg": AVG_PROMOTE,
        },
        "max_rounds": MAX_ROUNDS,
        "base_config": "maker_demo_100_usd_risk_pack.json",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calibrate_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)

    for i in range(1, MAX_ROUNDS + 1):
        # ---- Fase A: mini ----
        path = OUT / f"calibrate_mini_{i:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(
            f"\n######## CAL MINI {i}/{MAX_ROUNDS} {cfg['demo_label']} "
            f"{MINI_SESSIONS}x{MINI_MINUTES}m ########",
            flush=True,
        )
        print(
            f"size={cfg['quote_size_shares']} edge={cfg['min_edge']} "
            f"max_loss={cfg.get('max_loss_usdc')} kill={cfg.get('session_kill_net_usdc')} "
            f"entries={cfg.get('max_entry_fills')}",
            flush=True,
        )
        mini = await _run_batch_retry(
            strategy="maker_edge",
            config=str(path),
            sessions=MINI_SESSIONS,
            minutes=MINI_MINUTES,
        )
        reason = _fail_reason(mini, phase="mini")
        row = _row("mini", i, cfg, mini, reason)
        history.append(row)
        (OUT / "calibrate_history.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )
        print(
            f"MINI → WR={row['wr']} avg={row['avg_net']} losses={row['losses']} "
            f"traded={row['traded']} total={row['total']} fail={reason}",
            flush=True,
        )
        score = (float(row["wr"] or 0), float(row["avg_net"] or 0), -int(row["losses"] or 0))
        if best_mini is None or score > best_mini["score"]:
            best_mini = {"score": score, "cfg": deepcopy(cfg), "row": row}
            (OUT / "calibrate_best_mini.json").write_text(
                json.dumps({"cfg": cfg, "row": row}, indent=2), encoding="utf-8"
            )

        if reason is not None:
            cfg = mutate_gentle(cfg, rng, i, reason=reason)
            continue

        # ---- Fase B: promover a ≥10 min ----
        print(
            f"\n######## CAL PROMOTE {i} {cfg['demo_label']} "
            f"{PROMOTE_SESSIONS}x{PROMOTE_MINUTES}m ########",
            flush=True,
        )
        ppath = OUT / f"calibrate_promote_{i:02d}.json"
        ppath.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        long = await _run_batch_retry(
            strategy="maker_edge",
            config=str(ppath),
            sessions=PROMOTE_SESSIONS,
            minutes=PROMOTE_MINUTES,
        )
        preason = _fail_reason(long, phase="promote")
        prow = _row("promote", i, cfg, long, preason)
        history.append(prow)
        (OUT / "calibrate_history.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )
        print(
            f"PROMOTE → WR={prow['wr']} avg={prow['avg_net']} losses={prow['losses']} "
            f"traded={prow['traded']} total={prow['total']} fail={preason}",
            flush=True,
        )
        lscore = (float(prow["wr"] or 0), float(prow["avg_net"] or 0), -int(prow["losses"] or 0))
        if best_long is None or lscore > best_long["score"]:
            best_long = {"score": lscore, "cfg": deepcopy(cfg), "row": prow}
            (OUT / "calibrate_best_long.json").write_text(
                json.dumps({"cfg": cfg, "row": prow}, indent=2), encoding="utf-8"
            )

        if preason is None:
            promoted = {"cfg": deepcopy(cfg), "row": prow}
            freeze = CFG_DIR / "maker_demo_100_usd_calibrated.json"
            freeze.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            (OUT / "calibrate_promoted.json").write_text(
                json.dumps(promoted, indent=2), encoding="utf-8"
            )
            print(
                f"\n*** CALIBRATION TARGET HIT *** frozen → {freeze}",
                flush=True,
            )
            print(json.dumps(prow, indent=2), flush=True)
            return 0

        cfg = mutate_gentle(cfg, rng, i, reason=preason or "wr")

    print("\n*** CALIBRATION EXHAUSTED ***", flush=True)
    if best_long:
        print("best_long:", json.dumps(best_long["row"], indent=2), flush=True)
    elif best_mini:
        print("best_mini:", json.dumps(best_mini["row"], indent=2), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
