#!/usr/bin/env python3
"""
Multi-day resolved Temperature Ladder research + parameter sweep.

Investigates cities/horizons/filters until WR and PnL look strong on
resolved Polymarket weather markets (historical forecast + CLOB entry).

  python -m polymarket.research.local_lab.optimize_weather_ladder
  python -m polymarket.research.local_lab.optimize_weather_ladder --max-events 80
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from polymarket.src.weather.forecast import build_day_forecast, fetch_historical_model_maxes
from polymarket.src.weather.ladder import BucketQuote, build_ladder_plan
from polymarket.src.weather.markets import (
    TempEvent,
    discover_temperature_slugs,
    fetch_temp_event,
    historical_entry_ask,
    horizon_days,
    parse_event_slug,
    winning_bucket,
)
from polymarket.src.weather.stations import STATIONS, get_station

POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "weather_optimize"
GAMMA = "https://gamma-api.polymarket.com"


@dataclass
class TrialFilters:
    max_basket_cost: float
    max_leg_price: float
    min_cluster_prob: float
    min_basket_ev: float
    require_underdispersion: bool
    width: int
    budget: float
    bias_override: float | None = None  # added to all station bias


def _discover_more_slugs(cities: list[str], *, per_city: int = 12) -> list[str]:
    slugs = discover_temperature_slugs(cities=cities, limit_per_city=per_city)
    # Also probe explicit recent calendar slugs (search can miss)
    today = datetime.now(timezone.utc).date()
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
    with httpx.Client(timeout=20.0) as client:
        for city in cities:
            for delta in range(0, 45):
                d = today - timedelta(days=delta)
                slug = f"highest-temperature-in-{city}-on-{months[d.month-1]}-{d.day}-{d.year}"
                if slug in slugs:
                    continue
                r = client.get(f"{GAMMA}/events", params={"slug": slug})
                if r.status_code == 200 and r.json():
                    slugs.append(slug)
    # de-dupe
    seen: set[str] = set()
    out: list[str] = []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _load_resolved_cases(
    cities: list[str],
    *,
    max_events: int,
    max_age_days: int = 40,
    resume_path: Path | None = None,
    priority_cities: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Prefetch resolved events with forecasts + entry quotes (expensive I/O once)."""
    today = datetime.now(timezone.utc).date()
    # Priority cities first (longer lookback for SG/SH edge research)
    pri = [c.lower() for c in (priority_cities or ["singapore", "shanghai"])]
    ordered_cities = sorted(cities, key=lambda c: (0 if c.lower() in pri else 1, c))
    slugs = _discover_more_slugs(ordered_cities, per_city=14)
    # Prefer priority city slugs early
    slugs.sort(key=lambda s: (0 if any(f"-{c}-" in s or s.startswith(f"highest-temperature-in-{c}-") for c in pri) else 1, s))

    cases: list[dict[str, Any]] = []
    have: set[str] = set()
    if resume_path and resume_path.is_file():
        try:
            cases = json.loads(resume_path.read_text(encoding="utf-8"))
            have = {c["slug"] for c in cases}
            print(f"resuming with {len(cases)} cached cases", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"resume load failed: {exc}", flush=True)
            cases, have = [], set()

    # Shared CLOB client — fewer handshakes, longer timeout, soft retries
    with httpx.Client(timeout=httpx.Timeout(45.0, connect=15.0)) as clob:
        for slug in slugs:
            if len(cases) >= max_events:
                break
            if slug in have:
                continue
            parsed = parse_event_slug(slug)
            if parsed is None:
                continue
            city, day = parsed
            hz = horizon_days(day, today=today)
            age_cap = max_age_days + (20 if city.lower() in pri else 0)
            if hz > 0 or hz < -age_cap:
                continue
            station = get_station(city)
            if station is None or not station.volatile:
                continue
            try:
                event = fetch_temp_event(slug, use_clob=False)
            except Exception as exc:  # noqa: BLE001
                print(f"skip fetch {slug}: {exc}", flush=True)
                time.sleep(0.4)
                continue
            if event is None:
                continue
            # Skip °F markets when station is Celsius-modeled (or vice versa)
            if station.unit == "C" and any("°F" in (b.name or "") for b in event.buckets):
                continue
            if station.unit == "F" and any("°C" in (b.name or "") for b in event.buckets):
                continue
            winner = winning_bucket(event)
            if winner is None:
                continue
            try:
                models = fetch_historical_model_maxes(station, day)
            except Exception as exc:  # noqa: BLE001
                print(f"skip forecast {slug}: {exc}", flush=True)
                continue
            if len(models) < 2:
                continue
            point_temps = sorted({b.temp_c for b in event.buckets if b.temp_c is not None})
            if len(point_temps) < 3:
                continue
            entries: dict[str, float] = {}
            for b in event.buckets:
                if b.temp_c is None:
                    continue
                try:
                    px = historical_entry_ask(b.token_yes, client=clob, retries=2)
                except Exception:
                    px = None
                if px is not None and 0.01 <= px <= 0.70:
                    entries[b.name] = float(px)
            if len(entries) < 3:
                continue
            case = {
                "slug": slug,
                "city": city,
                "day": day.isoformat(),
                "winner": winner.name,
                "winner_temp": winner.temp_c,
                "winner_open_high": "or higher" in (winner.name or "").lower(),
                "winner_open_low": "or below" in (winner.name or "").lower(),
                "models": models,
                "point_temps": point_temps,
                "entries": entries,
                "buckets": [
                    {"name": b.name, "temp_c": b.temp_c} for b in event.buckets if b.temp_c is not None
                ],
            }
            cases.append(case)
            have.add(slug)
            print(
                f"case {len(cases)}: {slug} winner={winner.name} models={models}",
                flush=True,
            )
            if resume_path is not None and len(cases) % 5 == 0:
                resume_path.parent.mkdir(parents=True, exist_ok=True)
                resume_path.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    return cases


