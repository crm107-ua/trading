#!/usr/bin/env python3
"""
Hyper-realistic LIVE market verification for Temperature Ladder (SAFE, no posts).

Hits real Polymarket Gamma + CLOB right now:
  1) Discover open weather markets (SG/SH/HK/BJ, horizons)
  2) Pull full order books per ladder-leg token
  3) Walk-the-book fill simulation at $12/$25/$50 budgets (FAK-like)
  4) DNA revalidation at live asks (basket/leg/UD)
  5) Spread, depth, latency, partial-fill / abort-partial risk
  6) evaluate_real_stack (wallet + geo + accepted/near-miss)
  7) What-if after $100 deposit: could we fill a DNA take NOW?

Never sets ALLOW_REARM. Never posts orders.

  python3 -m polymarket.research.local_lab.hyperreal_market_verify
  python3 -m polymarket.research.local_lab.hyperreal_market_verify --write-docs
  python3 -m polymarket.research.local_lab.hyperreal_market_verify --budgets 12,25,50
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.data.book_utils import best_bid_ask
from polymarket.src.execution.clob_live import MIN_BUY_NOTIONAL_USDC, MIN_ORDER_SHARES, normalize_live_order

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "hyperreal_market"
DOCS = POLY / "docs"
VPS = POLY / "data_local" / "local_lab" / "vps_runs"
CLOB = "https://clob.polymarket.com"
GAMMA = "https://gamma-api.polymarket.com"

HIGH_CFG = POLY / "config" / "weather_ladder_high_income.json"
DEF_CFG = POLY / "config" / "weather_ladder_definitive_real.json"
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"

# Wide live universe for hyperreal (DNA gates still only certify core)
DNA_CITIES = ("singapore", "shanghai", "hong-kong", "beijing")
# Extra cities seen in cases.json + common Polymarket weather probes
EXTRA_CITIES = (
    "seoul",
    "tokyo",
    "taipei",
    "miami",
    "wellington",
    "london",
    "nyc",
    "new-york-city",
    "chicago",
    "dallas",
    "austin",
    "los-angeles",
    "san-francisco",
    "toronto",
    "paris",
    "berlin",
    "mumbai",
    "delhi",
    "bangkok",
    "jakarta",
    "manila",
    "sydney",
    "melbourne",
)
WIDE_HORIZONS = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14)
# Diagnostic-only basket thresholds (never promote to live DNA)
COUNTERFACTUAL_BASKETS = (0.50, 0.52, 0.55, 0.58, 0.60, 0.65, 0.70, 0.80)
DEPOSIT_WHATIFS = (50.0, 100.0, 200.0, 500.0, 1000.0)
SLIP_STRESS_CENTS = (0.0, 0.01, 0.02, 0.05)


def _fetch_book(client: httpx.Client, token_id: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    r = client.get(f"{CLOB}/book", params={"token_id": token_id}, timeout=15.0)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "latency_ms": ms, "asks": [], "bids": []}
    data = r.json()
    asks = data.get("asks") or []
    bids = data.get("bids") or []
    # Normalize: sort asks ascending price, bids descending
    def _px(level: dict) -> float:
        return float(level.get("price") or level.get("p") or 0)

    def _sz(level: dict) -> float:
        return float(level.get("size") or level.get("s") or 0)

    asks_s = sorted([{"price": _px(a), "size": _sz(a)} for a in asks if _px(a) > 0], key=lambda x: x["price"])
    bids_s = sorted(
        [{"price": _px(b), "size": _sz(b)} for b in bids if _px(b) > 0],
        key=lambda x: -x["price"],
    )
    bb, ba = best_bid_ask(bids_s, asks_s)
    spread = (ba - bb) if bb is not None and ba is not None else None
    ask_depth_5 = sum(a["size"] for a in asks_s[:5])
    ask_notional_5 = sum(a["size"] * a["price"] for a in asks_s[:5])
    return {
        "ok": True,
        "latency_ms": ms,
        "best_bid": bb,
        "best_ask": ba,
        "spread": round(spread, 4) if spread is not None else None,
        "ask_levels": len(asks_s),
        "bid_levels": len(bids_s),
        "ask_depth_top5_shares": round(ask_depth_5, 4),
        "ask_notional_top5_usdc": round(ask_notional_5, 4),
        "asks": asks_s[:20],
        "bids": bids_s[:10],
    }


def walk_book_buy(asks: list[dict[str, Any]], *, shares_needed: float, cap_price: float | None = None) -> dict[str, Any]:
    """Simulate taking liquidity up the ask book until shares filled or book ends."""
    remaining = float(shares_needed)
    spent = 0.0
    filled = 0.0
    worst_px = None
    levels_used = 0
    for lvl in asks:
        px = float(lvl["price"])
        sz = float(lvl["size"])
        if cap_price is not None and px > cap_price + 1e-12:
            break
        take = min(remaining, sz)
        if take <= 0:
            continue
        spent += take * px
        filled += take
        remaining -= take
        worst_px = px
        levels_used += 1
        if remaining <= 1e-9:
            break
    avg = (spent / filled) if filled > 1e-12 else None
    return {
        "shares_needed": round(shares_needed, 4),
        "filled_shares": round(filled, 4),
        "fill_ratio": round(filled / shares_needed, 4) if shares_needed > 0 else 0.0,
        "spent_usdc": round(spent, 4),
        "avg_fill_px": round(avg, 4) if avg is not None else None,
        "worst_fill_px": worst_px,
        "levels_used": levels_used,
        "unfilled": round(max(0.0, remaining), 4),
        "complete": remaining <= 1e-9,
    }


def probe_latency(client: httpx.Client) -> dict[str, Any]:
    out = {}
    for name, url, params in (
        ("gamma_events", f"{GAMMA}/events", {"limit": 1, "active": "true"}),
        ("clob_time", f"{CLOB}/time", None),
        ("clob_ok", f"{CLOB}/ok", None),
    ):
        t0 = time.perf_counter()
        try:
            r = client.get(url, params=params, timeout=15.0)
            out[name] = {
                "ok": r.status_code < 500,
                "status": r.status_code,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except Exception as e:
            out[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return out


def analyze_candidate_books(
    client: httpx.Client,
    cand: dict[str, Any],
    *,
    budgets: list[float],
    slip_cents: float = 0.01,
) -> dict[str, Any]:
    legs = cand.get("legs") or []
    if not legs:
        return {"slug": cand.get("slug"), "ok": False, "reason": "no_legs"}

    leg_books = []
    for leg in legs:
        tid = leg.get("token_id")
        if not tid:
            leg_books.append({"name": leg.get("name"), "ok": False, "reason": "no_token"})
            continue
        book = _fetch_book(client, str(tid))
        quoted = float(leg.get("price") or 0)
        ba = book.get("best_ask")
        slip_vs_quote = (ba - quoted) if ba is not None else None
        leg_books.append(
            {
                "name": leg.get("name"),
                "token_id": str(tid)[:16] + "…",
                "quoted_px": quoted,
                "book": {
                    k: book.get(k)
                    for k in (
                        "ok",
                        "latency_ms",
                        "best_bid",
                        "best_ask",
                        "spread",
                        "ask_levels",
                        "bid_levels",
                        "ask_depth_top5_shares",
                        "ask_notional_top5_usdc",
                    )
                },
                "slip_vs_quote": round(slip_vs_quote, 4) if slip_vs_quote is not None else None,
                "asks_top": (book.get("asks") or [])[:5],
            }
        )

    # Basket at best asks
    best_asks = []
    for lb, leg in zip(leg_books, legs):
        ba = (lb.get("book") or {}).get("best_ask")
        if ba is None:
            best_asks.append(None)
        else:
            best_asks.append(float(ba) + float(slip_cents))
    if any(x is None for x in best_asks):
        live_basket = None
    else:
        live_basket = round(sum(best_asks), 4)

    fill_sims = {}
    for budget in budgets:
        # Equal-dollar wings approx: split budget across legs proportional to quoted dollars
        spent0 = sum(float(l.get("dollars") or 0) for l in legs) or 1.0
        scale = float(budget) / spent0
        leg_fills = []
        all_complete = True
        total_spent = 0.0
        for lb, leg in zip(leg_books, legs):
            asks = []
            # re-fetch asks from stored top — need full walk; re-get from book field incomplete
            # Use asks_top only is weak; re-fetch book asks via token
            tid = leg.get("token_id")
            book = _fetch_book(client, str(tid)) if tid else {"asks": []}
            asks = book.get("asks") or []
            dollars = float(leg.get("dollars") or 0) * scale
            px0 = float((lb.get("book") or {}).get("best_ask") or leg.get("price") or 0.5)
            shares0 = dollars / px0 if px0 > 0 else 0.0
            px, sz = normalize_live_order(side="BUY", price=px0, size=shares0)
            # Cap walk at quoted+slip+2c hostile
            cap = px + 0.02
            walk = walk_book_buy(asks, shares_needed=sz, cap_price=cap)
            if not walk["complete"] or walk["fill_ratio"] < 0.80:
                all_complete = False
            total_spent += float(walk["spent_usdc"] or 0)
            leg_fills.append(
                {
                    "name": leg.get("name"),
                    "target_shares": sz,
                    "target_px": px,
                    "walk": walk,
                }
            )
        # Abort-partial risk: if any leg incomplete, whole DNA basket should abort
        fill_sims[f"budget_{budget:g}"] = {
            "budget": budget,
            "all_legs_complete_at_cap": all_complete,
            "abort_partial_would_trigger": not all_complete,
            "total_spent_if_partial_ok": round(total_spent, 4),
            "legs": leg_fills,
        }

    return {
        "slug": cand.get("slug"),
        "city": cand.get("city"),
        "day": cand.get("day"),
        "dna_take": bool(cand.get("dna_take") or cand.get("accepted")),
        "skip": cand.get("skip"),
        "plan_basket": cand.get("basket_cost"),
        "live_basket_best_ask_plus_slip": live_basket,
        "underdispersed": cand.get("underdispersed"),
        "leg_books": leg_books,
        "fill_sims": fill_sims,
        "books_ok": all((lb.get("book") or {}).get("ok") for lb in leg_books if lb.get("book")),
    }


def dna_distance(row: dict[str, Any], *, max_basket: float = 0.50, max_leg: float = 0.39) -> dict[str, Any]:
    bc = row.get("basket_cost")
    legs = row.get("legs") or []
    max_leg_px = None
    if legs:
        try:
            max_leg_px = max(float(l.get("price") or 0) for l in legs)
        except Exception:
            max_leg_px = None
    ud = row.get("underdispersed")
    gap_b = (float(bc) - max_basket) if bc is not None else None
    gap_l = (float(max_leg_px) - max_leg) if max_leg_px is not None else None
    gates = {
        "basket_ok": bc is not None and float(bc) <= max_basket + 1e-12,
        "leg_ok": max_leg_px is not None and float(max_leg_px) <= max_leg + 1e-12,
        "ud_ok": bool(ud) is True,
    }
    return {
        "gates": gates,
        "gates_passed": sum(1 for v in gates.values() if v),
        "gap_basket": round(gap_b, 4) if gap_b is not None else None,
        "gap_leg": round(gap_l, 4) if gap_l is not None else None,
        "basket": bc,
        "max_leg": max_leg_px,
        "ud": ud,
    }


def wide_scan_cfg(base: dict[str, Any]) -> dict[str, Any]:
    """Maximize open-market coverage for hyperreal (not for live posting)."""
    cfg = dict(base)
    cfg["cities"] = list(DNA_CITIES) + list(EXTRA_CITIES)
    cfg["city_priority"] = list(DNA_CITIES) + list(EXTRA_CITIES)
    cfg["exclude_cities"] = []
    cfg["prefer_horizons"] = list(WIDE_HORIZONS)
    cfg["limit_per_city"] = 40
    cfg["max_markets_per_run"] = 160
    cfg["max_per_city"] = 16
    cfg["resolved_max_age_days"] = 0
    cfg["open_only"] = True
    cfg["use_clob_asks"] = True
    return cfg


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    z2 = z * z
    den = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    marg = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n)
    return max(0.0, (centre - marg) / den)


def historical_cases_breadth() -> dict[str, Any]:
    """Contemplate full resolved-case universe (not just live)."""
    from collections import Counter

    from polymarket.research.local_lab.assure_wr80_income import take_income_wr80

    if not CASES.exists():
        return {"ok": False, "reason": "no_cases"}
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    takes = take_income_wr80(cases)
    by_city = Counter(c.get("city") for c in cases)
    take_city = Counter(t.get("city") for t in takes)
    by_hz = Counter(c.get("horizon") for c in cases if c.get("horizon") is not None)
    take_hz = Counter(t.get("horizon") for t in takes if t.get("horizon") is not None)
    days = sorted({c.get("day") for c in cases if c.get("day")})
    wins = [bool(t.get("win")) for t in takes]
    # Streak taxonomy
    max_win_streak = max_loss_streak = cur_w = cur_l = 0
    for w in wins:
        if w:
            cur_w += 1
            cur_l = 0
            max_win_streak = max(max_win_streak, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            max_loss_streak = max(max_loss_streak, cur_l)
    n = len(takes)
    k = sum(1 for w in wins if w)
    baskets = [float(t.get("basket_cost") or t.get("basket") or 0) for t in takes]
    pnls = [float(t.get("pnl") or 0) for t in takes]
    return {
        "ok": True,
        "n_cases": len(cases),
        "n_dna_takes": n,
        "dna_wins": k,
        "dna_wr_point": round(k / n, 4) if n else None,
        "dna_wilson95": round(_wilson_lower(k, n), 4) if n else None,
        "day_min": days[0] if days else None,
        "day_max": days[-1] if days else None,
        "n_days": len(days),
        "n_cities": len(by_city),
        "n_horizons": len(by_hz),
        "cases_by_city": dict(by_city),
        "dna_takes_by_city": dict(take_city),
        "cases_by_horizon": {str(k): v for k, v in sorted(by_hz.items(), key=lambda x: (x[0] is None, x[0]))},
        "dna_takes_by_horizon": {str(k): v for k, v in sorted(take_hz.items(), key=lambda x: (x[0] is None, x[0]))},
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "basket_min": round(min(baskets), 4) if baskets else None,
        "basket_max": round(max(baskets), 4) if baskets else None,
        "basket_mean": round(sum(baskets) / len(baskets), 4) if baskets else None,
        "pnl_sum": round(sum(pnls), 4) if pnls else None,
        "coverage_note": "Historical resolved universe; live scan is separate.",
    }


def contemplate_case_matrix(
    *,
    hist: dict[str, Any],
    pack: dict[str, Any],
    book_reports: list[dict[str, Any]],
    balance: float | None,
) -> dict[str, Any]:
    """Many what-if / taxonomy cases beyond the live DNA take snapshot."""
    from collections import Counter

    rows = list(pack.get("accepted") or []) + list(pack.get("near_miss") or []) + list(pack.get("skipped") or [])
    # Dedup by slug
    seen: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for r in rows:
        s = r.get("slug")
        if not s or s in seen:
            continue
        seen.add(s)
        uniq.append(r)

    skip_tax = Counter(str(r.get("skip") or "accepted") for r in uniq)
    gate_tax = Counter()
    distances = []
    for r in uniq:
        d = dna_distance(r)
        g = d["gates"]
        key = (
            f"b{'1' if g['basket_ok'] else '0'}"
            f"_l{'1' if g['leg_ok'] else '0'}"
            f"_u{'1' if g['ud_ok'] else '0'}"
        )
        gate_tax[key] += 1
        distances.append(
            {
                "slug": r.get("slug"),
                "city": r.get("city"),
                "day": r.get("day"),
                "skip": r.get("skip"),
                **d,
            }
        )
    distances.sort(
        key=lambda x: (
            -int(x.get("gates_passed") or 0),
            float(x.get("gap_basket") if x.get("gap_basket") is not None else 99),
        )
    )

    # Counterfactual: how many open rows would pass if basket max were X (leg+UD fixed)
    counterfactual = []
    for mx in COUNTERFACTUAL_BASKETS:
        n_pass = 0
        for r in uniq:
            d = dna_distance(r, max_basket=mx)
            if d["gates_passed"] == 3:
                n_pass += 1
        counterfactual.append(
            {
                "max_basket": mx,
                "would_pass_gates": n_pass,
                "note": "diagnostic_only_not_live_dna" if mx > 0.50 + 1e-12 else "canonical_dna",
            }
        )

    # Slip stress on book walks: recompute live basket + slip vs DNA 0.50
    slip_stress = []
    for slip in SLIP_STRESS_CENTS:
        n_under = 0
        for b in book_reports:
            live = b.get("live_basket_best_ask_plus_slip")
            # live already includes default +0.01; approximate delta
            if live is None:
                continue
            adj = float(live) - 0.01 + float(slip)
            if adj <= 0.50 + 1e-12 and b.get("dna_universe"):
                # still need leg+UD from dna_distance if present
                dd = b.get("dna_distance") or {}
                g = dd.get("gates") or {}
                if g.get("leg_ok") and g.get("ud_ok"):
                    n_under += 1
        slip_stress.append({"slip_cents": slip, "dna_city_rows_basket_ok_with_leg_ud": n_under})

    # Deposit what-ifs: miss runway after deposit (budget $12 / worst miss ~budget)
    deposit_cases = []
    bal0 = float(balance or 0.0)
    for dep in DEPOSIT_WHATIFS:
        after = round(bal0 + dep, 2)
        for budget, n_miss in ((12.0, 1), (12.0, 2), (25.0, 1), (25.0, 2), (25.0, 3), (50.0, 2)):
            miss = budget  # conservative full-budget miss
            left = after - miss * n_miss
            deposit_cases.append(
                {
                    "deposit": dep,
                    "balance_after": after,
                    "budget": budget,
                    "n_misses": n_miss,
                    "left": round(left, 2),
                    "survives": left >= budget * 0.95,
                    "runway_go_style": dep >= 100 and after >= 100,
                }
            )

    # City × horizon live matrix (presence + closest basket)
    matrix = []
    by_ch: dict[tuple[str, Any], dict[str, Any]] = {}
    for r in uniq:
        city = str(r.get("city") or "")
        day = r.get("day")
        key = (city, day)
        bc = r.get("basket_cost")
        prev = by_ch.get(key)
        if prev is None or (bc is not None and float(bc) < float(prev.get("basket") or 99)):
            d = dna_distance(r)
            by_ch[key] = {
                "city": city,
                "day": day,
                "slug": r.get("slug"),
                "basket": bc,
                "gates_passed": d["gates_passed"],
                "ud": d["ud"],
                "skip": r.get("skip"),
            }
    matrix = sorted(by_ch.values(), key=lambda x: (str(x.get("city")), str(x.get("day"))))

    # Book liquidity taxonomy
    liq = Counter()
    for b in book_reports:
        f25 = ((b.get("fill_sims") or {}).get("budget_25") or {})
        if not b.get("leg_books") and b.get("ok") is False:
            liq["no_book"] += 1
        elif f25.get("all_legs_complete_at_cap"):
            liq["fillable_25"] += 1
        elif f25.get("abort_partial_would_trigger"):
            liq["abort_partial_25"] += 1
        else:
            liq["other"] += 1

    return {
        "n_unique_open_rows": len(uniq),
        "skip_taxonomy": dict(skip_tax),
        "gate_taxonomy": dict(gate_tax),
        "closest_distances": distances[:20],
        "counterfactual_basket_thresholds": counterfactual,
        "slip_stress": slip_stress,
        "deposit_whatifs": deposit_cases,
        "city_day_matrix": matrix,
        "liquidity_taxonomy": dict(liq),
        "historical_streaks": {
            "max_win_streak": hist.get("max_win_streak"),
            "max_loss_streak": hist.get("max_loss_streak"),
            "wilson95": hist.get("dna_wilson95"),
            "n_dna_takes": hist.get("n_dna_takes"),
        },
        "invariants_es": [
            "Counterfactuales >0.50 NO cambian DNA live.",
            "Depósito what-if ≠ permiso de auto-execute.",
            "Taxonomía de skips explica por qué no hay take ahora.",
        ],
    }


def calendar_probe_slugs(cities: list[str], horizons: tuple[int, ...]) -> list[str]:
    """Force calendar slug probes beyond search discovery."""
    from datetime import timedelta

    months = [
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
    ]
    today = datetime.now(timezone.utc).date()
    slugs = []
    with httpx.Client(timeout=20.0) as client:
        for city in cities:
            for hz in horizons:
                d = today + timedelta(days=hz)
                slug = f"highest-temperature-in-{city}-on-{months[d.month - 1]}-{d.day}-{d.year}"
                try:
                    r = client.get(f"{GAMMA}/events", params={"slug": slug})
                    if r.status_code == 200 and r.json():
                        slugs.append(slug)
                except Exception:
                    continue
    # de-dupe
    seen: set[str] = set()
    out = []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _ensure_leg_tokens(cand: dict[str, Any]) -> dict[str, Any]:
    """If legs lack token_id, re-fetch live event and map by bucket name."""
    legs = list(cand.get("legs") or [])
    if legs and all(l.get("token_id") for l in legs):
        return cand
    slug = cand.get("slug")
    if not slug:
        return cand
    from polymarket.src.weather.markets import fetch_temp_event

    ev = fetch_temp_event(str(slug), use_clob=True)
    if ev is None:
        return cand
    by_name = {b.name: b for b in ev.buckets}
    new_legs = []
    for leg in legs:
        name = str(leg.get("name") or "")
        b = by_name.get(name)
        row = dict(leg)
        if b is not None:
            row["token_id"] = b.token_yes
            if row.get("price") is None and b.ask is not None:
                row["price"] = b.ask
        new_legs.append(row)
    # If plan had no legs, build token map for top-3 cheapest asks (diagnostic only)
    if not new_legs and ev.buckets:
        cheap = sorted([b for b in ev.buckets if b.ask is not None], key=lambda b: float(b.ask))[:3]
        for b in cheap:
            new_legs.append(
                {
                    "name": b.name,
                    "price": b.ask,
                    "token_id": b.token_yes,
                    "dollars": 4.0,
                    "shares": 4.0 / float(b.ask) if b.ask else 0,
                }
            )
    out = dict(cand)
    out["legs"] = new_legs
    return out


def run(*, budgets: list[float] | None = None, write_docs: bool = False, wide: bool = True) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ.pop("POLY_LADDER_ALLOW_REARM", None)
    os.environ.pop("POLY_LADDER_REAL_CONFIRM", None)

    budgets = budgets or [12.0, 25.0, 50.0]
    from polymarket.research.local_lab.weather_ladder_paper import load_cfg
    from polymarket.research.local_lab.weather_ladder_real import evaluate_real_stack
    from polymarket.research.local_lab.weather_ladder_live import prepare_candidates
    from polymarket.src.execution.live_policy import check_geoblock, geoblock_blocks_real

    cfg_high = load_cfg(HIGH_CFG)
    cfg_def = load_cfg(DEF_CFG)

    hist = historical_cases_breadth()
    print(
        f"historical cases n={hist.get('n_cases')} dna_takes={hist.get('n_dna_takes')} "
        f"days={hist.get('n_days')}",
        flush=True,
    )

    print("latency probes…", flush=True)
    with httpx.Client(timeout=20.0) as client:
        latency = probe_latency(client)

        print("evaluate_real_stack high…", flush=True)
        stack_micro = evaluate_real_stack(cfg_def)
        os.environ["POLY_LADDER_HIGH_INCOME"] = "1"
        stack_high = evaluate_real_stack(cfg_high)
        os.environ.pop("POLY_LADDER_HIGH_INCOME", None)

        print("wide prepare_candidates…", flush=True)
        cfg_scan = wide_scan_cfg(cfg_high) if wide else dict(cfg_high)
        if not wide:
            cfg_scan["max_markets_per_run"] = 12
            cfg_scan["max_per_city"] = 3
        pack = prepare_candidates(cfg_scan)

        # Extra calendar probes → synthetic skipped rows if missing from pack
        # Calendar slug spam only on cities that historically exist / DNA core
        print("calendar slug probes…", flush=True)
        cal_cities = list(DNA_CITIES) + ["seoul", "tokyo", "taipei", "miami", "wellington"]
        cal_slugs = calendar_probe_slugs(cal_cities, WIDE_HORIZONS if wide else (0, 1, 2, 3))
        known = {r.get("slug") for r in (pack.get("accepted") or [])}
        known |= {r.get("slug") for r in (pack.get("near_miss") or [])}
        known |= {r.get("slug") for r in (pack.get("skipped") or [])}
        extra_rows = []
        from polymarket.src.weather.markets import fetch_temp_event

        for slug in cal_slugs:
            if slug in known:
                continue
            try:
                ev = fetch_temp_event(slug, use_clob=True)
            except Exception:
                continue
            if ev is None or ev.closed:
                continue
            # Build diagnostic candidate from cheapest 3 asks
            cheap = sorted([b for b in ev.buckets if b.ask is not None], key=lambda b: float(b.ask))[:3]
            if len(cheap) < 3:
                continue
            bc = sum(float(b.ask) for b in cheap)
            legs = [
                {
                    "name": b.name,
                    "price": b.ask,
                    "token_id": b.token_yes,
                    "dollars": 4.0,
                    "shares": 4.0 / float(b.ask),
                }
                for b in cheap
            ]
            row = {
                "slug": slug,
                "city": ev.city,
                "day": ev.day.isoformat() if hasattr(ev.day, "isoformat") else str(ev.day),
                "skip": "calendar_probe_not_in_plan",
                "basket_cost": round(bc, 4),
                "legs": legs,
                "underdispersed": None,
                "dna_take": False,
                "source": "calendar_probe",
            }
            extra_rows.append(row)
            known.add(slug)

        # Targets: ALL accepted + ALL near_miss + ALL skipped with legs + calendar extras
        targets: list[dict[str, Any]] = []
        seen_t: set[str] = set()

        def _add(rows: list[dict[str, Any]]) -> None:
            for r in rows:
                s = r.get("slug")
                if not s or s in seen_t:
                    continue
                if not r.get("legs") and r.get("source") != "calendar_probe":
                    continue
                seen_t.add(s)
                targets.append(r)

        _add(list(pack.get("accepted") or []))
        _add(list(pack.get("near_miss") or []))
        skipped = [s for s in (pack.get("skipped") or []) if s.get("legs")]
        skipped.sort(key=lambda s: float(s.get("basket_cost") or 99))
        _add(skipped)
        _add(extra_rows)

        print(
            f"book-walk {len(targets)} candidates "
            f"(accepted={len(pack.get('accepted') or [])} "
            f"near={len(pack.get('near_miss') or [])} "
            f"skipped_legs={len(skipped)} calendar_extra={len(extra_rows)})…",
            flush=True,
        )
        book_reports = []
        for i, cand0 in enumerate(targets):
            if i and i % 5 == 0:
                print(f"  …{i}/{len(targets)}", flush=True)
            cand = _ensure_leg_tokens(cand0)
            if cand.get("legs") and not any(l.get("token_id") for l in cand["legs"]):
                book_reports.append(
                    {
                        "slug": cand.get("slug"),
                        "city": cand.get("city"),
                        "ok": False,
                        "reason": "legs_without_token_id",
                        "plan_basket": cand.get("basket_cost"),
                        "dna_universe": str(cand.get("city") or "").lower() in DNA_CITIES,
                        "dna_distance": dna_distance(cand),
                    }
                )
                continue
            try:
                rep = analyze_candidate_books(client, cand, budgets=budgets)
                rep["dna_distance"] = dna_distance(cand)
                rep["dna_universe"] = str(cand.get("city") or "").lower() in DNA_CITIES
                book_reports.append(rep)
            except Exception as e:
                book_reports.append(
                    {
                        "slug": cand.get("slug"),
                        "ok": False,
                        "error": f"{type(e).__name__}: {e}",
                        "dna_universe": str(cand.get("city") or "").lower() in DNA_CITIES,
                    }
                )

    geo = check_geoblock()
    geo_blocked, geo_msg = geoblock_blocks_real()
    geo_raw: dict[str, Any] = {"repr": str(geo)}
    try:
        if isinstance(geo, dict):
            geo_raw = {k: (v if isinstance(v, (str, int, float, bool, type(None))) else str(v)) for k, v in geo.items()}
        else:
            for k in ("blocked", "country", "region", "ip", "ok", "message", "msg"):
                if hasattr(geo, k):
                    v = getattr(geo, k)
                    geo_raw[k] = v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
    except Exception as e:
        geo_raw["serialize_error"] = f"{type(e).__name__}: {e}"

    # Grade hyperreal
    books_ok_n = sum(1 for b in book_reports if b.get("books_ok") or b.get("ok") is not False and b.get("leg_books"))
    any_dna_now = len(pack.get("accepted") or []) >= 1
    fillable_at_25 = any(
        (b.get("fill_sims") or {}).get("budget_25", {}).get("all_legs_complete_at_cap")
        for b in book_reports
        if b.get("dna_take")
    )
    near = []
    for s in (pack.get("skipped") or []) + (pack.get("near_miss") or []):
        d = dna_distance(s)
        if d["gates_passed"] >= 2 or (d.get("gap_basket") is not None and d["gap_basket"] <= 0.05):
            near.append(
                {
                    "slug": s.get("slug"),
                    "city": s.get("city"),
                    "day": s.get("day"),
                    "skip": s.get("skip"),
                    **d,
                }
            )

    wallet = (stack_high.get("wallet") or {})
    bal = wallet.get("balance_pusd")
    deposit_needed_100 = None if bal is None else max(0.0, round(100.0 - float(bal), 2))

    checks = {
        "clob_reachable": bool((latency.get("clob_time") or latency.get("clob_ok") or {}).get("ok")),
        "gamma_reachable": bool((latency.get("gamma_events") or {}).get("ok")),
        "signing_or_balance": bool((stack_high.get("wallet") or {}).get("balance_pusd") is not None)
        or bool(((stack_high.get("checks") or {}).get("signing_ready"))),
        "geoblock_ok_here": not geo_blocked,
        "open_events_gt0": int(pack.get("events_open") or 0) > 0,
        "books_probed_ok": books_ok_n >= 1 or len(targets) == 0,
        "dna_take_live_now": any_dna_now,
        "fillable_dna_budget25_now": fillable_at_25,
        "near_miss_tracked": len(near) >= 0,
        "stack_env_safe": bool((stack_high.get("checks") or {}).get("env_starts_safe", True)),
    }
    # Hyperreal PASS for deposit runway does NOT require dna_take_live_now
    required_ok = all(
        checks[k]
        for k in (
            "clob_reachable",
            "gamma_reachable",
            "open_events_gt0",
            "books_probed_ok",
            "stack_env_safe",
        )
    )
    # Market realism: if geo blocked in this environment, note it (VPS should pass)
    if not checks["geoblock_ok_here"]:
        market_tradeable_here = False
    else:
        market_tradeable_here = True

    if required_ok and market_tradeable_here:
        verdict = "HYPERREAL_MARKET_LIVE_OK"
        action = (
            "Mercado live alcanzable; books CLOB leídos; DNA stack evaluado. "
            + (
                "HAY take DNA fillable ahora."
                if any_dna_now and fillable_at_25
                else "NO hay take DNA executable ahora (normal: baskets ricos / UD stuck). "
                "Depósito runway $100 sigue válido; operar solo cuando aparezca edge."
            )
        )
    elif required_ok and not market_tradeable_here:
        verdict = "HYPERREAL_MARKET_REACHABLE_GEO_BLOCK"
        action = (
            f"APIs OK pero geoblock aquí ({geo_msg}). Verifica en VPS región permitida. "
            "No postear desde este entorno."
        )
    else:
        fails = [k for k, v in checks.items() if not v and k in (
            "clob_reachable", "gamma_reachable", "open_events_gt0", "books_probed_ok", "stack_env_safe"
        )]
        verdict = "HYPERREAL_MARKET_FAIL"
        action = f"Fallos de mercado live: {fails}"

    # Coverage stats across all book walks
    dna_books = [b for b in book_reports if b.get("dna_universe")]
    extra_books = [b for b in book_reports if b.get("dna_universe") is False]
    fillable_any = sum(
        1
        for b in book_reports
        if ((b.get("fill_sims") or {}).get("budget_25") or {}).get("all_legs_complete_at_cap")
    )
    fillable_dna_universe = sum(
        1
        for b in dna_books
        if ((b.get("fill_sims") or {}).get("budget_25") or {}).get("all_legs_complete_at_cap")
    )
    baskets = [float(b.get("plan_basket") or b.get("live_basket_best_ask_plus_slip") or 99) for b in dna_books]
    baskets = [x for x in baskets if x < 90]
    closest_bc = min(baskets) if baskets else None

    many = contemplate_case_matrix(
        hist=hist,
        pack=pack,
        book_reports=book_reports,
        balance=float(bal) if bal is not None else None,
    )

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "action_es": action,
        "passed": required_ok,
        "checks": checks,
        "coverage": {
            "wide": wide,
            "horizons": list(WIDE_HORIZONS) if wide else [0, 1, 2, 3],
            "cities_scanned": list(cfg_scan.get("cities") or []),
            "events_open_pack": pack.get("events_open"),
            "targets_book_walked": len(targets),
            "calendar_slugs_found": len(cal_slugs),
            "calendar_extras_added": len(extra_rows),
            "book_reports": len(book_reports),
            "dna_universe_books": len(dna_books),
            "extra_city_books": len(extra_books),
            "fillable_budget25_any": fillable_any,
            "fillable_budget25_dna_cities": fillable_dna_universe,
            "closest_dna_city_basket": closest_bc,
            "historical": hist,
            "case_matrix": {
                "n_unique_open_rows": many.get("n_unique_open_rows"),
                "skip_taxonomy": many.get("skip_taxonomy"),
                "gate_taxonomy": many.get("gate_taxonomy"),
                "liquidity_taxonomy": many.get("liquidity_taxonomy"),
                "counterfactual_n": len(many.get("counterfactual_basket_thresholds") or []),
                "deposit_whatifs_n": len(many.get("deposit_whatifs") or []),
                "city_day_matrix_n": len(many.get("city_day_matrix") or []),
            },
        },
        "many_cases": many,
        "latency": latency,
        "geoblock": {"raw": geo_raw, "blocked": geo_blocked, "msg": geo_msg},
        "wallet": {
            "balance_pusd": bal,
            "deposit_needed_to_100": deposit_needed_100,
            "balance_error": wallet.get("balance_error"),
        },
        "stack_definitive": {
            "accepted_n": (stack_micro.get("market_now") or {}).get("accepted_n"),
            "events_open": (stack_micro.get("market_now") or {}).get("events_open"),
            "near_miss_n": len((stack_micro.get("market_now") or {}).get("near_miss") or []),
            "checks": stack_micro.get("checks"),
            "ready_to_arm": stack_micro.get("ready_to_arm"),
        },
        "stack_high": {
            "accepted_n": (stack_high.get("market_now") or {}).get("accepted_n"),
            "events_open": (stack_high.get("market_now") or {}).get("events_open"),
            "near_miss_n": len((stack_high.get("market_now") or {}).get("near_miss") or []),
            "accepted": (stack_high.get("market_now") or {}).get("accepted"),
            "near_miss": (stack_high.get("market_now") or {}).get("near_miss"),
            "checks": stack_high.get("checks"),
            "ready_to_arm": stack_high.get("ready_to_arm"),
            "session_limits": stack_high.get("session_limits"),
        },
        "scan": {
            "events_open": pack.get("events_open"),
            "accepted_n": len(pack.get("accepted") or []),
            "near_miss_n": len(pack.get("near_miss") or []),
            "skipped_n": len(pack.get("skipped") or []),
            "closest_near": near[:12],
        },
        "book_walks": book_reports,
        "budgets_tested": budgets,
        "invariants_es": [
            "No se posta ninguna orden.",
            "Sin DNA take live ≠ fallo de depósito runway.",
            "FAK/abort-partial: si una pierna no llena, se aborta el basket.",
            "Auto-execute sigue bloqueado por evidencia n<50.",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    VPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    (OUT / f"hyperreal_{stamp}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    md = render_md(report)
    (OUT / "LATEST.md").write_text(md, encoding="utf-8")
    (VPS / "HYPERREAL_MARKET_VERIFY.md").write_text(md, encoding="utf-8")
    if write_docs:
        DOCS.mkdir(parents=True, exist_ok=True)
        (DOCS / "HYPERREAL_MARKET_VERIFY.md").write_text(md, encoding="utf-8")
    return report


def render_md(report: dict[str, Any]) -> str:
    w = report.get("wallet") or {}
    many = report.get("many_cases") or {}
    lines = [
        "# Hyperreal market verify — Polymarket LIVE",
        "",
        f"**UTC:** `{report['ts_utc']}`",
        f"**Veredicto:** `{report['verdict']}`",
        "",
        report["action_es"],
        "",
        "## Checks",
    ]
    for k, v in (report.get("checks") or {}).items():
        lines.append(f"- `{k}`={v}")
    cov = report.get("coverage") or {}
    hist = cov.get("historical") or {}
    lines += [
        "",
        "## Cobertura ampliada",
        f"- wide={cov.get('wide')} horizons={cov.get('horizons')} cities={cov.get('cities_scanned')}",
        f"- events_open={cov.get('events_open_pack')} calendar_slugs={cov.get('calendar_slugs_found')} "
        f"extras={cov.get('calendar_extras_added')}",
        f"- book_walks={cov.get('book_reports')} (DNA cities={cov.get('dna_universe_books')} "
        f"extra={cov.get('extra_city_books')})",
        f"- fillable@$25: any={cov.get('fillable_budget25_any')} dna_cities={cov.get('fillable_budget25_dna_cities')}",
        f"- closest DNA-city basket live≈{cov.get('closest_dna_city_basket')}",
        f"- histórico cases={hist.get('n_cases')} dna_takes={hist.get('n_dna_takes')} "
        f"WR={hist.get('dna_wr_point')} Wilson95={hist.get('dna_wilson95')} "
        f"days={hist.get('n_days')} ({hist.get('day_min')}→{hist.get('day_max')})",
        f"- streaks win={hist.get('max_win_streak')} loss={hist.get('max_loss_streak')} "
        f"basket_mean={hist.get('basket_mean')}",
        f"- histórico by_city={hist.get('cases_by_city')} dna_takes_by_city={hist.get('dna_takes_by_city')}",
        f"- histórico by_horizon={hist.get('cases_by_horizon')}",
        "",
        "## Matriz de muchos casos",
        f"- open_rows únicos={many.get('n_unique_open_rows')}",
        f"- skip_taxonomy={many.get('skip_taxonomy')}",
        f"- gate_taxonomy (b/l/u)={many.get('gate_taxonomy')}",
        f"- liquidity_taxonomy={many.get('liquidity_taxonomy')}",
        "",
        "### Counterfactual basket (diagnóstico; DNA live sigue ≤0.50)",
    ]
    for c in many.get("counterfactual_basket_thresholds") or []:
        lines.append(
            f"- max_basket={c.get('max_basket')} → would_pass={c.get('would_pass_gates')} ({c.get('note')})"
        )
    lines += ["", "### Slip stress (DNA cities + leg+UD)"]
    for s in many.get("slip_stress") or []:
        lines.append(f"- slip={s.get('slip_cents')} → rows_ok={s.get('dna_city_rows_basket_ok_with_leg_ud')}")
    lines += ["", "### Deposit what-if (sobrevive N misses)"]
    for d in many.get("deposit_whatifs") or []:
        if d.get("budget") == 25.0 and d.get("n_misses") in (1, 2, 3) and d.get("deposit") in (100.0, 200.0, 500.0):
            lines.append(
                f"- dep=${d.get('deposit'):.0f} +bal→{d.get('balance_after')} "
                f"budget={d.get('budget')} misses={d.get('n_misses')} "
                f"left={d.get('left')} survives={d.get('survives')}"
            )
    lines += [
        "",
        "### City×day matrix (live)",
    ]
    for m in (many.get("city_day_matrix") or [])[:40]:
        lines.append(
            f"- {m.get('city')} {m.get('day')} bc={m.get('basket')} "
            f"gates={m.get('gates_passed')}/3 ud={m.get('ud')} skip={m.get('skip')}"
        )
    lines += [
        "",
        "## Wallet / geo",
        f"- balance={w.get('balance_pusd')} need_to_100={w.get('deposit_needed_to_100')}",
        f"- geoblock_blocked={((report.get('geoblock') or {}).get('blocked'))} "
        f"msg={((report.get('geoblock') or {}).get('msg'))}",
        "",
        "## Latency",
        f"- `{report.get('latency')}`",
        "",
        "## Stack high (live DNA scan)",
        f"- events_open={((report.get('stack_high') or {}).get('events_open'))} "
        f"accepted={((report.get('stack_high') or {}).get('accepted_n'))} "
        f"near_miss={((report.get('stack_high') or {}).get('near_miss_n'))} "
        f"ready_to_arm={((report.get('stack_high') or {}).get('ready_to_arm'))}",
        "",
        "## Closest to DNA now",
    ]
    for n in ((report.get("scan") or {}).get("closest_near") or [])[:12]:
        lines.append(
            f"- {n.get('city')} {n.get('day')} basket={n.get('basket')} "
            f"max_leg={n.get('max_leg')} ud={n.get('ud')} gates={n.get('gates_passed')}/3 "
            f"gap_b={n.get('gap_basket')} skip={n.get('skip')}"
        )
    lines += ["", "## Book walks (todos)"]
    for b in report.get("book_walks") or []:
        lines.append(
            f"- `{b.get('slug')}` dna={b.get('dna_take')} dna_city={b.get('dna_universe')} "
            f"plan_bc={b.get('plan_basket')} live_bc={b.get('live_basket_best_ask_plus_slip')} "
            f"fill25={((b.get('fill_sims') or {}).get('budget_25') or {}).get('all_legs_complete_at_cap')} "
            f"abort={((b.get('fill_sims') or {}).get('budget_25') or {}).get('abort_partial_would_trigger')}"
        )
    lines += [
        "",
        "## Invariantes",
        "",
    ]
    for inv in report.get("invariants_es") or []:
        lines.append(f"- {inv}")
    for inv in many.get("invariants_es") or []:
        lines.append(f"- {inv}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-docs", action="store_true")
    ap.add_argument("--narrow", action="store_true", help="Fast scan (fewer cities/horizons)")
    ap.add_argument("--budgets", default="12,25,50")
    args = ap.parse_args()
    budgets = [float(x) for x in str(args.budgets).split(",") if x.strip()]
    rep = run(budgets=budgets, write_docs=bool(args.write_docs), wide=not bool(args.narrow))
    many = rep.get("many_cases") or {}
    # compact print
    print(
        json.dumps(
            {
                "verdict": rep["verdict"],
                "action_es": rep["action_es"],
                "checks": rep["checks"],
                "wallet": rep["wallet"],
                "geoblock_blocked": (rep.get("geoblock") or {}).get("blocked"),
                "latency": rep.get("latency"),
                "coverage": {
                    k: (rep.get("coverage") or {}).get(k)
                    for k in (
                        "wide",
                        "events_open_pack",
                        "targets_book_walked",
                        "calendar_slugs_found",
                        "book_reports",
                        "fillable_budget25_any",
                        "closest_dna_city_basket",
                        "case_matrix",
                    )
                },
                "historical": {
                    k: ((rep.get("coverage") or {}).get("historical") or {}).get(k)
                    for k in (
                        "n_cases",
                        "n_dna_takes",
                        "dna_wilson95",
                        "max_win_streak",
                        "max_loss_streak",
                        "cases_by_city",
                    )
                },
                "skip_taxonomy": many.get("skip_taxonomy"),
                "gate_taxonomy": many.get("gate_taxonomy"),
                "counterfactual": many.get("counterfactual_basket_thresholds"),
                "stack_high": {
                    k: (rep.get("stack_high") or {}).get(k)
                    for k in ("events_open", "accepted_n", "near_miss_n", "ready_to_arm")
                },
                "closest_near": ((rep.get("scan") or {}).get("closest_near") or [])[:8],
                "book_walks_n": len(rep.get("book_walks") or []),
                "book_sample": [
                    {
                        "slug": b.get("slug"),
                        "dna": b.get("dna_take"),
                        "plan_bc": b.get("plan_basket"),
                        "live_bc": b.get("live_basket_best_ask_plus_slip"),
                        "fill25_complete": ((b.get("fill_sims") or {}).get("budget_25") or {}).get(
                            "all_legs_complete_at_cap"
                        ),
                    }
                    for b in (rep.get("book_walks") or [])[:8]
                ],
            },
            indent=2,
        )
    )
    return 0 if rep.get("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
