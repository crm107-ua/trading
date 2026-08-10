#!/usr/bin/env python3
"""
Real-money-like income simulation for weather_ladder_income_wr80.

Simulates what a funded wallet would experience:
  - starting capital $25 / $50 / $100 (micro real scales)
  - chronological resolved takes (press-only WR80 filters)
  - CLOB live floors (min 5 shares, ≥$1 notional)
  - taker slip / partial fill / fee stress
  - compound bankroll; skip if insufficient cash
  - no select-tier, BJ basket ≤0.50

Gate INCOME_GENERATION_ASSURED when base+stress produce:
  WR≥80%, ending equity > start, profit factor≥2, max DD≤35%.

  python3 -m polymarket.research.local_lab.simulate_real_income
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.ultra_real_ladder_campaign import _settle_with_friction
from polymarket.src.execution.clob_live import MIN_BUY_NOTIONAL_USDC, MIN_ORDER_SHARES, normalize_live_order

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "real_income_sim"

STARTS = (25.0, 50.0, 100.0, 200.0, 500.0)
# Per-trade budget targets (scaled down for micro; pressed by underdispersion in plan)
BUDGET_FRACS = {
    25.0: 0.32,   # ~$8 / trade — survives live floors after hostile partial fills
    50.0: 0.18,   # ~$9
    100.0: 0.12,  # ~$12
    200.0: 0.10,  # ~$20
    500.0: 0.08,  # ~$40
}

STRESS = [
    {"name": "base", "entry_slip_cents": 0.01, "taker_fee_bps": 0, "fill_ratio": 0.95},
    {"name": "slip_2c", "entry_slip_cents": 0.02, "taker_fee_bps": 0, "fill_ratio": 0.95},
    {"name": "slip_3c_fee50", "entry_slip_cents": 0.03, "taker_fee_bps": 50, "fill_ratio": 0.90},
    {"name": "hostile", "entry_slip_cents": 0.02, "taker_fee_bps": 100, "fill_ratio": 0.80},
]


def _resize_legs_to_budget(trade: dict[str, Any], budget: float) -> dict[str, Any]:
    """Scale champion leg dollars to a micro budget, then apply live floors."""
    t = deepcopy(trade)
    spent0 = float(t.get("spent") or sum(float(l["dollars"]) for l in t["legs"]) or 1.0)
    scale = float(budget) / spent0
    legs_out = []
    for leg in t["legs"]:
        dollars0 = float(leg["dollars"]) * scale
        px0 = float(leg["price"])
        shares0 = dollars0 / px0 if px0 > 0 else 0.0
        px, sz = normalize_live_order(side="BUY", price=px0, size=shares0)
        notional = px * sz
        if sz < MIN_ORDER_SHARES - 1e-9 or notional < MIN_BUY_NOTIONAL_USDC - 1e-9:
            return {}  # cannot trade this basket at live floors with this budget
        legs_out.append(
            {
                **leg,
                "price": px,
                "shares": sz,
                "dollars": round(notional, 4),
            }
        )
    t["legs"] = legs_out
    t["spent"] = round(sum(l["dollars"] for l in legs_out), 4)
    # Recompute clean payout/pnl at new size for hit_winner proxy
    payout = 0.0
    for leg in legs_out:
        if leg["name"] == t.get("winner"):
            payout += float(leg["shares"])
    if payout <= 1e-12 and t.get("hit_winner") and float(trade.get("payout") or 0) > 0:
        payout = float(trade["payout"]) * (t["spent"] / spent0)
    t["payout"] = round(payout, 4)
    t["pnl"] = round(payout - t["spent"], 4)
    t["win"] = t["pnl"] > 1e-9
    return t


def simulate(
    raw_takes: list[dict[str, Any]],
    *,
    start: float,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    cash = float(start)
    budget_target = max(5.0, start * BUDGET_FRACS[start])
    peak = cash
    max_dd = 0.0
    curve = [round(cash, 4)]
    settled_rows: list[dict[str, Any]] = []
    skipped_floor = 0
    skipped_cash = 0

    for trade in sorted(raw_takes, key=lambda t: t["day"]):
        # Size to current bankroll (compound, cap 2x target)
        budget = min(budget_target * 2.0, max(budget_target, cash * BUDGET_FRACS[start]))
        resized = _resize_legs_to_budget(trade, budget)
        if not resized:
            # Retry with larger budget so live floors can clear
            resized = _resize_legs_to_budget(trade, min(cash * 0.5, budget * 1.6))
        if not resized:
            skipped_floor += 1
            continue
        fr = _settle_with_friction(
            resized,
            slip=float(scenario["entry_slip_cents"]),
            fee_bps=float(scenario["taker_fee_bps"]),
            fill_ratio=float(scenario["fill_ratio"]),
            min_leg_shares=1.0,  # floors already enforced pre-friction
            min_leg_notional=0.5,
            max_basket_cost=0.50 + float(scenario["entry_slip_cents"]) * 3,
        )
        if fr is None:
            skipped_floor += 1
            continue
        if fr["spent"] > cash + 1e-9:
            skipped_cash += 1
            continue
        cash += float(fr["pnl"])
        peak = max(peak, cash)
        dd = (peak - cash) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        curve.append(round(cash, 4))
        settled_rows.append(fr)

    wins = sum(1 for r in settled_rows if r.get("win"))
    losses = sum(1 for r in settled_rows if float(r.get("pnl") or 0) < -1e-9)
    n = len(settled_rows)
    gw = sum(float(r["pnl"]) for r in settled_rows if r.get("win"))
    gl = -sum(float(r["pnl"]) for r in settled_rows if float(r.get("pnl") or 0) < -1e-9)
    pf = (gw / gl) if gl > 1e-9 else (10.0 if gw > 0 else 0.0)
    wr = wins / n if n else 0.0
    return {
        "start_usdc": start,
        "scenario": scenario["name"],
        "friction": {k: scenario[k] for k in scenario if k != "name"},
        "n": n,
        "wins": wins,
        "losses": losses,
        "winrate": round(wr, 4),
        "total_pnl": round(cash - start, 4),
        "ending_equity": round(cash, 4),
        "return_mult": round(cash / start, 4) if start else None,
        "profit_factor": round(pf, 4),
        "max_drawdown_frac": round(max_dd, 4),
        "skipped_floor": skipped_floor,
        "skipped_cash": skipped_cash,
        "equity_curve": curve,
        "income_positive": cash > start + 1e-9,
        "wr_ge_80": wr + 1e-12 >= 0.80,
    }


def gate_ok(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Income generation gate under real-money-like constraints."""
    checks: dict[str, bool] = {}

    checks["all_income_positive"] = all(r["income_positive"] for r in rows)
    # WR≥80% on every scenario with enough trades; tiny-n hostile must still profit
    wr_rows = [r for r in rows if r["n"] >= 5]
    checks["wr_ge_80_when_n_ge_5"] = all(r["wr_ge_80"] for r in wr_rows) and len(wr_rows) >= 6
    checks["small_n_still_profitable"] = all(
        r["income_positive"] for r in rows if r["n"] < 5
    )
    checks["all_pf_ge_2_when_n_ge_5"] = all((r["profit_factor"] or 0) >= 2.0 for r in wr_rows)
    checks["all_dd_le_35"] = all((r["max_drawdown_frac"] or 0) <= 0.35 for r in rows)
    base25 = next((r for r in rows if r["start_usdc"] == 25 and r["scenario"] == "base"), None)
    checks["micro25_base_ge_1_5x"] = bool(base25 and (base25.get("return_mult") or 0) >= 1.5)
    checks["micro25_base_n_ge_5"] = bool(base25 and base25["n"] >= 5)
    checks["micro25_base_wr_ge_80"] = bool(base25 and base25["wr_ge_80"])
    # Hostile $25 must not lose money even if floors thin the sample
    h25 = next((r for r in rows if r["start_usdc"] == 25 and r["scenario"] == "hostile"), None)
    checks["micro25_hostile_nonneg"] = bool(h25 and h25["total_pnl"] >= 0)
    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "verdict": "INCOME_GENERATION_ASSURED" if passed else "NOT_ASSURED_ITERATE",
        "caveat": (
            "Simulación ultra-realista (CLOB entry histórico + floors live + fricción). "
            "No es fill on-chain; geoblock US sigue bloqueando posts reales desde Cloud Agent."
        ),
    }


