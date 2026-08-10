#!/usr/bin/env python3
"""
Simulación ultra-realista: wallet actual + qué pasa si aparece un take DNA.

Usa:
  - takes históricos press-only (income_wr80 / DNA)
  - floors CLOB reales (min 5 shares, ≥$1 notional/pierna)
  - fricción taker (slip / fee / fill parcial)
  - cap sesión micro ($5) y effective_cap = min(cap, balance*0.95)
  - libro vivo opcional (near-miss actuales)

NO posta órdenes. NO afloja DNA.

  python3 -m polymarket.research.local_lab.wallet_take_reality_sim
  python3 -m polymarket.research.local_lab.wallet_take_reality_sim --balance 3.4482 --live-book
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.ultra_real_ladder_campaign import _settle_with_friction
from polymarket.src.execution.clob_live import (
    MIN_BUY_NOTIONAL_USDC,
    MIN_ORDER_SHARES,
    normalize_live_order,
)

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
CFG = POLY / "config" / "weather_ladder_definitive_real.json"
OUT = POLY / "data_local" / "local_lab" / "wallet_take_reality"

STRESS = [
    {"name": "base", "entry_slip_cents": 0.01, "taker_fee_bps": 0, "fill_ratio": 0.95},
    {"name": "slip_2c", "entry_slip_cents": 0.02, "taker_fee_bps": 0, "fill_ratio": 0.95},
    {"name": "slip_3c_fee50", "entry_slip_cents": 0.03, "taker_fee_bps": 50, "fill_ratio": 0.90},
    {"name": "hostile", "entry_slip_cents": 0.02, "taker_fee_bps": 100, "fill_ratio": 0.80},
]


def effective_cap(balance: float, session_cap: float = 5.0) -> float:
    return round(min(float(session_cap), max(0.0, float(balance) * 0.95)), 4)


def _floor_notional(price: float) -> tuple[float, float, float]:
    """Return (px, shares, notional) at CLOB buy floors for one leg."""
    px, sz = normalize_live_order(side="BUY", price=float(price), size=MIN_ORDER_SHARES)
    return px, sz, round(px * sz, 6)


def _resize_to_cap(trade: dict[str, Any], budget: float) -> dict[str, Any] | None:
    """Size DNA legs into micro budget with live floors + wing-safe ≥28%.

    1) Compute per-leg CLOB floor notional.
    2) If floors alone exceed budget → not executable.
    3) Distribute leftover by research dollar weights (clipped to ≥28% each).
    4) Re-normalize each leg through live floors.
    """
    t = deepcopy(trade)
    legs0 = list(t.get("legs") or [])
    if not legs0 or budget <= 0:
        return None

    floors: list[tuple[dict[str, Any], float, float, float]] = []
    floor_sum = 0.0
    for leg in legs0:
        px, sz, notion = _floor_notional(float(leg["price"]))
        floors.append((leg, px, sz, notion))
        floor_sum += notion
    floor_sum = round(floor_sum, 6)
    if floor_sum > float(budget) + 1e-6:
        return None

    # Wing-safe weights from research dollars
    raw_w = [max(1e-9, float(l["dollars"])) for l in legs0]
    z = sum(raw_w) or 1.0
    weights = [w / z for w in raw_w]
    min_frac = 0.28 if len(legs0) >= 3 else (1.0 / max(1, len(legs0)))
    weights = [max(min_frac, w) for w in weights]
    z2 = sum(weights) or 1.0
    weights = [w / z2 for w in weights]

    leftover = max(0.0, float(budget) - floor_sum)
    target_dollars = [floors[i][3] + leftover * weights[i] for i in range(len(legs0))]
    # If any target still below floor (shouldn't), bump and renormalize down
    for i in range(len(target_dollars)):
        target_dollars[i] = max(target_dollars[i], floors[i][3])
    # Cap total to budget
    tot = sum(target_dollars)
    if tot > float(budget) + 1e-9:
        # scale only the surplus above floors
        surplus = [max(0.0, d - floors[i][3]) for i, d in enumerate(target_dollars)]
        ssum = sum(surplus)
        room = max(0.0, float(budget) - floor_sum)
        if ssum > 1e-12 and room >= 0:
            target_dollars = [
                floors[i][3] + (surplus[i] / ssum) * room for i in range(len(legs0))
            ]
        else:
            target_dollars = [floors[i][3] for i in range(len(legs0))]

    legs_out: list[dict[str, Any]] = []
    for i, (leg, px0, _sz0, _n0) in enumerate(floors):
        dollars_t = float(target_dollars[i])
        shares_t = dollars_t / px0 if px0 > 0 else 0.0
        px, sz = normalize_live_order(side="BUY", price=px0, size=shares_t)
        notional = round(px * sz, 4)
        if sz < MIN_ORDER_SHARES - 1e-9 or notional < MIN_BUY_NOTIONAL_USDC - 1e-9:
            return None
        legs_out.append({**leg, "price": px, "shares": sz, "dollars": notional})

    spent = round(sum(float(l["dollars"]) for l in legs_out), 4)
    if spent > float(budget) + 1e-6:
        return None

    payout = 0.0
    for leg in legs_out:
        if leg.get("name") == t.get("winner"):
            payout += float(leg["shares"])
    t["legs"] = legs_out
    t["spent"] = spent
    t["payout"] = round(payout, 4)
    t["pnl"] = round(payout - spent, 4)
    t["win"] = t["pnl"] > 1e-9
    t["budget_target"] = round(float(budget), 4)
    t["floor_notional_sum"] = round(floor_sum, 4)
    return t


def _loss_if_miss(resized: dict[str, Any]) -> dict[str, Any]:
    """Counterfactual: none of the 3 legs hits → full notional loss."""
    spent = float(resized["spent"])
    return {
        **resized,
        "scenario_outcome": "full_miss",
        "payout": 0.0,
        "pnl": round(-spent, 4),
        "win": False,
        "ending_if_start": None,
    }


def _win_hit(resized: dict[str, Any]) -> dict[str, Any]:
    return {
        **resized,
        "scenario_outcome": "hit_winner",
        "ending_if_start": None,
    }


def simulate_wallet_path(
    raw_takes: list[dict[str, Any]],
    *,
    start: float,
    scenario: dict[str, Any],
    session_cap: float = 5.0,
    budget_cfg: float = 3.0,
) -> dict[str, Any]:
    cash = float(start)
    peak = cash
    max_dd = 0.0
    curve = [round(cash, 4)]
    rows: list[dict[str, Any]] = []
    skipped_floor = 0
    skipped_cash = 0
    skipped_cap = 0

    for trade in sorted(raw_takes, key=lambda t: t["day"]):
        cap = effective_cap(cash, session_cap)
        budget = min(float(budget_cfg), cap)
        if budget < 2.0:
            skipped_cash += 1
            continue
        resized = _resize_to_cap(trade, budget)
        if not resized:
            # try max affordable under cap
            resized = _resize_to_cap(trade, cap)
        if not resized:
            skipped_floor += 1
            continue
        fr = _settle_with_friction(
            resized,
            slip=float(scenario["entry_slip_cents"]),
            fee_bps=float(scenario["taker_fee_bps"]),
            fill_ratio=float(scenario["fill_ratio"]),
            min_leg_shares=1.0,
            min_leg_notional=0.5,
            max_basket_cost=0.50 + float(scenario["entry_slip_cents"]) * 3,
        )
        if fr is None:
            skipped_floor += 1
            continue
        spent = float(fr["spent"])
        if spent > cash + 1e-9:
            skipped_cash += 1
            continue
        if spent > cap + 1e-9:
            skipped_cap += 1
            continue
        cash += float(fr["pnl"])
        peak = max(peak, cash)
        dd = (peak - cash) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
        curve.append(round(cash, 4))
        rows.append(
            {
                "day": trade.get("day"),
                "city": trade.get("city"),
                "slug": trade.get("slug"),
                "basket_cost": trade.get("basket_cost"),
                "spent": fr.get("spent"),
                "pnl": fr.get("pnl"),
                "win": fr.get("win"),
                "cash_after": round(cash, 4),
            }
        )

    wins = sum(1 for r in rows if r.get("win"))
    n = len(rows)
    wr = wins / n if n else 0.0
    return {
        "start_usdc": round(start, 4),
        "scenario": scenario["name"],
        "friction": {k: scenario[k] for k in scenario if k != "name"},
        "n_executed": n,
        "n_universe": len(raw_takes),
        "wins": wins,
        "losses": n - wins,
        "winrate": round(wr, 4),
        "total_pnl": round(cash - start, 4),
        "ending_equity": round(cash, 4),
        "return_mult": round(cash / start, 4) if start else None,
        "max_drawdown_frac": round(max_dd, 4),
        "skipped_floor": skipped_floor,
        "skipped_cash": skipped_cash,
        "skipped_cap": skipped_cap,
        "executable_frac": round(n / len(raw_takes), 4) if raw_takes else 0.0,
        "equity_curve": curve,
        "trades": rows,
    }


def what_if_single_take(
    raw_takes: list[dict[str, Any]],
    *,
    balance: float,
    session_cap: float,
    budget_cfg: float,
) -> dict[str, Any]:
    """If a DNA take appeared right now, size it and show win/loss/hostile paths."""
    cap = effective_cap(balance, session_cap)
    budget = min(budget_cfg, cap)
    # Use median historical basket shape (by spent proximity to research mean)
    templates = sorted(raw_takes, key=lambda t: abs(float(t.get("basket_cost") or 0.45) - 0.45))
    out: dict[str, Any] = {
        "balance_usdc": round(balance, 4),
        "effective_cap_usdc": cap,
        "budget_usdc": round(budget, 4),
        "clob_floors": {
            "min_shares": MIN_ORDER_SHARES,
            "min_notional_usdc": MIN_BUY_NOTIONAL_USDC,
        },
        "templates_tried": [],
        "executable_now": False,
        "block_reason": None,
        "paths": {},
    }

    resized = None
    used = None
    for t in templates:
        cand = _resize_to_cap(t, budget)
        out["templates_tried"].append(
            {
                "day": t.get("day"),
                "city": t.get("city"),
                "basket_cost": t.get("basket_cost"),
                "ok": cand is not None,
                "spent": None if cand is None else cand.get("spent"),
            }
        )
        if cand is not None:
            resized = cand
            used = t
            break

    if resized is None:
        # Diagnose minimum floor notional on best template
        t0 = templates[0] if templates else None
        if t0:
            legs_diag = []
            for leg in t0["legs"]:
                px, sz = normalize_live_order(
                    side="BUY", price=float(leg["price"]), size=MIN_ORDER_SHARES
                )
                legs_diag.append(
                    {
                        "name": leg["name"],
                        "price": px,
                        "min_floor_shares": sz,
                        "min_floor_notional": round(px * sz, 4),
                    }
                )
            min_basket = round(sum(x["min_floor_notional"] for x in legs_diag), 4)
            out["block_reason"] = (
                f"live_floors_need_~${min_basket:.2f} for 3-leg DNA basket; "
                f"wallet cap ${cap:.2f} insufficient after floor bumps"
            )
            out["floor_diagnosis"] = {
                "template_day": t0.get("day"),
                "template_city": t0.get("city"),
                "legs": legs_diag,
                "min_notional_3leg": min_basket,
                "gap_usdc": round(max(0.0, min_basket - cap), 4),
            }
        else:
            out["block_reason"] = "no_historical_dna_takes"
        return out

    out["executable_now"] = True
    out["template"] = {
        "day": used.get("day"),
        "city": used.get("city"),
        "slug": used.get("slug"),
        "basket_cost": used.get("basket_cost"),
        "basket_ev": used.get("basket_ev"),
        "underdispersed": used.get("underdispersed"),
    }
    out["sized_legs"] = resized["legs"]
    out["notional_usdc"] = resized["spent"]

    win = _win_hit(resized)
    miss = _loss_if_miss(resized)
    paths: dict[str, Any] = {}
    for name, base in (("clean_win", win), ("full_miss", miss)):
        paths[name] = {
            "spent": base["spent"],
            "payout": base["payout"],
            "pnl": base["pnl"],
            "equity_after": round(balance + float(base["pnl"]), 4),
            "roi_on_notional": round(float(base["pnl"]) / float(base["spent"]), 4)
            if base["spent"]
            else None,
        }

    for sc in STRESS:
        fr = _settle_with_friction(
            resized,
            slip=float(sc["entry_slip_cents"]),
            fee_bps=float(sc["taker_fee_bps"]),
            fill_ratio=float(sc["fill_ratio"]),
            min_leg_shares=1.0,
            min_leg_notional=0.5,
            max_basket_cost=0.50 + float(sc["entry_slip_cents"]) * 3,
        )
        if fr is None:
            paths[f"friction_{sc['name']}"] = {"executable": False}
            continue
        # win path under friction (keep hit_winner payout from fr)
        paths[f"friction_{sc['name']}_if_win"] = {
            "executable": True,
            "spent": fr.get("spent"),
            "pnl": fr.get("pnl"),
            "equity_after": round(balance + float(fr["pnl"]), 4),
            "win": fr.get("win"),
        }
        # miss path under same spent
        spent_f = float(fr["spent"])
        paths[f"friction_{sc['name']}_if_miss"] = {
            "executable": True,
            "spent": spent_f,
            "pnl": round(-spent_f, 4),
            "equity_after": round(balance - spent_f, 4),
            "note": "todas las piernas pierden; hold-to-resolution",
        }

    out["paths"] = paths
    return out


def compare_deposits(
    raw_takes: list[dict[str, Any]],
    *,
    balances: list[float],
    session_cap: float,
    budget_cfg: float,
) -> list[dict[str, Any]]:
    rows = []
    for bal in balances:
        for sc in STRESS:
            r = simulate_wallet_path(
                raw_takes,
                start=bal,
                scenario=sc,
                session_cap=session_cap,
                budget_cfg=budget_cfg if bal >= 5 else min(budget_cfg, effective_cap(bal)),
            )
            rows.append(r)
    return rows


def live_book_snapshot(cfg: dict[str, Any]) -> dict[str, Any] | None:
    try:
        from polymarket.research.local_lab.weather_ladder_live import run_book_sim

        book = run_book_sim(cfg, session_id="wallet_reality_book")
        return {
            "events_open": book.get("events_open"),
            "accepted_n": book.get("accepted_n"),
            "accepted": book.get("accepted") or [],
            "near_miss": book.get("near_miss") or [],
            "notional_total_usdc": book.get("notional_total_usdc"),
        }
    except Exception as e:
        return {"error": str(e)}


def force_near_miss_counterfactual(near_miss: list[dict[str, Any]], balance: float) -> list[dict[str, Any]]:
    """Show why DNA rejects near-miss AND what PnL math would look like if forced (NOT recommended)."""
    cap = effective_cap(balance)
    rows = []
    for nm in near_miss:
        basket = float(nm.get("basket_cost") or 0)
        skip = str(nm.get("skip") or "")
        dna_ok = basket <= 0.50 + 1e-12 and "not_underdispersed" not in skip and "max_leg" not in skip
        # Rough EV from report field if present
        ev = nm.get("basket_ev")
        # Hypothetical equal 3-leg spend of min(budget, cap) — illustrative only
        notional = min(3.0, cap)
        # If one winning leg pays ~ shares ≈ notional/3 / avg_px; use basket as sum of asks
        # Expected value style: EV_dollars ≈ notional * (ev / max(basket, 1e-9)) when ev is model edge on $1 basket
        pnl_if_edge_realizes = None
        if ev is not None and basket > 0:
            # basket_ev is expected surplus on $1 face of basket asks; scale to notional
            pnl_if_edge_realizes = round(float(ev) * (notional / max(basket, 1e-9)), 4)
        rows.append(
            {
                "slug": nm.get("slug"),
                "city": nm.get("city"),
                "day": nm.get("day"),
                "basket_cost": basket,
                "basket_ev": ev,
                "skip": skip,
                "dna_accept": dna_ok,
                "policy": "REJECT — DNA gate" if not dna_ok else "ACCEPT path",
                "if_forced_notional_usdc": notional if not dna_ok else None,
                "if_forced_model_ev_usd_approx": pnl_if_edge_realizes if not dna_ok else None,
                "warning": (
                    "Forzar near-miss diluye WR certificado; el bot NO lo hace."
                    if not dna_ok
                    else None
                ),
            }
        )
    return rows


def render_markdown(report: dict[str, Any]) -> str:
    bal = report["wallet"]["balance_usdc"]
    cap = report["wallet"]["effective_cap_usdc"]
    w = report["what_if_take_now"]
    lines = [
        "# Wallet Take Reality Sim",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Wallet:** `${bal}` · **effective cap:** `${cap}` · **session cap:** `${report['wallet']['session_cap_usdc']}`",
        f"**DNA:** press-only · basket≤0.50 · leg≤0.39 · underdispersion · floors CLOB",
        "",
        "## 1) ¿Puede ejecutarse un take ahora con este saldo?",
        "",
    ]
    if w.get("executable_now"):
        lines += [
            f"**SÍ (tamaño micro).** Notional sized ≈ `${w.get('notional_usdc')}`",
            f"Template: `{w.get('template', {}).get('city')}` `{w.get('template', {}).get('day')}` "
            f"basket={w.get('template', {}).get('basket_cost')}",
            "",
            "### Paths si aparece take DNA",
            "",
            "| Path | Spent | PnL | Equity after |",
            "|------|------:|----:|-------------:|",
        ]
        for k, p in (w.get("paths") or {}).items():
            if not isinstance(p, dict) or p.get("executable") is False:
                continue
            if "spent" not in p:
                continue
            lines.append(
                f"| `{k}` | {p.get('spent')} | {p.get('pnl')} | {p.get('equity_after')} |"
            )
    else:
        lines += [
            "**NO ejecutable ahora** aunque hubiera edge DNA en el libro.",
            f"Motivo: `{w.get('block_reason')}`",
            "",
        ]
        diag = w.get("floor_diagnosis") or {}
        if diag:
            lines += [
                f"Mínimo 3-leg con floors ≈ **${diag.get('min_notional_3leg')}**",
                f"Gap vs cap ≈ **${diag.get('gap_usdc')}**",
                "",
            ]

    lines += ["## 2) Replay histórico DNA con este bankroll", ""]
    lines += [
        "| Start | Scenario | Executed | WR | PnL | End | Skip floors | Skip cash |",
        "|------:|----------|---------:|---:|----:|----:|------------:|----------:|",
    ]
    for r in report.get("deposit_matrix") or []:
        if r["start_usdc"] not in report.get("highlight_starts", [bal, 25.0]):
            # still show all but markdown can be long — show all
            pass
        lines.append(
            f"| {r['start_usdc']} | {r['scenario']} | {r['n_executed']}/{r['n_universe']} | "
            f"{r['winrate']} | {r['total_pnl']} | {r['ending_equity']} | "
            f"{r['skipped_floor']} | {r['skipped_cash']} |"
        )

    lines += ["", "## 3) Estrés con misses (realismo)", ""]
    for name, st in (report.get("loss_stress") or {}).items():
        lines.append(
            f"- **{name}**: end `${st.get('ending_equity')}` · pnl `{st.get('total_pnl')}` · "
            f"ruined_below_$2=`{st.get('ruined_below_2')}` · "
            f"forced_idx `{st.get('forced_loss_indices')}` · n_exec `{st.get('n_executed')}`"
        )

    lines += ["", "## 4) Libro vivo (si disponible)", ""]
    book = report.get("live_book")
    if not book:
        lines.append("_Sin probe de libro en esta corrida._")
    elif book.get("error"):
        lines.append(f"_Error libro: `{book['error']}`_")
    else:
        lines.append(
            f"Open events: **{book.get('events_open')}** · accepted: **{book.get('accepted_n')}** · "
            f"near-miss: **{len(book.get('near_miss') or [])}**"
        )
        for nm in book.get("near_miss") or []:
            lines.append(
                f"- `{nm.get('city')}` basket={nm.get('basket_cost')} · `{nm.get('skip')}`"
            )

    lines += ["", "## 5) Contrafactual near-miss (NO se ejecuta)", ""]
    for row in report.get("near_miss_counterfactual") or []:
        lines.append(
            f"- **{row.get('city')}** {row.get('basket_cost')} → `{row.get('policy')}` "
            f"(EV approx if forced ${row.get('if_forced_model_ev_usd_approx')})"
        )

    lines += [
        "",
        "## 6) Veredicto operativo",
        "",
        f"- `{report['verdict']['code']}`: {report['verdict']['summary']}",
        f"- Recomendación: {report['verdict']['recommendation']}",
        "",
        "_Simulación research+floors+fricción. No es fill on-chain._",
        "",
    ]
    return "\n".join(lines)


def stress_with_forced_losses(
    raw_takes: list[dict[str, Any]],
    *,
    start: float,
    session_cap: float,
    budget_cfg: float,
    forced_loss_indices: set[int] | None = None,
    forced_loss_days: set[str] | None = None,
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay path but force full-miss on selected executable takes (0-based exec index)."""
    sc = scenario or STRESS[0]
    forced_loss_indices = forced_loss_indices or set()
    forced_loss_days = forced_loss_days or set()
    cash = float(start)
    peak = cash
    max_dd = 0.0
    rows: list[dict[str, Any]] = []
    ruined = False
    exec_i = 0
    for trade in sorted(raw_takes, key=lambda t: t["day"]):
        cap = effective_cap(cash, session_cap)
        budget = min(float(budget_cfg), cap)
        if budget < 2.0 or ruined:
            rows.append(
                {
                    "day": trade.get("day"),
                    "city": trade.get("city"),
                    "status": "skipped_insufficient" if not ruined else "halted_ruined",
                    "cash": round(cash, 4),
                }
            )
            continue
        resized = _resize_to_cap(trade, budget) or _resize_to_cap(trade, cap)
        if not resized:
            rows.append(
                {
                    "day": trade.get("day"),
                    "city": trade.get("city"),
                    "status": "skip_floor",
                    "cash": round(cash, 4),
                }
            )
            continue
        day = str(trade.get("day"))
        force = (exec_i in forced_loss_indices) or (day in forced_loss_days)
        if force:
            pnl = -float(resized["spent"])
            status = "forced_miss"
        else:
            fr = _settle_with_friction(
                resized,
                slip=float(sc["entry_slip_cents"]),
                fee_bps=float(sc["taker_fee_bps"]),
                fill_ratio=float(sc["fill_ratio"]),
                min_leg_shares=1.0,
                min_leg_notional=0.5,
                max_basket_cost=0.50 + float(sc["entry_slip_cents"]) * 3,
            )
            if fr is None:
                rows.append(
                    {
                        "day": day,
                        "city": trade.get("city"),
                        "status": "skip_friction",
                        "cash": round(cash, 4),
                    }
                )
                continue
            pnl = float(fr["pnl"])
            status = "win" if pnl > 0 else "loss"
        if float(resized["spent"]) > cash + 1e-9:
            rows.append({"day": day, "status": "skip_cash", "cash": round(cash, 4)})
            continue
        cash += pnl
        peak = max(peak, cash)
        max_dd = max(max_dd, (peak - cash) / peak if peak else 0.0)
        rows.append(
            {
                "day": day,
                "city": trade.get("city"),
                "exec_index": exec_i,
                "status": status,
                "spent": resized["spent"],
                "pnl": round(pnl, 4),
                "cash_after": round(cash, 4),
            }
        )
        exec_i += 1
        if cash < 2.0:
            ruined = True
    return {
        "start_usdc": start,
        "forced_loss_indices": sorted(forced_loss_indices),
        "forced_loss_days": sorted(forced_loss_days),
        "ending_equity": round(cash, 4),
        "total_pnl": round(cash - start, 4),
        "max_drawdown_frac": round(max_dd, 4),
        "ruined_below_2": ruined or cash < 2.0,
        "n_executed": exec_i,
        "trades": rows,
    }


