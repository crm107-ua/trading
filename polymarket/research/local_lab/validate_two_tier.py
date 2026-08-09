#!/usr/bin/env python3
"""Validate two-tier ladder edge on cached resolved cases."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case, _score

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "weather_research"


def _run(cases, filt: TrialFilters):
    rows = [r for r in (_eval_case(c, filt) for c in cases) if r]
    taken = [r for r in rows if r.get("taken")]
    ordered = sorted(taken, key=lambda t: t["day"])
    cut = max(2, len(ordered) // 2) if ordered else 0
    test = ordered[cut:]
    return {
        "metrics": _score(rows),
        "taken": ordered,
        "oos_half": {
            "n": len(test),
            "wins": sum(1 for t in test if t["win"]),
            "winrate": round(sum(1 for t in test if t["win"]) / len(test), 4) if test else None,
            "pnl": round(sum(float(t["pnl"]) for t in test), 4) if test else 0.0,
        },
    }


def main() -> int:
    cases = [c for c in json.loads(CASES.read_text(encoding="utf-8")) if c["city"] in ("singapore", "shanghai")]
    core = TrialFilters(0.50, 0.39, 0.45, 0.01, True, 3, 12.0, 0.0)
    volume = TrialFilters(0.65, 0.45, 0.40, 0.01, False, 3, 12.0, 0.5)

    # Two-tier: take core first else volume
    union_slugs = set()
    union_rows = []
    for c in sorted(cases, key=lambda x: x["day"]):
        r1 = _eval_case(c, core)
        if r1 and r1.get("taken"):
            r1 = {**r1, "tier": "core_under"}
            union_rows.append(r1)
            union_slugs.add(c["slug"])
            continue
        r2 = _eval_case(c, volume)
        if r2 and r2.get("taken"):
            r2 = {**r2, "tier": "volume_bias"}
            union_rows.append(r2)
            union_slugs.add(c["slug"])

    cut = max(2, len(union_rows) // 2) if union_rows else 0
    test = union_rows[cut:]
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "n_universe": len(cases),
        "core": _run(cases, core),
        "volume": _run(cases, volume),
        "two_tier": {
            "n_taken": len(union_rows),
            "wins": sum(1 for t in union_rows if t["win"]),
            "winrate": round(sum(1 for t in union_rows if t["win"]) / len(union_rows), 4) if union_rows else None,
            "total_pnl": round(sum(float(t["pnl"]) for t in union_rows), 4),
            "by_tier": {
                "core_under": sum(1 for t in union_rows if t.get("tier") == "core_under"),
                "volume_bias": sum(1 for t in union_rows if t.get("tier") == "volume_bias"),
            },
            "oos_half": {
                "n": len(test),
                "wins": sum(1 for t in test if t["win"]),
                "winrate": round(sum(1 for t in test if t["win"]) / len(test), 4) if test else None,
                "pnl": round(sum(float(t["pnl"]) for t in test), 4) if test else 0.0,
            },
            "trades": union_rows,
        },
    }
    m = report["two_tier"]
    report["verdict"] = (
        "STRONG"
        if m["n_taken"] >= 6 and (m["winrate"] or 0) >= 0.75 and m["total_pnl"] > 100
        and (m["oos_half"]["n"] >= 3 and (m["oos_half"]["winrate"] or 0) >= 0.7)
        else "PROMISING"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "two_tier_validation.json"
    # trim huge nested for console
    slim = {k: report[k] for k in report if k != "two_tier"}
    slim["two_tier"] = {k: v for k, v in report["two_tier"].items() if k != "trades"}
    slim["core_metrics"] = report["core"]["metrics"]
    slim["volume_metrics"] = report["volume"]["metrics"]
    slim["core_oos"] = report["core"]["oos_half"]
    slim["volume_oos"] = report["volume"]["oos_half"]
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(slim, indent=2))
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
