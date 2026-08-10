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

# Ops improvement (NOT DNA relaxation): if a near-miss basket is within this
# gap over 0.50, recheck books once after a short wait in the same round.
NEAR_MISS_RECHECK_GAP = 0.08
NEAR_MISS_RECHECK_SLEEP_S = 30.0
# Second pass when still very close (≤5¢): denser capture without relaxing DNA.
NEAR_MISS_RECHECK2_GAP = 0.05
NEAR_MISS_RECHECK2_SLEEP_S = 90.0
# Adaptive sleep: far books → slower poll; close books → denser (still DNA-safe).
GAP_FAR = 0.15
GAP_WATCH = 0.12  # denser watch when best book within 12¢ of DNA
INTERVAL_FAR_MULT = 1.5
INTERVAL_CLOSE_S = 60.0
INTERVAL_WATCH_S = 75.0
INTERVAL_GATES2_S = 45.0  # denser when any market has 2/3 DNA gates
HEARTBEAT_EVERY = 10


def _min_basket_gap(stack: dict[str, Any]) -> float | None:
    """Best (lowest) gap over DNA 0.50 across near_miss + skipped + accepted."""
    market = stack.get("market_now") or {}
    rows = []
    for key in ("near_miss", "skipped", "accepted"):
        rows.extend(market.get(key) or [])
    gaps: list[float] = []
    for nm in rows:
        b = nm.get("basket_cost")
        if isinstance(b, (int, float)) and float(b) > 0:
            gaps.append(max(0.0, float(b) - 0.50))
    return min(gaps) if gaps else None


def _best_gates_passed(stack: dict[str, Any]) -> int:
    try:
        from polymarket.research.local_lab.research_telemetry import gate_scoreboard
    except Exception:
        return 0
    market = stack.get("market_now") or {}
    best = 0
    for key in ("accepted", "near_miss", "skipped"):
        for block in market.get(key) or []:
            sb = gate_scoreboard(block)
            best = max(best, int(sb.get("gates_passed") or 0))
    return best


def _adaptive_interval(base_s: float, gap: float | None, *, gates_passed: int = 0) -> float:
    base = max(5.0, float(base_s))
    if gates_passed >= 2 and gap is not None and gap <= NEAR_MISS_RECHECK_GAP + 1e-12:
        return min(base, INTERVAL_GATES2_S)
    if gap is None:
        return base * INTERVAL_FAR_MULT
    if gap <= NEAR_MISS_RECHECK_GAP + 1e-12:
        return min(base, INTERVAL_CLOSE_S)
    if gap <= GAP_WATCH + 1e-12:
        return min(base, INTERVAL_WATCH_S)
    if gap >= GAP_FAR - 1e-12:
        return base * INTERVAL_FAR_MULT
    return base


def _watch_blockers(stack: dict[str, Any], *, watch_only: bool) -> list[str]:
    """Slim blockers for telemetry — avoid contradictory arm-gate noise in watch-only."""
    raw = list(stack.get("blockers") or [])
    if not watch_only:
        return raw
    drop = {
        "champion_take_available",
        "missing_POLY_LADDER_REAL_CONFIRM=1",
        "confirm_env_POLY_LADDER_REAL_CONFIRM",
    }
    out = [b for b in raw if b not in drop]
    if int((stack.get("market_now") or {}).get("accepted_n") or 0) == 0:
        if "no_champion_take_right_now" not in out:
            out.append("no_champion_take_right_now")
    out.append("watch_only_no_post")
    return out


def _row_from_stack(
    *,
    stack: dict[str, Any],
    round_id: int,
    mode: str,
    recheck: bool = False,
    recheck_pass: int | None = None,
    watch_only: bool = False,
    interval_next_s: float | None = None,
) -> dict[str, Any]:
    gap = _min_basket_gap(stack)
    gates_n = _best_gates_passed(stack)
    row: dict[str, Any] = {
        "round": round_id,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "balance_pusd": (stack.get("wallet") or {}).get("balance_pusd"),
        "geoblock_ok": (stack.get("checks") or {}).get("geoblock_ok"),
        "accepted_n": (stack.get("market_now") or {}).get("accepted_n"),
        "near_miss_n": len((stack.get("market_now") or {}).get("near_miss") or []),
        "ready_to_arm": stack.get("ready_to_arm"),
        "can_execute_now": stack.get("can_execute_now"),
        "blockers": _watch_blockers(stack, watch_only=watch_only),
        "accepted_slugs": [c["slug"] for c in (stack.get("market_now") or {}).get("accepted") or []],
        "mode": mode,
        "min_gap_basket": round(gap, 4) if gap is not None else None,
        "best_gates_passed": gates_n,
    }
    if interval_next_s is not None:
        row["interval_next_s"] = round(float(interval_next_s), 1)
    if recheck:
        row["recheck"] = True
        row["recheck_pass"] = int(recheck_pass or 1)
    return row