def build_verdict(report_core: dict[str, Any]) -> dict[str, Any]:
    bal = float(report_core["wallet"]["balance_usdc"])
    w = report_core["what_if_take_now"]
    cur = [
        r
        for r in report_core["deposit_matrix"]
        if abs(r["start_usdc"] - bal) < 1e-6 and r["scenario"] == "base"
    ]
    cur_h = [
        r
        for r in report_core["deposit_matrix"]
        if abs(r["start_usdc"] - bal) < 1e-6 and r["scenario"] == "hostile"
    ]
    b25 = [
        r
        for r in report_core["deposit_matrix"]
        if r["start_usdc"] == 25.0 and r["scenario"] == "base"
    ]
    ls = report_core.get("loss_stress") or {}
    first_miss = ls.get("first_exec_miss") or {}
    first_miss_25 = ls.get("first_exec_miss_at_25") or {}
    exec_now = bool(w.get("executable_now"))
    n_cur = cur[0]["n_executed"] if cur else 0

    if first_miss.get("ruined_below_2") and exec_now:
        return {
            "code": "MICRO_TAKE_OK_BUT_ONE_LOSS_RUINS",
            "summary": (
                f"Con ${bal:.2f} un take DNA de ~${w.get('notional_usdc')} es sizeable. "
                f"Win → ~${(w.get('paths') or {}).get('clean_win', {}).get('equity_after')}; "
                f"miss → ~${(w.get('paths') or {}).get('full_miss', {}).get('equity_after')} "
                f"y el path se arruina (cash < $2). "
                f"Con $25, el mismo primer miss termina en ~${first_miss_25.get('ending_equity')}."
            ),
            "recommendation": (
                "Seguir en WAIT DNA-gated. Antes del primer take real, depositar ≥$25 "
                "para sobrevivir 1 miss. No forzar near-miss."
            ),
            "current_base_executed": n_cur,
            "compare_25_base_executed": b25[0]["n_executed"] if b25 else None,
            "hostile_pnl_at_wallet": cur_h[0]["total_pnl"] if cur_h else None,
            "first_miss_end": first_miss.get("ending_equity"),
            "first_miss_at_25_end": first_miss_25.get("ending_equity"),
        }
    if not exec_now and bal < 5:
        return {
            "code": "WALLET_BELOW_LIVE_FLOOR_BASKET",
            "summary": (
                f"Con ${bal:.2f} el bot puede vigilar, pero un take DNA de 3 piernas "
                "suele chocar con floors CLOB (5 shares + ≥$1/pierna) tras el bump."
            ),
            "recommendation": (
                "Depositar ≥$10–25 para holgura real de notional; mantener DNA; "
                "no forzar near-miss. Hasta entonces: WAIT sin gastar."
            ),
            "current_base_executed": n_cur,
            "compare_25_base_executed": b25[0]["n_executed"] if b25 else None,
            "hostile_pnl_at_wallet": cur_h[0]["total_pnl"] if cur_h else None,
        }
    if exec_now:
        win_eq = (w.get("paths") or {}).get("clean_win", {}).get("equity_after")
        miss_eq = (w.get("paths") or {}).get("full_miss", {}).get("equity_after")
        return {
            "code": "TAKE_SIZABLE_AT_WALLET",
            "summary": (
                f"Un take DNA cabría a notional ≈${w.get('notional_usdc')}. "
                f"Win → equity≈${win_eq}; miss → equity≈${miss_eq}."
            ),
            "recommendation": (
                "Mantener auto-execute DNA-gated. Un miss deja el bankroll muy fino; "
                "ideal depositar a ≥$25 para absorber 1 loss y seguir."
            ),
            "current_base_executed": n_cur,
            "compare_25_base_executed": b25[0]["n_executed"] if b25 else None,
            "hostile_pnl_at_wallet": cur_h[0]["total_pnl"] if cur_h else None,
        }
    return {
        "code": "WATCH_ONLY",
        "summary": "Sin capacidad clara de postear basket DNA al tamaño actual.",
        "recommendation": "Esperar edge + reforzar balance.",
        "current_base_executed": n_cur,
        "compare_25_base_executed": b25[0]["n_executed"] if b25 else None,
        "hostile_pnl_at_wallet": cur_h[0]["total_pnl"] if cur_h else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Wallet take reality simulation")
    ap.add_argument("--balance", type=float, default=3.4482, help="Current Polymarket USDC balance")
    ap.add_argument("--session-cap", type=float, default=5.0)
    ap.add_argument("--budget", type=float, default=3.0)
    ap.add_argument("--live-book", action="store_true", help="Probe live CLOB book_sim")
    ap.add_argument(
        "--balances",
        default="3.4482,5,10,25",
        help="Comma list of starting balances for matrix",
    )
    args = ap.parse_args()

    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    raw = take_income_wr80(cases)
    print(f"DNA historical takes={len(raw)} balance={args.balance}", flush=True)

    bal_list = [float(x.strip()) for x in str(args.balances).split(",") if x.strip()]
    if args.balance not in bal_list:
        bal_list = [float(args.balance)] + bal_list

    matrix = compare_deposits(
        raw,
        balances=bal_list,
        session_cap=float(args.session_cap),
        budget_cfg=float(args.budget),
    )
    for r in matrix:
        if abs(r["start_usdc"] - float(args.balance)) < 1e-6 or r["start_usdc"] in (25.0, 10.0, 5.0):
            print(
                f"  ${r['start_usdc']:.2f} {r['scenario']}: exec={r['n_executed']}/{r['n_universe']} "
                f"WR={r['winrate']} pnl={r['total_pnl']} end={r['ending_equity']} "
                f"skip_floor={r['skipped_floor']} skip_cash={r['skipped_cash']}",
                flush=True,
            )

    what_if = what_if_single_take(
        raw,
        balance=float(args.balance),
        session_cap=float(args.session_cap),
        budget_cfg=float(args.budget),
    )
    print(
        f"what_if executable={what_if.get('executable_now')} "
        f"reason={what_if.get('block_reason') or what_if.get('notional_usdc')}",
        flush=True,
    )

    # Ruin / survival stresses on chronological DNA path (by executable index)
    loss_stress = {
        "first_exec_miss": stress_with_forced_losses(
            raw,
            start=float(args.balance),
            session_cap=float(args.session_cap),
            budget_cfg=float(args.budget),
            forced_loss_indices={0},
        ),
        "first_two_exec_miss": stress_with_forced_losses(
            raw,
            start=float(args.balance),
            session_cap=float(args.session_cap),
            budget_cfg=float(args.budget),
            forced_loss_indices={0, 1},
        ),
        "first_exec_miss_at_25": stress_with_forced_losses(
            raw,
            start=25.0,
            session_cap=float(args.session_cap),
            budget_cfg=float(args.budget),
            forced_loss_indices={0},
        ),
        "mid_path_one_miss_idx3": stress_with_forced_losses(
            raw,
            start=float(args.balance),
            session_cap=float(args.session_cap),
            budget_cfg=float(args.budget),
            forced_loss_indices={3},
        ),
    }
    for k, v in loss_stress.items():
        print(
            f"  stress {k}: end={v['ending_equity']} ruined={v['ruined_below_2']} pnl={v['total_pnl']}",
            flush=True,
        )

    live_book = None
    near_cf: list[dict[str, Any]] = []
    if args.live_book:
        print("probing live book_sim…", flush=True)
        live_book = live_book_snapshot(cfg)
        if live_book and not live_book.get("error"):
            near_cf = force_near_miss_counterfactual(
                list(live_book.get("near_miss") or []), float(args.balance)
            )

    report: dict[str, Any] = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "profile": "weather_ladder_definitive_real_v1",
        "mode": "simulation_only_no_orders",
        "wallet": {
            "balance_usdc": round(float(args.balance), 4),
            "session_cap_usdc": float(args.session_cap),
            "budget_per_market_usdc": float(args.budget),
            "effective_cap_usdc": effective_cap(float(args.balance), float(args.session_cap)),
            "min_balance_to_arm_usdc": float((cfg.get("live") or {}).get("min_balance_to_arm_usdc") or 2),
        },
        "dna_universe_n": len(raw),
        "dna_days": [t.get("day") for t in raw],
        "what_if_take_now": what_if,
        "loss_stress": loss_stress,
        "deposit_matrix": matrix,
        "highlight_starts": [float(args.balance), 5.0, 10.0, 25.0],
        "live_book": live_book,
        "near_miss_counterfactual": near_cf,
        "caveat": (
            "Simulación con entry histórico CLOB + floors live + fricción taker. "
            "Replay base hereda WR research (muestra pequeña); loss_stress fuerza misses. "
            "No garantiza fills on-chain. El bot real solo ejecuta si DNA+cap+geoblock OK."
        ),
    }
    report["verdict"] = build_verdict(report)

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"reality_{stamp}.json"
    latest = OUT / "latest.json"
    md_path = OUT / f"reality_{stamp}.md"
    latest_md = OUT / "LATEST.md"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_markdown(report)
    md_path.write_text(md, encoding="utf-8")
    latest_md.write_text(md, encoding="utf-8")

    print(json.dumps({"verdict": report["verdict"], "report": str(path)}, indent=2))
    print(f"markdown -> {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
