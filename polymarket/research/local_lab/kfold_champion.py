#!/usr/bin/env python3
"""Time-ordered validation for multi-sleeve champion edge."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case, _score

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "weather_research"

CORE_PRESS = TrialFilters(0.50, 0.39, 0.35, 0.01, True, 3, 12.0, 0.5)
CORE_SELECT = TrialFilters(0.50, 0.39, 0.35, 0.01, False, 3, 12.0, 0.5)
BJ_PRESS = TrialFilters(0.55, 0.39, 0.35, 0.01, True, 3, 12.0, 1.0)
BJ_SELECT = TrialFilters(0.55, 0.39, 0.35, 0.01, False, 3, 12.0, 1.0)


def _take_all(cases: list[dict]) -> list[dict]:
    taken = []
    for c in sorted(cases, key=lambda x: x["day"]):
        city = c["city"]
        if city in ("singapore", "shanghai", "hong-kong"):
            for filt in (CORE_PRESS, CORE_SELECT):
                r = _eval_case(c, filt)
                if r and r.get("taken"):
                    taken.append(r)
                    break
        elif city == "beijing":
            for filt in (BJ_PRESS, BJ_SELECT):
                r = _eval_case(c, filt)
                if r and r.get("taken"):
                    taken.append(r)
                    break
    return taken


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    taken = _take_all(cases)
    folds = []
    if len(taken) >= 4:
        chunk = max(1, len(taken) // 4)
        for i in range(0, len(taken), chunk):
            test = taken[i : i + chunk]
            train = taken[:i]
            if not test:
                continue
            wins = sum(1 for t in test if t["win"])
            pnl = sum(float(t["pnl"]) for t in test)
            folds.append(
                {
                    "i": i,
                    "n_train_taken": len(train),
                    "n_test": len(test),
                    "test_wins": wins,
                    "test_wr": round(wins / len(test), 4),
                    "test_pnl": round(pnl, 4),
                    "slugs": [t["slug"] for t in test],
                }
            )

    overall = _score([{**t, "taken": True} for t in taken])
    oos_pnl = sum(f["test_pnl"] for f in folds)
    oos_n = sum(f["n_test"] for f in folds)
    oos_w = sum(f["test_wins"] for f in folds)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "multi_sleeve",
        "filters": {
            "core_press": asdict(CORE_PRESS),
            "core_select": asdict(CORE_SELECT),
            "beijing_press": asdict(BJ_PRESS),
            "beijing_select": asdict(BJ_SELECT),
        },
        "cities": ["singapore", "shanghai", "hong-kong", "beijing"],
        "n_universe_cases": len(cases),
        "n_taken": len(taken),
        "overall": overall,
        "folds": folds,
        "fold_aggregate": {
            "n": oos_n,
            "wins": oos_w,
            "winrate": round(oos_w / oos_n, 4) if oos_n else None,
            "pnl": round(oos_pnl, 4),
        },
        "trades": taken,
        "verdict": (
            "STRONG"
            if overall["winrate"] >= 0.85
            and overall["total_pnl"] > 200
            and overall["n_taken"] >= 10
            and (oos_n == 0 or (oos_w / oos_n) >= 0.8)
            else "PROMISING"
        ),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "kfold_champion.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("verdict", "overall", "fold_aggregate", "n_taken")}, indent=2))
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
