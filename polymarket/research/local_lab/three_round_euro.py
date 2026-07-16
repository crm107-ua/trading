#!/usr/bin/env python3
"""
Prueba 100€ × 3 rondas — maximizar rondas con ganancia (WR > 50% ⇒ ≥2/3).

Paper real-feed. No on-chain. Métrica primaria: wins_count (0..3).
Secundaria: profit_sum solo de rondas verdes + total neto.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.batch_paper_eval import run_batch
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab"
CFG_DIR = POLY / "config"

ROUNDS = int(os.getenv("THREE_ROUNDS", "3"))
MINUTES = float(os.getenv("THREE_MINUTES", "4.0"))
MAX_TRIALS = int(os.getenv("THREE_MAX_TRIALS", "4"))
# WR > 50% con 3 rondas ⇒ al menos 2 verdes
MIN_WINS = int(os.getenv("THREE_MIN_WINS", "2"))


def _base() -> dict:
    p = CFG_DIR / "maker_demo_100_eur_three_round.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    best = OUT / "calibrate_best_mini.json"
    if best.exists():
        packed = json.loads(best.read_text(encoding="utf-8"))
        if isinstance(packed.get("cfg"), dict):
            # Keep risk from best mini but force 100€ label
            cfg = {**packed["cfg"], **{k: cfg[k] for k in (
                "currency_label", "initial_capital_usdc", "demo_label"
            ) if k in cfg}}
            cfg["currency_label"] = "EUR"
            cfg["initial_capital_usdc"] = 100.0
            cfg["fair_fade_exit"] = True
    cfg.update(
        {
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "flatten_after_fill": False,
            "mean_reversion_exit": False,
            "exit_hazard_per_s": 0,
            "initial_capital_usdc": 100.0,
            "currency_label": "EUR",
        }
    )
    return cfg


def mutate_for_wins(cfg: dict, rng: random.Random, gen: int, *, last_wins: int) -> dict:
    c = deepcopy(cfg)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    if last_wins < MIN_WINS:
        # Más selectivo / cola más corta para convertir losses en flat o small win
        c["min_edge"] = round(min(0.05, float(c["min_edge"]) + 0.003), 3)
        c["soft_edge"] = round(c["min_edge"] * 1.4, 3)
        c["hard_edge"] = round(c["min_edge"] * 2.2, 3)
        c["quote_size_shares"] = max(18, int(c["quote_size_shares"]) - 2)
        c["max_loss_usdc"] = round(max(2.0, float(c["max_loss_usdc"]) - 0.3), 1)
        c["max_entry_fills"] = max(4, int(c["max_entry_fills"]) - 1)
        c["session_kill_net_usdc"] = round(max(4.0, float(c.get("session_kill_net_usdc", 7)) - 0.5), 1)
    else:
        # Ya ≥2 wins: empujar un poco el € ganado sin romper WR
        c["quote_size_shares"] = min(36, int(c["quote_size_shares"]) + rng.choice([0, 1, 2]))
        c["tp_capture_frac"] = round(min(0.7, float(c.get("tp_capture_frac", 0.55)) + 0.02), 2)
        c["max_take_profit"] = round(min(0.1, float(c.get("max_take_profit", 0.08)) + 0.01), 3)
    c["max_inventory_shares"] = max(c["quote_size_shares"], int(c["quote_size_shares"] * 1.25))
    c["max_notional_per_side_usdc"] = round(c["quote_size_shares"] * 1.2, 1)
    c["max_inventory_usdc"] = round(c["max_inventory_shares"] * 1.05, 1)
    c["demo_label"] = f"three_eur_g{gen}_{stamp}"
    c["currency_label"] = "EUR"
    c["initial_capital_usdc"] = 100.0
    return c


def score_row(results: list[dict]) -> dict:
    rounds = []
    for i, r in enumerate(results, 1):
        net = float(r["net"])
        rounds.append(
            {
                "round": i,
                "session_id": r["session_id"],
                "net_eur": round(net, 2),
                "fills": r["fills"],
                "win": net > 0,
                "flat": net == 0 and r["fills"] == 0,
            }
        )
    wins = [x for x in rounds if x["win"]]
    losses = [x for x in rounds if x["net_eur"] < 0]
    profit_green = round(sum(x["net_eur"] for x in wins), 2)
    total = round(sum(x["net_eur"] for x in rounds), 2)
    wr = (len(wins) / len([x for x in rounds if x["fills"] > 0])) if any(
        x["fills"] > 0 for x in rounds
    ) else 0.0
    return {
        "rounds": rounds,
        "wins_count": len(wins),
        "losses_count": len(losses),
        "profit_on_green_eur": profit_green,
        "total_net_eur": total,
        "wr": round(wr, 4),
        "wr_gt_50": len(wins) >= MIN_WINS,
        "maximize_target": "wins_count then profit_on_green_eur",
    }


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "STOP_AUTONOMOUS_OOS").write_text("three_round_euro\n", encoding="utf-8")
    rng = random.Random(20260716)
    cfg = _base()
    history: list[dict] = []
    best: dict | None = None

    meta = {
        "mode": "three_round_100eur",
        "capital_eur": 100.0,
        "rounds": ROUNDS,
        "minutes_each": MINUTES,
        "min_wins_for_wr_gt_50": MIN_WINS,
        "maximize": ["wins_count", "profit_on_green_eur", "total_net_eur"],
        "live_onchain": False,
        "max_trials": MAX_TRIALS,
    }
    (OUT / "three_round_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)

    for trial in range(1, MAX_TRIALS + 1):
        path = OUT / f"three_round_cfg_{trial:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(
            f"\n######## 100€ × {ROUNDS} RONDAS — trial {trial}/{MAX_TRIALS} "
            f"{cfg['demo_label']} ({MINUTES} min c/u) ########",
            flush=True,
        )
        print(
            f"size={cfg['quote_size_shares']} edge={cfg['min_edge']} "
            f"max_loss={cfg.get('max_loss_usdc')}",
            flush=True,
        )
        summary = await run_batch(
            strategy="maker_edge",
            config=str(path),
            sessions=ROUNDS,
            minutes=MINUTES,
        )
        scored = score_row(summary["results"])
        row = {
            "trial": trial,
            "label": cfg["demo_label"],
            "cfg_snapshot": {
                "size": cfg["quote_size_shares"],
                "min_edge": cfg["min_edge"],
                "max_loss": cfg.get("max_loss_usdc"),
            },
            **scored,
        }
        history.append(row)
        (OUT / "three_round_history.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )

        print("\n--- RONDAS ---", flush=True)
        for r in scored["rounds"]:
            tag = "WIN" if r["win"] else ("FLAT" if r["flat"] else "LOSS")
            print(
                f"  Ronda {r['round']}: {tag}  net={r['net_eur']:+.2f}€  fills={r['fills']}",
                flush=True,
            )
        print(
            f"-> wins={scored['wins_count']}/{ROUNDS}  WR={100*scored['wr']:.1f}%  "
            f"verde_sum={scored['profit_on_green_eur']:+.2f}€  "
            f"total={scored['total_net_eur']:+.2f}€  "
            f"WR>50%={scored['wr_gt_50']}",
            flush=True,
        )

        key = (
            scored["wins_count"],
            scored["profit_on_green_eur"],
            scored["total_net_eur"],
        )
        if best is None or key > best["key"]:
            best = {"key": key, "cfg": deepcopy(cfg), "row": row}
            (OUT / "three_round_best.json").write_text(
                json.dumps({"cfg": cfg, "row": row}, indent=2), encoding="utf-8"
            )
            freeze = CFG_DIR / "maker_demo_100_eur_three_round_best.json"
            freeze.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

        if scored["wins_count"] >= MIN_WINS and scored["total_net_eur"] > 0:
            print(
                f"\n*** OBJETIVO: ≥{MIN_WINS}/3 rondas en verde y total>0 ***",
                flush=True,
            )
            # Un trial más para maximizar € en verdes si queda budget
            if trial < MAX_TRIALS:
                cfg = mutate_for_wins(cfg, rng, trial, last_wins=scored["wins_count"])
                continue
            break

        cfg = mutate_for_wins(cfg, rng, trial, last_wins=scored["wins_count"])

    print("\n======== MEJOR HASTA AHORA ========", flush=True)
    if best:
        print(json.dumps(best["row"], indent=2), flush=True)
        print(
            f"Congelado: config/maker_demo_100_eur_three_round_best.json",
            flush=True,
        )
    return 0 if best and best["row"]["wins_count"] >= MIN_WINS else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
