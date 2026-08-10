#!/usr/bin/env python3
"""
Ultra-real paper campaign for the frozen Temperature Ladder champion.

Two layers:
  1) Walk-forward on cached CLOB-entry cases (chronological bankroll + friction stress)
  2) Live paper session via weather_ladder_paper (asks/history) with the same friction

Does NOT arm live trading. Exit 0 only when income_gate passes under base + stress.

  python -m polymarket.research.local_lab.ultra_real_ladder_campaign
  python -m polymarket.research.local_lab.ultra_real_ladder_campaign --skip-live-paper
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.optimize_weather_ladder import TrialFilters, _eval_case
from polymarket.research.local_lab.validate_two_tier import BJ_PRESS, BJ_SELECT, CORE_PRESS, CORE_SELECT
from polymarket.research.local_lab.weather_ladder_paper import run_weather_ladder_paper

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
CFG_DEFAULT = POLY / "config" / "weather_ladder_ultra_real_sim.json"
OUT = POLY / "data_local" / "local_lab" / "ultra_real_campaign"

CORE_CITIES = ("singapore", "shanghai", "hong-kong")

STRESS_SCENARIOS: list[dict[str, Any]] = [
    {"name": "base", "entry_slip_cents": 0.01, "taker_fee_bps": 0, "fill_ratio": 0.95},
    {"name": "slip_2c", "entry_slip_cents": 0.02, "taker_fee_bps": 0, "fill_ratio": 0.95},
    {"name": "slip_3c_fee50", "entry_slip_cents": 0.03, "taker_fee_bps": 50, "fill_ratio": 0.90},
    {"name": "hostile_fill80", "entry_slip_cents": 0.02, "taker_fee_bps": 100, "fill_ratio": 0.80},
]


def _load_cfg(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _take_champion_case(case: dict[str, Any]) -> dict[str, Any] | None:
    city = case["city"]
    if city in CORE_CITIES:
        tiers: list[tuple[str, TrialFilters]] = [("press_under", CORE_PRESS), ("select", CORE_SELECT)]
        sleeve = "core"
    elif city == "beijing":
        tiers = [("press_under", BJ_PRESS), ("select", BJ_SELECT)]
        sleeve = "beijing"
    else:
        return None
    for tier_name, filt in tiers:
        r = _eval_case(case, filt)
        if r and r.get("taken"):
            return {**r, "sleeve": sleeve, "tier": tier_name}
    return None


def _settle_with_friction(
    trade: dict[str, Any],
    *,
    slip: float,
    fee_bps: float,
    fill_ratio: float,
    min_leg_shares: float,
    min_leg_notional: float,
    max_basket_cost: float,
) -> dict[str, Any] | None:
    """Re-price champion legs as a taker hitting ask+slip with partial fills."""
    legs = list(trade.get("legs") or [])
    if not legs:
        return None
    fee = float(fee_bps) / 10_000.0
    basket = 0.0
    spent = 0.0
    payout = 0.0
    eff_legs: list[dict[str, Any]] = []
    winner = trade.get("winner")

    for leg in legs:
        px0 = float(leg["price"])
        dollars0 = float(leg["dollars"])
        px = min(0.99, px0 + float(slip))
        dollars = dollars0 * float(fill_ratio)
        if dollars < min_leg_notional:
            return None
        shares = dollars / px if px > 0 else 0.0
        if shares + 1e-12 < min_leg_shares:
            return None
        notional = dollars * (1.0 + fee)
        basket += px
        spent += notional
        leg_hit = leg["name"] == winner
        if leg_hit:
            payout += shares
        eff_legs.append(
            {
                "name": leg["name"],
                "price0": px0,
                "price_eff": round(px, 4),
                "dollars": round(notional, 4),
                "shares": round(shares, 4),
                "hit": leg_hit,
            }
        )

    if basket > max_basket_cost + 1e-9:
        return None

    # Open-ended / proxy hits: _eval_case may mark hit_winner without exact name match.
    if payout <= 1e-12 and trade.get("hit_winner") and float(trade.get("payout") or 0) > 0:
        clean_payout = float(trade["payout"])
        avg_px0 = sum(float(l["price"]) for l in legs) / len(legs)
        avg_px = avg_px0 + float(slip)
        scale = float(fill_ratio) * (avg_px0 / max(avg_px, 1e-9))
        payout = clean_payout * scale

    pnl = payout - spent
    return {
        "slug": trade["slug"],
        "city": trade["city"],
        "day": trade["day"],
        "sleeve": trade.get("sleeve"),
        "tier": trade.get("tier"),
        "spent": round(spent, 4),
        "payout": round(payout, 4),
        "pnl": round(pnl, 4),
        "win": pnl > 1e-9,
        "basket_cost_eff": round(basket, 4),
        "legs": eff_legs,
    }


def _equity_stats(trades: list[dict[str, Any]], initial: float) -> dict[str, Any]:
    equity = float(initial)
    peak = equity
    max_dd = 0.0
    curve = [round(equity, 4)]
    for t in trades:
        equity += float(t["pnl"])
        peak = max(peak, equity)
        dd = (peak - equity) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        curve.append(round(equity, 4))
    wins = [t for t in trades if t.get("win")]
    losses = [t for t in trades if float(t.get("pnl") or 0) < -1e-9]
    gw = sum(float(t["pnl"]) for t in wins) if wins else 0.0
    gl = -sum(float(t["pnl"]) for t in losses) if losses else 0.0
    pf = (gw / gl) if gl > 1e-9 else (10.0 if gw > 0 else 0.0)
    return {
        "n": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(len(wins) / len(trades), 4) if trades else None,
        "total_pnl": round(sum(float(t["pnl"]) for t in trades), 4),
        "profit_factor": round(pf, 4),
        "ending_equity": round(equity, 4),
        "max_drawdown_frac": round(max_dd, 4),
        "equity_curve": curve,
        "avg_pnl": round(sum(float(t["pnl"]) for t in trades) / len(trades), 4) if trades else 0.0,
    }


def walk_forward_friction(
    cases: list[dict[str, Any]],
    *,
    initial: float,
    budget: float,
    scenario: dict[str, Any],
    min_leg_shares: float,
    min_leg_notional: float,
    max_basket_cost_core: float = 0.50,
    max_basket_cost_bj: float = 0.55,
) -> dict[str, Any]:
    raw: list[dict[str, Any]] = []
    for c in sorted(cases, key=lambda x: x["day"]):
        t = _take_champion_case(c)
        if t:
            # attach open-ended flags from case for proxy settlement
            t["winner_temp"] = c.get("winner_temp")
            t["winner_open_high"] = c.get("winner_open_high")
            t["winner_open_low"] = c.get("winner_open_low")
            raw.append(t)

    cash = float(initial)
    taken: list[dict[str, Any]] = []
    skipped_friction = 0
    skipped_bankroll = 0
    _ = budget  # sizing comes from champion TrialFilters; bankroll only gates entry
    for t in raw:
        mb = max_basket_cost_bj if t.get("sleeve") == "beijing" else max_basket_cost_core
        settled = _settle_with_friction(
            t,
            slip=float(scenario["entry_slip_cents"]),
            fee_bps=float(scenario["taker_fee_bps"]),
            fill_ratio=float(scenario["fill_ratio"]),
            min_leg_shares=min_leg_shares,
            min_leg_notional=min_leg_notional,
            # Allow basket to expand by slip×legs without inventing new edge
            max_basket_cost=mb + float(scenario["entry_slip_cents"]) * 3,
        )
        if settled is None:
            skipped_friction += 1
            continue
        if settled["spent"] > cash + 1e-9:
            skipped_bankroll += 1
            continue
        cash += settled["pnl"]
        taken.append(settled)

    stats = _equity_stats(taken, initial)
    return {
        "scenario": scenario["name"],
        "friction": {k: scenario[k] for k in scenario if k != "name"},
        "candidates": len(raw),
        "skipped_friction": skipped_friction,
        "skipped_bankroll": skipped_bankroll,
        "trades": taken,
        **stats,
    }


def _apply_friction_to_paper_report(report: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """Haircut resolved paper fills: worse entry + fee + partial fill."""
    slip = float(scenario["entry_slip_cents"])
    fee = float(scenario["taker_fee_bps"]) / 10_000.0
    fill_ratio = float(scenario["fill_ratio"])
    rows = []
    for t in report.get("taken") or []:
        if not t.get("resolved"):
            continue
        spent0 = float(t.get("spent") or 0)
        pnl0 = float(t.get("pnl") or 0)
        payout0 = spent0 + pnl0
        # inflate spend, shrink payout shares equivalently
        spent = spent0 * fill_ratio * (1.0 + fee) * ((1.0) )  # dollars filled
        # price slip reduces shares ≈ spent0/(avg_px) → spent0/(avg_px+slip)
        fills = t.get("fills") or []
        if fills:
            payout = 0.0
            spent = 0.0
            for f in fills:
                px0 = float(f["price"])
                px = min(0.99, px0 + slip)
                dollars = float(f["dollars"]) * fill_ratio
                shares = dollars / px if px > 0 else 0.0
                spent += dollars * (1.0 + fee)
                if f.get("resolved_win"):
                    payout += shares
        else:
            # fallback proportional haircut
            avg_px = 0.25
            payout = payout0 * fill_ratio * (avg_px / (avg_px + slip))
            spent = spent0 * fill_ratio * (1.0 + fee)
        pnl = payout - spent
        rows.append(
            {
                "slug": t.get("slug"),
                "city": t.get("city"),
                "day": t.get("day"),
                "spent": round(spent, 4),
                "payout": round(payout, 4),
                "pnl": round(pnl, 4),
                "win": pnl > 1e-9,
            }
        )
    stats = _equity_stats(rows, float(report.get("initial_capital_usdc") or 150))
    return {"scenario": scenario["name"], "resolved_rows": rows, **stats}


def income_gate(
    base: dict[str, Any],
    stresses: list[dict[str, Any]],
    gate: dict[str, Any],
    *,
    live_paper: dict[str, Any] | None = None,
    live_friction: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dd = base.get("max_drawdown_frac")
    if dd is None:
        dd = 1.0
    checks = {
        "min_resolved_trades": base.get("n", 0) >= int(gate.get("min_resolved_trades", 8)),
        "min_winrate": (base.get("winrate") or 0) >= float(gate.get("min_winrate", 0.75)),
        "min_profit_factor": (base.get("profit_factor") or 0) >= float(gate.get("min_profit_factor", 2.0)),
        "min_scorecard_pnl": (base.get("total_pnl") or 0) >= float(gate.get("min_scorecard_pnl_usdc", 50)),
        "max_drawdown": float(dd) <= float(gate.get("max_drawdown_frac", 0.35)),
    }
    stress_ok = all((s.get("total_pnl") or 0) >= float(gate.get("min_stress_pnl_usdc", 0)) for s in stresses)
    checks["all_stress_pnl_nonneg"] = stress_ok

    if live_paper is not None:
        checks["live_min_resolved"] = int(live_paper.get("resolved_taken") or 0) >= int(
            gate.get("live_min_resolved", 6)
        )
        wr = live_paper.get("winrate")
        checks["live_min_winrate"] = (wr is not None) and float(wr) >= float(gate.get("live_min_winrate", 0.6))
        checks["live_min_scorecard_pnl"] = float(live_paper.get("scorecard_pnl_usdc") or 0) >= float(
            gate.get("live_min_scorecard_pnl_usdc", 20)
        )
    if live_friction:
        base_live = next((x for x in live_friction if x.get("scenario") == "base"), live_friction[0])
        checks["live_friction_base_pnl"] = float(base_live.get("total_pnl") or 0) >= float(
            gate.get("live_friction_base_min_pnl_usdc", 0)
        )

    passed = all(checks.values())
    return {
        "passed": passed,
        "checks": checks,
        "verdict": "PAPER_INCOME_READY" if passed else "NOT_READY_KEEP_PAPER",
        "live_armed": False,
        "caveat": (
            "Paper+friction ≠ garantía live. Fills, latency y resolución real pueden diferir. "
            "POLY_LIVE_ARMED debe permanecer 0 hasta go-live dedicado del ladder."
        ),
    }


def run_campaign(
    *,
    config_path: Path,
    skip_live_paper: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    cfg = _load_cfg(config_path)
    friction_cfg = dict(cfg.get("friction") or {})
    gate = dict(cfg.get("income_gate") or {})
    initial = float(cfg.get("initial_capital_usdc", 150))
    budget = float(cfg.get("budget_per_market_usdc", 12))
    sid = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT / f"campaign_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    print(f"[ultra] walk-forward on {len(cases)} cached cases…", flush=True)

    scenarios = []
    # ensure base uses config friction first
    base_sc = {
        "name": "base",
        "entry_slip_cents": float(friction_cfg.get("entry_slip_cents", 0.01)),
        "taker_fee_bps": float(friction_cfg.get("taker_fee_bps", 0)),
        "fill_ratio": float(friction_cfg.get("fill_ratio", 0.95)),
    }
    scen_list = [base_sc] + [s for s in STRESS_SCENARIOS if s["name"] != "base"]
    for sc in scen_list:
        print(f"  scenario {sc['name']}…", flush=True)
        scenarios.append(
            walk_forward_friction(
                cases,
                initial=initial,
                budget=budget,
                scenario=sc,
                min_leg_shares=float(friction_cfg.get("min_leg_shares", 5.0)),
                min_leg_notional=float(friction_cfg.get("min_leg_notional_usdc", 1.0)),
            )
        )

    base = next(s for s in scenarios if s["scenario"] == "base")
    stresses = [s for s in scenarios if s["scenario"] != "base"]

    live_paper: dict[str, Any] | None = None
    live_friction: list[dict[str, Any]] = []
    if not skip_live_paper:
        print("[ultra] live CLOB paper session (champion ultra config)…", flush=True)
        # Point paper runner at this config path
        paper = run_weather_ladder_paper(config_path=config_path, session_id=f"{sid}_clob")
        live_paper = {k: paper[k] for k in paper if k not in ("taken", "skipped_head")}
        live_paper["taken_summary"] = [
            {
                "day": t.get("day"),
                "city": t.get("city"),
                "sleeve": t.get("sleeve"),
                "tier": t.get("tier"),
                "pnl": t.get("pnl"),
                "resolved": t.get("resolved"),
                "spent": t.get("spent"),
            }
            for t in paper.get("taken") or []
        ]
        for sc in scen_list[:3]:
            live_friction.append(_apply_friction_to_paper_report(paper, sc))

    gate_rep = income_gate(base, stresses, gate, live_paper=live_paper, live_friction=live_friction)

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "campaign_id": sid,
        "strategy_locked": "temperature_ladder_champion_v3",
        "config": str(config_path),
        "initial_capital_usdc": initial,
        "walk_forward": {
            "n_cases": len(cases),
            "scenarios": [
                {k: v for k, v in s.items() if k != "trades"} | {"trades_head": (s.get("trades") or [])[:5]}
                for s in scenarios
            ],
            "base": {k: v for k, v in base.items() if k not in ("trades", "equity_curve")}
            | {"equity_curve": base.get("equity_curve")},
        },
        "live_clob_paper": live_paper,
        "live_clob_friction": live_friction,
        "income_gate": gate_rep,
        "recommendation": {
            "deploy_paper_capital": gate_rep["passed"],
            "deploy_real_money": False,
            "next_step": (
                "Si PAPER_INCOME_READY: micro dry-run live del ladder (DRY_RUN=1) con $10–25. "
                "Solo entonces valorar DRY_RUN=0 con tope duro."
                if gate_rep["passed"]
                else "Seguir iterando paper/friction hasta pasar el gate."
            ),
        },
    }
    # Keep full trades separately for audit
    (out_dir / "walk_forward_trades.json").write_text(
        json.dumps({s["scenario"]: s.get("trades") for s in scenarios}, indent=2),
        encoding="utf-8",
    )
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"income_gate": gate_rep, "base": report["walk_forward"]["base"]}, indent=2))
    print(f"campaign -> {out_dir}", flush=True)
    return report


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(CFG_DEFAULT))
    p.add_argument("--skip-live-paper", action="store_true")
    p.add_argument("--session-id", default=None)
    args = p.parse_args()
    cfg = Path(args.config)
    if not cfg.is_file():
        cfg = POLY / args.config
    rep = run_campaign(config_path=cfg, skip_live_paper=args.skip_live_paper, session_id=args.session_id)
    return 0 if rep["income_gate"]["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
