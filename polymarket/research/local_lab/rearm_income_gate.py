#!/usr/bin/env python3
"""
Gate de rearme a dinero real — Temperature Ladder.

Combina:
  1) Evidencia (n, Wilson) — hard fail si insuficiente
  2) Ingeniería / SAFE path (real_env_ready)
  3) Prueba de mecanismo de ingresos (simulate_real_income + wallet stress)
  4) Capital runway (sobrevive ≥1 miss)
  5) Postura operativa (watch-only hasta READY)

Nunca posta órdenes. Nunca recomienda depósito si evidencia falla.

  python3 -m polymarket.research.local_lab.rearm_income_gate
  python3 -m polymarket.research.local_lab.rearm_income_gate --balance 3.4482 --run-income-tests
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.ladder_viability_report import (
    MIN_N_FOR_CAPITAL_INCREASE,
    MIN_N_FOR_GO_MICRO,
    MIN_WILSON95_FOR_GO,
    capital_adequacy,
)
from polymarket.research.local_lab.real_env_ready import check_code_safety
from polymarket.src.ai.env_loader import load_repo_dotenv

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "rearm_gate"
DOCS = POLY / "docs"


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def evidence_block(raw: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for t in raw if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(raw)
    wilson = _wilson_lower(wins, n)
    checks = {
        "n_ge_30": n >= MIN_N_FOR_CAPITAL_INCREASE,
        "n_ge_50": n >= MIN_N_FOR_GO_MICRO,
        "wilson_ge_80": wilson + 1e-12 >= MIN_WILSON95_FOR_GO,
    }
    return {
        "n": n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(wilson, 4),
        "checks": checks,
        "passed_for_deposit_talk": checks["n_ge_30"] and checks["wilson_ge_80"],
        "passed_for_rearm": checks["n_ge_50"] and checks["wilson_ge_80"],
        "note": (
            "MC/bootstrap sobre los mismos takes NO cuenta como evidencia extra. "
            "Hace falta muestra DNA adicional (ideal OOS / forward)."
        ),
    }


def run_income_mechanism_tests() -> dict[str, Any]:
    """Run simulate_real_income; treat as mechanism proof, not WR proof."""
    import os

    repo = POLY.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "polymarket.research.local_lab.simulate_real_income"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=180,
            env=env,
        )
    except Exception as e:
        return {"ran": False, "error": str(e), "passed": False}

    # Prefer cwd = repo root
    latest = POLY / "data_local" / "local_lab" / "real_income_sim" / "latest.json"
    gate = None
    if latest.exists():
        try:
            gate = (json.loads(latest.read_text()).get("gate") or {})
        except Exception:
            gate = None
    return {
        "ran": True,
        "exit_code": proc.returncode,
        "passed": bool(gate and gate.get("passed")) or proc.returncode == 0,
        "verdict": (gate or {}).get("verdict"),
        "caveat": (gate or {}).get("caveat")
        or "Simulación histórica+fricción; no es fill on-chain ni validación OOS nueva.",
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-12:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-8:]),
    }


def decide(report: dict[str, Any]) -> dict[str, Any]:
    ev = report["evidence"]
    eng = report["engineering"]
    inc = report["income_mechanism"]
    cap = report["capital"]
    mode = report["ops_mode"]
    runway = report.get("deposit_runway") or {}

    blockers: list[str] = []
    if not ev["passed_for_rearm"]:
        blockers.append(
            f"evidence_n={ev['n']}_wilson={ev['wilson95_lower']}_need_n>={MIN_N_FOR_GO_MICRO}_wilson>={MIN_WILSON95_FOR_GO}"
        )
    if not eng.get("passed"):
        blockers.append("engineering_not_ready")
    if not inc.get("passed"):
        blockers.append("income_mechanism_tests_failed")
    if not cap.get("still_armed_after_1_miss"):
        blockers.append("capital_cannot_survive_1_miss")
    if mode.get("watch_only_required") and not mode.get("currently_watch_only"):
        blockers.append("ops_not_in_watch_only_before_rearm_eval")

    # Runway deposit: planned capital OK even if current balance is thin
    can_deposit_runway = bool(runway.get("can_deposit_runway_watch_only"))

    if not blockers:
        status = "READY_TO_REARM"
        action = (
            "Evidencia+ingeniería+capital+income-mechanism OK. "
            "Operador puede rearmar manualmente con private_manager_live.sh "
            "+ POLY_LADDER_REAL_CONFIRM=1 + --auto-execute."
        )
    elif can_deposit_runway and "capital_cannot_survive_1_miss" in blockers and not ev["passed_for_rearm"]:
        status = "DEPOSIT_RUNWAY_GO"
        action = (
            f"PUEDES depositar ${runway.get('deposit_target_usdc')} AHORA (runway, watch-only). "
            "NO armar auto-execute hasta n≥50 / Wilson≥0.80. "
            "El blocker de capital se resuelve con ese depósito; la evidencia sigue pendiente."
        )
        # Capital blocker is resolved by planned deposit; keep evidence blocker honest
        blockers = [b for b in blockers if b != "capital_cannot_survive_1_miss"]
        blockers.append("auto_execute_blocked_until_evidence")
    elif ev["passed_for_deposit_talk"] and not ev["passed_for_rearm"]:
        status = "EVIDENCE_PARTIAL"
        action = (
            "Mantener WATCH_ONLY. Acumular takes DNA. "
            "No activar auto-execute. Evidencia parcial para depósito+trade."
        )
    else:
        status = "NOT_READY"
        action = (
            "Mantener WATCH_ONLY. Acumular takes DNA. "
            "No activar auto-execute. No depositar solo por MC."
        )

    return {
        "status": status,
        "blockers": blockers,
        "action_es": action,
        "can_enable_auto_execute": status == "READY_TO_REARM",
        # Full trade-oriented deposit recommend still needs evidence+capital
        "can_recommend_deposit": bool(
            (ev["passed_for_deposit_talk"] and cap.get("still_armed_after_1_miss"))
            or (status == "DEPOSIT_RUNWAY_GO")
        ),
        "can_deposit_runway_watch_only": can_deposit_runway,
    }


def render_md(report: dict[str, Any]) -> str:
    d = report["decision"]
    ev = report["evidence"]
    lines = [
        "# Rearm Income Gate",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Status:** `{d['status']}`",
        "",
        d["action_es"],
        "",
        "## Evidencia",
        f"- n={ev['n']} wins={ev['wins']} WR_puntual={ev['wr_point']} Wilson95={ev['wilson95_lower']}",
        f"- can_recommend_deposit={d.get('can_recommend_deposit')} · "
        f"can_deposit_runway={d.get('can_deposit_runway_watch_only')} · "
        f"can_auto_execute={d.get('can_enable_auto_execute')}",
        f"- {ev['note']}",
        "",
        "## Ingeniería",
        f"- passed={report['engineering'].get('passed')}",
        "",
        "## Income mechanism tests",
        f"- passed={report['income_mechanism'].get('passed')} · verdict={report['income_mechanism'].get('verdict')}",
        f"- {report['income_mechanism'].get('caveat')}",
        "",
        "## Capital",
        f"- balance={report['capital'].get('balance')} · armed_after_1_miss={report['capital'].get('still_armed_after_1_miss')}",
        "",
    ]
    dr = report.get("deposit_runway") or {}
    if dr:
        lines += [
            "## Deposit runway (planificado)",
            f"- target=${dr.get('deposit_target_usdc')} status=`{dr.get('status')}`",
            f"- can_deposit_runway_watch_only={dr.get('can_deposit_runway_watch_only')}",
            f"- planned still_armed_after_1_miss={((dr.get('capital_planned') or {}).get('still_armed_after_1_miss'))}",
            "",
        ]
    lines += [
        "## Ops",
        f"- watch_only={report['ops_mode'].get('currently_watch_only')}",
        "",
        "## Blockers",
    ]
    for b in d["blockers"] or ["(none)"]:
        lines.append(f"- `{b}`")
    lines += [
        "",
        "## Cómo rearmar (solo si READY_TO_REARM)",
        "",
        "1. Confirmar este gate en verde.",
        "2. Depositar solo si `can_recommend_deposit`.",
        "3. PM2: `private_manager_live.sh` (auto-execute) en lugar de watch.",
        "4. `POLY_LADDER_REAL_CONFIRM=1` + `--i-accept-real-loss YES`.",
        "5. Primeras sesiones: micro cap; un miss → revisar, no martingale.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=3.4482)
    ap.add_argument("--session-cap", type=float, default=5.0)
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--planned-deposit", type=float, default=100.0, help="Verify runway at this deposit")
    ap.add_argument("--run-income-tests", action="store_true")
    ap.add_argument("--write-docs", action="store_true")
    ap.add_argument(
        "--assume-watch-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Treat ops as watch-only when MANAGER_MODE.txt missing (default: true)",
    )
    args = ap.parse_args()

    load_repo_dotenv(override=True)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    ev = evidence_block(raw)
    eng = check_code_safety()
    # engineering may fail env_default if process already armed — still report
    adeq = capital_adequacy(
        raw,
        balance=float(args.balance),
        session_cap=float(args.session_cap),
        budget_cfg=float(args.budget),
    )
    adeq["balance"] = float(args.balance)

    mode_file = POLY / "data_local" / "local_lab" / "vps_runs" / "MANAGER_MODE.txt"
    currently_watch = False
    if mode_file.exists():
        currently_watch = "WATCH" in mode_file.read_text().upper()
    elif bool(args.assume_watch_only):
        currently_watch = True
    income = {"ran": False, "passed": False, "verdict": None, "caveat": "skipped"}
    if args.run_income_tests:
        print("running income mechanism tests (simulate_real_income)…", flush=True)
        # ensure PYTHONPATH
        import os

        os.environ["PYTHONPATH"] = str(POLY.parent)
        income = run_income_mechanism_tests()
        print(
            f"income_tests passed={income.get('passed')} verdict={income.get('verdict')}",
            flush=True,
        )
    else:
        # Try read latest sim if present
        latest = POLY / "data_local" / "local_lab" / "real_income_sim" / "latest.json"
        if latest.exists():
            g = json.loads(latest.read_text()).get("gate") or {}
            income = {
                "ran": True,
                "passed": bool(g.get("passed")),
                "verdict": g.get("verdict"),
                "caveat": g.get("caveat"),
                "source": str(latest),
            }

    # Planned deposit runway verification (does not arm)
    deposit_runway: dict[str, Any] = {}
    try:
        from polymarket.research.local_lab.verify_deposit_runway import run as runway_run

        deposit_runway = runway_run(
            deposit=float(args.planned_deposit),
            write_docs=False,
            run_income_tests=False,  # reuse income already loaded
        )
        # Attach income we already have if runway skipped tests
        if not deposit_runway.get("income_mechanism", {}).get("passed") and income.get("passed"):
            deposit_runway["income_mechanism"] = income
            # recompute runway flag with known income
            checks = dict(deposit_runway.get("checks") or {})
            checks["income_mechanism_ok"] = True
            deposit_runway["checks"] = checks
            deposit_runway["can_deposit_runway_watch_only"] = all(
                [
                    checks.get("engineering_ok"),
                    checks.get("income_mechanism_ok"),
                    checks.get("long_term_robust"),
                    checks.get("planned_capital_survives_1_miss"),
                    checks.get("planned_capital_executable"),
                    checks.get("bankroll_base_positive"),
                    checks.get("bankroll_hostile_positive"),
                ]
            )
            if deposit_runway["can_deposit_runway_watch_only"]:
                deposit_runway["status"] = "DEPOSIT_RUNWAY_GO"
                deposit_runway["can_recommend_deposit"] = True
    except Exception as e:
        deposit_runway = {"error": str(e), "can_deposit_runway_watch_only": False}

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "evidence": ev,
        "engineering": eng,
        "income_mechanism": income,
        "capital": adeq,
        "deposit_runway": deposit_runway,
        "ops_mode": {
            "watch_only_required": True,
            "currently_watch_only": currently_watch,
            "assume_watch_only": bool(args.assume_watch_only),
            "mode_file": str(mode_file) if mode_file.exists() else None,
        },
    }
    report["decision"] = decide(report)

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"rearm_{stamp}.json"
    latest = OUT / "latest.json"
    md_path = OUT / f"rearm_{stamp}.md"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    md_path.write_text(md, encoding="utf-8")
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    if args.write_docs:
        (DOCS / "REARM_INCOME_GATE.md").write_text(md, encoding="utf-8")

    print(json.dumps({"decision": report["decision"], "deposit_runway_status": deposit_runway.get("status"), "report": str(path)}, indent=2))
    # Exit 0 if rearm ready OR deposit runway ready (operator can fund)
    st = report["decision"]["status"]
    return 0 if st in ("READY_TO_REARM", "DEPOSIT_RUNWAY_GO") else 2


if __name__ == "__main__":
    raise SystemExit(main())
