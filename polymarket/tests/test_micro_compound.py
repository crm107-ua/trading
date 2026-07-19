"""Tests micro-compound 1–2€."""

from __future__ import annotations

from polymarket.research.local_lab.micro_compound import (
    MicroState,
    apply_round_result,
    can_afford_entry,
    max_affordable_price,
    recommend_path,
    session_capital,
)


def test_max_price_for_2eur():
    assert abs(max_affordable_price(2.0) - (2.0 / 5.0 - 0.001)) < 1e-9


def test_can_afford():
    assert can_afford_entry(2.0, 0.39, 5)
    assert not can_afford_entry(2.0, 0.45, 5)


def test_compound_win_increases_bank():
    s = MicroState(bankroll=2.0, peak=2.0)
    apply_round_result(s, net=0.08, fills=2)
    assert s.bankroll > 2.0
    assert s.wins == 1
    assert s.consec_losses == 0


def test_loss_triggers_cooldown_and_halt():
    s = MicroState(bankroll=2.0, peak=2.0)
    apply_round_result(s, net=-0.05, fills=2)
    assert s.cooldown_left >= 1
    apply_round_result(s, net=0.0, fills=0)  # cooldown tick
    apply_round_result(s, net=-0.05, fills=2)
    assert not s.halted  # 2 losses: aún no kill (MAX_CONSEC=3)
    apply_round_result(s, net=0.0, fills=0)  # cooldown
    apply_round_result(s, net=-0.05, fills=2)
    assert s.halted
    assert s.halt_reason == "max_consec_losses"


def test_session_capital_zero_on_cooldown():
    s = MicroState(bankroll=2.0, peak=2.0, cooldown_left=1)
    assert session_capital(s) == 0.0


def test_recommend_micro2():
    rec = recommend_path(
        {
            "paths": [
                {
                    "id": "micro2_single",
                    "safer": True,
                    "wr": 0.85,
                    "pnl": 0.3,
                    "collision_risk": 0.0,
                },
                {
                    "id": "scale_parallel",
                    "safer": False,
                    "wr": 0.7,
                    "pnl": 1.0,
                    "collision_risk": 0.85,
                },
            ]
        }
    )
    assert rec["recommended"] == "micro2_single"
