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

from polymarket.src.weather.forecast import build_day_forecast, fetch_model_maxes
from polymarket.src.weather.ladder import BucketQuote, LadderPlan, build_ladder_plan
from polymarket.src.weather.markets import (
    TempEvent,
    discover_temperature_slugs,
    fetch_temp_event,
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


def plan_event(
    event: TempEvent,
    cfg: dict[str, Any],
    *,
    today: date | None = None,
) -> tuple[LadderPlan | None, dict[str, Any]]:
    station = get_station(event.city)
    meta: dict[str, Any] = {
        "slug": event.slug,
        "city": event.city,
        "day": event.day.isoformat(),
        "horizon_d": horizon_days(event.day, today=today),
        "closed": event.closed,
    }
    if station is None:
        meta["skip"] = "unknown_station"
        return None, meta
    if cfg.get("volatile_only") and not station.volatile:
        meta["skip"] = "not_volatile"
        return None, meta
    prefer = set(int(x) for x in (cfg.get("prefer_horizons") or [1, 2]))
    hz = horizon_days(event.day, today=today)
    # Allow horizon 0 only for resolved PnL replay; open trades stick to D+1/D+2
    if not event.closed and hz not in prefer:
        meta["skip"] = f"horizon_{hz}"
        return None, meta

    point_temps = sorted({b.temp_c for b in event.buckets if b.temp_c is not None})
    if len(point_temps) < 2:
        meta["skip"] = "few_buckets"
        return None, meta

    raw = fetch_model_maxes(station, days=max(3, hz + 1))
    key = event.day.isoformat()
    if key not in raw:
        # Fall back to nearest available forecast day
        if not raw:
            meta["skip"] = "no_forecast"
            return None, meta
        key = min(raw.keys(), key=lambda d: abs(date.fromisoformat(d) - event.day).days)
        meta["forecast_day_used"] = key
    fc = build_day_forecast(station, date.fromisoformat(key), raw[key], bucket_temps=point_temps)
    if fc is None:
        meta["skip"] = "forecast_build_failed"
        return None, meta

    quotes = _quotes_for_event(event, fc.bucket_probs)
    min_ask = float(cfg.get("min_leg_ask", 0.015))
    max_ask = float(cfg.get("max_leg_ask", 0.70))
    if not event.closed:
        quotes = [q for q in quotes if min_ask <= q.market_price <= max_ask]
    require_ud = bool(cfg.get("require_underdispersion", True))
    plan = build_ladder_plan(
        quotes,
        center_temp=fc.truncated_center,
        model_temps=list(fc.models.values()),
        typical_spread=station.typical_model_spread_c,
        budget=float(cfg.get("budget_per_market_usdc", 8.0)),
        max_basket_cost=float(cfg.get("max_basket_cost", 0.85)),
        min_cluster_prob=float(cfg.get("min_cluster_prob", 0.50)),
        min_basket_ev=float(cfg.get("min_basket_ev", 0.015)),
        width=int(cfg.get("ladder_width", 3)),
        press_on_underdispersion=require_ud,
    )
    meta.update(
        {
            "models": fc.models,
            "corrected_center": fc.corrected_center,
            "truncated_center": fc.truncated_center,
            "sigma": fc.sigma,
            "underdispersed": plan.underdispersed,
            "basket_cost": plan.basket_cost,
            "basket_ev": plan.basket_ev,
            "take": plan.take,
            "reason": plan.reason,
            "legs": [asdict(x) for x in plan.legs],
        }
    )
    return plan, meta


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
    winner = winning_bucket(event) if event.closed else None
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
    slugs = discover_temperature_slugs(cities=cities, limit_per_city=3)
    # Also probe explicit near-term slugs for configured cities (search can miss)
    today = datetime.now(timezone.utc).date()
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

    max_markets = int(cfg.get("max_markets_per_run", 6))
    bankroll = float(cfg.get("initial_capital_usdc", 100.0))
    taken: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    all_fills: list[dict[str, Any]] = []
    realized_pnl = 0.0
    open_mark_pnl = 0.0
    spent_total = 0.0

    # Prefer open D+1/D+2 first, then recently closed for realized scorecard
    events_sorted = sorted(
        events,
        key=lambda e: (e.closed, abs(horizon_days(e.day, today=today) - 1), e.slug),
    )

    for event in events_sorted:
        if len(taken) >= max_markets:
            # still score closed events for comparison if we have room in skipped log only
            if not event.closed:
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
        row = {
            **meta,
            "spent": spent,
            "pnl": pnl,
            "fills": [asdict(f) for f in fills],
        }
        taken.append(row)
        all_fills.extend(row["fills"])
        if event.closed:
            realized_pnl += pnl
        else:
            open_mark_pnl += pnl

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
        "spent_usdc": round(spent_total, 4),
        "realized_pnl_usdc": round(realized_pnl, 4),
        "open_mark_pnl_usdc": round(open_mark_pnl, 4),
        "total_pnl_usdc": round(realized_pnl + open_mark_pnl, 4),
        "ending_equity_usdc": round(bankroll + realized_pnl + open_mark_pnl, 4),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "taken": taken,
        "skipped_head": skipped[:20],
        "note": "Paper — asks from CLOB/gamma; no on-chain. Open PnL is mark-to-mid.",
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
