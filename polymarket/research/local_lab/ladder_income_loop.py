#!/usr/bin/env python3
"""
Income loop for Temperature Ladder micro-real.

Polls open books; when a champion take appears AND real gates pass,
optionally executes (--auto-execute requires confirm env + accept flag).

This is the operational path to real income:
  POLY_LADDER_REAL_CONFIRM=1 \\
    python3 -m polymarket.research.local_lab.ladder_income_loop \\
      --auto-execute --i-accept-real-loss YES --rounds 40 --interval 180

Must run from a Polymarket-allowed region (not US-geoblocked).
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.weather_ladder_paper import load_cfg
from polymarket.research.local_lab.weather_ladder_real import evaluate_real_stack, execute_real
from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
DEFAULT_CFG = POLY / "config" / "weather_ladder_definitive_real.json"  # definitive press-only DNA
OUT = POLY / "data_local" / "local_lab" / "ladder_income"


def run_loop(
    *,
    config_path: Path,
    rounds: int,
    interval_s: float,
    auto_execute: bool,
    accept_loss: str,
    watch_only: bool = False,
) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    cfg = load_cfg(config_path)
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT / f"loop_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    history: list[dict[str, Any]] = []
    hit: dict[str, Any] | None = None
    edges_seen = 0

    if watch_only and auto_execute:
        raise RuntimeError("Refusing watch_only + auto_execute together")

    for i in range(rounds):
        stack = evaluate_real_stack(cfg)
        row = {
            "round": i + 1,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "balance_pusd": (stack.get("wallet") or {}).get("balance_pusd"),
            "geoblock_ok": (stack.get("checks") or {}).get("geoblock_ok"),
            "accepted_n": (stack.get("market_now") or {}).get("accepted_n"),
            "near_miss_n": len((stack.get("market_now") or {}).get("near_miss") or []),
            "ready_to_arm": stack.get("ready_to_arm"),
            "can_execute_now": stack.get("can_execute_now"),
            "blockers": stack.get("blockers"),
            "accepted_slugs": [c["slug"] for c in (stack.get("market_now") or {}).get("accepted") or []],
            "mode": "watch_only" if watch_only else ("auto_execute" if auto_execute else "manual_stop"),
        }
        history.append(row)
        print(json.dumps(row, indent=2), flush=True)

        # Forward telemetry (WATCH_ONLY research) — never posts
        try:
            from polymarket.research.local_lab.research_telemetry import log_watch_round

            log_watch_round(row, stack)
        except Exception as exc:
            print(f"telemetry_fail {type(exc).__name__}: {exc}", flush=True)

        accepted_n = int((stack.get("market_now") or {}).get("accepted_n") or 0)
        if accepted_n >= 1:
            edges_seen += 1
            if auto_execute and stack.get("ready_to_arm"):
                print("=== EDGE + GATES OK → EXECUTE REAL ===", flush=True)
                result = execute_real(cfg, accept_loss=accept_loss, session_id=f"{sid}_r{i+1}")
                hit = {"round": i + 1, "stack": stack, "result": result}
                break
            if watch_only:
                print(
                    "=== EDGE DNA (WATCH_ONLY) — no post; continue scanning ===",
                    flush=True,
                )
                hit = {
                    "round": i + 1,
                    "stack": stack,
                    "result": {"executed": False, "reason": "watch_only"},
                }
                # keep looping — do not break
            else:
                hit = {
                    "round": i + 1,
                    "stack": stack,
                    "result": {"executed": False, "reason": "auto_execute_off"},
                }
                print("Edge ready but --auto-execute not set; stopping for manual execute.", flush=True)
                break

        # Hard stop if geoblock — cannot earn from this egress
        if i == 0 and not (stack.get("checks") or {}).get("geoblock_ok"):
            print(
                "GEOBLOCK: este egress no puede postear órdenes reales. "
                "Corre el income loop desde una región permitida por Polymarket.",
                flush=True,
            )
            if auto_execute:
                print("Auto-execute deshabilitado de facto por geoblock.", flush=True)

        if i + 1 < rounds:
            time.sleep(max(5.0, float(interval_s)))

    if hit and (hit.get("result") or {}).get("executed"):
        verdict = "INCOME_POSTED"
    elif watch_only and edges_seen:
        verdict = "WATCH_EDGE_SEEN"
    elif hit and not auto_execute and not watch_only:
        verdict = "EDGE_READY_MANUAL"
    elif history and not history[0].get("geoblock_ok"):
        verdict = "BLOCKED_GEOBLOCK"
    else:
        verdict = "NO_EDGE_YET"

    report = {
        "loop_id": sid,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "auto_execute": auto_execute,
        "watch_only": watch_only,
        "rounds_run": len(history),
        "edges_seen": edges_seen,
        "history": history,
        "hit": hit,
        "verdict": verdict,
        "income_recipe": {
            "strategy": "temperature_ladder_definitive",
            "session_cap_usdc": 5.0,
            "deposit_target_usdc": 25.0,
            "run_from": "Polymarket-allowed region (not US geoblock)",
            "watch_command": (
                "python3 -m polymarket.research.local_lab.definitive_income_system "
                "--scale micro --income-loop --watch-only --rounds 240 --interval 90"
            ),
            "rearm_command": (
                "POLY_LADDER_REAL_CONFIRM=1 python3 -m polymarket.research.local_lab.definitive_income_system "
                "--income-loop --auto-execute --i-accept-real-loss YES --rounds 40 --interval 180"
            ),
            "rearm_gate": "python3 -m polymarket.research.local_lab.rearm_income_gate",
        },
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"verdict={report['verdict']} -> {out_dir}", flush=True)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(DEFAULT_CFG))
    p.add_argument("--rounds", type=int, default=20)
    p.add_argument("--interval", type=float, default=180.0)
    p.add_argument("--auto-execute", action="store_true")
    p.add_argument("--watch-only", action="store_true", help="Scan forever-ish; alert edge; never post")
    p.add_argument("--i-accept-real-loss", default="")
    args = p.parse_args()
    cfg = Path(args.config)
    if not cfg.is_file():
        cfg = POLY / args.config
    if args.watch_only and args.auto_execute:
        raise SystemExit("Refusing --watch-only together with --auto-execute")
    if args.auto_execute and args.i_accept_real_loss.strip().upper() != "YES":
        raise SystemExit("Refusing --auto-execute without --i-accept-real-loss YES")
    if args.auto_execute and (os.getenv("POLY_LADDER_REAL_CONFIRM") or "").strip() != "1":
        raise SystemExit("Refusing --auto-execute without POLY_LADDER_REAL_CONFIRM=1")
    rep = run_loop(
        config_path=cfg,
        rounds=args.rounds,
        interval_s=args.interval,
        auto_execute=args.auto_execute,
        accept_loss=args.i_accept_real_loss,
        watch_only=bool(args.watch_only),
    )
    ok = (
        "INCOME_POSTED",
        "EDGE_READY_MANUAL",
        "WATCH_EDGE_SEEN",
        "NO_EDGE_YET",
        "BLOCKED_GEOBLOCK",
    )
    return 0 if rep["verdict"] in ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
