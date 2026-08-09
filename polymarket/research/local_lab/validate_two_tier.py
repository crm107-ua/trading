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

CITIES = ("singapore", "shanghai", "hong-kong")
PRESS = TrialFilters(0.50, 0.39, 0.35, 0.01, True, 3, 12.0, 0.5)
SELECT = TrialFilters(0.50, 0.39, 0.35, 0.01, False, 3, 12.0, 0.5)


def _run(cases, filt: TrialFilters):
    rows = [r for r in (_eval_case(c, filt) for c in cases) if r]
    taken = sorted([r for r in rows if r.get("taken")], key=lambda t: t["day"])
    cut = max(2, len(taken) // 2) if taken else 0
    test = taken[cut:]
    return {
        "metrics": _score(rows),
        "taken": taken,
        "oos_half": {
            "n": len(test),
            "wins": sum(1 for t in test if t["win"]),
            "winrate": round(sum(1 for t in test if t["win"]) / len(test), 4) if test else None,
            "pnl": round(sum(float(t["pnl"]) for t in test), 4) if test else 0.0,
        },
    }


def main() -> int:
    cases = [c for c in json.loads(CASES.read_text(encoding="utf-8")) if c["city"] in CITIES]
    union_rows = []
    for c in sorted(cases, key=lambda x: x["day"]):
        r1 = _eval_case(c, PRESS)
        if r1 and r1.get("taken"):
            union_rows.append({**r1, "tier": "press_under"})
            continue
        r2 = _eval_case(c, SELECT)
        if r2 and r2.get("taken"):
            union_rows.append({**r2, "tier": "select"})

    cut = max(2, len(union_rows) // 2) if union_rows else 0
    test = union_rows[cut:]
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "n_universe": len(cases),
        "cities": list(CITIES),
        "press_under": _run(cases, PRESS),
        "select": _run(cases, SELECT),
        "two_tier": {
            "n_taken": len(union_rows),
            "wins": sum(1 for t in union_rows if t["win"]),
            "winrate": round(sum(1 for t in union_rows if t["win"]) / len(union_rows), 4)
            if union_rows
            else None,
            "total_pnl": round(sum(float(t["pnl"]) for t in union_rows), 4),
            "by_tier": {
                "press_under": sum(1 for t in union_rows if t.get("tier") == "press_under"),
                "select": sum(1 for t in union_rows if t.get("tier") == "select"),
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
        if m["n_taken"] >= 5
        and (m["winrate"] or 0) >= 0.80
        and m["total_pnl"] > 100
        and (m["oos_half"]["n"] >= 2 and (m["oos_half"]["winrate"] or 0) >= 0.7)
        else "PROMISING"
        if m["n_taken"] >= 3 and (m["winrate"] or 0) >= 0.6 and m["total_pnl"] > 0
        else "WEAK"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "two_tier_validation.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    slim = {
        "verdict": report["verdict"],
        "n_universe": report["n_universe"],
        "cities": report["cities"],
        "two_tier": {k: v for k, v in report["two_tier"].items() if k != "trades"},
        "press_metrics": report["press_under"]["metrics"],
        "select_metrics": report["select"]["metrics"],
        "press_oos": report["press_under"]["oos_half"],
        "select_oos": report["select"]["oos_half"],
    }
    print(json.dumps(slim, indent=2))
    print("wrote", path, file=__import__("sys").stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
