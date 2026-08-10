#!/usr/bin/env python3
"""Validate multi-sleeve ladder edge on cached resolved cases."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case, _score, city_breakdown

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "weather_research"

CORE_CITIES = ("singapore", "shanghai", "hong-kong")
CORE_PRESS = TrialFilters(0.50, 0.39, 0.35, 0.01, True, 3, 12.0, 0.5)
CORE_SELECT = TrialFilters(0.50, 0.39, 0.35, 0.01, False, 3, 12.0, 0.5)
BJ_PRESS = TrialFilters(0.55, 0.39, 0.35, 0.01, True, 3, 12.0, 1.0)
BJ_SELECT = TrialFilters(0.55, 0.39, 0.35, 0.01, False, 3, 12.0, 1.0)


def _oos(taken: list[dict]) -> dict:
    ordered = sorted(taken, key=lambda t: t["day"])
    cut = max(2, len(ordered) // 2) if ordered else 0
    test = ordered[cut:]
    return {
        "n": len(test),
        "wins": sum(1 for t in test if t["win"]),
        "winrate": round(sum(1 for t in test if t["win"]) / len(test), 4) if test else None,
        "pnl": round(sum(float(t["pnl"]) for t in test), 4) if test else 0.0,
    }


def main() -> int:
    all_cases = json.loads(CASES.read_text(encoding="utf-8"))
    union: list[dict] = []
    for c in sorted(all_cases, key=lambda x: x["day"]):
        city = c["city"]
        if city in CORE_CITIES:
            for name, filt in (("press_under", CORE_PRESS), ("select", CORE_SELECT)):
                r = _eval_case(c, filt)
                if r and r.get("taken"):
                    union.append({**r, "sleeve": "core", "tier": name})
                    break
        elif city == "beijing":
            for name, filt in (("press_under", BJ_PRESS), ("select", BJ_SELECT)):
                r = _eval_case(c, filt)
                if r and r.get("taken"):
                    union.append({**r, "sleeve": "beijing", "tier": name})
                    break

    core = [t for t in union if t["sleeve"] == "core"]
    bj = [t for t in union if t["sleeve"] == "beijing"]
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(all_cases),
        "multi_sleeve": {
            "n_taken": len(union),
            "wins": sum(1 for t in union if t["win"]),
            "winrate": round(sum(1 for t in union if t["win"]) / len(union), 4) if union else None,
            "total_pnl": round(sum(float(t["pnl"]) for t in union), 4),
            "by_sleeve": {"core": len(core), "beijing": len(bj)},
            "by_city": city_breakdown(union),
            "oos_half": _oos(union),
            "trades": union,
        },
        "core_only": {
            "n_taken": len(core),
            "winrate": round(sum(1 for t in core if t["win"]) / len(core), 4) if core else None,
            "total_pnl": round(sum(float(t["pnl"]) for t in core), 4),
            "oos_half": _oos(core),
        },
        "beijing_only": {
            "n_taken": len(bj),
            "winrate": round(sum(1 for t in bj if t["win"]) / len(bj), 4) if bj else None,
            "total_pnl": round(sum(float(t["pnl"]) for t in bj), 4),
            "oos_half": _oos(bj),
        },
    }
    m = report["multi_sleeve"]
    report["verdict"] = (
        "STRONG"
        if m["n_taken"] >= 10
        and (m["winrate"] or 0) >= 0.85
        and m["total_pnl"] > 300
        and (m["oos_half"]["n"] >= 5 and (m["oos_half"]["winrate"] or 0) >= 0.8)
        else "PROMISING"
        if m["n_taken"] >= 5 and (m["winrate"] or 0) >= 0.7 and m["total_pnl"] > 0
        else "WEAK"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "two_tier_validation.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    slim = {k: report[k] for k in report if k != "multi_sleeve"}
    slim["multi_sleeve"] = {k: v for k, v in report["multi_sleeve"].items() if k != "trades"}
    print(json.dumps(slim, indent=2))
    print("wrote", path, file=__import__("sys").stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
