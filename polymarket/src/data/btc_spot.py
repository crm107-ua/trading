"""BTC spot helpers with geo-fallback + multi-venue median.

Binance.com often 451 outside allowed regions. Binance.US can freeze.
For PulseGate latency we sample multiple live venues and take a median
so a single stale ticker cannot pin lead=0.
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

# Venues used for median blend (skip known-stale binance_us by default).
_MEDIAN_SOURCES = ("binance", "coinbase", "okx", "kraken")


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
                vals = [p for _, p in prices]
                mid = float(statistics.median(vals))
                latency_ms = (time.perf_counter() - t0) * 1000
                tag = "+".join(s for s, _ in prices)
                return mid, latency_ms, f"median:{tag}"

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
                mid = float(statistics.median([p for _, p in prices]))
                tag = "+".join(s for s, _ in prices)
                return mid, f"median:{tag}"

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
