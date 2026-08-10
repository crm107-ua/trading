#!/usr/bin/env python3
"""
Battery de preparación a dinero real + prueba de mecanismo de ingresos.

Corre en SAFE (no posta):
  1) simulate_real_income (mecanismo / fricción)
  2) wallet_take_reality_sim (bankroll actual)
  3) ladder_viability_report (RESEARCH_ONLY scorecard)
  4) rearm_income_gate (¿se puede rearmar?)
  5) book_sim opcional (--live-book)

  python3 -m polymarket.research.local_lab.prepare_real_money_battery \
    --balance 3.4482 --live-book --write-docs
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

POLY = Path(__file__).resolve().parents[2]
REPO = POLY.parent
OUT = POLY / "data_local" / "local_lab" / "prepare_real_money"
DOCS = POLY / "docs"


def _run(mod: str, args: list[str], timeout: int = 300) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)
    env["POLY_LIVE_ARMED"] = "0"
    env["POLY_LIVE_DRY_RUN"] = "1"
    cmd = [sys.executable, "-m", mod, *args]
    print(f">>> {' '.join(cmd)}", flush=True)
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout, env=env
        )
    except Exception as e:
        return {"mod": mod, "ok": False, "error": str(e)}
    return {
        "mod": mod,
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-10:]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--balance", type=float, default=3.4482)
    ap.add_argument("--live-book", action="store_true")
    ap.add_argument("--write-docs", action="store_true")
    ap.add_argument("--mc-reps", type=int, default=800)
    args = ap.parse_args()

    bal = str(args.balance)
    steps = []

    steps.append(_run("polymarket.research.local_lab.simulate_real_income", [], timeout=120))
    steps.append(
        _run(
            "polymarket.research.local_lab.wallet_take_reality_sim",
            ["--balance", bal, "--balances", f"{bal},10,25"],
            timeout=60,
        )
    )
    viab_args = ["--balance", bal, "--mc-reps", str(args.mc_reps), "--write-docs"]
    if args.live_book:
        viab_args.append("--live-book")
    steps.append(
        _run("polymarket.research.local_lab.ladder_viability_report", viab_args, timeout=400)
    )
    steps.append(
        _run(
            "polymarket.research.local_lab.rearm_income_gate",
            ["--balance", bal, "--run-income-tests", "--write-docs"],
            timeout=180,
        )
    )

    # Collect decisions
    rearm = {}
    rp = POLY / "data_local" / "local_lab" / "rearm_gate" / "latest.json"
    if rp.exists():
        rearm = json.loads(rp.read_text()).get("decision") or {}
    viab = {}
    vp = POLY / "data_local" / "local_lab" / "ladder_viability" / "latest.json"
    if vp.exists():
        viab = (json.loads(vp.read_text()).get("scorecard") or {})

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "balance_usdc": float(args.balance),
        "steps": steps,
        "viability_decision": viab.get("decision"),
        "rearm_status": rearm.get("status"),
        "rearm_action": rearm.get("action_es"),
        "can_enable_auto_execute": bool(rearm.get("can_enable_auto_execute")),
        "posture": "WATCH_ONLY" if not rearm.get("can_enable_auto_execute") else "READY_TO_REARM",
        "summary_es": (
            "Mecanismo de ingresos testeado en sim. "
            + (
                "Rearme a dinero real AÚN NO autorizado (evidencia/capital)."
                if not rearm.get("can_enable_auto_execute")
                else "Gate READY — operador puede rearmar auto-execute."
            )
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"battery_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = "\n".join(
        [
            "# Prepare Real Money Battery",
            "",
            f"**UTC:** `{report['ts_utc']}`",
            f"**Postura:** `{report['posture']}`",
            f"**Viabilidad:** `{report['viability_decision']}`",
            f"**Rearm:** `{report['rearm_status']}`",
            "",
            report["summary_es"],
            "",
            "## Steps",
            "",
            *[
                f"- `{s['mod']}` ok={s.get('ok')} exit={s.get('exit_code')} err={s.get('error')}"
                for s in steps
            ],
            "",
            f"Acción: {report.get('rearm_action')}",
            "",
        ]
    )
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    if args.write_docs:
        (DOCS / "PREPARE_REAL_MONEY.md").write_text(md, encoding="utf-8")

    print(json.dumps({k: report[k] for k in report if k != "steps"}, indent=2))
    print(f"report -> {path}", flush=True)
    # Battery succeeds if sims ran; rearm may still be NOT_READY (expected)
    return 0 if all(s.get("ok") or s.get("exit_code") in (0, 2) for s in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
