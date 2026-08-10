#!/usr/bin/env python3
"""
Paper runner — Temperature Ladder (Polymarket weather).

Discovers live/recent highest-temperature events, builds EV-filtered
adjacent-bucket ladders from multi-model Open-Meteo forecasts, and
simulates fills at ask (no on-chain).

  python -m polymarket.research.local_lab.weather_ladder_paper
  python -m polymarket.research.local_lab.weather_ladder_paper --config polymarket/config/weather_ladder.json
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.src.weather.forecast import (
    build_day_forecast,
    fetch_historical_model_maxes,
    fetch_model_maxes,
)
from polymarket.src.weather.ladder import BucketQuote, LadderPlan, build_ladder_plan, underdispersion_signal
from polymarket.src.weather.markets import (
    TempEvent,
    discover_temperature_slugs,
    fetch_temp_event,
    historical_entry_ask,
    horizon_days,
    winning_bucket,
)
from polymarket.src.weather.stations import STATIONS, get_station

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
DEFAULT_CFG = ROOT / "config" / "weather_ladder.json"
OUT_BASE = ROOT / "data_local" / "local_lab" / "weather_ladder"


@dataclass
class PaperFill:
    slug: str
    bucket: str
    dollars: float
    shares: float
    price: float
    resolved_win: bool | None
    mark_value: float


def load_cfg(path: Path | None) -> dict[str, Any]:
    p = path or DEFAULT_CFG
    return json.loads(p.read_text(encoding="utf-8"))

def _cfg_for_city(cfg: dict[str, Any], city: str) -> dict[str, Any]:
    """Merge sleeve overlays (city-specific tiers/bias) onto base config."""
    city_l = city.strip().lower()
    sleeves = list(cfg.get("sleeves") or [])
    if not sleeves:
        return cfg
    for sleeve in sleeves:
        cities = {str(c).lower() for c in (sleeve.get("cities") or [])}
        if city_l in cities:
            merged = {**cfg, **{k: v for k, v in sleeve.items() if k not in ("name", "cities")}}
            merged["sleeve"] = sleeve.get("name", "default")
            # If sleeve has tiers, they replace base tiers
            if "tiers" in sleeve:
                merged["tiers"] = sleeve["tiers"]
            return merged
    # City not in any sleeve → skip via empty cities allowlist signal
    out = dict(cfg)
    out["_sleeve_miss"] = True
    return out



def _quotes_for_event(event: TempEvent, probs: dict[int, float]) -> list[BucketQuote]:
    out: list[BucketQuote] = []
    for b in event.buckets:
        if b.temp_c is None:
            # Open-ended: assign residual mass lightly (not center of ladder)
            p = 0.02
        else:
            p = float(probs.get(b.temp_c, 0.0))
        px = float(b.ask)
        if not event.closed and (px <= 0.001 or px >= 0.99):
            # skip dust / already-resolved legs for open trading
            continue
        out.append(
            BucketQuote(
                name=b.name,
                my_prob=p,
                market_price=px,
                temp_c=b.temp_c,
            )
        )
    return out


def _event_resolved(event: TempEvent) -> bool:
    return event.closed or winning_bucket(event) is not None


def plan_event(
    event: TempEvent,
    cfg: dict[str, Any],
    *,
    today: date | None = None,
) -> tuple[LadderPlan | None, dict[str, Any]]:
    station = get_station(event.city)
    resolved = _event_resolved(event)
    meta: dict[str, Any] = {
        "slug": event.slug,
        "city": event.city,
        "day": event.day.isoformat(),
        "horizon_d": horizon_days(event.day, today=today),
        "closed": event.closed,
        "resolved": resolved,
    }
    if station is None:
        meta["skip"] = "unknown_station"
        return None, meta
    excluded = {str(c).lower() for c in (cfg.get("exclude_cities") or [])}
    if event.city.lower() in excluded:
        meta["skip"] = "excluded_city"
        return None, meta
    if cfg.get("volatile_only") and not station.volatile:
        meta["skip"] = "not_volatile"
        return None, meta
    # City sleeves: core SG/SH/HK vs Beijing expansion, etc.
    cfg = _cfg_for_city(cfg, event.city)
    if cfg.get("_sleeve_miss") and cfg.get("sleeves"):
        meta["skip"] = "no_sleeve_for_city"
        return None, meta
    if cfg.get("sleeve"):
        meta["sleeve"] = cfg["sleeve"]

    prefer = set(int(x) for x in (cfg.get("prefer_horizons") or [1, 2]))
    hz = horizon_days(event.day, today=today)
    # Open trades: D+1/D+2 only.
    if not resolved and hz not in prefer:
        meta["skip"] = f"horizon_{hz}"
        return None, meta
    # Live/micro-dry profiles can refuse resolved replay entirely.
    if resolved and bool(cfg.get("open_only")):
        meta["skip"] = "open_only"
        return None, meta
    # Resolved replay window (research desk can widen via resolved_max_age_days)
    max_age = int(cfg.get("resolved_max_age_days", 1))
    if resolved and (hz > 0 or hz < -max_age):
        meta["skip"] = f"resolved_age_{hz}"
        return None, meta

    point_temps = sorted({b.temp_c for b in event.buckets if b.temp_c is not None})
    if len(point_temps) < 2:
        meta["skip"] = "few_buckets"
        return None, meta

    if resolved:
        # Article path: center on station forecast available before resolution
        models = fetch_historical_model_maxes(station, event.day)
        meta["forecast_source"] = "historical_forecast_api"
    else:
        raw = fetch_model_maxes(station, days=max(3, hz + 1))
        key = event.day.isoformat()
        if key not in raw:
            if not raw:
                meta["skip"] = "no_forecast"
                return None, meta
            key = min(raw.keys(), key=lambda d: abs(date.fromisoformat(d) - event.day).days)
            meta["forecast_day_used"] = key
        models = raw[key]
        meta["forecast_source"] = "live_forecast_api"

    if not models:
        meta["skip"] = "no_forecast"
        return None, meta

    from polymarket.src.weather.stations import Station

    # Two-tier desk: core underdispersion first, then volume expansion tier.
    tiers: list[dict[str, Any]] = list(cfg.get("tiers") or [{"name": "default"}])
    min_ask = float(cfg.get("min_leg_ask", 0.015))
    max_ask = float(cfg.get("max_leg_ask", 0.70))
    base_station = station
    best_plan: LadderPlan | None = None
    last_extra: dict[str, Any] = {}

    for tier in tiers:
        tier_cfg = {**cfg, **{k: v for k, v in tier.items() if k != "name"}}
        bias_override = tier_cfg.get("bias_override_c")
        st = base_station
        if bias_override is not None:
            st = Station(
                city=base_station.city,
                icao=base_station.icao,
                lat=base_station.lat,
                lon=base_station.lon,
                timezone=base_station.timezone,
                unit=base_station.unit,
                typical_model_spread_c=base_station.typical_model_spread_c,
                bias_c=float(base_station.bias_c) + float(bias_override),
                volatile=base_station.volatile,
            )
        fc = build_day_forecast(st, event.day, models, bucket_temps=point_temps)
        if fc is None:
            continue
        if resolved:
            quotes = []
            for b in event.buckets:
                if b.temp_c is None:
                    continue
                entry = historical_entry_ask(b.token_yes)
                if entry is None or not (min_ask <= entry <= max_ask):
                    continue
                quotes.append(
                    BucketQuote(
                        name=b.name,
                        my_prob=float(fc.bucket_probs.get(b.temp_c, 0.0)),
                        market_price=float(entry),
                        temp_c=b.temp_c,
                    )
                )
            meta["entry_pricing"] = "clob_history_pre_resolution"
        else:
            quotes = _quotes_for_event(event, fc.bucket_probs)
            quotes = [q for q in quotes if min_ask <= q.market_price <= max_ask]
            meta["entry_pricing"] = "live_ask"
            meta["entries_all"] = {q.name: float(q.market_price) for q in quotes}

        require_ud = bool(tier_cfg.get("require_underdispersion", True))
        budget = float(tier_cfg.get("budget_per_market_usdc", 8.0)) * float(
            tier_cfg.get("budget_mult", 1.0)
        )
        plan = build_ladder_plan(
            quotes,
            center_temp=fc.truncated_center,
            model_temps=list(fc.models.values()),
            typical_spread=st.typical_model_spread_c,
            budget=budget,
            max_basket_cost=float(tier_cfg.get("max_basket_cost", 0.50)),
            min_cluster_prob=float(tier_cfg.get("min_cluster_prob", 0.50)),
            min_basket_ev=float(tier_cfg.get("min_basket_ev", 0.015)),
            width=int(tier_cfg.get("ladder_width", cfg.get("ladder_width", 3))),
            press_on_underdispersion=require_ud,
            max_leg_price=float(tier_cfg.get("max_leg_price", 0.42)),
        )
        # Optional long-term post filter (stricter than planner max)
        post_b = tier_cfg.get("post_max_basket_cost", cfg.get("post_max_basket_cost"))
        take_ok = bool(plan.take)
        if take_ok and post_b is not None and float(plan.basket_cost) > float(post_b) + 1e-12:
            take_ok = False
            plan = LadderPlan(
                legs=plan.legs,
                basket_cost=plan.basket_cost,
                basket_ev=plan.basket_ev,
                center_temp=plan.center_temp,
                underdispersed=plan.underdispersed,
                take=False,
                reason=plan.reason + f"+post_basket>{post_b}",
            )
        last_extra = {
            "tier": tier.get("name", "default"),
            "bias_override_c": float(bias_override) if bias_override is not None else None,
            "models": fc.models,
            "corrected_center": fc.corrected_center,
            "truncated_center": fc.truncated_center,
            "sigma": fc.sigma,
            "underdispersed": plan.underdispersed,
            "basket_cost": plan.basket_cost,
            "basket_ev": plan.basket_ev,
            "take": take_ok,
            "reason": plan.reason,
            "legs": [asdict(x) for x in plan.legs],
            "ud": underdispersion_signal(list(fc.models.values()), st.typical_model_spread_c),
            "model_temps": list(fc.models.values()),
            "typical_spread": st.typical_model_spread_c,
        }
        if take_ok:
            best_plan = plan
            break

    if not last_extra:
        meta["skip"] = "forecast_build_failed"
        return None, meta
    meta.update(last_extra)
    return best_plan, meta


def settle_plan(
    event: TempEvent,
    plan: LadderPlan,
    *,
    mark_open_to_mid: bool = True,
) -> tuple[list[PaperFill], float, float]:
    """
    Returns fills, realized_or_mark_pnl, spent.
    Resolved: winner pays $1/share; losers 0.
    Open: mark each leg to mid (or ask if no mid).
    """
    winner = winning_bucket(event)
    by_name = {b.name: b for b in event.buckets}
    fills: list[PaperFill] = []
    spent = 0.0
    value = 0.0
    for leg in plan.legs:
        if leg.shares <= 0 or leg.dollars <= 0:
            continue
        spent += leg.dollars
        b = by_name.get(leg.name)
        resolved_win: bool | None = None
        if winner is not None:
            resolved_win = winner.name == leg.name
            mark = leg.shares * (1.0 if resolved_win else 0.0)
        else:
            px = None
            if b is not None:
                px = b.mid if (mark_open_to_mid and b.mid is not None) else b.ask
            mark = leg.shares * float(px if px is not None else leg.price)
        value += mark
        fills.append(
            PaperFill(
                slug=event.slug,
                bucket=leg.name,
                dollars=leg.dollars,
                shares=leg.shares,
                price=leg.price,
                resolved_win=resolved_win,
                mark_value=round(mark, 4),
            )
        )
    pnl = value - spent
    return fills, round(pnl, 4), round(spent, 4)


def run_weather_ladder_paper(
    *,
    config_path: Path | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    cfg = load_cfg(config_path)
    sid = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_BASE / f"session_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    cities = list(cfg.get("cities") or list(STATIONS.keys()))
    slugs = discover_temperature_slugs(cities=cities, limit_per_city=int(cfg.get("limit_per_city", 8)))
    today = datetime.now(timezone.utc).date()
    # Probe calendar slugs for resolved replay / near-term open markets
    from datetime import timedelta
    import httpx
    months = [
        "january","february","march","april","may","june",
        "july","august","september","october","november","december",
    ]
    max_age = int(cfg.get("resolved_max_age_days", 1))
    probe_days = max(3, max_age + 2)
    with httpx.Client(timeout=20.0) as client:
        for city in cities:
            for delta in range(-2, probe_days + 1):
                d = today - timedelta(days=delta)
                slug = f"highest-temperature-in-{city}-on-{months[d.month-1]}-{d.day}-{d.year}"
                if slug in slugs:
                    continue
                try:
                    r = client.get("https://gamma-api.polymarket.com/events", params={"slug": slug})
                    if r.status_code == 200 and r.json():
                        slugs.append(slug)
                except Exception:
                    continue
    print(f"discovered {len(slugs)} slugs for {cities}", flush=True)
    t0 = time.perf_counter()

    events: list[TempEvent] = []
    for slug in slugs:
        try:
            ev = fetch_temp_event(slug, use_clob=bool(cfg.get("use_clob_asks", True)))
        except Exception as exc:  # noqa: BLE001
            (out_dir / "fetch_errors.jsonl").open("a", encoding="utf-8").write(
                json.dumps({"slug": slug, "error": str(exc)}) + "\n"
            )
            continue
        if ev is not None:
            events.append(ev)
    print(f"fetched {len(events)} events", flush=True)

    max_markets = int(cfg.get("max_markets_per_run", 6))
    max_per_city = int(cfg.get("max_per_city", 0) or 0)  # 0 = unlimited
    bankroll = float(cfg.get("initial_capital_usdc", 100.0))
    min_budget = float(cfg.get("budget_per_market_usdc", 8.0))
    taken: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    all_fills: list[dict[str, Any]] = []
    realized_pnl = 0.0
    open_mark_pnl = 0.0
    spent_total = 0.0
    taken_by_city: dict[str, int] = {}

    # Realized first; by default interleave by horizon so one city cannot consume bankroll.
    # Optional city_priority is a tie-breaker only (unless sort_mode=city_first).
    priority = {str(c).lower(): i for i, c in enumerate(cfg.get("city_priority") or [])}
    sort_mode = str(cfg.get("sort_mode") or "horizon_first")

    def _sort_key(e: TempEvent) -> tuple:
        resolved_rank = 0 if _event_resolved(e) else 1
        hz = abs(horizon_days(e.day, today=today))
        pri = priority.get(e.city.lower(), 100)
        if sort_mode == "city_first":
            return (resolved_rank, pri, hz, e.slug)
        return (resolved_rank, hz, pri, e.slug)

    events_sorted = sorted(events, key=_sort_key)

    print(
        f"planning {len(events_sorted)} events (max_markets={max_markets} "
        f"max_per_city={max_per_city or '∞'} sort={sort_mode})...",
        flush=True,
    )
    for i, event in enumerate(events_sorted):
        if len(taken) >= max_markets:
            break
        if bankroll - spent_total < min_budget * 0.5:
            print(f"  bankroll exhausted at event {i+1}; stopping early", flush=True)
            break
        if i % 5 == 0:
            print(f"  …event {i+1}/{len(events_sorted)} taken={len(taken)} skipped={len(skipped)}", flush=True)
        city_l = event.city.lower()
        if max_per_city and taken_by_city.get(city_l, 0) >= max_per_city:
            skipped.append({"slug": event.slug, "city": event.city, "skip": "max_per_city"})
            continue
        plan, meta = plan_event(event, cfg, today=today)
        if plan is None or not plan.take:
            skipped.append(meta)
            continue
        fills, pnl, spent = settle_plan(
            event,
            plan,
            mark_open_to_mid=bool(cfg.get("mark_open_to_mid", True)),
        )
        if spent > bankroll - spent_total + 1e-9:
            meta["skip"] = "insufficient_bankroll"
            skipped.append(meta)
            continue
        spent_total += spent
        taken_by_city[city_l] = taken_by_city.get(city_l, 0) + 1
        row = {
            **meta,
            "spent": spent,
            "pnl": pnl,
            "fills": [asdict(f) for f in fills],
        }
        taken.append(row)
        all_fills.extend(row["fills"])
        if _event_resolved(event):
            realized_pnl += pnl
        else:
            open_mark_pnl += pnl

    resolved_taken = [t for t in taken if t.get("resolved")]
    open_taken = [t for t in taken if not t.get("resolved")]
    wins = sum(1 for t in resolved_taken if float(t.get("pnl") or 0) > 1e-9)
    losses = sum(1 for t in resolved_taken if float(t.get("pnl") or 0) < -1e-9)
    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": sid,
        "strategy": "temperature_ladder",
        "demo_label": cfg.get("demo_label"),
        "initial_capital_usdc": bankroll,
        "cities": cities,
        "events_seen": len(events),
        "ladders_taken": len(taken),
        "ladders_skipped": len(skipped),
        "resolved_taken": len(resolved_taken),
        "open_taken": len(open_taken),
        "wins": wins,
        "losses": losses,
        "winrate": round(wins / len(resolved_taken), 4) if resolved_taken else None,
        "spent_usdc": round(spent_total, 4),
        "realized_pnl_usdc": round(realized_pnl, 4),
        "open_mark_pnl_usdc": round(open_mark_pnl, 4),
        # Primary scorecard = realized (resolved). Open mark is secondary drag.
        "total_pnl_usdc": round(realized_pnl + open_mark_pnl, 4),
        "scorecard_pnl_usdc": round(realized_pnl, 4),
        "ending_equity_usdc": round(bankroll + realized_pnl + open_mark_pnl, 4),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "taken": taken,
        "skipped_head": skipped[:20],
        "note": (
            "Paper. Resolved ladders use historical forecast + CLOB pre-resolution "
            "entry; open ladders mark-to-mid. No on-chain."
        ),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (out_dir / "fills.jsonl").open("w", encoding="utf-8") as fh:
        for f in all_fills:
            fh.write(json.dumps(f, ensure_ascii=False) + "\n")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Paper temperature ladder")
    p.add_argument("--config", default=str(DEFAULT_CFG))
    p.add_argument("--session-id", default=None)
    args = p.parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        alt = REPO / args.config
        cfg_path = alt if alt.is_file() else DEFAULT_CFG
    report = run_weather_ladder_paper(config_path=cfg_path, session_id=args.session_id)
    print(json.dumps({k: report[k] for k in report if k not in ("taken", "skipped_head")}, indent=2))
    print(f"session -> {OUT_BASE / ('session_' + report['session_id'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
