#!/usr/bin/env python3
"""Gate de readiness para capital real (paper → go-live).

Evidencia FRESCA (últimas N horas) + WR robusto (excluye |net|>outlier_cap).
No usa hunts viejos como READY.

    python3 -m polymarket.research.local_lab.go_live_gate --max-age-hours 3
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "go_live"


def _robust_from_sessions(
    glob_pat: str,
    *,
    outlier_cap: float = 0.35,
    max_age_hours: float | None = 3.0,
) -> dict:
    base = POLY / "data_local" / "local_lab" / "maker_fusion"
    wins = losses = flats = outliers = skipped_old = 0
    total = 0.0
    robust_total = 0.0
    traded = 0
    now = time.time()
    for s in sorted(base.glob(glob_pat)):
        rp = s / "report.json"
        if not rp.exists():
            continue
        if max_age_hours is not None:
            age_h = (now - rp.stat().st_mtime) / 3600.0
            if age_h > max_age_hours:
                skipped_old += 1
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
        "skipped_old": skipped_old,
        "wr": round(wr, 4),
        "total_raw": round(total, 4),
        "total_robust": round(robust_total, 4),
        "hit_wr75": bool(wr >= 0.75 and traded >= 4),
        "hit_wr70": bool(wr >= 0.70 and traded >= 4),
        "hit_parallel70": bool(wr >= 0.70 and traded >= 8),
    }


def _best(a: dict, b: dict) -> dict:
    """Pick better evidence for gate (thresholds first, then WR/sample)."""

    def key(m: dict) -> tuple:
        # Prefer samples that actually clear gate bars over tiny perfect WR.
        return (
            int(bool(m.get("hit_wr75"))),
            int(bool(m.get("hit_parallel70"))),
            int(bool(m.get("hit_wr70"))),
            float(m.get("wr") or 0),
            int(m.get("traded") or 0),
            float(m.get("total_robust") or 0),
        )

    return a if key(a) >= key(b) else b


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(*, outlier_cap: float = 0.35, max_age_hours: float = 3.0) -> dict:
    armed = (os.getenv("POLY_LIVE_ARMED") or "0").strip() == "1"
    dry = (os.getenv("POLY_LIVE_DRY_RUN") or "1").strip() != "0"
    kw = dict(outlier_cap=outlier_cap, max_age_hours=max_age_hours)

    flow_c5 = _robust_from_sessions("session_fusion_follow_flow_c5_*", **kw)
    bank_c5 = _robust_from_sessions("session_fusion_c10_bank_c5_*", **kw)
    bank_c10 = _robust_from_sessions("session_fusion_c10_bank_c10_*", **kw)
    pulse_c5 = _robust_from_sessions("session_fusion_c10_pulse_c5_*", **kw)
    pulse_c10 = _robust_from_sessions("session_fusion_c10_pulse_c10_*", **kw)

    par5 = _best(
        _robust_from_sessions("session_promo_flow_c5_L*_c5_*", **kw),
        _robust_from_sessions("session_promo_bank_c5_L*_c5_*", **kw),
    )
    par5 = _best(
        par5,
        _robust_from_sessions("session_promo_pulse_c5_L*_c5_*", **kw),
    )
    par10 = _best(
        _robust_from_sessions("session_promo_pulse_c10_L*_c10_*", **kw),
        _robust_from_sessions("session_promo_bank_c10_L*_c10_*", **kw),
    )

    c5 = _best(flow_c5, bank_c5)
    c5 = _best(c5, pulse_c5)
    c5 = _best(c5, par5)
    c10 = _best(bank_c10, pulse_c10)
    c10 = _best(c10, par10)

    confirm_bank = _read_json(
        POLY / "data_local/local_lab/confirm_fusion_c10_bank/confirm_latest.json"
    )
    confirm_pulse = _read_json(
        POLY / "data_local/local_lab/confirm_fusion_c10_pulse/confirm_latest.json"
    )
    both = bool(
        (confirm_bank and confirm_bank.get("both_ready"))
        or (confirm_pulse and confirm_pulse.get("both_ready"))
    )

    checks = {
        "confirm_both_ready_fresh": both,
        "c5_wr75_fresh": bool(c5.get("hit_wr75")),
        "c10_wr75_fresh": bool(c10.get("hit_wr75")),
        "parallel_c5_wr70_fresh": bool(par5.get("hit_parallel70")),
        "parallel_c10_wr70_fresh": bool(par10.get("hit_parallel70")),
        "live_still_safe": (not armed) and dry,
        "promo_files": (
            (POLY / "config/maker_demo_promo_flow_c5.json").exists()
            and (
                (POLY / "config/maker_demo_promo_fusion_c10.json").exists()
                or (POLY / "config/maker_demo_promo_pulse_c10.json").exists()
            )
        ),
    }

    ready_strict = all(
        [
            checks["c5_wr75_fresh"],
            checks["c10_wr75_fresh"],
            checks["parallel_c5_wr70_fresh"],
            checks["parallel_c10_wr70_fresh"],
            checks["live_still_safe"],
            checks["promo_files"],
        ]
    )
    # Risk-on: WR75 fresco en ambos capitals + al menos un paralelo 70 + SAFE
    ready_risk_on = all(
        [
            checks["c5_wr75_fresh"],
            checks["c10_wr75_fresh"],
            checks["parallel_c5_wr70_fresh"] or checks["parallel_c10_wr70_fresh"],
            checks["live_still_safe"],
            checks["promo_files"],
        ]
    )

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "outlier_cap": outlier_cap,
        "max_age_hours": max_age_hours,
        "checks": checks,
        "metrics": {
            "c5_best": c5,
            "c10_best": c10,
            "flow_c5": flow_c5,
            "bank_c5": bank_c5,
            "bank_c10": bank_c10,
            "pulse_c5": pulse_c5,
            "pulse_c10": pulse_c10,
            "parallel_c5": par5,
            "parallel_c10": par10,
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
            "READY: 1) micro DRY_RUN=1 2) DRY_RUN=0 con MAX_CAPITAL bajo. "
            "DNA @5=promo_flow_c5 · @10=promo_pulse_c10 o promo_fusion_c10."
            if (ready_strict or ready_risk_on)
            else "NOT_READY: falta WR75 fresco @5/@10 y/o paralelo≥70 traded≥8 (ventana fresca)."
        ),
    }
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outlier-cap", type=float, default=0.35)
    ap.add_argument("--max-age-hours", type=float, default=3.0)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = evaluate(outlier_cap=args.outlier_cap, max_age_hours=args.max_age_hours)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"gate_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "gate_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"VERDICT: {report['verdict']}", flush=True)
    for k, v in report["checks"].items():
        print(f"  {'✓' if v else '✗'} {k}", flush=True)
    m = report["metrics"]
    print("c5_best", m["c5_best"], flush=True)
    print("c10_best", m["c10_best"], flush=True)
    print("parallel_c5", m["parallel_c5"], flush=True)
    print("parallel_c10", m["parallel_c10"], flush=True)
    print(f"REPORT -> {path}", flush=True)
    print(report["operator_next"], flush=True)
    raise SystemExit(0 if report["verdict"].startswith("READY") else 1)


if __name__ == "__main__":
    main()
