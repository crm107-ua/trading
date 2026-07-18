"""BTC spot helpers with geo-fallback (Binance.com often 451 outside allowed regions)."""

from __future__ import annotations

import time
from typing import Any

import httpx

# Prefer Binance.com (historical default), then same-shape Binance.US, then Coinbase.
_SPOT_SOURCES: tuple[tuple[str, str, dict[str, str] | None, str], ...] = (
    ("binance", "https://api.binance.com/api/v3/ticker/price", {"symbol": "BTCUSDT"}, "price"),
    ("binance_us", "https://api.binance.us/api/v3/ticker/price", {"symbol": "BTCUSDT"}, "price"),
    ("coinbase", "https://api.coinbase.com/v2/prices/BTC-USD/spot", None, "coinbase"),
)


def _parse_price(source: str, payload: dict[str, Any], kind: str) -> float:
    if kind == "price":
        return float(payload["price"])
    if kind == "coinbase":
        return float(payload["data"]["amount"])
    raise ValueError(f"unknown price kind {kind!r} for {source}")


def fetch_btc_spot_rest(*, timeout: float = 10.0) -> tuple[float, float, str]:
    """Return (price, latency_ms, source). Raises RuntimeError if all sources fail."""
    errors: list[str] = []
    t0 = time.perf_counter()
    with httpx.Client(timeout=timeout) as client:
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
) -> tuple[float, str]:
    """Return (price, source). Raises RuntimeError if all sources fail."""
    errors: list[str] = []
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
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
