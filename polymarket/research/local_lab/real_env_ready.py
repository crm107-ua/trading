#!/usr/bin/env python3
"""
Real-environment readiness gate for Temperature Ladder income.

Separates:
  REAL_ENV_SYSTEM_READY   — code/DNA/safety path is production-grade
  REAL_ENV_OPERATOR_READY — system ready + signing + (optionally) funded
  REAL_ENV_GO             — can post now (region + balance + edge + confirms)

Never posts orders.

  python3 -m polymarket.research.local_lab.real_env_ready
  python3 -m polymarket.research.local_lab.real_env_ready --scale high
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.definitive_income_system import (
    SCALE_CONFIGS,
    check_dna_alignment,
    check_research_artifacts,
)
from polymarket.research.local_lab.weather_ladder_paper import load_cfg
from polymarket.research.local_lab.weather_ladder_real import (
    MAX_SESSION_CAP_HIGH,
    MAX_SESSION_CAP_MICRO,
    _session_cap,
    evaluate_real_stack,
)
from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.execution.clob_live import read_gates
from polymarket.src.execution.live_policy import check_geoblock, day_loss_breached, geoblock_blocks_real

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "real_env_ready"


def check_code_safety() -> dict[str, Any]:
    """Static/system checks that must pass before any real money."""
    checks: dict[str, bool] = {}
    notes: list[str] = []

    real_py = (POLY / "research" / "local_lab" / "weather_ladder_real.py").read_text(encoding="utf-8")
    checks["execute_requires_confirm_env"] = "POLY_LADDER_REAL_CONFIRM" in real_py
    checks["execute_requires_accept_loss"] = "i-accept-real-loss" in real_py or "accept_loss" in real_py
    checks["execute_restores_safe"] = "_restore_prev" in real_py and "_restore_safe" in real_py
    checks["execute_revalidates_dna"] = (
        "basket_above_dna_at_post" in real_py or "SKIP_BASKET_DNA" in real_py
    )
    checks["execute_revalidates_ud"] = (
        "not_underdispersed_at_post" in real_py or "SKIP_NOT_UD" in real_py
    )
    checks["execute_geoblock_at_post"] = "geoblock_at_execute" in real_py
    checks["execute_abort_partial"] = "abort_partial" in real_py
    checks["high_income_cap_helper"] = "POLY_LADDER_HIGH_INCOME" in real_py

    for name, path in SCALE_CONFIGS.items():
        if name == "aggressive":
            continue
        ok = path.is_file()
        checks[f"config_{name}_exists"] = ok
        if not ok:
            notes.append(f"missing {path}")

    dna = check_dna_alignment()
    checks["dna_aligned"] = bool(dna.get("passed"))
    if not dna.get("passed"):
        notes.append("dna_failed:" + ",".join(k for k, v in (dna.get("checks") or {}).items() if not v))

    research = check_research_artifacts(recertify=False)
    checks["research_certified"] = bool(research.get("passed"))

    # Safety defaults in process after dotenv
    load_repo_dotenv(override=True)
    g = read_gates()
    checks["env_default_not_armed"] = not g.armed
    checks["env_default_dry_run"] = bool(g.dry_run)
    checks["signing_keys_present"] = bool(g.signing_ready)
    checks["funder_present"] = bool(g.funder)

    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "notes": notes,
        "gates_snapshot": {
            "armed": g.armed,
            "dry_run": g.dry_run,
            "signing_ready": g.signing_ready,
            "eoa": g.eoa,
            "funder": g.funder,
        },
        "research_verdicts": research.get("verdicts"),
    }


def check_operator(cfg: dict[str, Any], *, scale: str) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    stack = evaluate_real_stack(cfg)
    bal = (stack.get("wallet") or {}).get("balance_pusd")
    deposit_target = float((cfg.get("live") or {}).get("deposit_target_usdc") or 25.0)
    min_arm = float((cfg.get("live") or {}).get("min_balance_to_arm_usdc") or 2.0)
    geo_blocked, geo_msg = geoblock_blocks_real()
    geo = check_geoblock()
    confirm = (os.getenv("POLY_LADDER_REAL_CONFIRM") or "").strip() == "1"
    high_env = (os.getenv("POLY_LADDER_HIGH_INCOME") or "").strip() == "1"
    high_needed = scale in ("high", "aggressive") or bool((cfg.get("live") or {}).get("high_income"))

    checks = {
        "geoblock_ok": not geo_blocked,
        "day_loss_ok": not day_loss_breached(),
        "balance_readable": bal is not None,
        "balance_gte_min_arm": (bal or 0) >= min_arm - 1e-9,
        "balance_gte_deposit_target": (bal or 0) >= deposit_target - 1e-9,
        "edge_open": int((stack.get("market_now") or {}).get("accepted_n") or 0) >= 1,
        "confirm_env_set": confirm,
        "high_income_env_ok": (not high_needed) or high_env,
        "session_cap_sane": _session_cap(cfg) <= (
            MAX_SESSION_CAP_HIGH if high_env else MAX_SESSION_CAP_MICRO
        )
        + 1e-9,
        "ready_to_arm_stack": bool(stack.get("ready_to_arm")),
    }

    blockers: list[str] = []
    if not checks["geoblock_ok"]:
        blockers.append(f"geoblock:{geo.country}/{geo.region}")
    if not checks["balance_gte_min_arm"]:
        blockers.append(f"deposit_min_{min_arm:g}_have_{bal}")
    elif not checks["balance_gte_deposit_target"]:
        blockers.append(f"deposit_target_{deposit_target:g}_have_{bal}")
    if not checks["edge_open"]:
        blockers.append("no_press_take_open")
    if not checks["confirm_env_set"]:
        blockers.append("set_POLY_LADDER_REAL_CONFIRM=1")
    if high_needed and not high_env:
        blockers.append("set_POLY_LADDER_HIGH_INCOME=1")
    if not checks["day_loss_ok"]:
        blockers.append("day_loss_breached")

    operator_funded = checks["balance_readable"] and checks["balance_gte_min_arm"] and checks["geoblock_ok"]
    can_go = bool(stack.get("can_execute_now")) and checks["high_income_env_ok"]

    return {
        "checks": checks,
        "blockers": blockers,
        "operator_funded_region_ok": operator_funded,
        "can_execute_now": can_go,
        "stack_summary": {
            "balance_pusd": bal,
            "deposit_target": deposit_target,
            "session_cap": (stack.get("session_limits") or {}).get("max_capital_usdc"),
            "effective_cap": (stack.get("session_limits") or {}).get("effective_cap_usdc"),
            "accepted_n": (stack.get("market_now") or {}).get("accepted_n"),
            "near_miss_n": len((stack.get("market_now") or {}).get("near_miss") or []),
            "income_mode": stack.get("income_mode"),
            "geoblock_message": geo_msg,
        },
        "commands": stack.get("commands"),
    }


def compose(system: dict[str, Any], operator: dict[str, Any]) -> dict[str, Any]:
    system_ready = bool(system.get("passed"))
    operator_ready = system_ready and bool(operator.get("operator_funded_region_ok"))
    go = system_ready and bool(operator.get("can_execute_now"))

    if go:
        verdict = "REAL_ENV_GO"
    elif operator_ready:
        verdict = "REAL_ENV_OPERATOR_READY"
    elif system_ready:
        verdict = "REAL_ENV_SYSTEM_READY"
    else:
        verdict = "REAL_ENV_NOT_READY"

    meanings = {
        "REAL_ENV_SYSTEM_READY": (
            "Código/DNA/safety listos para producción. Falta región permitida y/o depósito y/o edge."
        ),
        "REAL_ENV_OPERATOR_READY": (
            "Sistema + región + fondos mínimos OK. Espera edge press o pon confirm envs."
        ),
        "REAL_ENV_GO": "Listo para postear ingreso real ahora (con confirms ya puestos).",
        "REAL_ENV_NOT_READY": "Falla certificación o safety del sistema — no operar.",
    }
    return {
        "verdict": verdict,
        "meaning": meanings[verdict],
        "system_ready": system_ready,
        "operator_ready": operator_ready,
        "go": go,
    }


def run(*, scale: str = "high") -> dict[str, Any]:
    load_repo_dotenv(override=True)
    cfg_path = SCALE_CONFIGS.get(scale) or SCALE_CONFIGS["high"]
    cfg = load_cfg(cfg_path)
    if scale == "aggressive":
        cfg = dict(cfg)
        cfg["budget_per_market_usdc"] = 50.0
        live = dict(cfg.get("live") or {})
        live["max_capital_usdc"] = 100.0
        live["deposit_target_usdc"] = 200.0
        live["min_balance_to_arm_usdc"] = 50.0
        live["high_income"] = True
        cfg["live"] = live

    system = check_code_safety()
    operator = check_operator(cfg, scale=scale)
    composed = compose(system, operator)

    # Operator checklist for real machine
    checklist = [
        "1. Máquina en región Polymarket permitida (no US geoblock).",
        f"2. Depositar ≥{(cfg.get('live') or {}).get('deposit_target_usdc', 100)} USDC en funder.",
        "3. .env: POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1 por defecto.",
        "4. Private key + POLYMARKET_WALLET_ADDRESS (funder) configurados.",
        "5. Para high: export POLY_LADDER_HIGH_INCOME=1",
        "6. export POLY_LADDER_REAL_CONFIRM=1",
        "7. Preflight: python3 -m polymarket.research.local_lab.real_env_ready --scale "
        + scale,
        "8. Cuando verdict=REAL_ENV_GO o edge abierto:",
        "   POLY_LADDER_HIGH_INCOME=1 POLY_LADDER_REAL_CONFIRM=1 \\",
        "     python3 -m polymarket.research.local_lab.definitive_income_system \\",
        f"       --scale {scale} --income-loop --auto-execute --i-accept-real-loss YES",
    ]

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "scale": scale,
        "config": cfg_path.name,
        "system": system,
        "operator": {k: operator[k] for k in operator if k != "stack_summary"}
        | {"summary": operator.get("stack_summary")},
        **composed,
        "operator_checklist": checklist,
        "expectations_reminder": {
            "high_week_conservative_usd": 118,
            "high_week_clean_usd": 207,
            "today_often_zero_without_edge": True,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Real environment readiness")
    p.add_argument("--scale", choices=sorted(SCALE_CONFIGS.keys()), default="high")
    args = p.parse_args()
    rep = run(scale=args.scale)
    OUT.mkdir(parents=True, exist_ok=True)
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"ready_{sid}.json"
    path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "verdict": rep["verdict"],
                "meaning": rep["meaning"],
                "system_ready": rep["system_ready"],
                "operator_ready": rep["operator_ready"],
                "go": rep["go"],
                "system_checks_failed": [
                    k for k, v in (rep["system"]["checks"] or {}).items() if not v
                ],
                "operator_blockers": rep["operator"]["blockers"],
                "summary": rep["operator"]["summary"],
                "operator_checklist": rep["operator_checklist"],
                "expectations_reminder": rep["expectations_reminder"],
                "report": str(path),
            },
            indent=2,
        )
    )
    # Exit 0 if system ready (product is shippable); 2 if system broken
    return 0 if rep["system_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