def _do_recheck(
    *,
    cfg: dict[str, Any],
    interval_s: float,
    round_id: int,
    mode: str,
    history: list[dict[str, Any]],
    pass_n: int,
    sleep_s: float,
    gap: float,
    threshold: float,
) -> tuple[dict[str, Any], float | None, float, int]:
    print(
        f"=== NEAR_MISS RECHECK#{pass_n} gap_basket={gap:.4f}≤{threshold} "
        f"sleep {sleep_s:.0f}s (DNA unchanged) ===",
        flush=True,
    )
    time.sleep(sleep_s)
    stack = evaluate_real_stack(cfg)
    gap2 = _min_basket_gap(stack)
    gates_n = _best_gates_passed(stack)
    next_iv = _adaptive_interval(interval_s, gap2, gates_passed=gates_n)
    row = _row_from_stack(
        stack=stack,
        round_id=round_id,
        mode=mode,
        recheck=True,
        recheck_pass=pass_n,
        watch_only=True,
        interval_next_s=next_iv,
    )
    history.append(row)
    print(json.dumps(row, indent=2), flush=True)
    try:
        from polymarket.research.local_lab.research_telemetry import log_watch_round

        log_watch_round(row, stack)
    except Exception as exc:
        print(f"telemetry_fail {type(exc).__name__}: {exc}", flush=True)
    accepted_n = int((stack.get("market_now") or {}).get("accepted_n") or 0)
    return stack, gap2, next_iv, accepted_n


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
    mode = "watch_only" if watch_only else ("auto_execute" if auto_execute else "manual_stop")

    if watch_only and auto_execute:
        raise RuntimeError("Refusing watch_only + auto_execute together")

    for i in range(rounds):
        t0 = time.monotonic()
        stack = evaluate_real_stack(cfg)
        gap = _min_basket_gap(stack)
        gates_n = _best_gates_passed(stack)
        next_iv = (
            _adaptive_interval(interval_s, gap, gates_passed=gates_n)
            if watch_only
            else max(5.0, float(interval_s))
        )
        row = _row_from_stack(
            stack=stack,
            round_id=i + 1,
            mode=mode,
            watch_only=watch_only,
            interval_next_s=next_iv,
        )
        history.append(row)
        print(json.dumps(row, indent=2), flush=True)

        # Forward telemetry (WATCH_ONLY research) — never posts
        try:
            from polymarket.research.local_lab.research_telemetry import log_watch_round

            log_watch_round(row, stack)
        except Exception as exc:
            print(f"telemetry_fail {type(exc).__name__}: {exc}", flush=True)

        accepted_n = int((stack.get("market_now") or {}).get("accepted_n") or 0)
        # Close near-miss recheck (ops only; DNA unchanged)
        if (
            watch_only
            and accepted_n == 0
            and gap is not None
            and gap <= NEAR_MISS_RECHECK_GAP + 1e-12
        ):
            stack, gap, next_iv, accepted_n = _do_recheck(
                cfg=cfg,
                interval_s=interval_s,
                round_id=i + 1,
                mode=mode,
                history=history,
                pass_n=1,
                sleep_s=NEAR_MISS_RECHECK_SLEEP_S,
                gap=gap,
                threshold=NEAR_MISS_RECHECK_GAP,
            )
            # Second denser pass when still ≤5¢
            if accepted_n == 0 and gap is not None:
                do_second = gap <= NEAR_MISS_RECHECK2_GAP + 1e-12
                # Also densify when any book already has 2/3 DNA gates and gap≤8¢
                if (not do_second) and gap <= NEAR_MISS_RECHECK_GAP + 1e-12:
                    if _best_gates_passed(stack) >= 2:
                        do_second = True
                if do_second:
                    stack, gap, next_iv, accepted_n = _do_recheck(
                        cfg=cfg,
                        interval_s=interval_s,
                        round_id=i + 1,
                        mode=mode,
                        history=history,
                        pass_n=2,
                        sleep_s=NEAR_MISS_RECHECK2_SLEEP_S,
                        gap=gap,
                        threshold=(
                            NEAR_MISS_RECHECK2_GAP
                            if gap <= NEAR_MISS_RECHECK2_GAP + 1e-12
                            else NEAR_MISS_RECHECK_GAP
                        ),
                    )

        if watch_only and (i + 1) % HEARTBEAT_EVERY == 0:
            print(
                f"HEARTBEAT round={i+1} edges_seen={edges_seen} "
                f"gap={gap} gates={_best_gates_passed(stack)} next_iv={next_iv:.0f}s "
                f"bal={row.get('balance_pusd')}",
                flush=True,
            )

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
            elapsed = time.monotonic() - t0
            remaining = max(5.0, float(next_iv) - elapsed)
            time.sleep(remaining)

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
