"""Unit tests for capital ladder WR-first sizing."""

from __future__ import annotations

from polymarket.research.local_lab.capital_ladder_wr import SCENARIOS, _build_cfg


def test_scenarios_defined() -> None:
    assert "base" in SCENARIOS
    assert "combo_wr" in SCENARIOS
    assert float(SCENARIOS["combo_wr"]["min_edge"]) >= 0.031


def test_ladder_keeps_micro_size_at_100eur() -> None:
    path = _build_cfg("grind_nim_selective", 100.0, "combo_wr", {})
    import json

    cfg = json.loads(path.read_text(encoding="utf-8"))
    assert cfg["quote_size_shares"] == 5
    assert cfg["max_quote_size_shares"] == 5
    assert float(cfg["lock_profit_usdc"]) <= 0.12
    assert float(cfg["max_loss_usdc"]) <= 0.12
    assert float(cfg["max_notional_per_side_usdc"]) <= 3.0
    assert float(cfg["min_edge"]) >= 0.032
