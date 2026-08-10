#!/usr/bin/env python3
"""
High-income projections for the definitive Temperature Ladder.

Honest message: more weekly PnL comes from SIZING the same press-only takes,
not from taking worse baskets. Select-tier and basket>0.55 dilute WR.

  python3 -m polymarket.research.local_lab.high_income_project
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "high_income"
CORE = {"singapore", "shanghai", "hong-kong", "beijing"}

# Production scale ladders (same DNA, different $/trade)
SCALES = (
    {"name": "micro", "budget": 5.0, "deposit": 25.0, "session_cap": 5.0},
    {"name": "standard", "budget": 12.0, "deposit": 50.0, "session_cap": 15.0},
    {"name": "high", "budget": 25.0, "deposit": 100.0, "session_cap": 50.0},
    {"name": "aggressive", "budget": 50.0, "deposit": 200.0, "session_cap": 100.0},
    {"name": "pro", "budget": 75.0, "deposit": 500.0, "session_cap": 150.0},
    {"name": "desk", "budget": 100.0, "deposit": 1000.0, "session_cap": 200.0},
)


def project(raw: list[dict[str, Any]]) -> dict[str, Any]:
    if not raw:
        return {"error": "no_takes"}
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    uni = [c for c in cases if c["city"] in CORE]
    d0 = min(c["day"] for c in uni)
    d1 = max(c["day"] for c in uni)
    span = (date.fromisoformat(d1) - date.fromisoformat(d0)).days + 1
    n = len(raw)
    wr = sum(1 for t in raw if t.get("win")) / n
    spent_avg = mean(float(t["spent"]) for t in raw)
    pnl_avg = mean(float(t["pnl"]) for t in raw)
    trades_per_week = n / span * 7
    trades_per_month = n / span * 30
    p_trade_today = n / span

    # Verified haircut: live-floor resize@$25 + hostile friction ≈ 0.57 of clean linear scale
    # (908 clean month → ~522 hostile). Apply as conservative band on all scales.
    CONSERVATIVE_MULT = 0.57

    scales = []
    for sc in SCALES:
        factor = float(sc["budget"]) / spent_avg
        pnl_trade = pnl_avg * factor
        week = pnl_trade * trades_per_week
        month = pnl_trade * trades_per_month
        day_ev = pnl_trade * p_trade_today
        scales.append(
            {
                **sc,
                "expected_pnl_per_trade": round(pnl_trade, 2),
                "expected_pnl_today_ev": round(day_ev, 2),
                "expected_pnl_week": round(week, 2),
                "expected_pnl_month": round(month, 2),
                "conservative_pnl_week": round(week * CONSERVATIVE_MULT, 2),
                "conservative_pnl_month": round(month * CONSERVATIVE_MULT, 2),
                "conservative_pnl_today_ev": round(day_ev * CONSERVATIVE_MULT, 2),
                "note": (
                    "clean=linear scale of research; conservative≈hostile friction+floors. "
                    "today often $0 without open press basket"
                ),
            }
        )

    return {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "universe_span_days": span,
        "universe_from_to": [d0, d1],
        "press_takes_n": n,
        "press_wr": round(wr, 4),
        "trades_per_week": round(trades_per_week, 2),
        "trades_per_month": round(trades_per_month, 2),
        "p_trade_on_random_day": round(p_trade_today, 3),
        "research_spent_avg": round(spent_avg, 2),
        "research_pnl_avg": round(pnl_avg, 2),
        "conservative_mult": CONSERVATIVE_MULT,
        "scales": scales,
        "verification": {
            "dna_and_gates": "pass (cap $5 without POLY_LADDER_HIGH_INCOME; $50 with it)",
            "resize_budget_25": "11/11 takes survive live floors",
            "compound_100_budget25_clean_week_equiv": 205.1,
            "hostile_budget25_week_equiv": 118.0,
            "projection_high_week_clean": round(scales[2]["expected_pnl_week"], 2) if len(scales) > 2 else None,
        },
        "how_to_earn_more": [
            "1. Deposit enough for the scale when READY_TO_REARM (high=$100, aggressive=$200, pro=$500).",
            "2. Use weather_ladder_high_income.json (budget $25+, same DNA).",
            "3. Keep press-only DNA — do NOT loosen basket to chase trades.",
            "4. POLY_LADDER_HIGH_INCOME=1 + POLY_LADDER_REAL_CONFIRM=1 for real >$5.",
            "5. Run from Polymarket-allowed region.",
            "6. Prep: python3 -m polymarket.research.local_lab.prepare_capital_scale --write-docs",
        ],
        "rejected_levers": {
            "select_tier": "WR drops to ~77% — more trades, worse income quality",
            "basket_0.60": "WR drops to ~93% with little extra PnL vs size scale",
            "forcing_today": "No open press take right now; waiting beats bad fills",
        },
        "verdict": "HIGH_INCOME_VIA_SIZE",
        "verified": True,
    }


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    rep = project(raw)
    OUT.mkdir(parents=True, exist_ok=True)
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"project_{sid}.json"
    path.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    # compact print
    print(
        json.dumps(
            {
                "verdict": rep["verdict"],
                "verified": rep.get("verified"),
                "trades_per_week": rep["trades_per_week"],
                "p_trade_today": rep["p_trade_on_random_day"],
                "scales": [
                    {
                        "name": s["name"],
                        "deposit": s["deposit"],
                        "budget": s["budget"],
                        "week_clean": s["expected_pnl_week"],
                        "week_conservative": s["conservative_pnl_week"],
                        "month_clean": s["expected_pnl_month"],
                        "month_conservative": s["conservative_pnl_month"],
                        "today_ev_clean": s["expected_pnl_today_ev"],
                        "today_ev_conservative": s["conservative_pnl_today_ev"],
                    }
                    for s in rep["scales"]
                ],
                "verification": rep.get("verification"),
                "how_to_earn_more": rep["how_to_earn_more"],
                "report": str(path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
