"""Post-only no debe cruzar el libro."""

from __future__ import annotations

from polymarket.research.local_lab.live_maker import LiveSession
from polymarket.src.execution.clob_live import ClobLiveClient


def _session(tmp_path):
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
    return LiveSession(
        cfg={"initial_capital_usdc": 5.0},
        out_dir=tmp_path,
        clob=cli,
        bankroll=5.0,
    )


def test_buy_clamped_below_ask(tmp_path):
    s = _session(tmp_path)
    px = s._clamp_post_only_px("BUY", 0.50, best_bid=0.48, best_ask=0.49)
    assert px is not None
    assert px <= 0.48 + 1e-9


def test_buy_rejects_when_ask_is_min_tick(tmp_path):
    s = _session(tmp_path)
    # ask en el tick mínimo → ask-tick queda inválido / cruza
    px = s._clamp_post_only_px("BUY", 0.01, best_bid=0.01, best_ask=0.01)
    assert px is None


def test_sell_stays_above_bid(tmp_path):
    s = _session(tmp_path)
    px = s._clamp_post_only_px("SELL", 0.40, best_bid=0.40, best_ask=0.42)
    assert px is not None
    assert px >= 0.41 - 1e-9
