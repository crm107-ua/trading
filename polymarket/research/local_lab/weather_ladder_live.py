#!/usr/bin/env python3
"""
Temperature Ladder micro dry-run / live harness.

Modes:
  book_sim  — live books + would_post payloads, no CLOB auth required
  clob_dry  — ARMED=1 + DRY_RUN=1, signs/normalizes via ClobLiveClient (0 on-chain)

Never sets DRY_RUN=0. Real posts require an explicit --allow-real flag AND
POLY_LIVE_DRY_RUN=0 already in the environment (refuses to flip it itself).

  python -m polymarket.research.local_lab.weather_ladder_live --mode book_sim
  python -m polymarket.research.local_lab.weather_ladder_live --mode clob_dry
  python -m polymarket.research.local_lab.weather_ladder_live --mode both
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from polymarket.research.local_lab.weather_ladder_paper import load_cfg, plan_event
from polymarket.src.ai.env_loader import load_repo_dotenv
from polymarket.src.execution.clob_live import (
    MIN_BUY_NOTIONAL_USDC,
    MIN_ORDER_SHARES,
    ClobLiveClient,
    normalize_live_order,
    read_gates,
)
from polymarket.src.weather.ladder import LadderLeg, LadderPlan
from polymarket.src.weather.markets import TempEvent, discover_temperature_slugs, fetch_temp_event, horizon_days
from polymarket.src.weather.stations import STATIONS

POLY = Path(__file__).resolve().parents[2]
DEFAULT_CFG = POLY / "config" / "weather_ladder_micro_dry.json"
OUT = POLY / "data_local" / "local_lab" / "weather_ladder_live"


def _attach_tokens(plan: LadderPlan, event: TempEvent) -> LadderPlan | None:
    by_name = {b.name: b for b in event.buckets}
    legs: list[LadderLeg] = []
    for leg in plan.legs:
        b = by_name.get(leg.name)
        if b is None or not b.token_yes:
            return None
        legs.append(replace(leg, token_id=str(b.token_yes)))
    return LadderPlan(
        legs=legs,
        basket_cost=plan.basket_cost,
        basket_ev=plan.basket_ev,
        center_temp=plan.center_temp,
        underdispersed=plan.underdispersed,
        take=plan.take,
        reason=plan.reason,
    )


def _live_normalize_legs(
    plan: LadderPlan,
    *,
    slip_cents: float,
    max_capital: float,
) -> tuple[LadderPlan | None, str]:
    """Bump each leg to CLOB floors; abort if basket exceeds capital."""
    legs: list[LadderLeg] = []
    spent = 0.0
    for leg in plan.legs:
        px0 = min(0.99, float(leg.price) + float(slip_cents))
        px, sz = normalize_live_order(side="BUY", price=px0, size=float(leg.shares))
        notional = px * sz
        if sz < MIN_ORDER_SHARES - 1e-9:
            return None, f"leg_{leg.name}_below_min_shares"
        if notional < MIN_BUY_NOTIONAL_USDC - 1e-9:
            return None, f"leg_{leg.name}_below_min_notional"
        spent += notional
        legs.append(
            LadderLeg(
                name=leg.name,
                my_prob=leg.my_prob,
                price=px,
                dollars=round(notional, 4),
                shares=sz,
                ev=leg.ev,
                token_id=leg.token_id,
            )
        )
    if spent > max_capital + 1e-9:
        return None, f"basket_notional={spent:.2f}>max_capital={max_capital}"
    return (
        LadderPlan(
            legs=legs,
            basket_cost=round(sum(l.price for l in legs), 4),
            basket_ev=plan.basket_ev,
            center_temp=plan.center_temp,
            underdispersed=plan.underdispersed,
            take=True,
            reason=plan.reason + "+live_floors",
        ),
        "ok",
    )


def _discover_open_events(cfg: dict[str, Any]) -> list[TempEvent]:
    cities = list(cfg.get("cities") or list(STATIONS.keys()))
    slugs = discover_temperature_slugs(cities=cities, limit_per_city=int(cfg.get("limit_per_city", 6)))
    # Calendar probe for D+1/D+2
    from datetime import date, timedelta
    import httpx

    today = datetime.now(timezone.utc).date()
    months = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]
    prefer = {int(x) for x in (cfg.get("prefer_horizons") or [1, 2])}
    with httpx.Client(timeout=20.0) as client:
        for city in cities:
            for hz in sorted(prefer):
                d = today + timedelta(days=hz)
                slug = f"highest-temperature-in-{city}-on-{months[d.month-1]}-{d.day}-{d.year}"
                if slug not in slugs:
                    try:
                        r = client.get("https://gamma-api.polymarket.com/events", params={"slug": slug})
                        if r.status_code == 200 and r.json():
                            slugs.append(slug)
                    except Exception:
                        pass

    events: list[TempEvent] = []
    for slug in slugs:
        try:
            ev = fetch_temp_event(slug, use_clob=bool(cfg.get("use_clob_asks", True)))
        except Exception:
            continue
        if ev is None or ev.closed:
            continue
        hz = horizon_days(ev.day, today=today)
        if hz not in prefer:
            continue
        events.append(ev)
    priority = {str(c).lower(): i for i, c in enumerate(cfg.get("city_priority") or [])}
    events.sort(key=lambda e: (abs(horizon_days(e.day, today=today)), priority.get(e.city.lower(), 100), e.slug))
    return events


def _force_dry_env(*, max_capital: float) -> dict[str, str]:
    prev = {
        "POLY_LIVE_ARMED": os.environ.get("POLY_LIVE_ARMED", ""),
        "POLY_LIVE_DRY_RUN": os.environ.get("POLY_LIVE_DRY_RUN", ""),
        "POLY_LIVE_MAX_CAPITAL_USDC": os.environ.get("POLY_LIVE_MAX_CAPITAL_USDC", ""),
    }
    os.environ["POLY_LIVE_ARMED"] = "1"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"
    os.environ["POLY_LIVE_MAX_CAPITAL_USDC"] = str(float(max_capital))
    return prev


def _restore_env(prev: dict[str, str]) -> None:
    for k, v in prev.items():
        if v == "":
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    # Always leave SAFE after ladder dry harness
    os.environ["POLY_LIVE_ARMED"] = "0"
    os.environ["POLY_LIVE_DRY_RUN"] = "1"


def prepare_candidates(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return accepted candidates + skip/near-miss telemetry for open books."""
    max_markets = int(cfg.get("max_markets_per_run", 2))
    max_per_city = int(cfg.get("max_per_city", 1) or 0)
    max_cap = float((cfg.get("live") or {}).get("max_capital_usdc") or cfg.get("initial_capital_usdc") or 25)
    slip = float(cfg.get("entry_slip_cents", 0.01))
    today = datetime.now(timezone.utc).date()
    events = _discover_open_events(cfg)
    accepted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    near_miss: list[dict[str, Any]] = []
    by_city: dict[str, int] = {}
    for event in events:
        city_l = event.city.lower()
        if max_per_city and by_city.get(city_l, 0) >= max_per_city and len(accepted) >= max_markets:
            skipped.append({"slug": event.slug, "city": event.city, "skip": "max_per_city"})
            continue
        plan, meta = plan_event(event, cfg, today=today)
        if plan is None or not plan.take:
            legs = meta.get("legs") or []
            entries = {
                str(x.get("name")): float(x["price"])
                for x in legs
                if x.get("name") is not None and x.get("price") is not None
            }
            row = {
                "slug": event.slug,
                "city": event.city,
                "day": event.day.isoformat(),
                "skip": meta.get("skip") or meta.get("reason") or "no_take",
                "basket_cost": meta.get("basket_cost"),
                "basket_ev": meta.get("basket_ev"),
                "tier": meta.get("tier"),
                "underdispersed": meta.get("underdispersed"),
                "models": meta.get("models"),
                "legs": legs,
                "entries": entries,
                "dna_take": False,
            }
            skipped.append(row)
            # Near-miss: positive EV but basket slightly above champion max
            bc = meta.get("basket_cost")
            be = meta.get("basket_ev")
            if bc is not None and be is not None and float(be) > 0 and 0.5 < float(bc) <= 0.72:
                near_miss.append({**row, "watch": "basket_slightly_rich"})
            continue
        if len(accepted) >= max_markets:
            skipped.append({"slug": event.slug, "city": event.city, "skip": "max_markets"})
            continue
        if max_per_city and by_city.get(city_l, 0) >= max_per_city:
            skipped.append({"slug": event.slug, "city": event.city, "skip": "max_per_city"})
            continue
        wired = _attach_tokens(plan, event)
        if wired is None:
            skipped.append({"slug": event.slug, "city": event.city, "skip": "missing_token_id"})
            continue
        live_plan, reason = _live_normalize_legs(wired, slip_cents=slip, max_capital=max_cap)
        if live_plan is None:
            skipped.append(
                {
                    "slug": event.slug,
                    "city": event.city,
                    "day": event.day.isoformat(),
                    "skip": reason,
                    "tier": meta.get("tier"),
                }
            )
            continue
        # Definitive gate: reject if live-normalized basket blows past post/max cap.
        post_b = cfg.get("post_max_basket_cost")
        hard_b = float(cfg.get("max_basket_cost") or 0.50)
        live_bc = float(live_plan.basket_cost)
        lim = float(post_b) if post_b is not None else hard_b + 0.02
        if live_bc > lim + 1e-12:
            skipped.append(
                {
                    "slug": event.slug,
                    "city": event.city,
                    "day": event.day.isoformat(),
                    "skip": f"live_basket>{lim}",
                    "basket_cost": live_bc,
                    "tier": meta.get("tier"),
                }
            )
            continue
        if not live_plan.underdispersed and bool(cfg.get("require_underdispersion", True)):
            skipped.append(
                {
                    "slug": event.slug,
                    "city": event.city,
                    "day": event.day.isoformat(),
                    "skip": "not_underdispersed_live",
                    "tier": meta.get("tier"),
                }
            )
            continue
        by_city[city_l] = by_city.get(city_l, 0) + 1
        leg_rows = [asdict(l) for l in live_plan.legs]
        entries = {
            str(x.get("name")): float(x["price"])
            for x in leg_rows
            if x.get("name") is not None and x.get("price") is not None
        }
        accepted.append(
            {
                "slug": event.slug,
                "city": event.city,
                "day": event.day.isoformat(),
                "accepted": True,
                "sleeve": meta.get("sleeve"),
                "tier": meta.get("tier"),
                "horizon_d": meta.get("horizon_d"),
                "basket_cost": live_plan.basket_cost,
                "basket_ev": live_plan.basket_ev,
                "underdispersed": live_plan.underdispersed,
                "center_temp": live_plan.center_temp,
                "notional_usdc": round(sum(l.dollars for l in live_plan.legs), 4),
                "legs": leg_rows,
                "entries": entries,
                "models": meta.get("models"),
                "dna_take": True,
                "plan_reason": live_plan.reason,
                "meta": {k: v for k, v in meta.items() if k not in ("legs",)},
            }
        )
    return {
        "events_open": len(events),
        "accepted": accepted,
        "skipped": skipped,
        "near_miss": near_miss,
    }