def _eval_case(case: dict[str, Any], filt: TrialFilters) -> dict[str, Any] | None:
    station = get_station(case["city"])
    if station is None:
        return None
    models = dict(case["models"])
    bias = float(station.bias_c) + float(filt.bias_override or 0.0)
    # rebuild with bias override via temporary station-like adjust
    from polymarket.src.weather.stations import Station

    st = Station(
        city=station.city,
        icao=station.icao,
        lat=station.lat,
        lon=station.lon,
        timezone=station.timezone,
        unit=station.unit,
        typical_model_spread_c=station.typical_model_spread_c,
        bias_c=bias,
        volatile=station.volatile,
    )
    fc = build_day_forecast(
        st,
        date.fromisoformat(case["day"]),
        models,
        bucket_temps=list(case["point_temps"]),
    )
    if fc is None:
        return None
    quotes: list[BucketQuote] = []
    for b in case["buckets"]:
        name = b["name"]
        if name not in case["entries"]:
            continue
        quotes.append(
            BucketQuote(
                name=name,
                my_prob=float(fc.bucket_probs.get(int(b["temp_c"]), 0.0)),
                market_price=float(case["entries"][name]),
                temp_c=int(b["temp_c"]),
            )
        )
    plan = build_ladder_plan(
        quotes,
        center_temp=fc.truncated_center,
        model_temps=list(fc.models.values()),
        typical_spread=st.typical_model_spread_c,
        budget=filt.budget,
        max_basket_cost=filt.max_basket_cost,
        min_cluster_prob=filt.min_cluster_prob,
        min_basket_ev=filt.min_basket_ev,
        width=filt.width,
        press_on_underdispersion=filt.require_underdispersion,
        max_leg_price=filt.max_leg_price,
    )
    if not plan.take:
        return {"taken": False, "reason": plan.reason, "slug": case["slug"]}

    winner = case["winner"]
    spent = sum(leg.dollars for leg in plan.legs)
    payout = 0.0
    hit = False
    open_high = bool(case.get("winner_open_high"))
    open_low = bool(case.get("winner_open_low"))
    wtemp = case.get("winner_temp")
    for leg in plan.legs:
        leg_hit = leg.name == winner
        # Open-ended resolution: highest/lowest bucket in cluster can still collect
        if not leg_hit and wtemp is not None:
            # match exact temp label inside cluster
            if f"{wtemp}°C" == leg.name or f"{wtemp}°F" == leg.name:
                leg_hit = True
            if open_high and leg.temp_c is not None and int(leg.temp_c) >= int(wtemp):
                # only the top rung of our cluster should proxy the open-high bucket
                max_c = max((x.temp_c for x in plan.legs if x.temp_c is not None), default=None)
                if max_c is not None and leg.temp_c == max_c and int(max_c) >= int(wtemp):
                    leg_hit = True
            if open_low and leg.temp_c is not None and int(leg.temp_c) <= int(wtemp):
                min_c = min((x.temp_c for x in plan.legs if x.temp_c is not None), default=None)
                if min_c is not None and leg.temp_c == min_c and int(min_c) <= int(wtemp):
                    leg_hit = True
        if leg_hit:
            payout += leg.shares * 1.0
            hit = True
    pnl = payout - spent
    return {
        "taken": True,
        "slug": case["slug"],
        "city": case["city"],
        "day": case["day"],
        "winner": winner,
        "center": fc.truncated_center,
        "basket_cost": plan.basket_cost,
        "basket_ev": plan.basket_ev,
        "underdispersed": plan.underdispersed,
        "spent": round(spent, 4),
        "payout": round(payout, 4),
        "pnl": round(pnl, 4),
        "win": hit and pnl > 0,
        "hit_winner": hit,
        "legs": [asdict(x) for x in plan.legs],
    }