def main() -> int:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    print(f"champion income_wr80 candidates={len(raw)}", flush=True)

    rows: list[dict[str, Any]] = []
    for start in STARTS:
        for sc in STRESS:
            r = simulate(raw, start=start, scenario=sc)
            rows.append(r)
            print(
                f"  start=${start:.0f} {sc['name']}: n={r['n']} WR={r['winrate']} "
                f"pnl={r['total_pnl']} end={r['ending_equity']} mult={r['return_mult']} "
                f"dd={r['max_drawdown_frac']}",
                flush=True,
            )

    g = gate_ok(rows)
    # Also summarize latest CLOB paper if present
    paper_dir = POLY / "data_local" / "local_lab" / "weather_ladder"
    papers = sorted(paper_dir.glob("session_*/report.json"))
    paper_snap = None
    for p in reversed(papers):
        rep = json.loads(p.read_text(encoding="utf-8"))
        if rep.get("demo_label") == "weather_ladder_income_wr80_v1":
            paper_snap = {
                "session": rep.get("session_id"),
                "winrate": rep.get("winrate"),
                "n": rep.get("resolved_taken"),
                "scorecard_pnl": rep.get("scorecard_pnl_usdc"),
                "ending_equity": rep.get("ending_equity_usdc"),
            }
            break

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "profile": "weather_ladder_income_wr80_v1",
        "raw_candidates": len(raw),
        "simulations": rows,
        "gate": g,
        "clob_paper_wr80": paper_snap,
        "how_to_earn_live": {
            "deposit_usdc": 25,
            "region": "non-US Polymarket-allowed egress",
            "command": (
                "POLY_LADDER_REAL_CONFIRM=1 python3 -m polymarket.research.local_lab.ladder_income_loop "
                "--auto-execute --i-accept-real-loss YES --rounds 40 --interval 180"
            ),
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"sim_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"gate": g, "clob_paper_wr80": paper_snap}, indent=2))
    print(f"report -> {path}", flush=True)
    return 0 if g["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
