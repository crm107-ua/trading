#!/usr/bin/env python3
"""
Expand DNA evidence WITHOUT relaxing gates — incremental day backfill.

Unlike the full slug-discovery path (slow: hundreds of Gamma GETs before work),
this walks calendar days newest→oldest and only fetches missing city/day pairs.

  PYTHONPATH=. python3 -m polymarket.research.local_lab.expand_dna_evidence
  PYTHONPATH=. python3 -m polymarket.research.local_lab.expand_dna_evidence --max-new 40 --max-age-days 110
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from polymarket.research.local_lab.assure_wr80_income import take_income_wr80
from polymarket.research.local_lab.research_telemetry import write_evidence_progress
from polymarket.src.weather.forecast import fetch_historical_model_maxes
from polymarket.src.weather.markets import (
    fetch_temp_event,
    historical_entry_ask,
    winning_bucket,
)
from polymarket.src.weather.stations import get_station

POLY = Path(__file__).resolve().parents[2]
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"
OUT = POLY / "data_local" / "local_lab" / "vps_runs"
GAMMA = "https://gamma-api.polymarket.com"
DNA_CITIES = ["hong-kong", "beijing", "singapore", "shanghai"]
MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def _wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    den = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - margin) / den)


def _score_takes(takes: list[dict[str, Any]]) -> dict[str, Any]:
    wins = sum(1 for t in takes if t.get("win") or float(t.get("pnl") or 0) > 0)
    n = len(takes)
    return {
        "n": n,
        "wins": wins,
        "wr_point": round(wins / n, 4) if n else 0.0,
        "wilson95_lower": round(_wilson_lower(wins, n), 4),
        "by_city": dict(Counter(t.get("city") for t in takes)),
        "day_min": min((t.get("day") for t in takes), default=None),
        "day_max": max((t.get("day") for t in takes), default=None),
    }


def _slug(city: str, d) -> str:
    return f"highest-temperature-in-{city}-on-{MONTHS[d.month - 1]}-{d.day}-{d.year}"


def _gamma_exists(client: httpx.Client, slug: str) -> bool:
    try:
        r = client.get(f"{GAMMA}/events", params={"slug": slug}, timeout=15.0)
        return r.status_code == 200 and bool(r.json())
    except Exception:
        return False


def _build_case(slug: str, city: str, day, clob: httpx.Client) -> dict[str, Any] | None:
    station = get_station(city)
    if station is None or not station.volatile:
        return None
    try:
        event = fetch_temp_event(slug, use_clob=False)
    except Exception as exc:
        print(f"skip fetch {slug}: {exc}", flush=True)
        return None
    if event is None:
        return None
    if station.unit == "C" and any("°F" in (b.name or "") for b in event.buckets):
        return None
    if station.unit == "F" and any("°C" in (b.name or "") for b in event.buckets):
        return None
    winner = winning_bucket(event)
    if winner is None:
        return None
    try:
        models = fetch_historical_model_maxes(station, day)
    except Exception:
        time.sleep(0.6)
        try:
            models = fetch_historical_model_maxes(station, day)
        except Exception as exc:
            print(f"skip forecast {slug}: {exc}", flush=True)
            return None
    if len(models) < 2:
        return None
    point_temps = sorted({b.temp_c for b in event.buckets if b.temp_c is not None})
    if len(point_temps) < 3:
        return None
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
        return None
    return {
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
        "buckets": [{"name": b.name, "temp_c": b.temp_c} for b in event.buckets if b.temp_c is not None],
    }


def backfill(
    *,
    max_new: int,
    max_age_days: int,
    cities: list[str],
    start_age_days: int = 0,
    build_timeout_s: float = 55.0,
) -> tuple[list[dict[str, Any]], int]:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    cases: list[dict[str, Any]] = []
    if CASES.exists():
        cases = json.loads(CASES.read_text(encoding="utf-8"))
    have = {c["slug"] for c in cases}
    have_day_city = {(c["day"], c["city"]) for c in cases}
    today = datetime.now(timezone.utc).date()
    added = 0
    print(
        f"backfill start cases={len(cases)} max_new={max_new} age={max_age_days} "
        f"start_age={start_age_days} cities={cities}",
        flush=True,
    )
    with httpx.Client(timeout=httpx.Timeout(20.0, connect=8.0)) as clob, httpx.Client(
        timeout=12.0
    ) as gamma:
        for delta in range(int(start_age_days), int(max_age_days) + 1):
            if added >= max_new:
                break
            d = today - timedelta(days=delta)
            day_s = d.isoformat()
            for city in cities:
                if added >= max_new:
                    break
                if (day_s, city) in have_day_city:
                    continue
                slug = _slug(city, d)
                if slug in have:
                    continue
                if not _gamma_exists(gamma, slug):
                    continue
                print(f"trying {slug} …", flush=True)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    fut = pool.submit(_build_case, slug, city, d, clob)
                    try:
                        case = fut.result(timeout=float(build_timeout_s))
                    except FuturesTimeout:
                        print(f"timeout build {slug} (> {build_timeout_s}s)", flush=True)
                        continue
                    except Exception as exc:
                        print(f"error build {slug}: {type(exc).__name__}: {exc}", flush=True)
                        continue
                if case is None:
                    print(f"skip build {slug}", flush=True)
                    continue
                cases.append(case)
                have.add(slug)
                have_day_city.add((day_s, city))
                added += 1
                CASES.parent.mkdir(parents=True, exist_ok=True)
                CASES.write_text(json.dumps(cases, indent=2), encoding="utf-8")
                # live DNA probe for this case
                from polymarket.research.local_lab.assure_wr80_income import BJ_PRESS, CORE_PRESS
                from polymarket.research.local_lab.optimize_weather_ladder import _eval_case

                filt = BJ_PRESS if city == "beijing" else CORE_PRESS
                ev = _eval_case(case, filt)
                dna = bool(ev and ev.get("taken"))
                print(
                    f"+{added} case#{len(cases)} {slug} winner={case['winner']} dna_take={dna}",
                    flush=True,
                )
                time.sleep(0.1)
    return cases, added


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-new", type=int, default=40, help="Max NEW cases this run")
    ap.add_argument("--max-events", type=int, default=0, help="Deprecated compat")
    ap.add_argument("--max-age-days", type=int, default=110)
    ap.add_argument(
        "--start-age-days",
        type=int,
        default=0,
        help="Skip recent N days (e.g. 32 jumps before 2026-07-10 from mid-Aug)",
    )
    ap.add_argument("--build-timeout", type=float, default=55.0)
    ap.add_argument("--skip-fetch", action="store_true")
    args = ap.parse_args()
    max_new = int(args.max_new)
    if args.max_events and args.max_events > 0 and max_new == 40:
        before_n = len(json.loads(CASES.read_text())) if CASES.exists() else 0
        max_new = max(10, min(60, int(args.max_events) - before_n))

    before_cases = len(json.loads(CASES.read_text(encoding="utf-8"))) if CASES.exists() else 0
    before = _score_takes(
        take_income_wr80(json.loads(CASES.read_text(encoding="utf-8"))) if CASES.exists() else []
    )

    if args.skip_fetch:
        cases = json.loads(CASES.read_text(encoding="utf-8"))
        added = 0
        print(f"skip_fetch cases={len(cases)}", flush=True)
    else:
        # Auto-jump past dense covered window if start not set
        start_age = int(args.start_age_days)
        if start_age == 0 and CASES.exists():
            days = [c["day"] for c in json.loads(CASES.read_text(encoding="utf-8")) if c.get("city") in DNA_CITIES]
            if days:
                from datetime import date as date_cls

                oldest = date_cls.fromisoformat(min(days))
                today = datetime.now(timezone.utc).date()
                # start one day older than oldest covered DNA day
                start_age = max(0, (today - oldest).days + 1)
                print(f"auto start_age_days={start_age} (oldest DNA day {oldest})", flush=True)
        cases, added = backfill(
            max_new=max_new,
            max_age_days=int(args.max_age_days),
            cities=DNA_CITIES,
            start_age_days=start_age,
            build_timeout_s=float(args.build_timeout),
        )

    after_takes = take_income_wr80(cases)
    after = _score_takes(after_takes)
    ev = write_evidence_progress()

    prev_max = before.get("day_max") or "2026-08-09"
    prev_min = before.get("day_min") or "2026-07-10"
    new_take_slugs = [
        t["slug"]
        for t in after_takes
        if (t.get("day") or "") > prev_max or (t.get("day") or "") < prev_min
    ]

    report = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "incremental_day_backfill",
        "dna_gates": {"max_basket": 0.50, "max_leg": 0.39, "underdispersion": True},
        "cases_before": before_cases,
        "cases_after": len(cases),
        "cases_added": added,
        "takes_before": before,
        "takes_after": after,
        "delta_n": after["n"] - before["n"],
        "new_take_slugs": new_take_slugs,
        "evidence": ev,
        "note_es": (
            "Backfill incremental bajo la MISMA DNA. Forward WATCH sigue siendo OOS real. "
            "No depositar hasta READY_TO_REARM."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "DNA_EXPANSION_REPORT.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "DNA_EXPANSION_REPORT.md").write_text(
        "\n".join(
            [
                "# DNA evidence expansion",
                "",
                "- mode: incremental day backfill",
                f"- cases {before_cases} → {len(cases)} (+{added})",
                f"- DNA takes {before['n']} → {after['n']} (Δ {report['delta_n']})",
                f"- WR {before['wr_point']} → {after['wr_point']} · Wilson {before['wilson95_lower']} → {after['wilson95_lower']}",
                f"- by_city {after['by_city']}",
                f"- new_take_slugs {new_take_slugs}",
                "- DNA gates unchanged",
                "",
                report["note_es"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: report[k] for k in report if k != "evidence"}, indent=2), flush=True)
    print(f"report -> {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
