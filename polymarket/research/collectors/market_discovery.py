"""Gamma API — BTC Up/Down 5m market discovery and rotation."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from polymarket.src.data.market_info import MarketInfo

GAMMA = "https://gamma-api.polymarket.com"
WINDOW_SECONDS = 300

_TIME_RANGE = re.compile(
    r"(\d{1,2}):(\d{2})\s*(AM|PM)\s*-\s*(\d{1,2}):(\d{2})\s*(AM|PM)",
    re.IGNORECASE,
)


def _parse_clock(h: int, m: int, ampm: str) -> int:
    ampm = ampm.upper()
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return h * 60 + m


def _range_minutes(match: re.Match[str]) -> int | None:
    h1, m1, ap1, h2, m2, ap2 = match.groups()
    start = _parse_clock(int(h1), int(m1), ap1)
    end = _parse_clock(int(h2), int(m2), ap2)
    delta = end - start
    if delta <= 0:
        delta += 24 * 60
    return delta


def is_btc_5m_window(question: str) -> bool:
    """True only for explicit ~5 minute BTC Up/Down windows."""
    q = question.lower()
    if "bitcoin" not in q or "up or down" not in q:
        return False
    if re.search(r"\bon\s+\w+\s+\d", q) and _TIME_RANGE.search(question) is None:
        return False
    m = _TIME_RANGE.search(question)
    if not m:
        return False
    minutes = _range_minutes(m)
    if minutes is None:
        return False
    return 4 <= minutes <= 6


def _parse_token_ids(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return json.loads(raw)
    return [str(x) for x in raw]


def _parse_end_time(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _market_from_gamma(m: dict[str, Any], title: str) -> MarketInfo | None:
    question = m.get("question") or title
    if not is_btc_5m_window(question):
        return None
    tids = _parse_token_ids(m.get("clobTokenIds"))
    if not tids:
        return None
    return MarketInfo(
        market_id=str(m.get("id")),
        question=question,
        token_id_up=tids[0],
        token_id_down=tids[1] if len(tids) > 1 else None,
        end_time=m.get("endDate") or "",
        accepting_orders=bool(m.get("acceptingOrders")),
        event_title=title,
    )


def _fetch_event_by_slug(client: httpx.Client, slug: str) -> list[MarketInfo]:
    last: Exception | None = None
    for attempt in range(4):
        try:
            r = client.get(f"{GAMMA}/events", params={"slug": slug}, timeout=30.0)
            r.raise_for_status()
            events = r.json() if isinstance(r.json(), list) else []
            out: list[MarketInfo] = []
            for ev in events:
                title = ev.get("title") or ""
                for m in ev.get("markets") or []:
                    info = _market_from_gamma(m, title)
                    if info:
                        out.append(info)
            return out
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            time.sleep(min(20.0, 1.5 * (attempt + 1)))
    if last is not None:
        raise last
    return []


def discover_btc_5m_by_slug(
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> list[MarketInfo]:
    """Direct slug lookup — reliable for live 5m windows (public-search lags)."""
    own = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": "polymarket-lab/0.1-phase-a"})
    now = now or datetime.now(timezone.utc)
    base_ts = int(now.timestamp()) // WINDOW_SECONDS * WINDOW_SECONDS
    out: list[MarketInfo] = []
    seen: set[str] = set()
    try:
        for offset in (-WINDOW_SECONDS, 0, WINDOW_SECONDS, 2 * WINDOW_SECONDS):
            slug = f"btc-updown-5m-{base_ts + offset}"
            for info in _fetch_event_by_slug(client, slug):
                if info.market_id not in seen:
                    seen.add(info.market_id)
                    out.append(info)
        out.sort(key=lambda x: _parse_end_time(x.end_time) or datetime.max.replace(tzinfo=timezone.utc))
        return out
    finally:
        if own:
            client.close()


def discover_btc_5m_updown(client: httpx.Client | None = None) -> list[MarketInfo]:
    own = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": "polymarket-lab/0.1-phase-a"})
    try:
        slug_markets = discover_btc_5m_by_slug(client)
        r = client.get(
            f"{GAMMA}/public-search",
            params={"q": "Bitcoin Up or Down", "events_status": "active"},
        )
        r.raise_for_status()
        events = r.json().get("events") or []
        out: list[MarketInfo] = list(slug_markets)
        seen = {m.market_id for m in out}
        for ev in events:
            title = ev.get("title") or ""
            if "bitcoin" not in title.lower():
                continue
            for m in ev.get("markets") or []:
                info = _market_from_gamma(m, title)
                if info and info.market_id not in seen:
                    seen.add(info.market_id)
                    out.append(info)
        out.sort(key=lambda x: _parse_end_time(x.end_time) or datetime.max.replace(tzinfo=timezone.utc))
        return out
    finally:
        if own:
            client.close()


def window_end(m: MarketInfo) -> datetime | None:
    return _parse_end_time(m.end_time)


def window_start(m: MarketInfo) -> datetime | None:
    """5m windows: start = end - 5 minutes (endDate is window close)."""
    end = window_end(m)
    if end is None:
        return None
    return end - timedelta(minutes=5)


def pick_recording_targets(
    markets: list[MarketInfo],
    now: datetime | None = None,
) -> tuple[MarketInfo | None, MarketInfo | None]:
    """Return (current_active, next_upcoming) 5m windows."""
    now = now or datetime.now(timezone.utc)
    open_markets = []
    for m in markets:
        end = window_end(m)
        if end and end > now:
            open_markets.append(m)
    if not open_markets:
        future = sorted(
            [m for m in markets if (window_end(m) or now) > now],
            key=lambda x: window_end(x) or now,
        )
        return None, (future[0] if future else None)
    active = min(open_markets, key=lambda m: window_end(m) or now)
    active_end = window_end(active)
    nxt = None
    for m in markets:
        end = window_end(m)
        if end and active_end and end > active_end:
            if nxt is None or end < (window_end(nxt) or end):
                nxt = m
    return active, nxt


def should_pre_subscribe(
    active: MarketInfo,
    nxt: MarketInfo,
    now: datetime,
    pre_lead_s: float,
) -> bool:
    """True when within pre_lead_s of active window close (next opens at active end)."""
    active_end = window_end(active)
    if active_end is None:
        return False
    return 0 < (active_end - now).total_seconds() <= pre_lead_s


def discovery_poll_seconds(
    active: MarketInfo | None,
    now: datetime,
    default: float = 30.0,
    fast: float = 10.0,
    fast_window_s: float = 120.0,
) -> float:
    """Poll faster near window rollover or when no active market (Gamma gap)."""
    if active is None:
        return fast
    active_end = window_end(active)
    if active_end is None:
        return default
    if (active_end - now).total_seconds() <= fast_window_s:
        return fast
    return default


def discover_btc_updown(client: httpx.Client | None = None) -> list[MarketInfo]:
    """All active BTC up/down (unfiltered — legacy)."""
    own = client is None
    client = client or httpx.Client(timeout=20.0, headers={"User-Agent": "polymarket-lab/0.1"})
    try:
        r = client.get(
            f"{GAMMA}/public-search",
            params={"q": "Bitcoin Up or Down", "events_status": "active"},
        )
        r.raise_for_status()
        events = r.json().get("events") or []
        out: list[MarketInfo] = []
        for ev in events:
            title = ev.get("title") or ""
            if "bitcoin" not in title.lower():
                continue
            for m in ev.get("markets") or []:
                tids = _parse_token_ids(m.get("clobTokenIds"))
                if not tids:
                    continue
                out.append(
                    MarketInfo(
                        market_id=str(m.get("id")),
                        question=m.get("question") or title,
                        token_id_up=tids[0],
                        token_id_down=tids[1] if len(tids) > 1 else None,
                        end_time=m.get("endDate") or ev.get("endDate") or "",
                        accepting_orders=bool(m.get("acceptingOrders")),
                        event_title=title,
                    )
                )
        return out
    finally:
        if own:
            client.close()


def main() -> None:
    from polymarket.src.data import write_manifest

    markets = discover_btc_5m_updown()
    write_manifest(
        "market_discovery_latest",
        {
            "source": "gamma_public_search",
            "scope": "btc_5m_only",
            "count": len(markets),
            "markets": [m.__dict__ for m in markets[:20]],
        },
    )
    print(f"Found {len(markets)} active BTC Up/Down 5m windows")
    for m in markets[:5]:
        print(f"  {m.question} | up={m.token_id_up[:16]}... | end={m.end_time}")


if __name__ == "__main__":
    main()
