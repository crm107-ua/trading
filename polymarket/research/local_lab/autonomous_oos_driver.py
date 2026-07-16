#!/usr/bin/env python3
"""
Supervisor autónomo: lanza real-sim OOS, analiza fallos, muta config y repite
hasta WR>=75% y avg_net>=TARGET (feeds reales, no on-chain).

Uso:
  python -u -m polymarket.research.local_lab.autonomous_oos_driver
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab"
CFG_DIR = POLY / "config"
REPO = POLY.parent
LOG = OUT / "autonomous_oos.log"
STOP = OUT / "STOP_AUTONOMOUS_OOS"
WR_TARGET = 0.75
AVG_TARGET = 20.0
MAX_GENERATIONS = 8


def _log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _base_cfg() -> dict:
    for name in (
        "maker_demo_100_usd_real_sim_best.json",
        "maker_demo_100_usd_margin_best.json",
        "maker_demo_100_usd_margin.json",
    ):
        p = CFG_DIR / name
        if p.is_file():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            break
    else:
        raise FileNotFoundError("No base config for autonomous OOS")
    cfg.update(
        {
            "paper_touch_fill_every_n": 0,
            "paper_pnl_mode": "",
            "flatten_after_fill": False,
            "mean_reversion_exit": False,
            "exit_hazard_per_s": 0,
            "initial_capital_usdc": 100.0,
        }
    )
    return cfg


def _adapt(cfg: dict, last: dict | None, gen: int, rng: random.Random) -> dict:
    """Mutate toward fewer losses / higher avg based on last trial summary."""
    c = deepcopy(cfg)
    c["demo_label"] = f"auto_oos_g{gen}_{datetime.now(timezone.utc).strftime('%H%M%S')}"
    if not last:
        return c
    wr = float(last.get("win_rate") or 0)
    avg = float(last.get("avg_net_usdc") or 0)
    losses = int(last.get("losses") or 0)
    # Too many losses → tighter risk
    if wr < WR_TARGET or losses >= 3:
        c["max_loss_usdc"] = round(max(3.5, float(c.get("max_loss_usdc", 6)) * 0.85), 2)
        c["stop_loss_mid"] = round(max(0.012, float(c.get("stop_loss_mid", 0.018)) * 0.9), 3)
        c["min_edge"] = round(min(0.05, float(c.get("min_edge", 0.03)) + 0.005), 3)
        c["soft_edge"] = round(c["min_edge"] + 0.015, 3)
        c["hard_edge"] = round(c["soft_edge"] + 0.03, 3)
        c["quote_size_shares"] = max(28, int(float(c.get("quote_size_shares", 42)) * 0.9))
        c["max_entry_fills"] = max(6, int(c.get("max_entry_fills", 14)) - 2)
        c["cooldown_after_fill_s"] = max(3, int(c.get("cooldown_after_fill_s", 3)) + 1)
    # WR ok but avg low → size / TP up carefully
    elif avg < AVG_TARGET:
        c["quote_size_shares"] = min(60, int(float(c.get("quote_size_shares", 42)) * 1.1))
        c["max_size_mult"] = min(3.5, float(c.get("max_size_mult", 3.0)) + 0.2)
        c["tp_capture_frac"] = min(0.7, float(c.get("tp_capture_frac", 0.55)) + 0.05)
        c["max_take_profit"] = min(0.12, float(c.get("max_take_profit", 0.09)) + 0.01)
        c["max_notional_per_side_usdc"] = min(60, float(c.get("max_notional_per_side_usdc", 48)) + 3)
        c["max_inventory_usdc"] = min(65, float(c.get("max_inventory_usdc", 55)) + 3)
    c["max_inventory_shares"] = max(
        c["quote_size_shares"], int(c["quote_size_shares"] * 1.3)
    )
    # Small random jitter
    c["min_take_profit"] = round(rng.choice([0.018, 0.02, 0.022, 0.025]), 3)
    return c


def _run_one_generation(gen: int, cfg: dict) -> dict | None:
    """Patch real_sim to use our cfg as seed-0 by writing margin_best override file."""
    # Write as the hito file real_sim reads first via our dedicated seed file
    seed_path = CFG_DIR / "maker_demo_100_usd_auto_seed.json"
    seed_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    # Also refresh margin_best so real_sim _hito_cfg picks latest if we point it there
    # Prefer injecting via env-less patch: overwrite a known path real_sim uses
    # We'll pass by temporarily replacing margin_best backup-safe
    hito = CFG_DIR / "maker_demo_100_usd_margin_best.json"
    backup = CFG_DIR / "maker_demo_100_usd_margin_best.json.bak_auto"
    if hito.is_file() and not backup.is_file():
        backup.write_text(hito.read_text(encoding="utf-8"), encoding="utf-8")
    hito.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    sim_log = OUT / f"real_sim_gen{gen:02d}.log"
    err = OUT / f"real_sim_gen{gen:02d}.log.err"
    _log(f"GEN {gen}: starting real_sim_confirm_loop -> {sim_log.name}")
    import os

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["REAL_SIM_MAX_TRIALS"] = "4"
    env["REAL_SIM_SESSIONS"] = "6"
    env["REAL_SIM_MINUTES"] = "4"
    env["REAL_SIM_AVG_TARGET"] = str(AVG_TARGET)
    with sim_log.open("w", encoding="utf-8") as out_fh, err.open("w", encoding="utf-8") as err_fh:
        proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "polymarket.research.local_lab.real_sim_confirm_loop"],
            cwd=str(REPO),
            stdout=out_fh,
            stderr=err_fh,
            env=env,
        )
        proc.wait()
    # Parse best
    best_path = OUT / "real_sim_best.json"
    hist_path = OUT / "real_sim_history.json"
    last = None
    if best_path.is_file():
        best = json.loads(best_path.read_text(encoding="utf-8"))
        last = best
    if hist_path.is_file():
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
        if hist:
            last = hist[-1]
    hit = False
    if sim_log.is_file() and "REAL-SIM TARGET HIT" in sim_log.read_text(encoding="utf-8", errors="ignore"):
        hit = True
    if last:
        _log(
            f"GEN {gen}: WR={last.get('win_rate', 0):.1%} avg={last.get('avg_net_usdc', 0):+.2f} "
            f"losses={last.get('losses')} traded={last.get('sessions_with_fills')} hit={hit} "
            f"exit={proc.returncode}"
        )
    else:
        _log(f"GEN {gen}: no summary (exit={proc.returncode})")
    return {"hit": hit, "last": last, "exit": proc.returncode, "log": str(sim_log)}


def _cmdline_running(pattern: str) -> bool:
    ps = (
        f"$n=@(Get-CimInstance Win32_Process | Where-Object {{ $_.CommandLine -match '{pattern}' }}).Count; "
        f"Write-Output $n"
    )
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return int(out.strip() or "0") > 0
    except Exception:
        return False


def _ensure_recorders() -> None:
    import os

    if _cmdline_running("daemon_btc_feed"):
        return
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["POLY_DATASET"] = "local_lab"
    env["POLY_MANIFEST_INTERVAL_S"] = "60"
    for mod in (
        "polymarket.research.collectors.daemon_btc_feed",
        "polymarket.research.collectors.daemon_clob_recorder",
    ):
        subprocess.Popen(
            [sys.executable, "-u", "-m", mod],
            cwd=str(REPO),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    _log("Restarted WS recorders (btc+clob)")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if STOP.exists() or os.getenv("POLY_DISABLE_AUTONOMOUS_OOS", "").strip() in {
        "1",
        "true",
        "yes",
    }:
        print(
            f"autonomous_oos_driver disabled ({STOP.name} or POLY_DISABLE_AUTONOMOUS_OOS)",
            flush=True,
        )
        return 0
    LOG.write_text("", encoding="utf-8")
    rng = random.Random(20260716)
    cfg = _base_cfg()
    last_summary = None

    _log("Autonomous OOS driver start")
    _ensure_recorders()

    inflight = _cmdline_running("real_sim_confirm_loop")

    if inflight:
        _log("In-flight real_sim detected — waiting for it to finish before adapting")
        while _cmdline_running("real_sim_confirm_loop"):
            if STOP.exists():
                _log("STOP_AUTONOMOUS_OOS — abort wait")
                return 0
            time.sleep(30)
        # Load result of in-flight run
        best_path = OUT / "real_sim_best.json"
        hist_path = OUT / "real_sim_history.json"
        if hist_path.is_file():
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
            if hist:
                last_summary = hist[-1]
        elif best_path.is_file():
            last_summary = json.loads(best_path.read_text(encoding="utf-8"))
        sim_log = OUT / "real_sim.log"
        if sim_log.is_file() and "REAL-SIM TARGET HIT" in sim_log.read_text(
            encoding="utf-8", errors="ignore"
        ):
            _log("*** TARGET ALREADY HIT by in-flight run ***")
            if last_summary:
                (CFG_DIR / "maker_demo_100_usd_real_sim_best.json").write_text(
                    json.dumps(last_summary.get("cfg", cfg), indent=2), encoding="utf-8"
                )
            return 0
        if last_summary:
            _log(
                f"In-flight finished: WR={last_summary.get('win_rate', 0):.1%} "
                f"avg={last_summary.get('avg_net_usdc', 0):+.2f} — adapting"
            )
            cfg = _adapt(cfg, last_summary, 0, rng)

    for gen in range(1, MAX_GENERATIONS + 1):
        _ensure_recorders()
        cfg = _adapt(cfg, last_summary, gen, rng)
        (OUT / f"auto_cfg_gen{gen:02d}.json").write_text(
            json.dumps(cfg, indent=2), encoding="utf-8"
        )
        result = _run_one_generation(gen, cfg)
        last_summary = (result or {}).get("last")
        if result and result.get("hit"):
            _log("*** AUTONOMOUS TARGET HIT — WR>=75% avg>=$20 ***")
            if last_summary and last_summary.get("cfg"):
                (CFG_DIR / "maker_demo_100_usd_real_sim_best.json").write_text(
                    json.dumps(last_summary["cfg"], indent=2), encoding="utf-8"
                )
            (OUT / "autonomous_oos_success.json").write_text(
                json.dumps(
                    {
                        "generation": gen,
                        "result": last_summary,
                        "ts": datetime.now(timezone.utc).isoformat(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return 0
        # Also accept if metrics meet even without string hit (losses<=2)
        if last_summary:
            wr = float(last_summary.get("win_rate") or 0)
            avg = float(last_summary.get("avg_net_usdc") or 0)
            traded = int(last_summary.get("sessions_with_fills") or 0)
            losses = int(last_summary.get("losses") or 99)
            if wr >= WR_TARGET and avg >= AVG_TARGET and traded >= 5 and losses <= 2:
                _log("*** AUTONOMOUS TARGET HIT (metrics) ***")
                (CFG_DIR / "maker_demo_100_usd_real_sim_best.json").write_text(
                    json.dumps(last_summary.get("cfg", cfg), indent=2), encoding="utf-8"
                )
                return 0
        _log(f"GEN {gen} missed — next adaptation")

    _log(f"Gave up after {MAX_GENERATIONS} generations")
    if last_summary:
        (OUT / "autonomous_oos_best_effort.json").write_text(
            json.dumps(last_summary, indent=2), encoding="utf-8"
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
