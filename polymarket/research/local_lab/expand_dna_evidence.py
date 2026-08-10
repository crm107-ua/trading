#!/usr/bin/env python3
"""
Expand DNA evidence WITHOUT relaxing gates.

1) Fetch older resolved weather cases (lookback up to ~120d)
2) Re-score with the same CORE_PRESS / BJ_PRESS DNA (0.50 / 0.39 / UD)
3) Refresh EVIDENCE_PROGRESS + write DNA_EXPANSION_REPORT.json

Does NOT place orders. Safe alongside WATCH_ONLY processes.

  PYTHONPATH=. python3 -m polymarket.research.local_lab.expand_dna_evidence
  PYTHONPATH=. python3 -m polymarket.research.local_lab.expand_dna_evidence --max-events 200
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.optimize_weather_ladder import _load_resolved_cases
from polymarket.research.local_lab.research_telemetry import write_evidence_progress

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "vps_runs"
DNA_CITIES = ["hong-kong", "beijing", "singapore", "shanghai"]


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _score_takes(takes: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for t in takes if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(takes)
    return {
        "n": n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
        "by_city": dict(Counter(t.get("city") for t in takes)),
        "day_min": min((t.get("day") for t in takes), default=None),
        "day_max": max((t.get("day") for t in takes), default=None),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-events", type=int, default=220)
    ap.add_argument("--max-age-days", type=int, default=110)
    ap.add_argument("--skip-fetch", action="store_true", help="Only re-score existing cases.json")
    args = ap.parse_args()

    before_cases = 0
    if CASES.exists():
        before_cases = len(json.loads(CASES.read_text(encoding="utf-8")))
    before_takes = take_income_wr80(json.loads(CASES.read_text(encoding="utf-8"))) if CASES.exists() else []
    before = _score_takes(before_takes)

    if not args.skip_fetch:
        print(
            f"fetching resolved cases cities={DNA_CITIES} max_events={args.max_events} "
            f"max_age_days={args.max_age_days} resume={CASES}",
            flush=True,
        )
        cases = _load_resolved_cases(
            DNA_CITIES,
            max_events=int(args.max_events),
            max_age_days=int(args.max_age_days),
            resume_path=CASES,
            priority_cities=["hong-kong", "beijing", "singapore", "shanghai"],
        )
        CASES.parent.mkdir(parents=True, exist_ok=True)
        CASES.write_text(json.dumps(cases, indent=2), encoding="utf-8")
        print(f"cases_written={len(cases)} path={CASES}", flush=True)
    else:
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        print(f"skip_fetch cases={len(cases)}", flush=True)

    after_takes = take_income_wr80(cases)
    after = _score_takes(after_takes)
    ev = write_evidence_progress()

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "dna_gates": {"max_basket": 0.50, "max_leg": 0.39, "underdispersion": True},
        "cases_before": before_cases,
        "cases_after": len(cases),
        "cases_added": max(0, len(cases) - before_cases),
        "takes_before": before,
        "takes_after": after,
        "delta_n": after["n"] - before["n"],
        "evidence": ev,
        "note_es": (
            "Expansión histórica bajo la MISMA DNA. Si n sube con pérdidas, Wilson puede bajar: "
            "eso es honestidad, no fallo. Forward WATCH sigue siendo la vía OOS real."
        ),
        "next_es": [
            "Mantener WATCH_ONLY x3 hasta ver dna_hits forward",
            "No depositar hasta n>=50 y Wilson>=0.80 + capital aguanta 1 miss",
            "Si delta_n~0: mercado pre-julio ya digesto o sin entry quotes",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "DNA_EXPANSION_REPORT.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "DNA_EXPANSION_REPORT.md").write_text(
        "\n".join(
            [
                "# DNA evidence expansion",
                "",
                f"- cases {before_cases} → {len(cases)} (+{report['cases_added']})",
                f"- DNA takes {before['n']} → {after['n']} (Δ {report['delta_n']})",
                f"- WR {before['wr_point']} → {after['wr_point']} · Wilson {before['wilson95_lower']} → {after['wilson95_lower']}",
                f"- by_city {after['by_city']}",
                f"- DNA gates unchanged: basket≤0.50 leg≤0.39 UD",
                "",
                report["note_es"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2), flush=True)
    print(f"report -> {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
