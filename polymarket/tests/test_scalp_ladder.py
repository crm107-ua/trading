"""Tests metodología SCALP LADDER (1/2/3/4€ + cut inmediato)."""

from __future__ import annotations

from polymarket.research.local_lab.scalp_ladder import decide_scalp_exit


def test_early_bank_small_green():
    d = decide_scalp_exit(unreal=0.08, hold_s=5.0, early_bank_usdc=0.08)
    assert d.action == "bank"
    assert d.reason == "scalp_early_bank"


def test_ladder_rung_1_euro():
    d = decide_scalp_exit(unreal=1.05, hold_s=2.0)
    assert d.action == "bank"
    assert d.reason == "scalp_ladder"
    assert d.rung == 1.0


def test_ladder_takes_first_rung_reached():
    """Con unreal=3.2 ya superó 1€ → bank en el primer escalón (sin hold a 3)."""
    d = decide_scalp_exit(unreal=3.2, hold_s=1.0)
    assert d.action == "bank"
    assert d.reason == "scalp_ladder"
    assert d.rung == 1.0


def test_cap_at_4_never_hold():
    d = decide_scalp_exit(unreal=4.5, hold_s=0.1, max_bank_usdc=4.0)
    assert d.action == "cap"
    assert d.reason == "scalp_cap"


def test_cut_immediate_after_min_hold():
    d = decide_scalp_exit(
        unreal=-0.09, hold_s=3.1, scalp_cut_usdc=0.08, min_hold_cut_s=3.0
    )
    assert d.action == "cut"
    assert d.reason == "scalp_cut"


def test_cut_gated_before_min_hold():
    d = decide_scalp_exit(
        unreal=-0.20, hold_s=1.0, scalp_cut_usdc=0.08, min_hold_cut_s=3.0
    )
    assert d.action == "hold"
    assert d.reason == "scalp_cut_hold_gate"


def test_hold_in_noise_zone():
    d = decide_scalp_exit(unreal=-0.02, hold_s=10.0, scalp_cut_usdc=0.08)
    assert d.action == "hold"
