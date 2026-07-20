"""Top-up no debe comprar +5 enteros si solo falta polvo (bug 181122)."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from polymarket.research.local_lab.live_maker import LiveSession, MIN_ORDER_SHARES
from polymarket.src.execution.clob_live import ClobLiveClient


@pytest.fixture
def session(tmp_path, monkeypatch):
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
    cli.place_aggressive = MagicMock(
        side_effect=AssertionError("no debe top-up con need<5")
    )
    s = LiveSession(
        cfg={"initial_capital_usdc": 5.0, "demo_label": "promo_pulse_micro5_scalp"},
        out_dir=tmp_path,
        clob=cli,
        bankroll=5.0,
    )
    return s


def test_topup_skips_when_only_dust_gap(session):
    s = session
    s.inventory_shares = 4.99
    s.held_token_id = "UP"
    ok = asyncio.run(s._topup_dust_to_min("UP", best_ask=0.40))
    assert ok is False
    assert s.clob.place_aggressive.call_count == 0
    assert abs(s.inventory_shares - 4.99) < 1e-6


def test_flatten_scalp_cut_waits_instead_of_topup(session, capsys):
    s = session
    s.inventory_shares = 4.99
    s.cost_basis = 4.99 * 0.36
    s.held_token_id = "UP"
    s.clob.balance_conditional_shares = MagicMock(return_value=4.99)
    asyncio.run(
        s._force_flatten("UP", best_bid=0.34, best_ask=0.35, reason="scalp_cut")
    )
    out = capsys.readouterr().out
    assert "FLATTEN_WAIT_SIZE" in out
    assert s.clob.place_aggressive.call_count == 0
    assert abs(s.inventory_shares - 4.99) < 1e-6


def test_flatten_inv_sync_when_clob_has_full_lot(session, capsys):
    s = session
    s.inventory_shares = 4.99375
    s.cost_basis = 4.99375 * 0.36
    s.held_token_id = "UP"
    s.clob.balance_conditional_shares = MagicMock(return_value=5.0)
    s.clob.place_aggressive = MagicMock(
        return_value={"status": "DRY_RUN", "would_post": {"price": 0.34, "size": 5.0}}
    )
    # dry_run path needs gates.dry_run True for synthetic clear OR place_aggressive
    s.clob.gates = type(
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
    asyncio.run(
        s._force_flatten("UP", best_bid=0.34, best_ask=0.35, reason="scalp_early_bank")
    )
    out = capsys.readouterr().out
    assert "INV_SYNC" in out
    assert s.clob.place_aggressive.call_count == 0 or abs(s.inventory_shares) < 1e-6


def test_buy_fill_halts_on_inv_cap(session, capsys):
    s = session
    s.cfg["max_inventory_shares"] = 5
    s.inventory_shares = 4.99
    s.cost_basis = 4.99 * 0.36
    s.open_token_id = "UP"
    s._record_fill("BUY", 0.34, 5.0, "oid-extra", dry=False)
    out = capsys.readouterr().out
    assert "INV_CAP_BREACH" in out
    assert s._halt_new_entries is True
    assert s.inventory_shares > 5.2
