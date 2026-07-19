"""Unit tests for BTC spot geo-fallback helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from polymarket.src.data.btc_spot import (
    _blend_prices,
    fetch_btc_spot_rest,
    reset_venue_freshness,
)


def _resp(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.test"))


def test_fetch_btc_spot_fresh_blend() -> None:
    reset_venue_freshness()

    def fake_get(url: str, params=None):  # noqa: ANN001
        if "binance.com" in url:
            return _resp(451, {"code": 0, "msg": "restricted"})
        if "coinbase" in url:
            return _resp(200, {"data": {"amount": "100.0", "base": "BTC", "currency": "USD"}})
        if "okx" in url:
            return _resp(200, {"data": [{"last": "200.0"}]})
        if "kraken" in url:
            return _resp(200, {"result": {"XXBTZUSD": {"c": ["300.0", "0.1"]}}})
        if "binance.us" in url:
            return _resp(200, {"price": "250.0"})
        return _resp(500, {"error": "no"})

    client = MagicMock()
    client.get.side_effect = fake_get
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        price, _lat, source = fetch_btc_spot_rest()

    assert price == 225.0
    assert source.startswith("fresh:")
    assert "okx" in source and "kraken" in source


def test_blend_prefers_ticking_venues_over_sticky() -> None:
    reset_venue_freshness()
    t0 = 1000.0
    mid1, tag1 = _blend_prices(
        [("coinbase", 200.0), ("okx", 100.0), ("kraken", 300.0)],
        stale_s=4.0,
        now=t0,
    )
    assert mid1 == 200.0
    assert "coinbase" in tag1
    # Coinbase frozen; okx+kraken still tick → median without sticky pivot
    mid2, tag2 = _blend_prices(
        [("coinbase", 200.0), ("okx", 250.0), ("kraken", 270.0)],
        stale_s=4.0,
        now=t0 + 5.0,
    )
    assert "coinbase" not in tag2
    assert mid2 == 260.0
    assert "okx" in tag2 and "kraken" in tag2


def test_blend_keeps_all_when_nothing_ticks() -> None:
    reset_venue_freshness()
    t0 = 1000.0
    _blend_prices(
        [("coinbase", 100.0), ("okx", 101.0), ("kraken", 99.0)],
        stale_s=4.0,
        now=t0,
    )
    mid, tag = _blend_prices(
        [("coinbase", 100.0), ("okx", 101.0), ("kraken", 99.0)],
        stale_s=4.0,
        now=t0 + 5.0,
    )
    assert "coinbase" in tag and "okx" in tag and "kraken" in tag
    assert mid == 100.0


def test_fetch_btc_spot_coinbase_single_mode() -> None:
    reset_venue_freshness()

    def fake_get(url: str, params=None):  # noqa: ANN001
        if "coinbase" in url:
            return _resp(200, {"data": {"amount": "64111.25", "base": "BTC", "currency": "USD"}})
        return _resp(451, {"msg": "no"})

    client = MagicMock()
    client.get.side_effect = fake_get
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        price, _lat, source = fetch_btc_spot_rest(median=False)

    assert price == 64111.25
    assert source == "coinbase"


def test_fetch_btc_spot_all_fail() -> None:
    reset_venue_freshness()
    client = MagicMock()
    client.get.return_value = _resp(503, {"error": "down"})
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match="BTC spot unavailable"):
            fetch_btc_spot_rest()