def run_book_sim(cfg: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    pack = prepare_candidates(cfg)
    accepted = pack["accepted"]
    would_posts = []
    for c in accepted:
        for leg in c["legs"]:
            would_posts.append(
                {
                    "slug": c["slug"],
                    "bucket": leg["name"],
                    "token_id": leg["token_id"],
                    "side": "BUY",
                    "price": leg["price"],
                    "size": leg["shares"],
                    "notional": leg["dollars"],
                    "order_type": cfg.get("order_type", "FAK"),
                    "post_only": False,
                    "mode": "book_sim",
                }
            )
    return {
        "mode": "book_sim",
        "session_id": session_id,
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "events_open": pack["events_open"],
        "candidates": accepted,
        "skipped_head": pack["skipped"][:20],
        "near_miss": pack["near_miss"],
        "accepted_n": len(accepted),
        "would_posts": would_posts,
        "notional_total_usdc": round(sum(c.get("notional_usdc") or 0 for c in accepted), 4),
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "onchain": False,
    }


def run_clob_dry(
    cfg: dict[str, Any],
    *,
    session_id: str,
    allow_real: bool = False,
) -> dict[str, Any]:
    """CLOB dry path. Refuses to disable DRY_RUN itself."""
    max_cap = float((cfg.get("live") or {}).get("max_capital_usdc") or cfg.get("initial_capital_usdc") or 25)
    require_dry = bool((cfg.get("live") or {}).get("require_dry_run", True))
    prev = _force_dry_env(max_capital=max_cap)
    t0 = time.perf_counter()
    try:
        if allow_real:
            # Only honor real if env already had DRY_RUN=0 before we forced dry — we never flip it.
            raise RuntimeError(
                "Refusing --allow-real in this harness. Unset require_dry and use a dedicated "
                "real runner after explicit human confirmation."
            )
        gates = read_gates()
        if require_dry and not gates.dry_run:
            raise RuntimeError("ABORT: DRY_RUN must be 1 for ladder micro dry")
        if not gates.armed:
            raise RuntimeError("ABORT: failed to arm temporarily for dry")

        cli = ClobLiveClient()
        cli.connect(derive_api_creds=True)
        bal = None
        try:
            bal = cli.balance_collateral_usdc()
        except Exception as exc:  # noqa: BLE001
            bal = None
            bal_err = f"{type(exc).__name__}: {exc}"
        else:
            bal_err = None

        # Cap session capital to wallet + configured max (dry still exercises path).
        eff_cap = max_cap if bal is None else min(max_cap, max(float(bal), 5.0))
        cli.assert_can_trade(capital=min(eff_cap, max_cap), allow_dry=True)
        pack = prepare_candidates(cfg)
        accepted = pack["accepted"]
        posts: list[dict[str, Any]] = []
        aborted = []
        smoke_posts: list[dict[str, Any]] = []
        order_type = str(cfg.get("order_type") or "FAK")
        abort_partial = bool(cfg.get("abort_partial_basket", True))

        for c in accepted:
            basket_posts: list[dict[str, Any]] = []
            ok = True
            for leg in c["legs"]:
                try:
                    resp = cli.place_aggressive(
                        token_id=str(leg["token_id"]),
                        side="BUY",
                        price=float(leg["price"]),
                        size=float(leg["shares"]),
                        order_type=order_type,
                    )
                    basket_posts.append(
                        {
                            "slug": c["slug"],
                            "bucket": leg["name"],
                            "status": resp.get("status"),
                            "would_post": resp.get("would_post"),
                            "orderID": resp.get("orderID"),
                        }
                    )
                    if resp.get("status") not in ("DRY_RUN", "LIVE"):
                        ok = False
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    basket_posts.append(
                        {
                            "slug": c["slug"],
                            "bucket": leg["name"],
                            "status": "ERROR",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
            if ok or not abort_partial:
                posts.extend(basket_posts)
            else:
                aborted.append({"slug": c["slug"], "posts": basket_posts})
                try:
                    cli.cancel_all()
                except Exception:
                    pass

        # Plumbing smoke: if no champion edge, still dry-post one live ask to prove path.
        if not accepted and bool(cfg.get("smoke_post_when_empty", True)):
            smoke_posts = _smoke_dry_post(cli, cfg, order_type=order_type)

        gates_during = read_gates()
        verdict = (
            "DRY_OK"
            if posts and all(p.get("status") == "DRY_RUN" for p in posts)
            else (
                "DRY_PATH_OK_NO_EDGE"
                if smoke_posts and all(p.get("status") == "DRY_RUN" for p in smoke_posts)
                else ("DRY_NO_CANDIDATES" if not accepted else "DRY_PARTIAL")
            )
        )
        return {
            "mode": "clob_dry",
            "session_id": session_id,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "gates_during": {
                "armed": gates_during.armed,
                "dry_run": gates_during.dry_run,
                "max_capital_usdc": gates_during.max_capital_usdc,
                "clob_ready": gates_during.clob_ready,
                "signing_ready": gates_during.signing_ready,
                "funder": gates_during.funder,
                "eoa": gates_during.eoa,
            },
            "balance_pusd": round(bal, 4) if bal is not None else None,
            "balance_error": bal_err,
            "effective_cap_usdc": eff_cap,
            "events_open": pack["events_open"],
            "candidates": accepted,
            "skipped_head": pack["skipped"][:20],
            "near_miss": pack["near_miss"],
            "accepted_n": len(accepted),
            "posts": posts,
            "smoke_posts": smoke_posts,
            "aborted_baskets": aborted,
            "dry_posts_n": sum(1 for p in posts + smoke_posts if p.get("status") == "DRY_RUN"),
            "notional_posted_usdc": round(
                sum(
                    float((p.get("would_post") or {}).get("notional") or 0)
                    for p in posts + smoke_posts
                ),
                4,
            ),
            "elapsed_s": round(time.perf_counter() - t0, 2),
            "onchain": False,
            "verdict": verdict,
        }
    finally:
        _restore_env(prev)


def _smoke_dry_post(cli: ClobLiveClient, cfg: dict[str, Any], *, order_type: str) -> list[dict[str, Any]]:
    """Single-leg dry would_post against cheapest open ask — plumbing only, not a strategy take."""
    events = _discover_open_events(cfg)
    best: tuple[float, Any, Any] | None = None
    for ev in events:
        for b in ev.buckets:
            if b.closed or not b.token_yes:
                continue
            ask = float(b.ask)
            if 0.05 <= ask <= 0.45:
                if best is None or ask < best[0]:
                    best = (ask, ev, b)
    if best is None:
        return []
    ask, ev, b = best
    px, sz = normalize_live_order(side="BUY", price=ask + 0.01, size=MIN_ORDER_SHARES)
    try:
        resp = cli.place_aggressive(
            token_id=str(b.token_yes),
            side="BUY",
            price=px,
            size=sz,
            order_type=order_type,
        )
        return [
            {
                "slug": ev.slug,
                "bucket": b.name,
                "status": resp.get("status"),
                "would_post": resp.get("would_post"),
                "orderID": resp.get("orderID"),
                "plumbing_smoke": True,
                "note": "Not a champion take — dry path exercise only",
            }
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "slug": ev.slug,
                "bucket": b.name,
                "status": "ERROR",
                "error": f"{type(exc).__name__}: {exc}",
                "plumbing_smoke": True,
            }
        ]


def run_session(
    *,
    config_path: Path,
    mode: str = "both",
    session_id: str | None = None,
) -> dict[str, Any]:
    load_repo_dotenv(override=True)
    cfg = load_cfg(config_path)
    sid = session_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT / f"session_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "session_id": sid,
        "config": str(config_path),
        "demo_label": cfg.get("demo_label"),
        "modes": {},
    }

    if mode in ("book_sim", "both"):
        print("=== LADDER book_sim ===", flush=True)
        report["modes"]["book_sim"] = run_book_sim(cfg, session_id=f"{sid}_book")
        print(
            f"book_sim accepted={report['modes']['book_sim']['accepted_n']} "
            f"notional={report['modes']['book_sim']['notional_total_usdc']}",
            flush=True,
        )

    if mode in ("clob_dry", "both"):
        print("=== LADDER clob_dry (ARMED temp + DRY_RUN=1) ===", flush=True)
        report["modes"]["clob_dry"] = run_clob_dry(cfg, session_id=f"{sid}_clob")
        cd = report["modes"]["clob_dry"]
        print(
            f"clob_dry verdict={cd.get('verdict')} posts={cd.get('dry_posts_n')} "
            f"bal={cd.get('balance_pusd')} restored_SAFE=1",
            flush=True,
        )

    # Final safety stamp
    g = read_gates()
    report["safe_after"] = {"armed": g.armed, "dry_run": g.dry_run}
    report["overall_verdict"] = _overall(report)
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"session -> {out_dir}", flush=True)
    return report


