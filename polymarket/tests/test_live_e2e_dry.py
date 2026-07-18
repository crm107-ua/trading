"""Fase B — ciclos dry Up / Down / dust / SKIP_CASH (sin red CLOB)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from polymarket.research.local_lab.live_maker import LiveSession
from polymarket.src.execution.clob_live import (
    ClobLiveClient,
    MIN_ORDER_SHARES,
    normalize_live_order,
    read_gates,
)


@pytest.fixture
def dry_session(tmp_path, monkeypatch):
    monkeypatch.setenv("POLY_LIVE_ARMED", "1")
    monkeypatch.setenv("POLY_LIVE_DRY_RUN", "1")
    cli = ClobLiveClient()
    # Avoid network in balance refresh
    cli.balance_collateral_usdc = MagicMock(return_value=6.0)
    cli.balance_conditional_shares = MagicMock(return_value=5.0)
    cli.place_post_only_gtc = MagicMock(
        return_value={
            "status": "DRY_RUN",
            "orderID": None,
            "would_post": {"price": 0.40, "size": 5.0},
        }
    )
    cli.place_aggressive = MagicMock(
        return_value={
            "status": "DRY_RUN",
            "orderID": None,
            "would_post": {"price": 0.39, "size": 5.0},
        }
    )
    cli.cancel = MagicMock(return_value={"status": "DRY_RUN"})
    cli.get_order = MagicMock(return_value=None)
    cli.open_orders = MagicMock(return_value=[])
    s = LiveSession(
        cfg={
            "initial_capital_usdc": 1.2,
            "max_notional_per_side_usdc": 2.0,
            "allow_rich_side_live": True,
            "lock_profit_usdc": 0.15,
            "max_loss_usdc": 0.35,
            "session_kill_net_usdc": 0.40,
            "max_entry_fills": 1,
        },
        out_dir=tmp_path,
        clob=cli,
        bankroll=1.2,
    )
    return s


def test_e2e_up_entry_sets_held_token(dry_session):
    s = dry_session
    target = SimpleNamespace(
        token_id_up="UP_TOKEN",
        token_id_down="DOWN_TOKEN",
    )
    quote = SimpleNamespace(bid=0.40, ask=0.99, size_shares=5)

    async def _run():
        tag = await s._post_entry(target, quote, bb=0.40, ba=0.45, fair_up=0.50)
        return tag

    tag = asyncio.run(_run())
    assert tag == "quote_up"
    assert s.held_token_id == "UP_TOKEN"
    assert s.position_leg == "up"


def test_e2e_rich_entry_sets_down_held(dry_session):
    s = dry_session

    async def fake_fetch(tid):
        return {
            "spot": 100000.0,
            "bids": [{"price": "0.35", "size": "10"}],
            "asks": [{"price": "0.36", "size": "10"}],
            "best_bid": 0.35,
            "best_ask": 0.36,
            "feed_ts_ms": 0,
        }

    s._fetch_state = fake_fetch  # type: ignore
    target = SimpleNamespace(token_id_up="UP_TOKEN", token_id_down="DOWN_TOKEN")
    quote = SimpleNamespace(bid=0.01, ask=0.65, size_shares=5)

    async def _run():
        return await s._post_entry(target, quote, bb=0.60, ba=0.65, fair_up=0.45)

    tag = asyncio.run(_run())
    assert tag == "quote_down"
    assert s.held_token_id == "DOWN_TOKEN"
    assert s.position_leg == "down"


def test_e2e_flatten_uses_held_not_up(dry_session):
    s = dry_session
    s.inventory_shares = 5.0
    s.cost_basis = 2.0
    s.held_token_id = "DOWN_TOKEN"
    s.position_leg = "down"
    s.open_token_id = "DOWN_TOKEN"

    async def fake_fetch(tid):
        assert tid == "DOWN_TOKEN"
        return {
            "spot": 1.0,
            "bids": [{"price": "0.30", "size": "10"}],
            "asks": [{"price": "0.31", "size": "10"}],
            "best_bid": 0.30,
            "best_ask": 0.31,
            "feed_ts_ms": 0,
        }

    s._fetch_state = fake_fetch  # type: ignore

    async def _run():
        await s._force_flatten(
            "UP_TOKEN",  # wrong on purpose
            best_bid=0.70,
            best_ask=0.71,
            reason="tp",
        )

    asyncio.run(_run())
    # aggressive or post_only called with DOWN
    calls = s.clob.place_aggressive.call_args_list + s.clob.place_post_only_gtc.call_args_list
    assert calls, "debía intentar salir"
    # kwargs token_id
    found = False
    for c in calls:
        kwargs = c.kwargs if c.kwargs else {}
        tid = kwargs.get("token_id") or (c.args[0] if c.args else None)
        if tid == "DOWN_TOKEN":
            found = True
    assert found, f"exit no usó DOWN: {calls}"


def test_e2e_skip_cash_when_broke(dry_session):
    s = dry_session
    s.cfg["max_notional_per_side_usdc"] = 5.0
    s.clob.balance_collateral_usdc = MagicMock(return_value=0.50)

    async def _run():
        await s._post_quote("UP", "BUY", 0.40, 5.0, best_bid=0.40, best_ask=0.45)

    asyncio.run(_run())
    assert s.clob.place_post_only_gtc.call_count == 0
    assert s._skip_cash_until > 0


def test_e2e_record_fill_preserves_held():
    monkey_cli = ClobLiveClient()
    s = LiveSession(cfg={}, out_dir=Path("."), clob=monkey_cli, bankroll=1.0)
    s.open_token_id = "DOWN_X"
    s.open_order_id = "ord1"
    s.open_side = "BUY"
    s.open_price = 0.4
    s.open_size = 5.0
    s._record_fill("BUY", 0.4, 5.0, "ord1", dry=True)
    assert s.held_token_id == "DOWN_X"
    assert s.inventory_shares == 5.0
    assert s.open_order_id is None  # cleared
    # held must remain
    assert s.held_token_id == "DOWN_X"


def test_session_kill_net_triggers(dry_session):
    s = dry_session
    s.realized_pnl = -0.45
    s.cfg["session_kill_net_usdc"] = 0.40
    assert s._session_loss_kill() is True