def _score(results: list[dict[str, Any]]) -> dict[str, Any]:
    taken = [r for r in results if r.get("taken")]
    if not taken:
        return {
            "n_taken": 0,
            "winrate": 0.0,
            "hit_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "profit_factor": 0.0,
            "score": -1e9,
        }
    wins = [r for r in taken if r.get("win")]
    losses = [r for r in taken if not r.get("win")]
    hits = [r for r in taken if r.get("hit_winner")]
    total_pnl = sum(float(r["pnl"]) for r in taken)
    gross_win = sum(float(r["pnl"]) for r in wins) if wins else 0.0
    gross_loss = -sum(float(r["pnl"]) for r in losses) if losses else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 1e-9 else (10.0 if gross_win > 0 else 0.0)
    wr = len(wins) / len(taken)
    hit = len(hits) / len(taken)
    avg = total_pnl / len(taken)
    # Objective: prefer high WR + positive PnL + enough samples
    score = (
        100.0 * wr
        + 2.0 * total_pnl
        + 15.0 * min(len(taken), 12)
        + 10.0 * pf
        + (20.0 if total_pnl > 0 and wr >= 0.6 and len(taken) >= 5 else 0.0)
        + (40.0 if total_pnl > 0 and wr >= 0.75 and len(taken) >= 6 else 0.0)
    )
    return {
        "n_taken": len(taken),
        "n_skipped": sum(1 for r in results if not r.get("taken")),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(wr, 4),
        "hit_rate": round(hit, 4),
        "total_pnl": round(total_pnl, 4),
        "avg_pnl": round(avg, 4),
        "profit_factor": round(pf, 3),
        "score": round(score, 3),
    }


