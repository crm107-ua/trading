#!/usr/bin/env python3
"""Checklist operador: ¿se puede armar capital real?

No modifica env. Solo evaluá el gate fresco y imprime pasos seguros.

    python3 -m polymarket.research.local_lab.go_live_arm_check
    python3 -m polymarket.research.local_lab.go_live_arm_check --allow-risk-on
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from polymarket.research.local_lab.go_live_gate import evaluate
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-age-hours", type=float, default=3.0)
    ap.add_argument(
        "--allow-risk-on",
        action="store_true",
        help="Acepta READY_RISK_ON además de READY_STRICT",
    )
    args = ap.parse_args()
    report = evaluate(max_age_hours=args.max_age_hours)
    verdict = report["verdict"]
    ok = verdict == "READY_STRICT" or (
        args.allow_risk_on and verdict == "READY_RISK_ON"
    )

    print(f"VERDICT: {verdict}", flush=True)
    print(json.dumps(report["checks"], indent=2), flush=True)
    print("metrics:", flush=True)
    for k in ("c5_best", "c10_best", "parallel_c5", "parallel_c10"):
        print(f"  {k}: {report['metrics'][k]}", flush=True)

    armed = (os.getenv("POLY_LIVE_ARMED") or "0").strip()
    dry = os.getenv("POLY_LIVE_DRY_RUN") or "1"
    cap = os.getenv("POLY_LIVE_MAX_CAPITAL_USDC") or "5"
    print(
        f"\nEnv actual: ARMED={armed} DRY_RUN={dry} MAX_CAPITAL={cap}",
        flush=True,
    )
    print("\nDNA canónico:", flush=True)
    print("  @5  → polymarket/config/maker_demo_promo_pulse_c5.json", flush=True)
    print("  @10 → polymarket/config/maker_demo_promo_pulse_c10.json", flush=True)
    print("  backup @5 → maker_demo_promo_flow_c5.json", flush=True)

    if not ok:
        print(
            "\nNO ARMAR. Sigue paper hasta READY_STRICT "
            "(o --allow-risk-on si aceptas READY_RISK_ON).",
            flush=True,
        )
        return 1

    print(
        "\nLISTO paper. Secuencia sugerida (manual, no automática):\n"
        "  1) Micro dry-run:\n"
        "       POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 "
        "POLY_LIVE_MAX_CAPITAL_USDC=5\n"
        "       → live_maker con DNA @5 (0 órdenes reales)\n"
        "  2) Si dry-run sano 30–60 min:\n"
        "       POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=2..5\n"
        "       → solo micro, matar si WR/adverse se degrada\n"
        "  3) Escalar capital solo tras ≥1 sesión live estable\n"
        "\nPaper ≠ live (fees, latency, fills). Asume riesgo residual.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
