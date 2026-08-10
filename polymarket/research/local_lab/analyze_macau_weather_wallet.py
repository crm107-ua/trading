#!/usr/bin/env python3
"""
Analyze Polymarket wallet macau.weather (temperature ladder DNA).

  python -m polymarket.research.local_lab.analyze_macau_weather_wallet
"""

from __future__ import annotations

import collections
import json
import re
import statistics
from pathlib import Path

import httpx

ADDR = "0x4989bfed5900ba096b08ba1f9b718464527c983e"
POLY = Path(__file__).resolve().parents[2]
OUT = POLY / "data_local" / "local_lab" / "weather_research" / "macau_weather_profile.json"
SLUG_RE = re.compile(r"(highest|lowest)-temperature-in-([a-z0-9\-]+)-on-", re.I)


def _paginate(client: httpx.Client, path: str, *, limit: int = 50, max_rows: int = 800) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while offset < max_rows:
        r = client.get(
            f"https://data-api.polymarket.com{path}",
            params={"user": ADDR, "limit": limit, "offset": offset},
        )
        r.raise_for_status()
        batch = r.json() or []
        if not batch:
            break
        rows.extend(batch)
        offset += len(batch)
        if len(batch) < limit:
            break
    return rows


def main() -> int:
    with httpx.Client(timeout=40.0, headers={"User-Agent": "Mozilla/5.0"}) as client:
        closed = _paginate(client, "/closed-positions", limit=50, max_rows=800)
        profile = client.get(f"https://gamma-api.polymarket.com/public-profile?address={ADDR}").json()

    events: dict[tuple[str, str, str], list[dict]] = collections.defaultdict(list)
    for p in closed:
        slug = str(p.get("eventSlug") or "")
        m = SLUG_RE.search(slug)
        if not m:
            continue
        events[(m.group(1).lower(), m.group(2).lower(), slug)].append(p)

    by_city_kind: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    widths: list[int] = []
    baskets: list[float] = []
    for (kind, city, slug), ps in events.items():
        pnl = sum(float(x.get("realizedPnl") or 0) for x in ps)
        unit = sum(float(x.get("avgPrice") or 0) for x in ps)
        widths.append(len(ps))
        baskets.append(unit)
        by_city_kind[(city, kind)].append(
            {"slug": slug, "pnl": pnl, "legs": len(ps), "unit_basket": unit, "win": pnl > 0}
        )

    all_ev = [x for xs in by_city_kind.values() for x in xs]
    rows = []
    for (city, kind), xs in by_city_kind.items():
        n = len(xs)
        wins = sum(1 for x in xs if x["win"])
        pnl = sum(x["pnl"] for x in xs)
        rows.append(
            {
                "city": city,
                "kind": kind,
                "n": n,
                "wr": round(wins / n, 4) if n else None,
                "pnl": round(pnl, 2),
            }
        )
    rows.sort(key=lambda r: r["pnl"], reverse=True)

    report = {
        "address": ADDR,
        "name": profile.get("name") or "macau.weather",
        "created_at": profile.get("createdAt"),
        "weighted_volume": profile.get("weightedVolume"),
        "closed_positions": len(closed),
        "event_n": len(all_ev),
        "event_wr": round(sum(1 for x in all_ev if x["win"]) / len(all_ev), 4) if all_ev else None,
        "event_pnl": round(sum(x["pnl"] for x in all_ev), 2),
        "width_median": statistics.median(widths) if widths else None,
        "unit_basket_median": round(statistics.median(baskets), 4) if baskets else None,
        "by_city_kind": rows,
        "takeaways": [
            "Temperature ladder bot (SurferX family), not BTC-5m maker",
            "Profit concentrated in Hong Kong highest + lowest",
            "Do not copy Shenzhen/Guangzhou or expensive baskets (~0.82 median)",
            "Compatible with our weather ladder; keep cheap-basket + floor gates",
            "Next research sleeve: lowest-temperature-in-hong-kong",
        ],
        "compatibility": {
            "our_modules": ["polymarket/src/weather/*", "weather_ladder_champion_v2.json"],
            "overlap": "high",
            "copy_mode": "universe+discipline (HK focus), not size/width clone",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)[:3500])
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