def sweep(cases: list[dict[str, Any]]) -> tuple[TrialFilters, dict[str, Any], list[dict[str, Any]]]:
    grid = {
        "max_basket_cost": [0.40, 0.47, 0.50, 0.55],
        "max_leg_price": [0.35, 0.39, 0.42, 0.48],
        "min_cluster_prob": [0.45, 0.55, 0.65],
        "min_basket_ev": [0.01, 0.02, 0.04],
        "require_underdispersion": [True, False],
        "width": [3, 4],
        "budget": [8.0, 12.0],
        "bias_override": [0.0, -0.5, 0.5],
    }
    keys = list(grid.keys())
    best_filt: TrialFilters | None = None
    best_score = -1e18
    best_metrics: dict[str, Any] = {}
    best_rows: list[dict[str, Any]] = []
    n_combos = 1
    for v in grid.values():
        n_combos *= len(v)
    print(f"sweeping {n_combos} filter combos over {len(cases)} cases...", flush=True)
    tested = 0
    for values in itertools.product(*[grid[k] for k in keys]):
        params = dict(zip(keys, values, strict=True))
        filt = TrialFilters(**params)
        rows = [_eval_case(c, filt) for c in cases]
        rows = [r for r in rows if r is not None]
        metrics = _score(rows)
        tested += 1
        if metrics["score"] > best_score:
            best_score = metrics["score"]
            best_filt = filt
            best_metrics = metrics
            best_rows = [r for r in rows if r.get("taken")]
            print(
                f"  new best score={best_score:.1f} WR={metrics['winrate']} "
                f"pnl={metrics['total_pnl']} n={metrics['n_taken']} filt={params}",
                flush=True,
            )
        if tested % 200 == 0:
            print(f"  ...tested {tested}/{n_combos}", flush=True)
    assert best_filt is not None
    return best_filt, best_metrics, best_rows


def city_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by.setdefault(str(r["city"]), []).append(r)
    out: dict[str, Any] = {}
    for city, rs in sorted(by.items()):
        wins = sum(1 for r in rs if r.get("win"))
        pnl = sum(float(r["pnl"]) for r in rs)
        out[city] = {
            "n": len(rs),
            "wins": wins,
            "winrate": round(wins / len(rs), 4),
            "pnl": round(pnl, 4),
        }
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--max-events", type=int, default=60)
    p.add_argument(
        "--cities",
        default=",".join(
            c
            for c, s in STATIONS.items()
            if s.volatile
        ),
    )
    args = p.parse_args()
    cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    print("loading resolved cases...", flush=True)
    cases_path = OUT / "cases.json"
    cases = _load_resolved_cases(
        cities,
        max_events=int(args.max_events),
        max_age_days=55,
        resume_path=cases_path,
        priority_cities=["singapore", "shanghai"],
    )
    cases_path.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"loaded {len(cases)} resolved cases", flush=True)
    if len(cases) < 3:
        print("NOT ENOUGH CASES")
        return 2
    filt, metrics, rows = sweep(cases)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "n_cases": len(cases),
        "best_filters": asdict(filt),
        "metrics": metrics,
        "by_city": city_breakdown(rows),
        "trades": rows,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "verdict": (
            "PASS"
            if metrics["winrate"] >= 0.75
            and metrics["total_pnl"] > 0
            and metrics["n_taken"] >= 5
            else "ITERATE"
        ),
    }
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = OUT / f"optimize_{sid}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    # freeze champion filters into config snippet
    champ = {
        "demo_label": "weather_ladder_champion",
        "strategy": "temperature_ladder",
        "notes": "Optimized resolved multi-day sweep — paper only",
        "initial_capital_usdc": 100.0,
        "budget_per_market_usdc": filt.budget,
        "max_markets_per_run": 8,
        "ladder_width": filt.width,
        "max_basket_cost": filt.max_basket_cost,
        "min_cluster_prob": filt.min_cluster_prob,
        "min_basket_ev": filt.min_basket_ev,
        "min_leg_ask": 0.015,
        "max_leg_ask": 0.70,
        "max_leg_price": filt.max_leg_price,
        "require_underdispersion": filt.require_underdispersion,
        "bias_override_c": filt.bias_override,
        "prefer_horizons": [1, 2],
        "volatile_only": True,
        "use_clob_asks": True,
        "mark_open_to_mid": True,
        "cities": sorted({c["city"] for c in cases if c["city"] in {r['city'] for r in rows}})
        or cities,
        "optimize_metrics": metrics,
    }
    cfg_path = POLY / "config" / "weather_ladder_champion.json"
    cfg_path.write_text(json.dumps(champ, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(path), "config": str(cfg_path), **metrics, "verdict": report["verdict"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
