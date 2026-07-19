#!/usr/bin/env python3
"""Gate de readiness para capital real (paper → go-live).

Criterios (excelente WR, realista):
  - Confirm dual mismo DNA @5 y @10: WR>=75% traded>=4 (robusto: |net|<=cap)
  - Paralelo @5 y @10: agg WR>=70% traded>=8, tot>0
  - Live flags SAFE hasta que el operador arme a mano
  - Excluye outliers |net| > outlier_cap del WR (anti-lotería)

    python3 -m polymarket.research.local_lab.go_live_gate
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "go_live"


def _robust_from_sessions(glob_pat: str, *, outlier_cap: float = 0.35) -> dict:
    base = POLY / "data_local" / "local_lab" / "maker_fusion"
    wins = losses = flats = outliers = 0
    total = 0.0
    robust_total = 0.0
    traded = 0
    for s in sorted(base.glob(glob_pat)):
        rp = s / "report.json"
        if not rp.exists():
            continue
        r = json.loads(rp.read_text(encoding="utf-8"))
        n = float(r.get("net_session_usdc") or 0)
        f = int(r.get("fills") or 0)
        total += n
        if f <= 0:
            continue
        if abs(n) > outlier_cap:
            outliers += 1
            continue
        robust_total += n
        traded += 1
        if n > 1e-9:
            wins += 1
        elif n < -1e-9:
            losses += 1
        else:
            flats += 1
    wr = (wins / traded) if traded else 0.0
    return {
        "traded": traded,
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "outliers_excluded": outliers,
        "wr": round(wr, 4),
        "total_raw": round(total, 4),
        "total_robust": round(robust_total, 4),
        "hit_wr75": bool(wr >= 0.75 and traded >= 4),
        "hit_wr70": bool(wr >= 0.70 and traded >= 4),
    }


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(*, outlier_cap: float = 0.35) -> dict:
    armed = (os.getenv("POLY_LIVE_ARMED") or "0").strip() == "1"
    dry = (os.getenv("POLY_LIVE_DRY_RUN") or "1").strip() != "0"

    confirm_bank = _read_json(
        POLY / "data_local/local_lab/confirm_fusion_c10_bank/confirm_latest.json"
    )
    parallel_c5 = _read_json(
        POLY / "data_local/local_lab/parallel_promo_bank_c5/parallel_latest.json"
    )
    parallel_c10 = _read_json(
        POLY / "data_local/local_lab/parallel_promo_bank_c10/parallel_latest.json"
    )

    # Robust session scans for bank DNA
    bank_c5 = _robust_from_sessions("session_fusion_c10_bank_c5_*", outlier_cap=outlier_cap)
    bank_c10 = _robust_from_sessions("session_fusion_c10_bank_c10_*", outlier_cap=outlier_cap)
    # Also include parallel bank lines
    par5 = _robust_from_sessions("session_promo_bank_c5_L*_c5_*", outlier_cap=outlier_cap)
    par10 = _robust_from_sessions("session_promo_bank_c10_L*_c10_*", outlier_cap=outlier_cap)

    checks = {
        "confirm_both_ready": bool(confirm_bank and confirm_bank.get("both_ready")),
        "bank_c5_wr75_robust": bool(bank_c5.get("hit_wr75")),
        "bank_c10_wr75_robust": bool(bank_c10.get("hit_wr75")),
        "parallel_c5_wr70_robust": bool(par5.get("wr", 0) >= 0.70 and par5.get("traded", 0) >= 8),
        "parallel_c10_wr70_robust": bool(
            par10.get("wr", 0) >= 0.70 and par10.get("traded", 0) >= 8
        ),
        "live_still_safe": (not armed) and dry,
        "promo_c10_exists": (POLY / "config/maker_demo_promo_fusion_c10.json").exists(),
        "promo_c5_exists": (POLY / "config/maker_demo_promo_bank_c5.json").exists(),
    }
    # Minimum for "listo con riesgo asumido": dual robust WR75 + parallel one capital + SAFE
    ready_strict = all(
        [
            checks["bank_c5_wr75_robust"],
            checks["bank_c10_wr75_robust"],
            checks["parallel_c5_wr70_robust"],
            checks["parallel_c10_wr70_robust"],
            checks["live_still_safe"],
            checks["promo_c10_exists"],
            checks["promo_c5_exists"],
        ]
    )
    ready_risk_on = all(
        [
            checks["bank_c5_wr75_robust"] or checks["parallel_c5_wr70_robust"],
            checks["bank_c10_wr75_robust"] or checks["parallel_c10_wr70_robust"],
            checks["live_still_safe"],
            checks["promo_c10_exists"],
        ]
    )

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "outlier_cap": outlier_cap,
        "checks": checks,
        "metrics": {
            "bank_c5": bank_c5,
            "bank_c10": bank_c10,
            "parallel_bank_c5": par5,
            "parallel_bank_c10": par10,
            "confirm_bank": confirm_bank,
            "parallel_c5_report": (parallel_c5 or {}).get("aggregate"),
            "parallel_c10_report": (parallel_c10 or {}).get("aggregate"),
        },
        "ready_strict": ready_strict,
        "ready_risk_on": ready_risk_on,
        "verdict": (
            "READY_STRICT"
            if ready_strict
            else ("READY_RISK_ON" if ready_risk_on else "NOT_READY")
        ),
        "live_flags": {"POLY_LIVE_ARMED": armed, "POLY_LIVE_DRY_RUN": dry},
        "operator_next": (
            "Si READY_*: micro-live DRY_RUN=1 primero; luego DRY_RUN=0 con "
            "POLY_LIVE_MAX_CAPITAL_USDC bajo. Nunca armar sin checklist."
            if (ready_strict or ready_risk_on)
            else "Seguir paper: confirm dual bank + paralelo @5/@10 hasta WR robusto."
        ),
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outlier-cap", type=float, default=0.35)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = evaluate(outlier_cap=args.outlier_cap)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"gate_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "gate_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"VERDICT: {report['verdict']}", flush=True)
    for k, v in report["checks"].items():
        print(f"  {'✓' if v else '✗'} {k}", flush=True)
    print("metrics.bank_c5", report["metrics"]["bank_c5"], flush=True)
    print("metrics.bank_c10", report["metrics"]["bank_c10"], flush=True)
    print("metrics.parallel_bank_c5", report["metrics"]["parallel_bank_c5"], flush=True)
    print("metrics.parallel_bank_c10", report["metrics"]["parallel_bank_c10"], flush=True)
    print(f"REPORT -> {path}", flush=True)
    print(report["operator_next"], flush=True)
    raise SystemExit(0 if report["verdict"].startswith("READY") else 1)


if __name__ == "__main__":
    main()
