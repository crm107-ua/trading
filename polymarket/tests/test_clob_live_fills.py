"""Tests de detección de fills CLOB (orden MATCHED + maker_orders)."""

from __future__ import annotations

from polymarket.src.execution.clob_live import ClobLiveClient, normalize_live_order


def test_normalize_min_shares_and_notional():
    px, sz = normalize_live_order(side="BUY", price=0.43, size=1.0)
    assert sz >= 5.0
    assert px * sz >= 1.0 - 1e-9


def test_normalize_sell_never_bumps_above_inventory():
    px, sz = normalize_live_order(side="SELL", price=0.10, size=4.990644)
    assert sz <= 4.990644 + 1e-9
    assert sz >= 4.99  # floor 6dp keeps most of it


def test_apply_live_floors_widen_opportunity():
    from polymarket.web_lab.catalog import apply_live_clob_floors

    cfg = apply_live_clob_floors(
        {
            "quote_size_shares": 1,
            "min_quote_mid": 0.24,
            "max_quote_mid": 0.76,
            "min_edge": 0.034,
            "min_z": 1.0,
            "min_expected_pnl_usdc": 0.35,
        }
    )
    assert cfg["quote_size_shares"] >= 5
    assert cfg["max_quote_mid"] >= 0.84
    assert cfg["min_quote_mid"] <= 0.18
    assert cfg["min_edge"] <= 0.026
    assert cfg["allow_rich_side_live"] is True


def test_apply_live_floors_preserve_grind_lock_loss():
    from polymarket.web_lab.catalog import apply_live_clob_floors

    cfg = apply_live_clob_floors(
        {
            "demo_label": "grind_nim_flow",
            "preserve_selectivity": True,
            "quote_size_shares": 5,
            "lock_profit_usdc": 0.10,
            "max_loss_usdc": 0.10,
            "min_quote_mid": 0.28,
            "max_quote_mid": 0.72,
            "min_edge": 0.028,
        }
    )
    assert cfg["lock_profit_usdc"] <= 0.12
    assert cfg["max_loss_usdc"] <= 0.12
    assert cfg["min_quote_mid"] >= 0.28
    assert cfg["max_quote_mid"] <= 0.72


def test_position_token_prefers_held():
    from pathlib import Path
    from polymarket.research.local_lab.live_maker import LiveSession
    from polymarket.src.execution.clob_live import ClobLiveClient

    s = LiveSession(cfg={}, out_dir=Path("."), clob=ClobLiveClient(), bankroll=1.0)
    s.inventory_shares = 5.0
    s.held_token_id = "DOWN_TOKEN"
    s.open_token_id = "UP_TOKEN"
    assert s._position_token("UP_TOKEN") == "DOWN_TOKEN"
    s.inventory_shares = 0.0
    assert s._position_token("UP_TOKEN") == "UP_TOKEN"


def test_quote_side_helpers():
    from types import SimpleNamespace
    from polymarket.research.local_lab.live_maker import LiveSession

    cheap = SimpleNamespace(bid=0.42, ask=0.99, size_shares=5)
    rich = SimpleNamespace(bid=0.01, ask=0.61, size_shares=5)
    assert LiveSession._is_cheap_quote(cheap)
    assert not LiveSession._is_rich_quote(cheap)
    assert LiveSession._is_rich_quote(rich)
    assert not LiveSession._is_cheap_quote(rich)


def test_place_post_only_rejects_dust_sell_without_api(monkeypatch):
    """SELL < 5 no debe llegar al CLOB (evita spam 4990644 vs 5000000)."""
    from polymarket.src.execution import clob_live as mod

    cli = ClobLiveClient()
    cli.gates = mod.read_gates()
    # Fake client that would fail the test if called
    class Boom:
        def get_tick_size(self, *_a, **_k):
            return 0.01

        def create_order(self, *_a, **_k):
            raise AssertionError("no debe firmar dust sell")

    cli._client = Boom()
    try:
        cli.place_post_only_gtc(
            token_id="1", side="SELL", price=0.10, size=4.990644
        )
        assert False, "debía lanzar ValueError"
    except ValueError as e:
        assert "dust" in str(e).lower() or "min" in str(e).lower()


def test_fill_from_order_matched():
    order = {
        "id": "0xabc",
        "status": "MATCHED",
        "side": "BUY",
        "original_size": "5",
        "size_matched": "5",
        "price": "0.36",
        "asset_id": "123",
    }
    fill = ClobLiveClient.fill_from_order(order)
    assert fill is not None
    assert fill["size"] == 5.0
    assert fill["price"] == 0.36
    assert fill["side"] == "BUY"


def test_fills_from_trades_maker_orders():
    our = "0xca0675cebf218fce116120cca9df89d63b16522f1c0e92f89b1c54a0e2865894"
    trades = [
        {
            "id": "8f17b57a-54c5-45bd-90ea-bf8c30e4195b",
            "asset_id": "DOWN_TOKEN",
            "side": "BUY",
            "size": "77",
            "price": "0.65",
            "maker_orders": [
                {
                    "order_id": our,
                    "price": "0.36",
                    "matched_amount": "5",
                    "side": "BUY",
                }
            ],
        }
    ]
    found = ClobLiveClient.fills_from_trades(trades, {our})
    assert len(found) == 1
    assert found[0]["size"] == 5.0
    assert found[0]["price"] == 0.36
    assert found[0]["order_id"].lower() == our.lower()
