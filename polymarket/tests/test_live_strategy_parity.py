"""Paridad live: pulse configs deben usar maker_fusion, no maker_edge."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polymarket.research.local_lab.live_maker import LiveSession
from polymarket.src.execution.clob_live import ClobLiveClient


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fusion_session(tmp_path, monkeypatch):
    monkeypatch.setenv("POLY_LIVE_ARMED", "1")
    monkeypatch.setenv("POLY_LIVE_DRY_RUN", "1")
    cli = ClobLiveClient()
    cli.balance_collateral_usdc = MagicMock(return_value=6.0)
    cli.balance_conditional_shares = MagicMock(return_value=0.0)
    cli.place_post_only_gtc = MagicMock(
        return_value={"status": "DRY_RUN", "would_post": {"price": 0.40, "size": 5.0}}
    )
    cli.cancel = MagicMock(return_value={"status": "DRY_RUN"})
    cli.open_orders = MagicMock(return_value=[])
    cfg = {
        "initial_capital_usdc": 1.5,
        "demo_label": "promo_pulse_c10_micro",
        "strategy_id": "maker_fusion",
        "preserve_selectivity": True,
        "fusion_enable_pulse": True,
        "fusion_enable_follow": True,
        "fusion_enable_edge": False,
        "quote_size_shares": 5,
        "max_quote_size_shares": 5,
        "max_inventory_shares": 5,
        "min_edge": 0.016,
        "min_spot_lead_usd": 2.0,
        "min_spot_velocity_usd": 0.6,
        "min_quote_mid": 0.34,
        "max_quote_mid": 0.66,
        "pulse_symmetric": True,
        "pulse_persist_polls": 1,
        "lock_profit_usdc": 0.04,
        "grind_bank_usdc": 0.03,
        "hard_bank_usdc": 0.08,
        "max_loss_usdc": 0.03,
        "session_kill_net_usdc": 0.12,
    }
    return LiveSession(
        cfg=cfg,
        out_dir=tmp_path,
        clob=cli,
        bankroll=1.5,
        strategy_id="maker_fusion",
    )


def test_default_strategy_is_fusion_not_edge(fusion_session):
    assert fusion_session.strategy_id == "maker_fusion"
    assert fusion_session.strategy_id != "maker_edge"


def test_inject_pulse_runtime_sets_streak(fusion_session):
    s = fusion_session
    s.strike_trusted = True
    s.window_start_ns = 0
    # Fabricar historial spot con lead fuerte
    import time

    now = time.time_ns()
    s.spot_history = [(now - int(4e9), 100000.0), (now, 100010.0)]
    s.mid_history = [(now - int(4e9), 0.50), (now, 0.50)]
    s._inject_pulse_runtime(
        fair=0.55,
        spot=100010.0,
        bids=[{"price": "0.49", "size": "10"}],
        asks=[{"price": "0.51", "size": "10"}],
        bb=0.49,
        ba=0.51,
        time_remaining_s=180.0,
    )
    assert "_roll_lead_usd" in s.cfg
    assert "_pulse_streak" in s.cfg


def test_dry_flatten_clears_sim_inventory(fusion_session):
    s = fusion_session
    s.inventory_shares = 5.0
    s.cost_basis = 2.0
    s.held_token_id = "UP_TOKEN"
    s.position_leg = "up"

    async def _run():
        await s._force_flatten(
            "UP_TOKEN", best_bid=0.45, best_ask=0.50, reason="test"
        )

    asyncio.run(_run())
    assert abs(s.inventory_shares) < 1e-9


def test_micro_config_exists_and_capital():
    p = ROOT / "config" / "maker_demo_promo_pulse_c10_micro_live.json"
    assert p.is_file()
    import json

    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert float(cfg["initial_capital_usdc"]) <= 1.5
    assert cfg.get("strategy_id") == "maker_fusion"
