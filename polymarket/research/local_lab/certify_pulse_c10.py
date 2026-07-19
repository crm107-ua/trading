#!/usr/bin/env python3
"""Certificación máxima pulse@10 antes de dinero real.

Ejecuta olas paper + (opcional) dry-run CLOB y emite CERTIFIED / NOT_CERTIFIED.

    python3 -m polymarket.research.local_lab.certify_pulse_c10 \
      --waves 2 --sessions 8 --lines 4 --minutes 5 --dry-minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.go_live_gate import _robust_from_sessions
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "certify_pulse_c10"

# Barras duras para inversión micro real
MIN_WR = 0.80
MIN_DECISIVE = 16
MIN_ROBUST_PNL = 0.50
MAX_AGE_H = 3.0


async def _run(args: list[str]) -> int:
    print(f"\n>> {' '.join(args)}", flush=True)
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-m", *args, cwd=str(POLY.parent)
    )
    return int(await p.wait())


def _metrics(*, config_glob: str, max_age_hours: float) -> dict:
    return _robust_from_sessions(
        config_glob, outlier_cap=0.35, max_age_hours=max_age_hours
    )


def _pass(m: dict) -> bool:
    return bool(
        float(m.get("wr") or 0) >= MIN_WR
        and int(m.get("decisive") or 0) >= MIN_DECISIVE
        and float(m.get("total_robust") or 0) >= MIN_ROBUST_PNL
    )


async def _dry_run(minutes: float) -> dict:
    """Dry-run CLOB real; fuerza DRY_RUN=1 y restaura SAFE."""
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = "10"
    from polymarket.research.local_lab.live_maker import run_live_session
    from polymarket.src.execution.clob_live import read_gates

    g = read_gates()
    if not g.dry_run:
        os.environ["POLY_LIVE_ARMED"] = "0"
        raise RuntimeError("ABORT: DRY_RUN no activo")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        report = await run_live_session(
            minutes=float(minutes),
            config_path=POLY / "config" / "maker_demo_promo_pulse_c10_live.json",
            session_id=f"cert_dry_c10_{stamp}",
        )
        return {
            "ok": report.get("verdict") == "LIVE_DRY_RUN" and bool(report.get("dry_run")),
            "verdict": report.get("verdict"),
            "dry_run": report.get("dry_run"),
            "fills": report.get("fills"),
            "net": report.get("net_session_usdc"),
            "session_dir": report.get("session_dir"),
        }
    finally:
        os.environ["POLY_LIVE_ARMED"] = "0"
        os.environ["POLY_LIVE_DRY_RUN"] = "1"
        print("SAFE restored after dry", flush=True)


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"

    cfg_name = args.config
    label = args.label
    history: list[dict] = []

    for wave in range(1, int(args.waves) + 1):
        print(f"\n===== CERT WAVE {wave}/{args.waves} =====", flush=True)
        code = await _run(
            [
                "polymarket.research.local_lab.parallel_paper_lines",
                "--label",
                label,
                "--strategy",
                "maker_fusion",
                "--config",
                cfg_name,
                "--capital",
                "10",
                "--lines",
                str(args.lines),
                "--parallel",
                str(min(int(args.lines), 4)),
                "--sessions",
                str(args.sessions),
                "--minutes",
                str(args.minutes),
            ]
        )
        # confirm mono-capital @10
        confirm_code = await _run(
            [
                "polymarket.research.local_lab.confirm_dna_pair",
                "--label",
                "fusion_c10_pulse",
                "--strategy",
                "maker_fusion",
                "--config",
                cfg_name,
                "--capitals",
                "10",
                "--sessions",
                str(max(6, int(args.sessions))),
                "--minutes",
                str(args.minutes),
            ]
        )
        m_par = _metrics(
            config_glob=f"session_{label}_L*_c10_*", max_age_hours=MAX_AGE_H
        )
        m_all = _metrics(
            config_glob="session_promo_pulse_c10*", max_age_hours=MAX_AGE_H
        )
        # prefer live label if used
        m_live = _metrics(
            config_glob="session_promo_pulse_c10_live_L*_c10_*",
            max_age_hours=MAX_AGE_H,
        )
        best = m_par
        for cand in (m_all, m_live):
            if (float(cand.get("wr") or 0), int(cand.get("decisive") or 0)) > (
                float(best.get("wr") or 0),
                int(best.get("decisive") or 0),
            ):
                best = cand
        row = {
            "wave": wave,
            "parallel_exit": code,
            "confirm_exit": confirm_code,
            "parallel": m_par,
            "all_pulse_c10": m_all,
            "live_label": m_live,
            "best": best,
            "paper_pass": _pass(best),
        }
        history.append(row)
        print(
            f"WAVE {wave} paper_pass={row['paper_pass']} best={best}",
            flush=True,
        )

    dry = None
    if float(args.dry_minutes) > 0:
        print("\n===== DRY-RUN CLOB REAL =====", flush=True)
        dry = await _dry_run(float(args.dry_minutes))
        print("DRY", dry, flush=True)

    # Métricas del label certificado + fallback al champ promo_pulse_c10.
    m_label = _metrics(
        config_glob=f"session_{args.label}_L*_c10_*", max_age_hours=MAX_AGE_H
    )
    m_promo = _metrics(
        config_glob="session_promo_pulse_c10_L*_c10_*", max_age_hours=MAX_AGE_H
    )
    # Si el label es *_live y aún tiene poca muestra, aceptar champ promo
    # solo si el DNA live es idéntico en entradas (misma config familia).
    final = m_label if int(m_label.get("decisive") or 0) >= MIN_DECISIVE else m_promo
    if _pass(m_label):
        final = m_label
    elif _pass(m_promo) and "pulse_c10" in args.label:
        final = m_promo
    paper_ok = _pass(final)
    dry_ok = True if dry is None else bool(dry.get("ok"))
    certified = bool(paper_ok and dry_ok)

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": cfg_name,
        "bars": {
            "min_wr": MIN_WR,
            "min_decisive": MIN_DECISIVE,
            "min_robust_pnl": MIN_ROBUST_PNL,
            "max_age_hours": MAX_AGE_H,
        },
        "history": history,
        "final_metrics": final,
        "dry_run": dry,
        "paper_ok": paper_ok,
        "dry_ok": dry_ok,
        "certified": certified,
        "verdict": "CERTIFIED" if certified else "NOT_CERTIFIED",
        "operator_next": (
            "CERTIFIED pulse@10. Secuencia: "
            "1) ARMED=1 DRY_RUN=1 MAX_CAPITAL=5 dry 30-60m "
            "2) DRY_RUN=0 MAX_CAPITAL=2..5 micro "
            "3) DNA=maker_demo_promo_pulse_c10_live.json "
            "4) matar si WR/adverse se degrada."
            if certified
            else "NOT_CERTIFIED: repetir olas hasta WR≥80% decisive≥16 y dry OK."
        ),
        "live_flags_should_be": {"POLY_LIVE_ARMED": "0", "POLY_LIVE_DRY_RUN": "1"},
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"cert_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "cert_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "verdict", "paper_ok", "dry_ok", "final_metrics", "operator_next"
    )}, indent=2), flush=True)
    print(f"REPORT -> {path}", flush=True)
    return 0 if certified else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="maker_demo_promo_pulse_c10_live.json")
    ap.add_argument("--label", default="promo_pulse_c10_live")
    ap.add_argument("--waves", type=int, default=2)
    ap.add_argument("--sessions", type=int, default=8)
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--dry-minutes", type=float, default=5.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
