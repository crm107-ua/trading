"""urgent/scalp_cut debe cancelar SELL resting y no quedarse bloqueado."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from polymarket.research.local_lab.live_maker import LiveSession
from polymarket.src.execution.clob_live import ClobLiveClient


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("POLY_LIVE_ARMED", "1")
    monkeypatch.setenv("POLY_LIVE_DRY_RUN", "1")
    cli = ClobLiveClient()
    cli.gates = type(
        "G",
        (),
        {
            "armed": True,
            "dry_run": True,
            "signature_type": 3,
            "funder": "0x0",
            "max_capital_usdc": 5.0,
            "missing": [],
        },
    )()
    cli.cancel = MagicMock(return_value={"canceled": True})
    cli.balance_conditional_shares = MagicMock(return_value=5.0)
    cli.place_aggressive = MagicMock(
        return_value={"status": "DRY_RUN", "would_post": {"price": 0.30, "size": 5.0}}
    )
    s = LiveSession(
        cfg={"initial_capital_usdc": 5.0, "max_inventory_shares": 5},
        out_dir=tmp_path,
        clob=cli,
        bankroll=5.0,
    )
    s.inventory_shares = 5.0
    s.cost_basis = 5.0 * 0.40
    s.held_token_id = "UP"
    s.open_order_id = "resting-sell"
    s.open_side = "SELL"
    s.open_price = 0.42
    s.open_size = 5.0
    s.open_token_id = "UP"
    return s


def test_urgent_cancels_resting_sell(session, capsys):
    s = session
    asyncio.run(
        s._force_flatten("UP", best_bid=0.30, best_ask=0.31, reason="urgent")
    )
    assert s.clob.cancel.call_count == 1
    out = capsys.readouterr().out
    assert "flatten_bypass:urgent" in out or "CANCEL" in out
