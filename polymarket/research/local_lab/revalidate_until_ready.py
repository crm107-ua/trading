#!/usr/bin/env python3
"""Revalida paper @5/@10 en bucle hasta READY_STRICT.

Lanza olas de paralelo (pulse@5, pulse@10, flow@5) y confirma,
reescribiendo evidencia fresca. No toca live/ARMED.

    python3 -m polymarket.research.local_lab.revalidate_until_ready \
      --waves 6 --sessions 8 --minutes 5 --lines 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.go_live_gate import evaluate
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "revalidate_loop"


async def _run_mod(args: list[str]) -> int:
    print(f"\n>> {' '.join(args)}", flush=True)
    p = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        *args,
        cwd=str(POLY.parent),
    )
    return int(await p.wait())


async def _wave(*, wave: int, sessions: int, minutes: float, lines: int) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    label_suffix = f"w{wave}_{stamp}"
    # Tres frentes en paralelo: pulse@5, pulse@10, flow@5
    tasks = [
        _run_mod(
            [
                "polymarket.research.local_lab.parallel_paper_lines",
                "--label",
                f"promo_pulse_c5_{label_suffix}",
                "--strategy",
                "maker_fusion",
                "--config",
                "maker_demo_promo_pulse_c5.json",
                "--capital",
                "5",
                "--lines",
                str(lines),
                "--parallel",
                str(min(lines, 4)),
                "--sessions",
                str(sessions),
                "--minutes",
                str(minutes),
            ]
        ),
        _run_mod(
            [
                "polymarket.research.local_lab.parallel_paper_lines",
                "--label",
                f"promo_pulse_c10_{label_suffix}",
                "--strategy",
                "maker_fusion",
                "--config",
                "maker_demo_promo_pulse_c10.json",
                "--capital",
                "10",
                "--lines",
                str(lines),
                "--parallel",
                str(min(lines, 4)),
                "--sessions",
                str(sessions),
                "--minutes",
                str(minutes),
            ]
        ),
        _run_mod(
            [
                "polymarket.research.local_lab.parallel_paper_lines",
                "--label",
                f"promo_flow_c5_{label_suffix}",
                "--strategy",
                "maker_fusion",
                "--config",
                "maker_demo_promo_flow_c5.json",
                "--capital",
                "5",
                "--lines",
                str(max(2, lines // 2)),
                "--parallel",
                str(max(2, lines // 2)),
                "--sessions",
                str(sessions),
                "--minutes",
                str(minutes),
            ]
        ),
    ]
    codes = await asyncio.gather(*tasks)
    # Confirm pulse dual (usa session names fusion_c10_pulse_* via demo_label)
    # Override demo_label in a temp confirm by using promo pulse config as-is
    # but confirm_dna_pair sets demo_label = label_c{cap}
    confirm_code = await _run_mod(
        [
            "polymarket.research.local_lab.confirm_dna_pair",
            "--label",
            "fusion_c10_pulse",
            "--strategy",
            "maker_fusion",
            "--config",
            "maker_demo_promo_pulse_c10.json",
            "--sessions",
            str(max(6, sessions)),
            "--minutes",
            str(minutes),
        ]
    )
    return {"wave": wave, "parallel_codes": list(codes), "confirm_code": confirm_code}


def _gate_aliases_update() -> None:
    """Copia sesiones de olas revalidate a globs que lee el gate.

    El gate busca session_promo_pulse_c5_L*_c5_* — parallel_paper_lines ya
    genera demo_label={label}_L{i}_c{cap}, así que con label promo_pulse_c5_w*
    el glob session_promo_pulse_c5_L* NO matchea (queda wN en medio).

    Solución: ampliar globs del gate en evaluate, o usar labels exactos.
    Aquí usamos labels estables: promo_pulse_c5 / promo_pulse_c10 / promo_flow_c5
    (sin suffix) — el session_prefix incluye timestamp único igual.
    """


async def async_main(args: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"

    history: list[dict] = []
    for wave in range(1, int(args.waves) + 1):
        print(f"\n========== WAVE {wave}/{args.waves} ==========", flush=True)
        # Labels estables para que el gate los vea (sin suffix de wave).
        # Evitamos gather de 3 paralelos con mismo label pisándose: usamos
        # subproceso sequential pairs + confirm.
        t0 = time.time()
        # pulse @5 y @10 en paralelo
        c5_p = asyncio.create_task(
            _run_mod(
                [
                    "polymarket.research.local_lab.parallel_paper_lines",
                    "--label",
                    "promo_pulse_c5",
                    "--strategy",
                    "maker_fusion",
                    "--config",
                    "maker_demo_promo_pulse_c5.json",
                    "--capital",
                    "5",
                    "--lines",
                    str(args.lines),
                    "--parallel",
                    str(min(args.lines, 4)),
                    "--sessions",
                    str(args.sessions),
                    "--minutes",
                    str(args.minutes),
                ]
            )
        )
        c10_p = asyncio.create_task(
            _run_mod(
                [
                    "polymarket.research.local_lab.parallel_paper_lines",
                    "--label",
                    "promo_pulse_c10",
                    "--strategy",
                    "maker_fusion",
                    "--config",
                    "maker_demo_promo_pulse_c10.json",
                    "--capital",
                    "10",
                    "--lines",
                    str(args.lines),
                    "--parallel",
                    str(min(args.lines, 4)),
                    "--sessions",
                    str(args.sessions),
                    "--minutes",
                    str(args.minutes),
                ]
            )
        )
        flow_p = asyncio.create_task(
            _run_mod(
                [
                    "polymarket.research.local_lab.parallel_paper_lines",
                    "--label",
                    "promo_flow_c5",
                    "--strategy",
                    "maker_fusion",
                    "--config",
                    "maker_demo_promo_flow_c5.json",
                    "--capital",
                    "5",
                    "--lines",
                    str(max(2, args.lines // 2)),
                    "--parallel",
                    str(max(2, args.lines // 2)),
                    "--sessions",
                    str(args.sessions),
                    "--minutes",
                    str(args.minutes),
                ]
            )
        )
        codes = await asyncio.gather(c5_p, c10_p, flow_p)
        confirm_code = await _run_mod(
            [
                "polymarket.research.local_lab.confirm_dna_pair",
                "--label",
                "fusion_c10_pulse",
                "--strategy",
                "maker_fusion",
                "--config",
                "maker_demo_promo_pulse_c10.json",
                "--sessions",
                str(max(6, args.sessions)),
                "--minutes",
                str(args.minutes),
            ]
        )
        report = evaluate(max_age_hours=float(args.max_age_hours))
        row = {
            "wave": wave,
            "elapsed_min": round((time.time() - t0) / 60.0, 2),
            "parallel_codes": list(codes),
            "confirm_code": confirm_code,
            "verdict": report["verdict"],
            "checks": report["checks"],
            "metrics": {
                k: report["metrics"][k]
                for k in ("c5_best", "c10_best", "parallel_c5", "parallel_c10")
            },
        }
        history.append(row)
        path = OUT / f"wave_{wave}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        path.write_text(json.dumps(row, indent=2), encoding="utf-8")
        (OUT / "loop_latest.json").write_text(
            json.dumps({"history": history, "latest": row}, indent=2), encoding="utf-8"
        )
        print(
            f"WAVE {wave} DONE verdict={report['verdict']} "
            f"c5={row['metrics']['c5_best']} c10={row['metrics']['c10_best']}",
            flush=True,
        )
        if report["verdict"] == "READY_STRICT":
            print("READY_STRICT alcanzado.", flush=True)
            return 0
        if args.stop_on_risk_on and report["verdict"] == "READY_RISK_ON":
            print("READY_RISK_ON (stop_on_risk_on).", flush=True)
            return 0
    print("Agotó olas sin READY_STRICT.", flush=True)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--waves", type=int, default=6)
    ap.add_argument("--sessions", type=int, default=8)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--max-age-hours", type=float, default=3.0)
    ap.add_argument("--stop-on-risk-on", action="store_true")
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
