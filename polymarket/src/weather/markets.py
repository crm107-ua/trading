"""Gamma + CLOB discovery for Polymarket highest-temperature events."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import httpx

from polymarket.src.data.book_utils import best_bid_ask
from polymarket.src.weather.stations import STATIONS, get_station

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

_TEMP_RE = re.compile(
    r"(?P<lo>\d+)\s*°\s*[CF]\s*or\s*below|"
    r"(?P<hi>\d+)\s*°\s*[CF]\s*or\s*higher|"
    r"(?P<exact>\d+)\s*°\s*[CF]",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(
    r"highest-temperature-in-(?P<city>[a-z0-9-]+)-on-(?P<mon>[a-z]+)-(?P<day>\d{1,2})-(?P<year>\d{4})",
    re.IGNORECASE,
)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass
class TempBucketMarket:
    name: str
    temp_c: int | None
    token_yes: str
    ask: float
    bid: float | None
    mid: float | None
    gamma_yes: float | None
    market_id: str
    closed: bool


@dataclass
class TempEvent:
    slug: str
    title: str
    city: str
    day: date
    buckets: list[TempBucketMarket]
    closed: bool


def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


def parse_bucket_label(label: str) -> tuple[str, int | None]:
    """Return (normalized_name, temp_c or None for open-ended)."""
    text = label.strip()
    m = _TEMP_RE.search(text)
    if not m:
        return text, None
    if m.group("exact"):
        t = int(m.group("exact"))
        return f"{t}°C", t
    if m.group("lo"):
        t = int(m.group("lo"))
        return f"{t}°C or below", None
    if m.group("hi"):
        t = int(m.group("hi"))
        return f"{t}°C or higher", None
    return text, None


def parse_event_slug(slug: str) -> tuple[str, date] | None:
    m = _SLUG_RE.fullmatch(slug.strip())
    if not m:
        return None
    city = m.group("city").lower()
    mon = _MONTHS.get(m.group("mon").lower())
    if mon is None:
        return None
    return city, date(int(m.group("year")), mon, int(m.group("day")))


def discover_temperature_slugs(
    *,
    cities: list[str] | None = None,
    limit_per_city: int = 4,
    timeout_s: float = 20.0,
) -> list[str]:
    cities = cities or list(STATIONS.keys())
    slugs: list[str] = []
    with httpx.Client(timeout=timeout_s) as client:
        for city in cities:
            q = f"highest temperature in {city.replace('-', ' ')}"
            r = client.get(f"{GAMMA}/public-search", params={"q": q, "limit": limit_per_city})
            if r.status_code != 200:
                continue
            data = r.json()
            events = data.get("events") if isinstance(data, dict) else data
            if not isinstance(events, list):
                continue
            for e in events:
                if not isinstance(e, dict):
                    continue
                slug = str(e.get("slug") or "")
                if slug.startswith("highest-temperature-in-"):
                    slugs.append(slug)
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for s in slugs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _clob_ask(token_id: str, client: httpx.Client) -> tuple[float | None, float | None]:
    r = client.get(f"{CLOB}/book", params={"token_id": token_id})
    if r.status_code != 200:
        return None, None
    data = r.json()
    bb, ba = best_bid_ask(data.get("bids") or [], data.get("asks") or [])
    return bb, ba


def fetch_temp_event(slug: str, *, timeout_s: float = 20.0, use_clob: bool = True) -> TempEvent | None:
    parsed = parse_event_slug(slug)
    if parsed is None:
        return None
    city, day = parsed
    if get_station(city) is None:
        # still allow unknown cities with default handling upstream
        pass
    with httpx.Client(timeout=timeout_s) as client:
        r = client.get(f"{GAMMA}/events", params={"slug": slug})
        r.raise_for_status()
        payload = r.json()
        if not payload:
            return None
        ev = payload[0] if isinstance(payload, list) else payload
        buckets: list[TempBucketMarket] = []
        for m in ev.get("markets") or []:
            label = m.get("groupItemTitle") or m.get("question") or ""
            name, temp_c = parse_bucket_label(str(label))
            tokens = _parse_json_list(m.get("clobTokenIds"))
            if not tokens:
                continue
            token_yes = str(tokens[0])
            prices = _parse_json_list(m.get("outcomePrices"))
            gamma_yes = float(prices[0]) if prices else None
            bid = ask = None
            if use_clob and not bool(m.get("closed")):
                bid, ask = _clob_ask(token_yes, client)
            # Prefer executable ask; fall back to gamma YES price
            px = ask if ask is not None else gamma_yes
            if px is None:
                continue
            mid = None
            if bid is not None and ask is not None:
                mid = (bid + ask) / 2.0
            elif gamma_yes is not None:
                mid = gamma_yes
            buckets.append(
                TempBucketMarket(
                    name=name,
                    temp_c=temp_c,
                    token_yes=token_yes,
                    ask=float(px),
                    bid=bid,
                    mid=mid,
                    gamma_yes=gamma_yes,
                    market_id=str(m.get("id") or ""),
                    closed=bool(m.get("closed")),
                )
            )
        buckets.sort(key=lambda b: (b.temp_c is None, b.temp_c if b.temp_c is not None else 10**9, b.name))
        return TempEvent(
            slug=slug,
            title=str(ev.get("title") or slug),
            city=city,
            day=day,
            buckets=buckets,
            closed=bool(ev.get("closed")),
        )


def winning_bucket(event: TempEvent) -> TempBucketMarket | None:
    """Resolved winner ≈ gamma YES near 1."""
    best = None
    best_p = -1.0
    for b in event.buckets:
        p = b.gamma_yes if b.gamma_yes is not None else -1.0
        if p > best_p:
            best_p = p
            best = b
    if best is not None and best_p >= 0.95:
        return best
    return None


def horizon_days(event_day: date, *, today: date | None = None) -> int:
    today = today or datetime.utcnow().date()  # noqa: DTZ003 — paper lab wall clock
    return (event_day - today).days


def historical_entry_ask(
    token_id: str,
    *,
    timeout_s: float = 30.0,
    client: httpx.Client | None = None,
    retries: int = 2,
) -> float | None:
    """
    Pre-resolution YES price from CLOB history.
    Uses an early percentile (not the final spike to ~1) so paper entry
    matches the article's 'buy the neighborhood before the crowd reprices'.
    """
    own = client is None
    http = client or httpx.Client(timeout=timeout_s)
    try:
        last_exc: Exception | None = None
        for attempt in range(max(1, retries + 1)):
            try:
                r = http.get(
                    f"{CLOB}/prices-history",
                    params={"market": token_id, "interval": "max", "fidelity": 60},
                )
                if r.status_code != 200:
                    return None
                hist = (r.json() or {}).get("history") or []
                prices = [float(p["p"]) for p in hist if p.get("p") is not None]
                if not prices:
                    return None
                # Drop terminal resolution spike; take early/mid uncertainty window
                usable = [p for p in prices if 0.01 <= p <= 0.85]
                if not usable:
                    usable = prices[: max(1, len(prices) // 2)]
                usable_sorted = sorted(usable)
                # ~35th percentile — still cheap insurance / center before squeeze
                idx = max(0, min(len(usable_sorted) - 1, int(0.35 * (len(usable_sorted) - 1))))
                return float(usable_sorted[idx])
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt < retries:
                    continue
                return None
        _ = last_exc
        return None
    finally:
        if own:
            http.close()
