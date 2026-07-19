#!/usr/bin/env python3
"""Certificación PRO desk pulse@10 — barra ultra + paralelo + dry multi + EV.

Emite PRO_CERTIFIED / NOT_PRO_CERTIFIED y el playbook de primera inversión.

    python3 -m polymarket.research.local_lab.certify_pro_desk \
      --waves 1 --sessions 6 --lines 4 --dry-lines 2 --dry-minutes 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.desk_risk import (
    CAPITAL_LADDER_USDC,
    build_risk_budget,
    forecast_pnl,
    ladder_stage,
    metrics_from_robust,
)
from polymarket.research.local_lab.go_live_gate import _robust_from_sessions
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "certify_pro_desk"

# Barras ultra (más duras que certify_pulse_c10)
MIN_WR = 0.80
MIN_DECISIVE = 20
MIN_ROBUST_PNL = 0.75
MAX_AGE_H = 3.0
MIN_PARALLEL_WR = 0.75
MIN_PARALLEL_DECISIVE = 12


async def _run(args: list[str]) -> int:
    print(f"\n>> {' '.join(args)}", flush=True)
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-m", *args, cwd=str(POLY.parent)
    )
    return int(await p.wait())


def _pass_paper(m: dict) -> bool:
    return bool(
        float(m.get("wr") or 0) >= MIN_WR
        and int(m.get("decisive") or 0) >= MIN_DECISIVE
        and float(m.get("total_robust") or 0) >= MIN_ROBUST_PNL
    )


def _pass_parallel(m: dict) -> bool:
    return bool(
        float(m.get("wr") or 0) >= MIN_PARALLEL_WR
        and int(m.get("decisive") or 0) >= MIN_PARALLEL_DECISIVE
    )


def _first_investment_block(*, forecast: dict, certified: bool) -> dict:
    return {
        "ready": certified,
        "dna": "maker_demo_promo_pulse_c10_micro_live.json",
        "strategy": "maker_fusion",
        "ladder_usdc": list(CAPITAL_LADDER_USDC),
        "steps": [
            {
                "n": 1,
                "title": "Preflight SAFE",
                "cmd": (
                    "export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1 "
                    "POLY_LIVE_MAX_CAPITAL_USDC=1.5 && "
                    "python3 -m polymarket.research.local_lab.go_live_arm_check "
                    "--pulse-only"
                ),
            },
            {
                "n": 2,
                "title": "Dry operativo 30–60 min (1 línea)",
                "cmd": (
                    "export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=1 "
                    "POLY_LIVE_MAX_CAPITAL_USDC=5 POLY_LIVE_DRY_SMOKE_POST=0 && "
                    "python3 -m polymarket.research.local_lab.live_maker "
                    "--config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json "
                    "--strategy maker_fusion --minutes 45"
                ),
            },
            {
                "n": 3,
                "title": "Dry paralelo 2 líneas (opcional, stagger)",
                "cmd": (
                    "python3 -m polymarket.research.local_lab.run_live_dry_parallel "
                    "--lines 2 --minutes 15 --stagger-s 45 "
                    "--config maker_demo_promo_pulse_c10_micro_live.json"
                ),
            },
            {
                "n": 4,
                "title": "Primera inversión MICRO real (1.5 USDC)",
                "cmd": (
                    "export POLY_LIVE_ARMED=1 POLY_LIVE_DRY_RUN=0 "
                    "POLY_LIVE_MAX_CAPITAL_USDC=1.5 && "
                    "python3 -m polymarket.research.local_lab.live_maker "
                    "--config polymarket/config/maker_demo_promo_pulse_c10_micro_live.json "
                    "--strategy maker_fusion --minutes 30"
                ),
                "kill_if": [
                    "FLATTEN_WRONG_TOKEN",
                    "DUST_STUCK",
                    "inventory residual > 0 al final",
                    "WR vivo < 60% en ≥6 trades",
                    "pérdida sesión > session_kill",
                ],
            },
            {
                "n": 5,
                "title": "Volver a SAFE",
                "cmd": "export POLY_LIVE_ARMED=0 POLY_LIVE_DRY_RUN=1",
            },
            {
                "n": 6,
                "title": "Escalar ladder 1.5→2→3→5 (nunca 10 de golpe)",
                "cmd": "Subir MAX_CAPITAL solo tras ≥3 sesiones live limpias.",
            },
        ],
        "forecast": forecast,
        "notes": [
            "Solo pulse@10. NO armar @5 ni Shadow.",
            "Paralelismo correlacionado (rho≈0.85): usa EV corr-adjusted, no N×.",
            "Paper ≠ live. Previsión orientativa, no garantía.",
        ],
    }


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"

    history: list[dict] = []
    for wave in range(1, int(args.waves) + 1):
        print(f"\n===== PRO CERT WAVE {wave}/{args.waves} =====", flush=True)
        code = await _run(
            [
                "polymarket.research.local_lab.pro_parallel_pulse",
                "--label",
                args.label,
                "--strategy",
                "maker_fusion",
                "--config",
                args.config,
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
                "--stagger-s",
                str(args.stagger_s),
            ]
        )
        m_par = _robust_from_sessions(
            f"session_{args.label}_L*_c10_*",
            outlier_cap=0.35,
            max_age_hours=MAX_AGE_H,
        )
        m_promo = _robust_from_sessions(
            "session_promo_pulse_c10*",
            outlier_cap=0.35,
            max_age_hours=MAX_AGE_H,
        )
        best = m_par if (m_par.get("decisive") or 0) >= (m_promo.get("decisive") or 0) else m_promo
        if float(m_promo.get("wr") or 0) > float(best.get("wr") or 0) and int(
            m_promo.get("decisive") or 0
        ) >= MIN_DECISIVE:
            best = m_promo
        row = {
            "wave": wave,
            "pro_parallel_exit": code,
            "parallel": m_par,
            "promo": m_promo,
            "best": best,
            "paper_pass": _pass_paper(best),
            "parallel_pass": _pass_parallel(m_par),
        }
        history.append(row)
        print(
            f"WAVE {wave} paper={row['paper_pass']} parallel={row['parallel_pass']} "
            f"best={best}",
            flush=True,
        )

    dry = None
    if int(args.dry_lines) > 0 and float(args.dry_minutes) > 0:
        print("\n===== DRY PARALLEL CLOB REAL =====", flush=True)
        dry_code = await _run(
            [
                "polymarket.research.local_lab.run_live_dry_parallel",
                "--config",
                args.live_config,
                "--strategy",
                "maker_fusion",
                "--lines",
                str(args.dry_lines),
                "--minutes",
                str(args.dry_minutes),
                "--stagger-s",
                str(min(float(args.stagger_s), 30.0)),
            ]
        )
        dry_path = (
            POLY
            / "data_local"
            / "local_lab"
            / "live_dry_parallel"
            / "dry_parallel_latest.json"
        )
        dry = json.loads(dry_path.read_text(encoding="utf-8")) if dry_path.is_file() else {
            "verdict": "MISSING",
            "exit": dry_code,
        }
        dry["exit_code"] = dry_code

    m_label = _robust_from_sessions(
        f"session_{args.label}_L*_c10_*", outlier_cap=0.35, max_age_hours=MAX_AGE_H
    )
    m_promo = _robust_from_sessions(
        "session_promo_pulse_c10*", outlier_cap=0.35, max_age_hours=MAX_AGE_H
    )
    final = m_label if _pass_paper(m_label) else (
        m_promo if _pass_paper(m_promo) else m_label
    )
    paper_ok = _pass_paper(final)
    parallel_ok = _pass_parallel(m_label) or _pass_parallel(m_promo)
    dry_ok = True if dry is None else dry.get("verdict") == "DRY_PARALLEL_OK"
    parity_ok = True if dry is None else bool(dry.get("parity_ok", True))
    certified = bool(paper_ok and parallel_ok and dry_ok and parity_ok)

    prox = metrics_from_robust(final)
    # Micro scale: size 5 @1.5 vs paper size 3 @10 → ~1.0 notional floor live
    fc_1h = forecast_pnl(
        hours=1.0,
        lines=1,
        wr=float(prox["wr"] or 0.83),
        avg_win=float(prox["avg_win_usdc"]),
        avg_loss=float(prox["avg_loss_usdc"]),
        capital_scale=1.0,
    )
    fc_1h_2L = forecast_pnl(
        hours=1.0,
        lines=2,
        wr=float(prox["wr"] or 0.83),
        avg_win=float(prox["avg_win_usdc"]),
        avg_loss=float(prox["avg_loss_usdc"]),
        capital_scale=1.0,
        rho=0.85,
    )
    fc_day = forecast_pnl(
        hours=8.0,
        lines=1,
        wr=float(prox["wr"] or 0.83),
        avg_win=float(prox["avg_win_usdc"]),
        avg_loss=float(prox["avg_loss_usdc"]),
        capital_scale=1.0,
    )
    budget = build_risk_budget(lines=2, capital_per_line=1.5, stagger_s=45.0)
    playbook = _first_investment_block(
        forecast={
            "1h_1line": fc_1h,
            "1h_2lines_corr": fc_1h_2L,
            "8h_1line": fc_day,
            "ladder": ladder_stage(1.5),
            "risk_budget": budget.to_dict(),
        },
        certified=certified,
    )

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "config": args.config,
        "live_config": args.live_config,
        "bars": {
            "min_wr": MIN_WR,
            "min_decisive": MIN_DECISIVE,
            "min_robust_pnl": MIN_ROBUST_PNL,
            "min_parallel_wr": MIN_PARALLEL_WR,
            "min_parallel_decisive": MIN_PARALLEL_DECISIVE,
            "max_age_hours": MAX_AGE_H,
        },
        "history": history,
        "final_metrics": final,
        "parallel_metrics": m_label,
        "dry_parallel": dry,
        "paper_ok": paper_ok,
        "parallel_ok": parallel_ok,
        "dry_ok": dry_ok,
        "parity_ok": parity_ok,
        "certified": certified,
        "verdict": "PRO_CERTIFIED" if certified else "NOT_PRO_CERTIFIED",
        "first_investment": playbook,
        "live_flags_should_be": {"POLY_LIVE_ARMED": "0", "POLY_LIVE_DRY_RUN": "1"},
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"pro_cert_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "pro_cert_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "verdict": report["verdict"],
                "paper_ok": paper_ok,
                "parallel_ok": parallel_ok,
                "dry_ok": dry_ok,
                "parity_ok": parity_ok,
                "final_metrics": final,
                "forecast_1h_1L": fc_1h,
                "forecast_1h_2L_corr": fc_1h_2L,
            },
            indent=2,
        ),
        flush=True,
    )
    print(f"REPORT -> {path}", flush=True)
    return 0 if certified else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="maker_demo_promo_pulse_c10.json")
    ap.add_argument(
        "--live-config", default="maker_demo_promo_pulse_c10_micro_live.json"
    )
    ap.add_argument("--label", default="pro_pulse_c10")
    ap.add_argument("--waves", type=int, default=1)
    ap.add_argument("--sessions", type=int, default=6)
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--stagger-s", type=float, default=45.0)
    ap.add_argument("--dry-lines", type=int, default=2)
    ap.add_argument("--dry-minutes", type=float, default=5.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
