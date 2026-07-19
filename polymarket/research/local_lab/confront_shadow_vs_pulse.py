#!/usr/bin/env python3
"""Confronta Shadow OFIR vs Pulse champ @5 y @10 (paper feeds reales).

    python3 -m polymarket.research.local_lab.confront_shadow_vs_pulse \
      --sessions 8 --minutes 5 --lines 4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.go_live_gate import _robust_from_sessions, evaluate
from polymarket.src.ai.env_loader import load_repo_dotenv

load_repo_dotenv()

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "confront_shadow"


async def _run(args: list[str]) -> int:
    print(f"\n>> {' '.join(args)}", flush=True)
    p = await asyncio.create_subprocess_exec(
        sys.executable, "-m", *args, cwd=str(POLY.parent)
    )
    return int(await p.wait())


async def async_main(ns: argparse.Namespace) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    jobs = [
        (
            "promo_pulse_c5",
            "maker_demo_promo_pulse_c5.json",
            5,
        ),
        (
            "promo_shadow_c5",
            "maker_demo_promo_shadow_c5.json",
            5,
        ),
        (
            "promo_pulse_c10",
            "maker_demo_promo_pulse_c10.json",
            10,
        ),
        (
            "promo_shadow_c10",
            "maker_demo_promo_shadow_c10.json",
            10,
        ),
    ]
    codes = await asyncio.gather(
        *[
            _run(
                [
                    "polymarket.research.local_lab.parallel_paper_lines",
                    "--label",
                    label,
                    "--strategy",
                    "maker_fusion",
                    "--config",
                    cfg,
                    "--capital",
                    str(cap),
                    "--lines",
                    str(ns.lines),
                    "--parallel",
                    str(min(ns.lines, 4)),
                    "--sessions",
                    str(ns.sessions),
                    "--minutes",
                    str(ns.minutes),
                ]
            )
            for label, cfg, cap in jobs
        ]
    )
    kw = dict(outlier_cap=0.35, max_age_hours=float(ns.max_age_hours))
    rows = {
        "pulse_c5": _robust_from_sessions("session_promo_pulse_c5_L*_c5_*", **kw),
        "shadow_c5": _robust_from_sessions("session_promo_shadow_c5_L*_c5_*", **kw),
        "pulse_c10": _robust_from_sessions("session_promo_pulse_c10_L*_c10_*", **kw),
        "shadow_c10": _robust_from_sessions("session_promo_shadow_c10_L*_c10_*", **kw),
    }
    gate = evaluate(max_age_hours=float(ns.max_age_hours))

    def score(m: dict) -> tuple:
        return (
            int(bool(m.get("hit_wr75"))),
            int(bool(m.get("hit_parallel70"))),
            float(m.get("wr") or 0),
            int(m.get("decisive") or 0),
            float(m.get("total_robust") or 0),
        )

    best5 = "shadow_c5" if score(rows["shadow_c5"]) > score(rows["pulse_c5"]) else "pulse_c5"
    best10 = (
        "shadow_c10" if score(rows["shadow_c10"]) > score(rows["pulse_c10"]) else "pulse_c10"
    )
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_min": round((time.time() - t0) / 60.0, 2),
        "codes": list(codes),
        "rows": rows,
        "best_c5": best5,
        "best_c10": best10,
        "gate_verdict": gate["verdict"],
        "gate_checks": gate["checks"],
        "ready_for_real_money": gate["verdict"] == "READY_STRICT",
        "champion_dna": {
            "c5": "maker_demo_promo_pulse_c5.json"
            if best5 == "pulse_c5"
            else "maker_demo_promo_shadow_c5.json",
            "c10": "maker_demo_promo_pulse_c10.json"
            if best10 == "pulse_c10"
            else "maker_demo_promo_shadow_c10.json",
        },
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"confront_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "confront_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    print(f"REPORT -> {path}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=8)
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--max-age-hours", type=float, default=3.0)
    return asyncio.run(async_main(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
