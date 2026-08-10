#!/usr/bin/env python3
"""
Verify operator deposit runway (fund wallet) vs auto-execute rearm.

Deposit runway ≠ permission to trade automatically.
  - DEPOSIT_RUNWAY_GO: capital@$100+ survives misses + mechanism + DNA LT + watch-only
  - AUTO_EXECUTE still needs n≥50 / Wilson≥0.80 (READY_TO_REARM)

Never posts. Never sets ALLOW_REARM.

  python3 -m polymarket.research.local_lab.verify_deposit_runway
  python3 -m polymarket.research.local_lab.verify_deposit_runway --deposit 100 --write-docs
  python3 -m polymarket.research.local_lab.verify_deposit_runway --deposit 200 --write-docs
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.ladder_viability_report import (
    MIN_N_FOR_GO_MICRO,
    MIN_WILSON95_FOR_GO,
    capital_adequacy,
)
from polymarket.research.local_lab.long_term_robustness import evaluate_profile, make_profiles
from polymarket.research.local_lab.real_env_ready import check_code_safety
from polymarket.research.local_lab.rearm_income_gate import evidence_block, run_income_mechanism_tests
from polymarket.research.local_lab.simulate_real_income import STRESS, simulate
from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "deposit_runway"
DOCS = POLY / "docs"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"
CORE = ("singapore", "shanghai", "hong-kong", "beijing")

# Scale presets for post-deposit ops (still watch-only until READY_TO_REARM)
PRESETS = {
    100.0: {"name": "high", "session_cap": 50.0, "budget": 25.0, "first_budget": 12.0, "first_cap": 25.0},
    200.0: {"name": "aggressive", "session_cap": 100.0, "budget": 50.0, "first_budget": 25.0, "first_cap": 50.0},
    500.0: {"name": "pro", "session_cap": 150.0, "budget": 75.0, "first_budget": 50.0, "first_cap": 75.0},
}


def _bankroll_at(takes: list[dict[str, Any]], start: float) -> dict[str, Any]:
    from polymarket.research.local_lab import simulate_real_income as sri

    fracs = {25.0: 0.32, 50.0: 0.18, 100.0: 0.12, 200.0: 0.10, 500.0: 0.08, 1000.0: 0.06}
    old = dict(sri.BUDGET_FRACS)
    out = {}
    try:
        sri.BUDGET_FRACS = {**old, **fracs}
        if start not in sri.BUDGET_FRACS:
            # nearest
            sri.BUDGET_FRACS[start] = 0.10
        for sc in STRESS:
            if sc["name"] not in ("base", "hostile"):
                continue
            r = simulate(takes, start=float(start), scenario=sc)
            out[sc["name"]] = {
                "n": r["n"],
                "wr": r["winrate"],
                "pnl": r["total_pnl"],
                "end": r["ending_equity"],
                "mult": r["return_mult"],
                "dd": r["max_drawdown_frac"],
                "income_positive": r["income_positive"],
            }
    finally:
        sri.BUDGET_FRACS = old
    return out


def run(*, deposit: float = 100.0, write_docs: bool = False, run_income_tests: bool = True) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    deposit = float(deposit)
    preset = PRESETS.get(deposit) or {
        "name": "custom",
        "session_cap": max(25.0, deposit * 0.5),
        "budget": max(12.0, deposit * 0.25),
        "first_budget": max(8.0, deposit * 0.12),
        "first_cap": max(15.0, deposit * 0.25),
    }

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    takes = take_income_wr80(cases)
    ev = evidence_block(takes)
    eng = check_code_safety()

    # Long-term DNA
    prof, post_b = make_profiles()["income_wr80"]
    uni = [c for c in cases if c["city"] in CORE]
    lt = evaluate_profile("income_wr80", prof, uni, post_max_basket=post_b)

    # Capital at CURRENT balance (~3.45) vs PLANNED deposit
    current_bal = 3.4482
    try:
        # best-effort live balance from latest go-live if present
        gl = sorted((POLY / "data_local" / "local_lab" / "ladder_go_live").glob("check_*.json"))
        if gl:
            bal = (json.loads(gl[-1].read_text()).get("balance") or {}).get("usdc")
            if bal is not None:
                current_bal = float(bal)
    except Exception:
        pass

    cap_now = capital_adequacy(
        takes, balance=current_bal, session_cap=5.0, budget_cfg=3.0
    )
    cap_now["balance"] = current_bal
    cap_plan = capital_adequacy(
        takes,
        balance=deposit,
        session_cap=float(preset["session_cap"]),
        budget_cfg=float(preset["budget"]),
    )
    cap_plan["balance"] = deposit
    cap_plan["preset"] = preset

    if run_income_tests:
        income = run_income_mechanism_tests()
    else:
        latest = POLY / "data_local" / "local_lab" / "real_income_sim" / "latest.json"
        if latest.exists():
            g = json.loads(latest.read_text()).get("gate") or {}
            income = {
                "ran": True,
                "passed": bool(g.get("passed")),
                "verdict": g.get("verdict"),
                "caveat": g.get("caveat"),
            }
        else:
            income = {"ran": False, "passed": False, "verdict": None}

    bank = _bankroll_at(takes, deposit)

    checks = {
        "engineering_ok": bool(eng.get("passed")),
        "income_mechanism_ok": bool(income.get("passed")),
        "long_term_robust": bool(lt["gate"].get("passed")),
        "planned_capital_survives_1_miss": bool(cap_plan.get("still_armed_after_1_miss")),
        "planned_capital_executable": bool(cap_plan.get("executable")),
        "bankroll_base_positive": bool((bank.get("base") or {}).get("income_positive")),
        "bankroll_hostile_positive": bool((bank.get("hostile") or {}).get("income_positive")),
        "current_capital_blocks": not bool(cap_now.get("still_armed_after_1_miss")),
        "evidence_n_ge_50": bool(ev["checks"]["n_ge_50"]),
        "evidence_wilson_ge_80": bool(ev["checks"]["wilson_ge_80"]),
    }

    runway_ok = all(
        [
            checks["engineering_ok"],
            checks["income_mechanism_ok"],
            checks["long_term_robust"],
            checks["planned_capital_survives_1_miss"],
            checks["planned_capital_executable"],
            checks["bankroll_base_positive"],
            checks["bankroll_hostile_positive"],
        ]
    )
    auto_ok = runway_ok and checks["evidence_n_ge_50"] and checks["evidence_wilson_ge_80"]

    if auto_ok:
        status = "READY_TO_REARM"
        action = (
            f"Depósito ${deposit:g} + evidencia OK. Se puede rearmar con confirms "
            "(POLY_LADDER_REAL_CONFIRM + ALLOW_REARM + accept-loss)."
        )
    elif runway_ok:
        status = "DEPOSIT_RUNWAY_GO"
        action = (
            f"PUEDES depositar ${deposit:g} AHORA para runway (watch-only). "
            f"NO armar auto-execute: evidencia n={ev['n']} Wilson={ev['wilson95_lower']} "
            f"(falta n≥{MIN_N_FOR_GO_MICRO}, Wilson≥{MIN_WILSON95_FOR_GO}). "
            f"Tras depositar, primera sesión solo cuando READY_TO_REARM: "
            f"budget ${preset['first_budget']:g} / cap ${preset['first_cap']:g}."
        )
    else:
        status = "NOT_READY"
        fails = [k for k, v in checks.items() if not v and k not in (
            "current_capital_blocks", "evidence_n_ge_50", "evidence_wilson_ge_80"
        )]
        action = f"Corrigir antes de depositar: {fails}"

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "action_es": action,
        "deposit_target_usdc": deposit,
        "preset": preset,
        "checks": checks,
        "evidence": ev,
        "engineering_passed": eng.get("passed"),
        "income_mechanism": {
            "passed": income.get("passed"),
            "verdict": income.get("verdict"),
            "caveat": income.get("caveat"),
        },
        "long_term": {
            "verdict": lt["gate"]["verdict"],
            "passed": lt["gate"]["passed"],
            "overall": lt["overall"],
        },
        "capital_current": cap_now,
        "capital_planned": cap_plan,
        "bankroll_planned": bank,
        "can_deposit_runway_watch_only": runway_ok,
        "can_enable_auto_execute": auto_ok,
        "can_recommend_deposit": runway_ok,  # runway deposit yes; trade later
        "disclaimer_es": (
            "Depositar runway ≠ auto-execute. DNA intacta. "
            "Tras depositar sigue WATCH_ONLY hasta READY_TO_REARM."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (OUT / f"deposit_runway_{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "DEPOSIT_RUNWAY.md").write_text(md, encoding="utf-8")
    (VPS / "MONEY_READY_STATUS.md").write_text(md, encoding="utf-8")
    if write_docs:
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "DEPOSIT_RUNWAY.md").write_text(md, encoding="utf-8")
        (DOCS / "MONEY_READY_STATUS.md").write_text(md, encoding="utf-8")
        # short prepare pointer
        (DOCS / "PREPARE_REAL_MONEY.md").write_text(
            "\n".join(
                [
                    "# Prepare Real Money Battery",
                    "",
                    f"**UTC:** `{report['ts_utc']}`",
                    f"**Depósito runway:** `{status}`",
                    f"**Auto-execute:** `{'GO' if auto_ok else 'BLOCKED_EVIDENCE'}`",
                    "",
                    action,
                    "",
                    f"- can_deposit_runway_watch_only=`{runway_ok}`",
                    f"- can_enable_auto_execute=`{auto_ok}`",
                    f"- target=`${deposit:g}` ({preset['name']})",
                    "",
                    "Detalle: [`DEPOSIT_RUNWAY.md`](DEPOSIT_RUNWAY.md)",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return report


def render_md(report: dict[str, Any]) -> str:
    c = report["checks"]
    lines = [
        "# Deposit runway — verificación",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Status:** `{report['status']}`",
        f"**Target:** `${report['deposit_target_usdc']:g}` ({report['preset']['name']})",
        "",
        report["action_es"],
        "",
        "## Flags",
        f"- can_deposit_runway_watch_only=`{report['can_deposit_runway_watch_only']}`",
        f"- can_enable_auto_execute=`{report['can_enable_auto_execute']}`",
        f"- can_recommend_deposit (runway)=`{report['can_recommend_deposit']}`",
        "",
        "## Checks",
    ]
    for k, v in c.items():
        lines.append(f"- `{k}`={v}")
    cp = report["capital_planned"]
    lines += [
        "",
        "## Capital planificado",
        f"- balance=${cp.get('balance')} notional≈{cp.get('notional_first')} "
        f"after_1_miss={cp.get('equity_after_1_miss')} "
        f"still_armed={cp.get('still_armed_after_1_miss')} "
        f"misses_until_ruin={cp.get('misses_until_ruin')}",
        "",
        "## Evidencia (auto-execute)",
        f"- n={report['evidence']['n']} Wilson={report['evidence']['wilson95_lower']} "
        f"rearm_ok={report['evidence']['passed_for_rearm']}",
        "",
        "## Bankroll sim @ depósito",
        f"- base: {report['bankroll_planned'].get('base')}",
        f"- hostile: {report['bankroll_planned'].get('hostile')}",
        "",
        report["disclaimer_es"],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deposit", type=float, default=100.0)
    ap.add_argument("--write-docs", action="store_true")
    ap.add_argument("--skip-income-tests", action="store_true")
    args = ap.parse_args()
    rep = run(
        deposit=float(args.deposit),
        write_docs=bool(args.write_docs),
        run_income_tests=not bool(args.skip_income_tests),
    )
    print(
        json.dumps(
            {
                "status": rep["status"],
                "action_es": rep["action_es"],
                "can_deposit_runway_watch_only": rep["can_deposit_runway_watch_only"],
                "can_enable_auto_execute": rep["can_enable_auto_execute"],
                "checks": rep["checks"],
                "capital_planned": {
                    k: rep["capital_planned"].get(k)
                    for k in (
                        "balance",
                        "notional_first",
                        "equity_after_1_miss",
                        "still_armed_after_1_miss",
                        "misses_until_ruin",
                    )
                },
                "evidence": {
                    "n": rep["evidence"]["n"],
                    "wilson": rep["evidence"]["wilson95_lower"],
                },
                "bankroll": rep["bankroll_planned"],
            },
            indent=2,
        )
    )
    return 0 if rep["can_deposit_runway_watch_only"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
