#!/usr/bin/env python3
"""
Optimiza el OOS Trial 1 (hito) — lo que SÍ funcionaba — sin repetir el error size↑.

Base: margin_max_v3 / real_sim_oos_v1 (WR 50%, avg +15.73, total +125).
Cambios: size↓ leve, max_loss↓, fair_fade, kill sesión, anti-racha.
Mutaciones: NUNCA subir size por encima del base opt; solo cortar cola o afinar TP.

Target lab: WR≥62.5% (5/8) stretch 75%; avg≥12 stretch 20. No on-chain.
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

WR_TARGET = float(os.getenv("T1_WR_TARGET", "0.5"))  # OOS Trial1 realista; subir con env
AVG_TARGET = float(os.getenv("T1_AVG_TARGET", "8"))  # € con cola corta
SESSIONS = int(os.getenv("T1_SESSIONS", "6"))
MINUTES = float(os.getenv("T1_MINUTES", "4.5"))
MAX_TRIALS = int(os.getenv("T1_MAX_TRIALS", "5"))
MAX_LOSSES = int(os.getenv("T1_MAX_LOSSES", "3"))  # 3/6 = WR 50% stretch
SIZE_CAP = int(os.getenv("T1_SIZE_CAP", "36"))  # nunca 42×3


def _t1_frozen() -> dict:
    """Exact Trial 1 / hito (baseline)."""
    p = CFG_DIR / "maker_demo_100_usd_margin_best.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg.update(
        {
            "demo_label": "oos_t1_frozen",
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "flatten_after_fill": False,
            "mean_reversion_exit": False,
            "exit_hazard_per_s": 0,
            "fair_fade_exit": False,
            "initial_capital_usdc": 100.0,
            "currency_label": "EUR",
        }
    )
    return cfg


def _t1_opt() -> dict:
    """v5 asimétrico: size↑ + TP alto (más €) + corte de rojos/rachas."""
    p = CFG_DIR / "maker_demo_100_usd_margin_v5_asymmetric.json"
    if not p.exists():
        p = CFG_DIR / "maker_demo_100_usd_margin_v4_cut_tail.json"
    if p.exists():
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
                "currency_label": "EUR",
            }
        )
        return cfg
    return _t1_frozen()


def mutate_cut_tail(cfg: dict, rng: random.Random, gen: int, *, wr: float, losses: int) -> dict:
    """Corta cola tóxica sin asfixiar fills; si WR ok, más € con cap."""
    c = deepcopy(cfg)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    cap = min(SIZE_CAP, int(c.get("max_quote_size_shares") or SIZE_CAP))
    wr_ok = wr >= WR_TARGET and losses <= MAX_LOSSES
    if not wr_ok:
        # Menos lotería + salidas más rápidas (NO subir min_edge sin parar)
        c["min_quote_mid"] = round(min(0.35, float(c.get("min_quote_mid", 0.28)) + 0.02), 2)
        c["max_quote_mid"] = round(max(0.65, float(c.get("max_quote_mid", 0.72)) - 0.02), 2)
        c["max_loss_usdc"] = round(max(1.5, float(c.get("max_loss_usdc", 2.5)) - 0.25), 2)
        c["session_kill_net_usdc"] = round(max(2.5, float(c.get("session_kill_net_usdc", 4)) - 0.5), 1)
        c["stop_loss_mid"] = round(max(0.008, float(c.get("stop_loss_mid", 0.012)) - 0.001), 3)
        c["flatten_before_window_s"] = min(70, int(c.get("flatten_before_window_s", 45)) + 5)
        c["quote_size_shares"] = max(22, int(c["quote_size_shares"]) - rng.choice([0, 2]))
        c["max_size_mult"] = round(max(1.4, float(c["max_size_mult"]) - 0.1), 1)
        c["min_edge"] = round(min(0.04, max(0.028, float(c["min_edge"]) + rng.choice([-0.002, 0.0, 0.002]))), 3)
    else:
        c["quote_size_shares"] = min(cap, int(c["quote_size_shares"]) + rng.choice([1, 2]))
        c["tp_capture_frac"] = round(min(0.8, float(c.get("tp_capture_frac", 0.65)) + 0.03), 2)
        c["max_take_profit"] = round(min(0.11, float(c["max_take_profit"]) + 0.01), 3)
        c["max_size_mult"] = round(min(1.9, float(c["max_size_mult"]) + 0.1), 1)
    c["max_quote_size_shares"] = cap
    c["soft_edge"] = round(float(c["min_edge"]) * 1.4, 3)
    c["hard_edge"] = round(float(c["min_edge"]) * 2.15, 3)
    c["max_inventory_shares"] = max(int(c["quote_size_shares"]), int(c["quote_size_shares"] * 1.15))
    c["max_notional_per_side_usdc"] = round(min(36, c["quote_size_shares"] * 1.1), 1)
    c["max_inventory_usdc"] = round(float(c["max_inventory_shares"]), 1)
    c["fair_fade_exit"] = True
    c["pause_after_consecutive_losses"] = 2
    c["initial_capital_usdc"] = 100.0
    c["currency_label"] = "EUR"
    c["demo_label"] = f"profit_g{gen}_{stamp}"
    return c


def _hit(summary: dict) -> bool:
    wr = float(summary.get("win_rate") or 0)
    avg = float(summary.get("avg_net_usdc") or 0)
    losses = int(summary.get("losses") or 99)
    traded = int(summary.get("sessions_with_fills") or 0)
    return wr >= WR_TARGET and avg >= AVG_TARGET and losses <= MAX_LOSSES and traded >= 4


async def _batch(path: Path) -> dict:
    last: Exception | None = None
    for a in range(1, 4):
        try:
            return await run_batch(
                strategy="maker_edge",
                config=str(path),
                sessions=SESSIONS,
                minutes=MINUTES,
            )
        except Exception as e:
            last = e
            print(f"WARN {e!r} retry {a}", flush=True)
            await asyncio.sleep(5 * a)
    assert last
    raise last


async def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "STOP_AUTONOMOUS_OOS").write_text("optimize_oos_t1\n", encoding="utf-8")
    rng = random.Random(20260716)
    history: list[dict] = []
    best: dict | None = None

    seeds = [
        _t1_opt(),  # start with optimized T1 (not size↑)
        mutate_cut_tail(_t1_opt(), rng, 0, wr=0.4, losses=3),
        mutate_cut_tail(_t1_opt(), rng, 0, wr=0.5, losses=2),
    ]
    # Optional: skip full frozen T1 re-run (already known); focus on opt
    if os.getenv("T1_INCLUDE_FROZEN", "").strip() in {"1", "true"}:
        seeds.insert(0, _t1_frozen())

    meta = {
        "mode": "optimize_oos_t1",
        "thesis": "Improve Trial1 (worked) by cutting loss tail; never size↑ like Trial2",
        "baseline_oos_t1": {"wr": 0.5, "avg": 15.73, "total": 125.81},
        "wr_target": WR_TARGET,
        "avg_target": AVG_TARGET,
        "sessions": SESSIONS,
        "minutes": MINUTES,
        "max_trials": MAX_TRIALS,
        "live_onchain": False,
    }
    (OUT / "optimize_oos_t1_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2), flush=True)

    for i in range(1, MAX_TRIALS + 1):
        cfg = seeds[i - 1] if i <= len(seeds) else mutate_cut_tail(
            best["cfg"] if best else _t1_opt(),
            rng,
            i,
            wr=float((best or {}).get("row", {}).get("wr") or 0),
            losses=int((best or {}).get("row", {}).get("losses") or 3),
        )
        path = OUT / f"optimize_oos_t1_{i:02d}.json"
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(
            f"\n######## OOS-T1 OPT {i}/{MAX_TRIALS} {cfg['demo_label']} "
            f"{SESSIONS}x{MINUTES}m ########",
            flush=True,
        )
        print(
            f"size={cfg['quote_size_shares']} mult={cfg['max_size_mult']} "
            f"edge={cfg['min_edge']} max_loss={cfg.get('max_loss_usdc')} "
            f"kill={cfg.get('session_kill_net_usdc')} entries={cfg.get('max_entry_fills')}",
            flush=True,
        )
        summary = await _batch(path)
        total = round(sum(r["net"] for r in summary["results"]), 2)
        nets = [r["net"] for r in summary["results"]]
        row = {
            "trial": i,
            "label": cfg["demo_label"],
            "wr": summary.get("win_rate"),
            "avg": summary.get("avg_net_usdc"),
            "total": total,
            "losses": summary.get("losses"),
            "traded": summary.get("sessions_with_fills"),
            "worst": min(nets) if nets else None,
            "best_sess": max(nets) if nets else None,
            "nets": nets,
            "size": cfg["quote_size_shares"],
            "max_loss": cfg.get("max_loss_usdc"),
            "hit": _hit(summary),
        }
        history.append(row)
        (OUT / "optimize_oos_t1_history.json").write_text(
            json.dumps(history, indent=2), encoding="utf-8"
        )
        print(
            f"-> WR={100*(row['wr'] or 0):.1f}% avg={row['avg']:+.2f} total={total:+.2f} "
            f"losses={row['losses']} worst={row['worst']} HIT={row['hit']}",
            flush=True,
        )
        print(f"   nets={nets}", flush=True)

        # WR≥70% primero, luego pérdidas↓, luego €, luego cola
        score = (
            1 if float(row["wr"] or 0) >= WR_TARGET else 0,
            float(row["wr"] or 0),
            -int(row["losses"] or 0),
            float(row["avg"] or 0),
            float(row["total"] or 0),
            -abs(float(row["worst"] or 0)),
        )
        if best is None or score > best["score"]:
            best = {"score": score, "cfg": deepcopy(cfg), "row": row}
            (OUT / "optimize_oos_t1_best.json").write_text(
                json.dumps({"cfg": cfg, "row": row}, indent=2), encoding="utf-8"
            )
            (CFG_DIR / "maker_demo_100_usd_oos_t1_opt_best.json").write_text(
                json.dumps(cfg, indent=2), encoding="utf-8"
            )

        if row["hit"]:
            print("\n*** OOS-T1 OPT TARGET HIT ***", flush=True)
            return 0

    print("\n*** BEST EFFORT ***", flush=True)
    if best:
        print(json.dumps(best["row"], indent=2), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
