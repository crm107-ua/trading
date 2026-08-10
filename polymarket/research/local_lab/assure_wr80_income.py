#!/usr/bin/env python3
"""
Iterate / score the income_wr80 ladder profile until point WR>=80% (and OOS>=80%).

Honest about statistics: Wilson/bootstrap lower bounds are reported; we do NOT
claim 95% CI > 80% unless the math supports it. Real-money assurance still
requires allowed-region live fills.

  python3 -m polymarket.research.local_lab.assure_wr80_income
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case
from polymarket.research.local_lab.ultra_real_ladder_campaign import (
    STRESS_SCENARIOS,
    _settle_with_friction,
    _equity_stats,
)

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
CFG = POLY / "config" / "weather_ladder_income_wr80.json"
OUT = POLY / "data_local" / "local_lab" / "wr80_assurance"

CORE = ("singapore", "shanghai", "hong-kong")
CORE_PRESS = TrialFilters(0.50, 0.39, 0.35, 0.01, True, 3, 12.0, 0.5)
BJ_PRESS = TrialFilters(0.50, 0.39, 0.35, 0.01, True, 3, 12.0, 1.0)  # 0.50 not 0.55


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _bootstrap_lower(wins_flags: list[bool], *, alpha: float = 0.05, reps: int = 8000) -> float:
    n = len(wins_flags)
    if n == 0:
        return 0.0
    rng = random.Random(42)
    boots = []
    for _ in range(reps):
        sample = [wins_flags[rng.randrange(n)] for _ in range(n)]
        boots.append(sum(sample) / n)
    boots.sort()
    return float(boots[int(alpha * len(boots))])


def take_income_wr80(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    taken: list[dict[str, Any]] = []
    for c in sorted(cases, key=lambda x: x["day"]):
        city = c["city"]
        if city in CORE:
            filt = CORE_PRESS
            sleeve = "core_press"
        elif city == "beijing":
            filt = BJ_PRESS
            sleeve = "beijing_press"
        else:
            continue
        r = _eval_case(c, filt)
        if r and r.get("taken"):
            taken.append({**r, "sleeve": sleeve, "tier": "press_under"})
    return taken


def friction_wr(taken: list[dict[str, Any]], scenario: dict[str, Any]) -> dict[str, Any]:
    settled = []
    for t in taken:
        s = _settle_with_friction(
            t,
            slip=float(scenario["entry_slip_cents"]),
            fee_bps=float(scenario["taker_fee_bps"]),
            fill_ratio=float(scenario["fill_ratio"]),
            min_leg_shares=5.0,
            min_leg_notional=1.0,
            max_basket_cost=0.50 + float(scenario["entry_slip_cents"]) * 3,
        )
        if s is not None:
            settled.append(s)
    stats = _equity_stats(settled, 150.0)
    return {"scenario": scenario["name"], **{k: stats[k] for k in stats if k != "equity_curve"}}


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    gate = dict(cfg.get("income_wr80_gate") or {})
    taken = take_income_wr80(cases)
    wins_flags = [bool(t.get("win")) for t in taken]
    n = len(taken)
    wins = sum(wins_flags)
    wr = wins / n if n else 0.0
    ordered = sorted(taken, key=lambda t: t["day"])
    cut = max(2, n // 2) if n else 0
    oos = ordered[cut:]
    oos_wins = sum(1 for t in oos if t.get("win"))
    oos_wr = oos_wins / len(oos) if oos else 0.0
    pnl = sum(float(t["pnl"]) for t in taken)
    wilson_l = _wilson_lower(wins, n)
    boot_l = _bootstrap_lower(wins_flags)

    # Compare legacy multi-sleeve (press+select, BJ 0.55) for honesty
    from polymarket.research.local_lab.validate_two_tier import (
        BJ_PRESS as BJ55,
        BJ_SELECT,
        CORE_PRESS as CP,
        CORE_SELECT,
    )

    legacy = []
    for c in sorted(cases, key=lambda x: x["day"]):
        if c["city"] in CORE:
            for f in (CP, CORE_SELECT):
                r = _eval_case(c, f)
                if r and r.get("taken"):
                    legacy.append(r)
                    break
        elif c["city"] == "beijing":
            for f in (BJ55, BJ_SELECT):
                r = _eval_case(c, f)
                if r and r.get("taken"):
                    legacy.append(r)
                    break
    leg_n = len(legacy)
    leg_w = sum(1 for t in legacy if t.get("win"))
    leg_wr = leg_w / leg_n if leg_n else 0.0

    stress = []
    base_sc = {"name": "base", "entry_slip_cents": 0.01, "taker_fee_bps": 0, "fill_ratio": 0.95}
    for sc in [base_sc] + [s for s in STRESS_SCENARIOS if s["name"] != "base"]:
        stress.append(friction_wr(taken, sc))

    min_stress_wr = min((s.get("winrate") or 0) for s in stress) if stress else 0.0

    checks = {
        "min_n": n >= int(gate.get("min_n", 8)),
        "point_wr_ge_80": wr + 1e-12 >= float(gate.get("min_point_winrate", 0.80)),
        "oos_half_wr_ge_80": oos_wr + 1e-12 >= float(gate.get("min_oos_half_winrate", 0.80)),
        "min_pnl": pnl >= float(gate.get("min_pnl_usdc", 100)),
        "stress_wr_ge_80": min_stress_wr + 1e-12 >= float(gate.get("min_stress_winrate", 0.80)),
        "beats_legacy_wr": wr + 1e-12 >= leg_wr,  # informational / should beat diluted select
    }
    # Statistical CI assurance (stricter) — optional badge
    ci_assured = wilson_l >= 0.80 and boot_l >= 0.80
    point_assured = all(checks[k] for k in ("min_n", "point_wr_ge_80", "oos_half_wr_ge_80", "min_pnl", "stress_wr_ge_80"))

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "profile": "weather_ladder_income_wr80_v1",
        "n_cases_universe": len(cases),
        "income_wr80": {
            "n": n,
            "wins": wins,
            "losses": n - wins,
            "winrate": round(wr, 4),
            "total_pnl": round(pnl, 4),
            "oos_half_n": len(oos),
            "oos_half_wr": round(oos_wr, 4),
            "oos_half_pnl": round(sum(float(t["pnl"]) for t in oos), 4),
            "wilson_lower_95": round(wilson_l, 4),
            "bootstrap_lower_05": round(boot_l, 4),
            "by_city": {
                city: {
                    "n": sum(1 for t in taken if t["city"] == city),
                    "wr": round(
                        sum(1 for t in taken if t["city"] == city and t["win"])
                        / max(1, sum(1 for t in taken if t["city"] == city)),
                        4,
                    ),
                }
                for city in sorted({t["city"] for t in taken})
            },
            "loss_slugs": [t["slug"] for t in taken if not t.get("win")],
        },
        "legacy_v3_press_select_expanded": {
            "n": leg_n,
            "wins": leg_w,
            "winrate": round(leg_wr, 4),
            "note": "Expanded 132-case universe — select tier dilutes WR below 80%",
        },
        "friction_stress": stress,
        "checks": checks,
        "point_wr80_assured": point_assured,
        "ci95_wr80_assured": ci_assured,
        "verdict": (
            "INCOME_WR80_CI_ASSURED"
            if point_assured and ci_assured
            else ("INCOME_WR80_POINT_ASSURED" if point_assured else "NOT_ASSURED")
        ),
        "real_money_caveat": (
            "Point/OOS/friction WR>=80% on resolved CLOB-entry replay. "
            "This is the strongest paper assurance available here. "
            "Live fills can differ; Cloud Agent is US-geoblocked for real posts. "
            "Wilson/bootstrap CI>80% needs larger n — reported separately."
        ),
        "sizing_fix": "underdispersion blend + min 28%/leg (fixes wing-starve losses)",
        "filters": {
            "core_press": CORE_PRESS.__dict__,
            "beijing_press": BJ_PRESS.__dict__,
            "no_select_tier": True,
        },
    }

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"assure_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)[:6000])
    print(f"\nVERDICT: {report['verdict']} -> {path}", flush=True)
    return 0 if point_assured else 2


if __name__ == "__main__":
    raise SystemExit(main())
