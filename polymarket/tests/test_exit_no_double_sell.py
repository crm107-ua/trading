"""Tras POST_EXIT LIVE sin fill, no publicar un segundo SELL."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from polymarket.research.local_lab.live_maker import LiveSession
from polymarket.src.execution.clob_live import ClobLiveClient


def test_exit_resting_skips_second_sell(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("POLY_LIVE_ARMED", "1")
    monkeypatch.setenv("POLY_LIVE_DRY_RUN", "0")
    cli = ClobLiveClient()
    cli.gates = type(
        "G",
        (),
        {
            "armed": True,
            "dry_run": False,
            "signature_type": 3,
            "funder": "0x0",
            "max_capital_usdc": 5.0,
            "missing": [],
        },
    )()
    cli.balance_conditional_shares = MagicMock(return_value=5.0)
    cli.place_aggressive = MagicMock(
        return_value={
            "status": "LIVE",
            "orderID": "exit-live-1",
            "would_post": {"price": 0.35, "size": 5.0},
        }
    )
    cli.get_order = MagicMock(return_value={"status": "LIVE", "size_matched": "0"})
    cli.place_limit = MagicMock(side_effect=AssertionError("no second sell"))

    s = LiveSession(
        cfg={"initial_capital_usdc": 5.0},
        out_dir=tmp_path,
        clob=cli,
        bankroll=5.0,
    )
    s.inventory_shares = 5.0
    s.cost_basis = 2.4
    s.held_token_id = "UP"

    asyncio.run(
        s._force_flatten("UP", best_bid=0.35, best_ask=0.36, reason="scalp_cut")
    )
    out = capsys.readouterr().out
    assert "EXIT_RESTING" in out
    assert s.open_order_id == "exit-live-1"
    assert s.open_side == "SELL"
    assert cli.place_aggressive.call_count == 1
