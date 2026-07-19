"""BTC spot helpers with geo-fallback + anti-sticky multi-venue blend.

Binance.com often 451 outside allowed regions. Coinbase / Binance.US can
freeze for many seconds and pin a naive median — which kills FollowGate
roll/velocity. We drop sticky pivot venues when the cross-section has moved,
and never flip to a single outlier print.
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import httpx

# (source, url, params, kind) — order is probe order for single-source mode
_SPOT_SOURCES: tuple[tuple[str, str, dict[str, str] | None, str], ...] = (
    ("binance", "https://api.binance.com/api/v3/ticker/price", {"symbol": "BTCUSDT"}, "price"),
    ("coinbase", "https://api.coinbase.com/v2/prices/BTC-USD/spot", None, "coinbase"),
    ("okx", "https://www.okx.com/api/v5/market/ticker", {"instId": "BTC-USDT"}, "okx"),
    ("kraken", "https://api.kraken.com/0/public/Ticker", {"pair": "XBTUSD"}, "kraken"),
    ("binance_us", "https://api.binance.us/api/v3/ticker/price", {"symbol": "BTCUSDT"}, "price"),
)

_MEDIAN_SOURCES = ("binance", "okx", "kraken", "coinbase", "binance_us")

# source -> (last_price, last_change_mono)
_VENUE_LAST: dict[str, tuple[float, float]] = {}
_LAST_BLEND: float | None = None
_DEFAULT_STALE_S = 4.0
_MAX_BLEND_JUMP_USD = 40.0


def _parse_price(source: str, payload: dict[str, Any], kind: str) -> float:
    if kind == "price":
        return float(payload["price"])
    if kind == "coinbase":
        return float(payload["data"]["amount"])
    if kind == "okx":
        data = payload.get("data") or []
        if not data:
            raise ValueError("okx empty data")
        return float(data[0]["last"])
    if kind == "kraken":
        result = payload.get("result") or {}
        if not result:
            raise ValueError("kraken empty result")
        first = next(iter(result.values()))
        return float(first["c"][0])
    raise ValueError(f"unknown price kind {kind!r} for {source}")


def _source_map() -> dict[str, tuple[str, dict[str, str] | None, str]]:
    return {name: (url, params, kind) for name, url, params, kind in _SPOT_SOURCES}


def _note_venue_price(source: str, price: float, *, now: float | None = None) -> float:
    """Record venue print; return seconds since last price change."""
    ts = time.monotonic() if now is None else now
    prev = _VENUE_LAST.get(source)
    if prev is None or abs(prev[0] - price) > 1e-9:
        _VENUE_LAST[source] = (price, ts)
        return 0.0
    return max(0.0, ts - prev[1])


def _center(vals: list[float]) -> float:
    if len(vals) == 1:
        return float(vals[0])
    if len(vals) == 2:
        return float(statistics.mean(vals))
    return float(statistics.median(vals))


def _blend_prices(
    prices: list[tuple[str, float]],
    *,
    stale_s: float = _DEFAULT_STALE_S,
    now: float | None = None,
) -> tuple[float, str]:
    """Prefer venues that still tick; avoid sticky Coinbase pinning the median."""
    global _LAST_BLEND
    ts = time.monotonic() if now is None else now
    tracked: list[tuple[str, float, float]] = []
    for source, price in prices:
        age = _note_venue_price(source, price, now=ts)
        tracked.append((source, price, age))

    fresh = [(s, p) for s, p, age in tracked if age < stale_s]
    sticky = [(s, p) for s, p, age in tracked if age >= stale_s]

    if len(fresh) >= 2:
        kept = fresh
    elif len(fresh) == 1:
        # Un solo ticker fresco: anclar con stickies cercanos (anti-salto).
        fp = fresh[0][1]
        near = [(s, p) for s, p in sticky if abs(p - fp) <= 25.0]
        kept = fresh + near if near else fresh
    else:
        kept = [(s, p) for s, p, _a in tracked]

    mid = _center([p for _, p in kept])
    # Clamp solo si queda 1 venue (evita salto falso); 2+ frescos pueden moverse.
    if (
        len(kept) == 1
        and _LAST_BLEND is not None
        and abs(mid - _LAST_BLEND) > _MAX_BLEND_JUMP_USD
    ):
        mid = 0.55 * mid + 0.45 * _LAST_BLEND
    _LAST_BLEND = mid
    tag = "+".join(s for s, _ in kept)
    return float(mid), f"fresh:{tag}"


def reset_venue_freshness() -> None:
    """Test helper — clear stale-tracking state."""
    global _LAST_BLEND
    _VENUE_LAST.clear()
    _LAST_BLEND = None


def fetch_btc_spot_rest(*, timeout: float = 10.0, median: bool = True) -> tuple[float, float, str]:
    """Return (price, latency_ms, source). Raises RuntimeError if all sources fail."""
    errors: list[str] = []
    t0 = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
        if median:
            prices: list[tuple[str, float]] = []
            for source in _MEDIAN_SOURCES:
                url, params, kind = _source_map()[source]
                try:
                    r = client.get(url, params=params)
                    if r.status_code >= 400:
                        errors.append(f"{source}:{r.status_code}")
                        continue
                    prices.append((source, _parse_price(source, r.json(), kind)))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{source}:{type(exc).__name__}")
            if prices:
                mid, tag = _blend_prices(prices)
                latency_ms = (time.perf_counter() - t0) * 1000
                return mid, latency_ms, tag

        for source, url, params, kind in _SPOT_SOURCES:
            try:
                r = client.get(url, params=params)
                if r.status_code >= 400:
                    errors.append(f"{source}:{r.status_code}")
                    continue
                price = _parse_price(source, r.json(), kind)
                latency_ms = (time.perf_counter() - t0) * 1000
                return price, latency_ms, source
            except Exception as exc:  # noqa: BLE001 — try next source
                errors.append(f"{source}:{type(exc).__name__}")
    raise RuntimeError("BTC spot unavailable: " + "; ".join(errors))


async def fetch_btc_spot_async(
    client: httpx.AsyncClient | None = None,
    *,
    timeout: float = 12.0,
    median: bool = True,
) -> tuple[float, str]:
    """Return (price, source). Raises RuntimeError if all sources fail."""
    errors: list[str] = []
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        if median:
            prices: list[tuple[str, float]] = []
            for source in _MEDIAN_SOURCES:
                url, params, kind = _source_map()[source]
                try:
                    r = await client.get(url, params=params)
                    if r.status_code >= 400:
                        errors.append(f"{source}:{r.status_code}")
                        continue
                    prices.append((source, _parse_price(source, r.json(), kind)))
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{source}:{type(exc).__name__}")
            if prices:
                mid, tag = _blend_prices(prices)
                return mid, tag

        for source, url, params, kind in _SPOT_SOURCES:
            try:
                r = await client.get(url, params=params)
                if r.status_code >= 400:
                    errors.append(f"{source}:{r.status_code}")
                    continue
                return _parse_price(source, r.json(), kind), source
            except Exception as exc:  # noqa: BLE001 — try next source
                errors.append(f"{source}:{type(exc).__name__}")
    finally:
        if owns:
            await client.aclose()
    raise RuntimeError("BTC spot unavailable: " + "; ".join(errors))
