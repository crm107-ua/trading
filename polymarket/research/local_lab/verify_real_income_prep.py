#!/usr/bin/env python3
"""
Verificación completa de preparación a ingreso real (Temperature Ladder).

SAFE: nunca posta, nunca arma de forma persistente, nunca recomienda depositar
si evidencia/capital fallan.

Cubre:
  1) SAFE env + geoblock + signing
  2) Ingeniería / DNA (real_env_ready system)
  3) Ladder dry go-live check
  4) Mecanismo de ingresos (simulate_real_income)
  5) Rearm gate (evidencia n/Wilson + capital runway)
  6) Forward watch progress (snapshots / gates scoreboard)
  7) Stack live evaluate (EDGE ahora?)
  8) What-if capital $25 / $50 / $100 (sim only)

  python3 -m polymarket.research.local_lab.verify_real_income_prep
  python3 -m polymarket.research.local_lab.verify_real_income_prep --write-docs
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

POLY = Path(__file__).resolve().parents[2]
REPO = POLY.parent
OUT = POLY / "data_local" / "local_lab" / "real_income_prep"
DOCS = POLY / "docs"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(mod: str, args: list[str], timeout: int = 300) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["POLY_LIVE_ARMED"] = "0"
    env["POLY_LIVE_DRY_RUN"] = "1"
    # Never inherit accidental confirm/rearm into verification
    env.pop("POLY_LADDER_REAL_CONFIRM", None)
    env.pop("POLY_LADDER_ALLOW_REARM", None)
    cmd = [sys.executable, "-m", mod, *args]
    print(f">>> {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout, env=env
        )
    except Exception as exc:  # noqa: BLE001
        return {"mod": mod, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "mod": mod,
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-30:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-12:]),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def check_safe_live() -> dict[str, Any]:
    from polymarket.src.ai.env_loader import load_repo_dotenv
    from polymarket.src.execution.clob_live import read_gates
    from polymarket.src.execution.live_policy import check_geoblock, geoblock_blocks_real

    load_repo_dotenv(override=True)
    # Force SAFE for this process check
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    g = read_gates()
    blocked, msg = geoblock_blocks_real()
    geo = check_geoblock()
    mode_file = VPS / "MANAGER_MODE.txt"
    mode = mode_file.read_text(encoding="utf-8").strip() if mode_file.exists() else None
    checks = {
        "armed_off": not g.armed,
        "dry_run_on": bool(g.dry_run),
        "signing_ready": bool(g.signing_ready),
        "funder_present": bool(g.funder),
        "eoa_present": bool(g.eoa),
        "geoblock_ok": not blocked,
        "allow_rearm_unset": (os.getenv("POLY_LADDER_ALLOW_REARM") or "").strip() != "1",
        "real_confirm_unset": (os.getenv("POLY_LADDER_REAL_CONFIRM") or "").strip() != "1",
        "watch_mode_file": (mode or "").upper().startswith("WATCH") if mode else True,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "geoblock_msg": msg,
        "geo": {
            "blocked": getattr(geo, "blocked", None),
            "country": getattr(geo, "country", None),
            "region": getattr(geo, "region", None),
            "ip": getattr(geo, "ip", None),
        },
        "manager_mode": mode,
        "gates": {
            "armed": g.armed,
            "dry_run": g.dry_run,
            "signing_ready": g.signing_ready,
            "funder_set": bool(g.funder),
            "eoa_set": bool(g.eoa),
        },
    }


def check_live_scripts() -> dict[str, Any]:
    watch = POLY / "scripts" / "private_manager_watch.sh"
    live = POLY / "scripts" / "private_manager_live.sh"
    live_txt = live.read_text(encoding="utf-8") if live.is_file() else ""
    checks = {
        "watch_script_exists": watch.is_file(),
        "live_script_exists": live.is_file(),
        "live_requires_allow_rearm": "POLY_LADDER_ALLOW_REARM" in live_txt,
        "live_starts_safe": "POLY_LIVE_ARMED=0" in live_txt and "POLY_LIVE_DRY_RUN=1" in live_txt,
        "live_requires_accept_loss": "i-accept-real-loss YES" in live_txt,
        "live_checks_rearm_gate": "rearm_income_gate" in live_txt,
    }
    return {"passed": all(checks.values()), "checks": checks}


def check_forward() -> dict[str, Any]:
    try:
        from polymarket.research.local_lab.research_telemetry import (
            write_evidence_progress,
            write_forward_progress,
        )

        ev = write_evidence_progress()
        fwd = ev.get("forward_progress") or write_forward_progress()
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    hist = ev.get("historical") or {}
    return {
        "passed": True,
        "historical_n": hist.get("n"),
        "wilson95": hist.get("wilson95_lower"),
        "n_to_go_micro": ev.get("n_to_go_micro"),
        "wilson_ok": ev.get("wilson_ok"),
        "forward_hits": (ev.get("forward") or {}).get("forward_hits_logged"),
        "snapshots": fwd.get("snapshots_total"),
        "markets_tracked": fwd.get("markets_tracked"),
        "gates_2_of_3": [
            {
                "city": x.get("city"),
                "day": x.get("day"),
                "gates": (x.get("gates_live") or {}).get("gates_passed"),
                "waiting": (x.get("gates_live") or {}).get("waiting"),
                "basket": (x.get("gates_live") or {}).get("basket"),
            }
            for x in (fwd.get("gates_2_of_3") or [])[:5]
        ],
        "close": [
            {
                "city": x.get("city"),
                "day": x.get("day"),
                "best_basket": x.get("best_basket"),
                "gap": x.get("gap"),
            }
            for x in (fwd.get("close_to_dna_gap_le_12c") or [])[:5]
        ],
    }


def check_stack_now() -> dict[str, Any]:
    try:
        from polymarket.research.local_lab.weather_ladder_paper import load_cfg
        from polymarket.research.local_lab.weather_ladder_real import evaluate_real_stack

        cfg = load_cfg(POLY / "config" / "weather_ladder_definitive_real.json")
        stack = evaluate_real_stack(cfg)
    except Exception as exc:  # noqa: BLE001
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}
    market = stack.get("market_now") or {}
    return {
        "passed": True,
        "balance_pusd": (stack.get("wallet") or {}).get("balance_pusd"),
        "geoblock_ok": (stack.get("checks") or {}).get("geoblock_ok"),
        "accepted_n": market.get("accepted_n"),
        "near_miss_n": len(market.get("near_miss") or []),
        "ready_to_arm": stack.get("ready_to_arm"),
        "can_execute_now": stack.get("can_execute_now"),
        "blockers": list(stack.get("blockers") or [])[:12],
        "accepted_slugs": [c.get("slug") for c in (market.get("accepted") or [])],
    }


def capital_what_if(balance: float) -> dict[str, Any]:
    """Sim runway at current + target deposits (does not recommend if evidence weak)."""
    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
    from polymarket.research.local_lab.ladder_viability_report import capital_adequacy

    cases_path = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
    if not cases_path.exists():
        return {"passed": False, "error": "missing_cases"}
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    rows = {}
    for bal in (balance, 25.0, 50.0, 100.0):
        adeq = capital_adequacy(raw, balance=float(bal), session_cap=5.0, budget_cfg=3.0)
        rows[f"{bal:g}"] = {
            "balance": bal,
            "still_armed_after_1_miss": adeq.get("still_armed_after_1_miss"),
            "notional": adeq.get("notional_first") or adeq.get("notional"),
            "equity_after_1_miss": adeq.get("equity_after_1_miss"),
            "executable": adeq.get("executable"),
        }
    return {"passed": True, "profiles": rows, "note_es": "What-if sim; no es orden de depósito."}


def decide(report: dict[str, Any]) -> dict[str, Any]:
    safe = report["safe"]
    scripts = report["live_scripts"]
    rearm = (report.get("rearm") or {}).get("decision") or {}
    eng = report.get("engineering") or {}
    dry = report.get("ladder_dry") or {}
    mech = report.get("income_mechanism") or {}
    fwd = report.get("forward") or {}
    stack = report.get("stack_now") or {}

    blockers: list[str] = []
    if not safe.get("passed"):
        failed = [k for k, v in (safe.get("checks") or {}).items() if not v]
        blockers.append("safe_env:" + ",".join(failed))
    if not scripts.get("passed"):
        failed = [k for k, v in (scripts.get("checks") or {}).items() if not v]
        blockers.append("live_scripts:" + ",".join(failed))
    if not eng.get("passed"):
        failed = [k for k, v in (eng.get("checks") or {}).items() if not v]
        blockers.append("engineering:" + ",".join(failed[:8]))
    if not dry.get("passed"):
        blockers.append(f"ladder_dry:{dry.get('verdict')}")
    if not mech.get("passed"):
        blockers.append("income_mechanism_failed")
    if rearm.get("status") != "READY_TO_REARM":
        blockers.extend(list(rearm.get("blockers") or ["rearm_not_ready"]))

    # Layered verdict — honest about what is ready
    system_ok = bool(safe.get("passed") and scripts.get("passed") and eng.get("passed") and dry.get("passed"))
    mechanism_ok = bool(mech.get("passed"))
    evidence_ok = rearm.get("status") == "READY_TO_REARM"
    edge_now = int(stack.get("accepted_n") or 0) >= 1

    if evidence_ok and system_ok and mechanism_ok:
        status = "READY_TO_REARM"
        action = (
            "Gate verde. Operador humano puede depositar (si can_recommend_deposit) "
            "y poner POLY_LADDER_ALLOW_REARM=1 + private_manager_live.sh."
        )
    elif system_ok and mechanism_ok:
        status = "SYSTEM_PREP_OK_EVIDENCE_BLOCK"
        action = (
            "Ingeniería/SAFE/mecanismo OK. Mantener WATCH_ONLY. "
            "NO depositar ni armar: evidencia/capital bloquean rearme. "
            "Seguir capturando forward DNA hasta n≥50 y Wilson≥0.80 + capital ≥1 miss."
        )
    else:
        status = "NOT_READY"
        action = "Corregir blockers de sistema/SAFE/scripts antes de hablar de ingreso real."

    return {
        "status": status,
        "action_es": action,
        "system_prep_ok": system_ok,
        "mechanism_ok": mechanism_ok,
        "evidence_ready": evidence_ok,
        "edge_open_now": edge_now,
        "can_enable_auto_execute": bool(rearm.get("can_enable_auto_execute")),
        "can_recommend_deposit": bool(rearm.get("can_recommend_deposit")),
        "blockers": blockers,
        "forward_n_to_go": fwd.get("n_to_go_micro"),
        "balance_live": stack.get("balance_pusd"),
    }


def render_md(report: dict[str, Any]) -> str:
    d = report["decision"]
    safe = report["safe"]
    rearm = (report.get("rearm") or {}).get("decision") or {}
    fwd = report.get("forward") or {}
    dry = report.get("ladder_dry") or {}
    eng = report.get("engineering") or {}
    lines = [
        "# Verificación — preparación ingreso real",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Veredicto:** `{d['status']}`",
        "",
        d["action_es"],
        "",
        "## Capas",
        f"- system_prep_ok={d['system_prep_ok']}",
        f"- mechanism_ok={d['mechanism_ok']}",
        f"- evidence_ready={d['evidence_ready']}",
        f"- edge_open_now={d['edge_open_now']}",
        f"- can_enable_auto_execute={d['can_enable_auto_execute']}",
        f"- can_recommend_deposit={d['can_recommend_deposit']}",
        "",
        "## SAFE / región",
        f"- passed={safe.get('passed')} · country={(safe.get('geo') or {}).get('country')} · mode={safe.get('manager_mode')}",
        f"- checks={json.dumps(safe.get('checks'), ensure_ascii=False)}",
        "",
        "## Ingeniería / dry",
        f"- engineering_passed={eng.get('passed')}",
        f"- ladder_dry={dry.get('verdict')} passed={dry.get('passed')} balance={dry.get('balance_pusd')}",
        "",
        "## Rearm gate",
        f"- status={rearm.get('status')}",
        f"- blockers={rearm.get('blockers')}",
        "",
        "## Forward evidencia",
        f"- n histórico={fwd.get('historical_n')} · Wilson={fwd.get('wilson95')} · faltan GO_MICRO={fwd.get('n_to_go_micro')}",
        f"- snapshots={fwd.get('snapshots')} · tracked={fwd.get('markets_tracked')} · dna_hits_fwd={fwd.get('forward_hits')}",
        f"- gates_2_of_3={fwd.get('gates_2_of_3')}",
        f"- close={fwd.get('close')}",
        "",
        "## Capital what-if (sim)",
    ]
    for k, row in ((report.get("capital_what_if") or {}).get("profiles") or {}).items():
        lines.append(
            f"- ${k}: armed_after_1_miss={row.get('still_armed_after_1_miss')} "
            f"notional={row.get('notional')} equity_after_1={row.get('equity_after_1_miss')}"
        )
    lines += [
        "",
        "## Blockers",
    ]
    for b in d.get("blockers") or ["(none)"]:
        lines.append(f"- `{b}`")
    lines += [
        "",
        "## Qué NO hacer ahora",
        "",
        "- No `POLY_LADDER_ALLOW_REARM=1` hasta READY_TO_REARM.",
        "- No depositar solo por MC / WR puntual con n pequeño.",
        "- No aflojar DNA (basket 0.50 / leg 0.39 / UD).",
        "- No sustituir watch por live manager.",
        "",
        "## Qué sí está listo",
        "",
        "- Path SAFE + scripts watch/live gated.",
        "- Mecanismo de ingresos simulado con fricción.",
        "- Watch forward acumulando snapshots → cases al resolver.",
        "",
        "## Rearme (solo si READY_TO_REARM)",
        "",
        "1. `python3 -m polymarket.research.local_lab.verify_real_income_prep` → READY.",
        "2. Depositar solo si `can_recommend_deposit` (típicamente ≥$25 micro).",
        "3. `POLY_LADDER_ALLOW_REARM=1` + PM2 `private_manager_live.sh`.",
        "4. `POLY_LADDER_REAL_CONFIRM=1` ya lo pone el script live; accept-loss YES incluido.",
        "5. Cap micro ≤$5/sesión; 1 miss → parar y revisar.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=None, help="Override balance; default = live wallet")
    ap.add_argument("--write-docs", action="store_true")
    ap.add_argument("--skip-slow", action="store_true", help="Skip simulate_real_income / viability MC")
    args = ap.parse_args()

    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["PYTHONPATH"] = str(REPO)

    print("=== 1/8 SAFE ===", flush=True)
    safe = check_safe_live()
    print(json.dumps({"safe_passed": safe["passed"], "geo": safe.get("geo")}, indent=2), flush=True)

    print("=== 2/8 live scripts ===", flush=True)
    scripts = check_live_scripts()

    print("=== 3/8 engineering (real_env_ready system) ===", flush=True)
    from polymarket.research.local_lab.real_env_ready import check_code_safety

    eng = check_code_safety()

    print("=== 4/8 ladder_go_live_check ===", flush=True)
    dry_step = _run(
        "polymarket.research.local_lab.ladder_go_live_check",
        [],
        timeout=240,
    )
    dry_rep = _load_json(
        sorted((POLY / "data_local" / "local_lab" / "ladder_go_live").glob("check_*.json"))[-1]
    ) if (POLY / "data_local" / "local_lab" / "ladder_go_live").exists() and list(
        (POLY / "data_local" / "local_lab" / "ladder_go_live").glob("check_*.json")
    ) else {}
    ladder_dry = {
        "passed": bool(dry_rep.get("passed")),
        "verdict": dry_rep.get("verdict"),
        "balance_pusd": dry_rep.get("balance_pusd"),
        "checks_failed": [k for k, v in (dry_rep.get("checks") or {}).items() if not v],
        "step": dry_step,
    }

    print("=== 5/8 income mechanism ===", flush=True)
    if args.skip_slow:
        latest = _load_json(POLY / "data_local" / "local_lab" / "real_income_sim" / "latest.json")
        gate = (latest.get("gate") or {})
        mech = {
            "passed": bool(gate.get("passed")),
            "verdict": gate.get("verdict"),
            "source": "cached_latest",
        }
    else:
        mech_step = _run("polymarket.research.local_lab.simulate_real_income", [], timeout=180)
        latest = _load_json(POLY / "data_local" / "local_lab" / "real_income_sim" / "latest.json")
        gate = (latest.get("gate") or {})
        mech = {
            "passed": bool(gate.get("passed")) or bool(mech_step.get("ok")),
            "verdict": gate.get("verdict"),
            "step": mech_step,
        }

    print("=== 6/8 stack now + balance ===", flush=True)
    stack = check_stack_now()
    bal = float(args.balance) if args.balance is not None else float(stack.get("balance_pusd") or 3.4482)

    print("=== 7/8 rearm_income_gate ===", flush=True)
    rearm_args = ["--balance", str(bal), "--write-docs"]
    if not args.skip_slow:
        rearm_args.append("--run-income-tests")
    rearm_step = _run(
        "polymarket.research.local_lab.rearm_income_gate",
        rearm_args,
        timeout=240,
    )
    rearm_full = _load_json(POLY / "data_local" / "local_lab" / "rearm_gate" / "latest.json")

    print("=== 8/8 forward + capital what-if ===", flush=True)
    fwd = check_forward()
    cap = capital_what_if(bal)

    report: dict[str, Any] = {
        "ts_utc": _ts(),
        "balance_usdc": bal,
        "safe": safe,
        "live_scripts": scripts,
        "engineering": eng,
        "ladder_dry": ladder_dry,
        "income_mechanism": mech,
        "stack_now": stack,
        "rearm": rearm_full,
        "rearm_step": rearm_step,
        "forward": fwd,
        "capital_what_if": cap,
    }
    report["decision"] = decide(report)

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"verify_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "REAL_INCOME_PREP.md").write_text(md, encoding="utf-8")
    (VPS / "REAL_INCOME_PREP.json").write_text(json.dumps(report["decision"], indent=2), encoding="utf-8")
    if args.write_docs:
        (DOCS / "REAL_INCOME_PREP.md").write_text(md, encoding="utf-8")
        # Keep PREPARE_REAL_MONEY in sync with short pointer
        prep = "\n".join(
            [
                "# Prepare Real Money Battery",
                "",
                f"**UTC:** `{report['ts_utc']}`",
                f"**Veredicto unificado:** `{report['decision']['status']}`",
                "",
                report["decision"]["action_es"],
                "",
                "Detalle: [`REAL_INCOME_PREP.md`](REAL_INCOME_PREP.md) · "
                "`python3 -m polymarket.research.local_lab.verify_real_income_prep --write-docs`",
                "",
                f"- rearm={((report.get('rearm') or {}).get('decision') or {}).get('status')}",
                f"- ladder_dry={ladder_dry.get('verdict')}",
                f"- system_prep_ok={report['decision']['system_prep_ok']}",
                f"- can_recommend_deposit={report['decision']['can_recommend_deposit']}",
                "",
            ]
        )
        (DOCS / "PREPARE_REAL_MONEY.md").write_text(prep, encoding="utf-8")

    print(json.dumps(report["decision"], indent=2), flush=True)
    print(f"report -> {path}", flush=True)
    print(f"md -> {OUT / 'LATEST.md'}", flush=True)

    # Exit 0 = verification ran and system layer OK (even if evidence blocks rearm)
    # Exit 2 = system not prep-ready
    # Exit 3 = READY_TO_REARM (signal for operators/CI)
    if report["decision"]["status"] == "READY_TO_REARM":
        return 3
    if report["decision"]["system_prep_ok"] and report["decision"]["mechanism_ok"]:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
