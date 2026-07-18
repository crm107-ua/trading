"""Unit tests for BTC spot geo-fallback helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from polymarket.src.data.btc_spot import fetch_btc_spot_rest


def _resp(status: int, payload: dict) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.test"))


def test_fetch_btc_spot_median_blend() -> None:
    def fake_get(url: str, params=None):  # noqa: ANN001
        if "binance.com" in url:
            return _resp(451, {"code": 0, "msg": "restricted"})
        if "coinbase" in url:
            return _resp(200, {"data": {"amount": "100.0", "base": "BTC", "currency": "USD"}})
        if "okx" in url:
            return _resp(200, {"data": [{"last": "200.0"}]})
        if "kraken" in url:
            return _resp(200, {"result": {"XXBTZUSD": {"c": ["300.0", "0.1"]}}})
        return _resp(500, {"error": "no"})

    client = MagicMock()
    client.get.side_effect = fake_get
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        price, _lat, source = fetch_btc_spot_rest()

    assert price == 200.0  # median of 100,200,300
    assert source.startswith("median:")
    assert "coinbase" in source and "okx" in source and "kraken" in source


def test_fetch_btc_spot_coinbase_single_mode() -> None:
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
    client = MagicMock()
    client.get.return_value = _resp(503, {"error": "down"})
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)

    with patch("polymarket.src.data.btc_spot.httpx.Client", return_value=client):
        with pytest.raises(RuntimeError, match="BTC spot unavailable"):
            fetch_btc_spot_rest()
