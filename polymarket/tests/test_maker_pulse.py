"""Unit tests for PulseGate (maker_pulse) gates."""

from __future__ import annotations

from polymarket.research.local_lab.strategies import maker_pulse, pulse_spot_fair
from polymarket.src.data.book_utils import top_size_imbalance


def _cfg(**over):
    base = {
        "min_edge": 0.028,
        "min_z": 0.9,
        "sigma_mid": 0.03,
        "max_abs_edge": 0.09,
        "min_quote_mid": 0.38,
        "max_quote_mid": 0.62,
        "quote_time_min_s": 110,
        "quote_time_max_s": 260,
        "min_spot_lead_usd": 12,
        "min_spot_velocity_usd": 4,
        "pulse_persist_polls": 2,
        "min_bid_imbalance": 0.52,
        "min_market_spread": 0.01,
        "half_spread": 0.012,
        "safety_buffer": 0.002,
        "quote_size_shares": 5,
        "quote_join_touch": True,
        "max_quote_size_shares": 5,
        "min_expected_pnl_usdc": 0.0,
        "_strike_trusted": True,
        "_time_remaining_s": 180,
        "_spot_velocity_usd": 8.0,
        "_book_imbalance": 0.60,
        "_pulse_streak": 2,
    }
    base.update(over)
    return base


def test_pulse_quotes_when_all_gates_pass():
    # lead ~$15 → spot-fair ~0.63; mid 0.50 → edge ~0.13 capped by max_abs
    q = maker_pulse(
        0.55,
        0.49,
        0.51,
        100_015.0,
        100_000.0,
        _cfg(max_abs_edge=0.20, min_edge=0.022, pulse_fair_scale_usd=28),
    )
    assert q is not None
    assert q.strategy_id == "maker_pulse"
    assert q.bid > 0.02
    assert q.ask == 0.99


def test_pulse_symmetric_ask_on_down_momentum():
    # spot below strike + vel down; spot-fair < mid → ask
    q = maker_pulse(
        0.45,
        0.49,
        0.51,
        99_985.0,
        100_000.0,
        _cfg(
            pulse_symmetric=True,
            max_abs_edge=0.20,
            min_edge=0.022,
            _spot_velocity_usd=-8.0,
            _book_imbalance=0.35,
        ),
    )
    assert q is not None
    assert q.ask < 0.98
    assert q.bid == 0.01


def test_pulse_rejects_untrusted_strike():
    assert (
        maker_pulse(0.58, 0.49, 0.51, 100_050.0, 100_000.0, _cfg(_strike_trusted=False))
        is None
    )


def test_pulse_rejects_settlement_window():
    assert (
        maker_pulse(0.58, 0.49, 0.51, 100_050.0, 100_000.0, _cfg(_time_remaining_s=60))
        is None
    )


def test_pulse_rejects_no_momentum():
    assert (
        maker_pulse(
            0.58, 0.49, 0.51, 100_005.0, 100_000.0, _cfg(_spot_velocity_usd=1.0)
        )
        is None
    )


def test_pulse_rejects_toxic_book():
    assert (
        maker_pulse(0.58, 0.49, 0.51, 100_050.0, 100_000.0, _cfg(_book_imbalance=0.35))
        is None
    )


def test_pulse_requires_persistence():
    assert (
        maker_pulse(0.58, 0.49, 0.51, 100_050.0, 100_000.0, _cfg(_pulse_streak=1))
        is None
    )


def test_top_size_imbalance_bid_heavy():
    bids = [{"price": "0.50", "size": "20"}, {"price": "0.49", "size": "10"}]
    asks = [{"price": "0.51", "size": "5"}, {"price": "0.52", "size": "5"}]
    imb = top_size_imbalance(bids, asks, n=2)
    assert imb is not None and imb > 0.5


def test_pulse_spot_fair_reacts_to_lead():
    assert pulse_spot_fair(100_028.0, 100_000.0, 28.0) > 0.55
    assert pulse_spot_fair(99_972.0, 100_000.0, 28.0) < 0.45
    assert abs(pulse_spot_fair(100_000.0, 100_000.0, 28.0) - 0.5) < 1e-6
