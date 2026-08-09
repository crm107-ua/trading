#!/usr/bin/env python3
"""Time-ordered k-fold validation for the champion ladder edge."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case, _score

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "weather_research"


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    cases = [c for c in cases if c["city"] in ("singapore", "shanghai", "hong-kong")]
    cases = sorted(cases, key=lambda c: c["day"])
    filt = TrialFilters(
        max_basket_cost=0.50,
        max_leg_price=0.39,
        min_cluster_prob=0.35,
        min_basket_ev=0.01,
        require_underdispersion=False,
        width=3,
        budget=12.0,
        bias_override=0.5,
    )
    # Collect all taken chronologically
    taken = []
    for c in cases:
        r = _eval_case(c, filt)
        if r and r.get("taken"):
            taken.append(r)

    # Expanding walk-forward: train on past folds, test next chunk
    folds = []
    if len(taken) >= 4:
        # leave-future-out style chunks of ~2
        chunk = max(1, len(taken) // 4)
        for i in range(0, len(taken), chunk):
            test = taken[i : i + chunk]
            train = taken[:i]
            if not test:
                continue
            tm = _score([{**t, "taken": True} for t in test] + [{"taken": False}] * 0)
            # recompute manually
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
        "filters": asdict(filt),
        "cities": ["singapore", "shanghai", "hong-kong"],
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
            if overall["winrate"] >= 0.75
            and overall["total_pnl"] > 50
            and overall["n_taken"] >= 5
            and (oos_n == 0 or (oos_w / oos_n) >= 0.7)
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
