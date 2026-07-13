#!/usr/bin/env python3
"""
#16 Maker stale-quote simulator — stub.

Frozen: polymarket/docs/PREREG_16_POLY_MAKER_STALE.md

Implement after phase A (>=30d WS depth panel). Screen rejects synthetic.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUTPUT_BASE = Path(__file__).resolve().parents[2] / "research" / "output" / "poly_16"
PREREG = "polymarket/docs/PREREG_16_POLY_MAKER_STALE.md"


def run_screen(run_id: str, replay_dir: Path | None = None) -> dict:
    if replay_dir is None or not (replay_dir / "book_snapshots.json").exists():
        report = {
            "hypothesis": 16,
            "run_id": run_id,
            "prereg": PREREG,
            "verdict": "SCREEN_INVALIDO",
            "verdict_binding": False,
            "hypothesis_judged": False,
            "reason": "Fase A incompleta: requiere >=30d depth WS + paper maker 14d",
            "phase_required": "A",
        }
    else:
        report = {
            "hypothesis": 16,
            "run_id": run_id,
            "prereg": PREREG,
            "verdict": "NOT_IMPLEMENTED",
            "reason": "sim_maker_quote replay mapper pendiente",
        }
    out = OUTPUT_BASE / run_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--run-id", default="pending")
    p.add_argument("--replay-dir", type=Path, default=None)
    args = p.parse_args()
    r = run_screen(args.run_id, args.replay_dir)
    print(json.dumps(r, indent=2))
    if r.get("verdict") in ("SCREEN_INVALIDO", "NOT_IMPLEMENTED"):
        sys.exit(2)