def _overall(report: dict[str, Any]) -> str:
    modes = report.get("modes") or {}
    if not modes:
        return "EMPTY"
    if "clob_dry" in modes:
        v = modes["clob_dry"].get("verdict")
        if v == "DRY_OK":
            return "MICRO_DRY_READY"
        if v == "DRY_PATH_OK_NO_EDGE":
            return "MICRO_DRY_PATH_READY"
        if v == "DRY_NO_CANDIDATES":
            bs = modes.get("book_sim") or {}
            if bs.get("accepted_n", 0) > 0:
                return "BOOK_OK_CLOB_NO_POST"
            return "NO_OPEN_EDGE"
        return v or "DRY_PARTIAL"
    bs = modes.get("book_sim") or {}
    return "BOOK_SIM_OK" if bs.get("accepted_n", 0) > 0 else "NO_OPEN_EDGE"


def run_watch(
    *,
    config_path: Path,
    interval_s: float = 180.0,
    max_rounds: int = 20,
) -> dict[str, Any]:
    """Poll open books until a champion take appears or rounds exhaust."""
    load_repo_dotenv(override=True)
    cfg = load_cfg(config_path)
    sid = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = OUT / f"watch_{sid}"
    out_dir.mkdir(parents=True, exist_ok=True)
    rounds: list[dict[str, Any]] = []
    for i in range(max_rounds):
        print(f"[watch] round {i+1}/{max_rounds}", flush=True)
        pack = prepare_candidates(cfg)
        row = {
            "round": i + 1,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "events_open": pack["events_open"],
            "accepted_n": len(pack["accepted"]),
            "near_miss": pack["near_miss"],
            "accepted_slugs": [c["slug"] for c in pack["accepted"]],
        }
        rounds.append(row)
        print(json.dumps(row, indent=2), flush=True)
        if pack["accepted"]:
            # Full dry when edge appears
            live = run_session(config_path=config_path, mode="both", session_id=f"{sid}_hit{i+1}")
            report = {
                "watch_id": sid,
                "hit": True,
                "rounds": rounds,
                "live_session": live,
            }
            (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            return report
        if i + 1 < max_rounds:
            time.sleep(max(5.0, float(interval_s)))
    report = {"watch_id": sid, "hit": False, "rounds": rounds, "verdict": "WATCH_NO_EDGE"}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Weather ladder micro dry-run")
    p.add_argument("--config", default=str(DEFAULT_CFG))
    p.add_argument("--mode", choices=["book_sim", "clob_dry", "both", "watch"], default="both")
    p.add_argument("--session-id", default=None)
    p.add_argument("--watch-interval", type=float, default=180.0)
    p.add_argument("--watch-rounds", type=int, default=10)
    args = p.parse_args()
    cfg_path = Path(args.config)
    if not cfg_path.is_file():
        alt = POLY.parent / args.config
        cfg_path = alt if alt.is_file() else DEFAULT_CFG
    if args.mode == "watch":
        rep = run_watch(
            config_path=cfg_path,
            interval_s=args.watch_interval,
            max_rounds=args.watch_rounds,
        )
        print(json.dumps({k: rep[k] for k in rep if k != "live_session"}, indent=2)[:5000])
        return 0 if rep.get("hit") or rep.get("verdict") == "WATCH_NO_EDGE" else 2
    rep = run_session(config_path=cfg_path, mode=args.mode, session_id=args.session_id)
    print(json.dumps({k: rep[k] for k in rep if k != "modes"}, indent=2))
    for name, mode_rep in (rep.get("modes") or {}).items():
        slim = {k: mode_rep[k] for k in mode_rep if k not in ("candidates", "skipped_head")}
        slim["accepted_slugs"] = [c["slug"] for c in mode_rep.get("candidates", [])]
        slim["near_miss_n"] = len(mode_rep.get("near_miss") or [])
        print(f"\n--- {name} ---")
        print(json.dumps(slim, indent=2)[:4500])
    ok = rep.get("overall_verdict") in (
        "MICRO_DRY_READY",
        "MICRO_DRY_PATH_READY",
        "BOOK_SIM_OK",
        "NO_OPEN_EDGE",
        "BOOK_OK_CLOB_NO_POST",
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
