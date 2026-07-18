"""Unit tests for BTC spot geo-fallback helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from polymarket.src.data.btc_spot import fetch_btc_spot_rest


def _resp(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.test"))


def test_fetch_btc_spot_falls_back_to_binance_us() -> None:
    calls: list[str] = []

    def fake_get(url: str, params=None):  # noqa: ANN001
        calls.append(url)
        if "binance.com" in url:
            return _resp(451, {"code": 0, "msg": "restricted"})
        if "binance.us" in url:
            return _resp(200, {"symbol": "BTCUSDT", "price": "64000.5"})
        return _resp(500, {"error": "no"})

    client = MagicMock()
    client.get.side_effect = fake_get
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        price, _lat, source = fetch_btc_spot_rest()

    assert price == 64000.5
    assert source == "binance_us"
    assert any("binance.com" in u for u in calls)
    assert any("binance.us" in u for u in calls)


def test_fetch_btc_spot_coinbase_fallback() -> None:
    def fake_get(url: str, params=None):  # noqa: ANN001
        if "coinbase" in url:
            return _resp(200, {"data": {"amount": "64111.25", "base": "BTC", "currency": "USD"}})
        return _resp(451, {"msg": "no"})

    client = MagicMock()
    client.get.side_effect = fake_get
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        price, _lat, source = fetch_btc_spot_rest()

    assert price == 64111.25
    assert source == "coinbase"


def test_fetch_btc_spot_all_fail() -> None:
    client = MagicMock()
    client.get.return_value = _resp(503, {"error": "down"})
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match="BTC spot unavailable"):
            fetch_btc_spot_rest()
