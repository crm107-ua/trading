#!/usr/bin/env python3
"""Checklist operador: ¿se puede armar capital real?

No modifica env. Solo evaluá el gate fresco y imprime pasos seguros.

    python3 -m polymarket.research.local_lab.go_live_arm_check
    python3 -m polymarket.research.local_lab.go_live_arm_check --pulse-only
    python3 -m polymarket.research.local_lab.go_live_arm_check --allow-risk-on
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from polymarket.research.local_lab.go_live_gate import _robust_from_sessions, evaluate
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
PRO_CERT = POLY / "data_local" / "local_lab" / "certify_pro_desk" / "pro_cert_latest.json"
PULSE_CERT = POLY / "data_local" / "local_lab" / "certify_pulse_c10" / "cert_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-age-hours", type=float, default=3.0)
    ap.add_argument(
        "--allow-risk-on",
        action="store_true",
        help="Acepta READY_RISK_ON además de READY_STRICT",
    )
    ap.add_argument(
        "--pulse-only",
        action="store_true",
        help="Camino micro real solo pulse@10 (ignora fallo @5 del gate dual)",
    )
    args = ap.parse_args()
    report = evaluate(max_age_hours=args.max_age_hours)
    verdict = report["verdict"]
    ok = verdict == "READY_STRICT" or (
        args.allow_risk_on and verdict == "READY_RISK_ON"
    )

    # Camino pionero: pulse@10 certificado + evidencia fresca @10
    m10 = _robust_from_sessions(
        "session_promo_pulse_c10*",
        outlier_cap=0.35,
        max_age_hours=args.max_age_hours,
    )
    pro = json.loads(PRO_CERT.read_text(encoding="utf-8")) if PRO_CERT.is_file() else None
    pulse = (
        json.loads(PULSE_CERT.read_text(encoding="utf-8")) if PULSE_CERT.is_file() else None
    )
    pulse_ok = bool(
        float(m10.get("wr") or 0) >= 0.80
        and int(m10.get("decisive") or 0) >= 16
        and float(m10.get("total_robust") or 0) >= 0.50
    )
    cert_ok = bool((pro and pro.get("certified")) or (pulse and pulse.get("certified")))
    if args.pulse_only:
        ok = pulse_ok and cert_ok

    print(f"VERDICT: {verdict}", flush=True)
    if args.pulse_only:
        print(
            f"PULSE_ONLY: pulse_ok={pulse_ok} cert_ok={cert_ok} "
            f"→ {'ARM_MICRO_OK' if ok else 'NO_ARM'}",
            flush=True,
        )
    print(json.dumps(report["checks"], indent=2), flush=True)
    print("metrics:", flush=True)
    for k in ("c5_best", "c10_best", "parallel_c5", "parallel_c10"):
        print(f"  {k}: {report['metrics'][k]}", flush=True)
    print(f"  pulse_c10_fresh: {m10}", flush=True)
    if pro:
        print(f"  pro_cert: {pro.get('verdict')}", flush=True)
    elif pulse:
        print(f"  pulse_cert: {pulse.get('verdict')}", flush=True)

    armed = (os.getenv("POLY_LIVE_ARMED") or "0").strip()
    dry = os.getenv("POLY_LIVE_DRY_RUN") or "1"
    cap = os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or "5"
    print(
        f"\nEnv actual: ARMED={armed} DRY_RUN={dry} MAX_CAPITAL={cap}",
        flush=True,
    )
    print("\nDNA canónico:", flush=True)
    print(
        "  @10 micro → polymarket/config/maker_demo_promo_pulse_c10_micro_live.json",
        flush=True,
    )
    print("  @10 paper → polymarket/config/maker_demo_promo_pulse_c10.json", flush=True)
    print("  strategy → maker_fusion (NO maker_edge)", flush=True)
    print("  NO armar @5 ni Shadow hasta recertificar", flush=True)

    if not ok:
        print(
            "\nNO ARMAR. "
            + (
                "Corre certify_pro_desk / certify_pulse_c10 y revalida @10 fresco."
                if args.pulse_only
                else "Sigue paper hasta READY_STRICT (o --pulse-only / --allow-risk-on)."
            ),
            flush=True,
        )
        return 1

    print(
        "\nLISTO micro pulse@10. Secuencia (manual):\n"
        "  1) Dry:\n"
        "       POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 "
        "POLY_LIVE_MAX_CAPITAL_USDC=5 POLY_LIVE_DRY_SMOKE_POST=0\n"
        "       → live_maker --config ...pulse_c10_micro_live.json "
        "--strategy maker_fusion --minutes 45\n"
        "  2) Micro real:\n"
        "       POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=1.5\n"
        "       → mismo DNA; ladder 1.5→2→3→5\n"
        "  3) SAFE: POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1\n"
        "\nVer: docs/PRO_DESK_PLAYBOOK.md · "
        "python3 -m polymarket.research.local_lab.first_investment_playbook\n"
        "Paper ≠ live. Asume riesgo residual.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
