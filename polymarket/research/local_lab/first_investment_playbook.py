#!/usr/bin/env python3
"""Playbook ejecutable: preflight + impresión de 1ª inversión y previsión EV.

No arma live automáticamente. Solo verifica y muestra pasos.

    python3 -m polymarket.research.local_lab.first_investment_playbook
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from polymarket.research.local_lab.desk_risk import (
    CAPITAL_LADDER_USDC,
    forecast_pnl,
    ladder_stage,
    metrics_from_robust,
)
from polymarket.research.local_lab.go_live_gate import _robust_from_sessions
from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.execution.clob_live import read_gates
from polymarket.src.execution.live_policy import load_checklist

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
PRO_CERT = POLY / "data_local" / "local_lab" / "certify_pro_desk" / "pro_cert_latest.json"
PULSE_CERT = POLY / "data_local" / "local_lab" / "certify_pulse_c10" / "cert_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hours", type=float, default=1.0)
    ap.add_argument("--lines", type=int, default=1)
    args = ap.parse_args()

    gates = read_gates()
    checklist = load_checklist()
    m = _robust_from_sessions(
        "session_promo_pulse_c10*", outlier_cap=0.35, max_age_hours=3.0
    )
    prox = metrics_from_robust(m)
    fc = forecast_pnl(
        hours=float(args.hours),
        lines=int(args.lines),
        wr=float(prox["wr"] or 0.83),
        avg_win=float(prox["avg_win_usdc"]),
        avg_loss=float(prox["avg_loss_usdc"]),
        rho=0.85,
        capital_scale=1.0,
    )
    fc2 = forecast_pnl(
        hours=float(args.hours),
        lines=2,
        wr=float(prox["wr"] or 0.83),
        avg_win=float(prox["avg_win_usdc"]),
        avg_loss=float(prox["avg_loss_usdc"]),
        rho=0.85,
        capital_scale=1.0,
    )

    pro = None
    if PRO_CERT.is_file():
        pro = json.loads(PRO_CERT.read_text(encoding="utf-8"))
    pulse = None
    if PULSE_CERT.is_file():
        pulse = json.loads(PULSE_CERT.read_text(encoding="utf-8"))

    certified = bool(
        (pro and pro.get("certified"))
        or (pulse and pulse.get("certified") and (pro is None or pro.get("parity_ok", True)))
    )
    # Prefer PRO_CERTIFIED when present
    if pro is not None:
        certified = bool(pro.get("certified"))

    print("=== PLAYBOOK PRIMERA INVERSIÓN pulse@10 ===", flush=True)
    print(
        f"Env: ARMED={gates.armed} DRY_RUN={gates.dry_run} "
        f"MAX_CAP={gates.max_capital_usdc} missing={gates.missing}",
        flush=True,
    )
    print(
        f"Checklist dry: {checklist.get('dry_sessions_clean')}/{checklist.get('required')} "
        f"ok={checklist.get('ok')}",
        flush=True,
    )
    print(f"Paper fresco @10: WR={m.get('wr')} decisive={m.get('decisive')} "
          f"PnL_rob={m.get('total_robust')}", flush=True)
    if pro:
        print(f"PRO cert: {pro.get('verdict')} parity={pro.get('parity_ok')}", flush=True)
    elif pulse:
        print(f"Pulse cert: {pulse.get('verdict')}", flush=True)
    else:
        print("Sin artefacto de certificación — corre certify_pro_desk primero.", flush=True)

    print("\n--- Previsión de ganancia (orientativa, no garantía) ---", flush=True)
    print(json.dumps({"1_linea": fc, "2_lineas_corr": fc2}, indent=2), flush=True)
    print("\n--- Ladder capital ---", flush=True)
    print(json.dumps(ladder_stage(5.0), indent=2), flush=True)

    print("\n--- Pasos (manual) ---", flush=True)
    steps = [
        "1) SAFE: POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1",
        "2) Dry 30–60m con maker_demo_promo_pulse_c10_micro_live.json --strategy maker_fusion",
        "3) Si dry sano: POLY_LIVE_DRY_RUN=0 POLY_LIVE_MAX_CAPITAL_USDC=5 → 1ª sesión 30m",
        "4) Matar si FLATTEN_WRONG_TOKEN / DUST / residual / WR vivo cae",
        "5) SAFE al terminar; no subir de 5 hasta ≥3 sesiones limpias",
        "6) Paralelismo: máx 2 líneas, stagger≥45s; EV usa haircut rho=0.85",
    ]
    for s in steps:
        print(s, flush=True)

    print(
        f"\nLISTO_PARA_MICRO={'SI' if certified and gates.dry_run and not gates.armed else 'NO'}",
        flush=True,
    )
    if not certified:
        print(
            "Certificación incompleta. Ejecuta:\n"
            "  python3 -m polymarket.research.local_lab.certify_pro_desk",
            flush=True,
        )
        return 1
    if gates.armed and not gates.dry_run:
        print("PELIGRO: ya estás en LIVE real. Vuelve a SAFE si no es intencional.", flush=True)
        return 2
    print(
        f"\nPrimera inversión: capital={CAPITAL_LADDER_USDC[0]} USDC (mín CLOB) · "
        f"EV≈{fc['pnl_corr_adjusted_usdc']:+.3f} USDC / {args.hours}h (1 línea, corr-adj)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
