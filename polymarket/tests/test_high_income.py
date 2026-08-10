"""High-income scale keeps press DNA and raises size only."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket.research.local_lab.definitive_income_system import check_dna_alignment
from polymarket.research.local_lab.high_income_project import project
from polymarket.research.local_lab.assure_wr80_income import take_income_wr80

POLY = Path(__file__).resolve().parents[1]
HI = POLY / "config" / "weather_ladder_high_income.json"
CASES = POLY / "data_local" / "local_lab" / "weather_optimize" / "cases.json"


def test_high_income_config_is_press_only_scaled():
    cfg = json.loads(HI.read_text(encoding="utf-8"))
    assert cfg["income_mode"] == "high"
    assert float(cfg["budget_per_market_usdc"]) >= 20
    assert float(cfg["max_basket_cost"]) <= 0.5
    assert cfg["require_underdispersion"] is True
    assert bool((cfg.get("live") or {}).get("high_income")) is True
    for s in cfg["sleeves"]:
        assert [t["name"] for t in s["tiers"]] == ["press_under"]


def test_dna_still_passes_with_high_income():
    assert check_dna_alignment()["passed"] is True


def test_high_scale_week_beats_micro():
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    rep = project(take_income_wr80(cases))
    by = {s["name"]: s for s in rep["scales"]}
    assert by["high"]["expected_pnl_week"] > by["micro"]["expected_pnl_week"] * 3
    assert by["high"]["conservative_pnl_week"] < by["high"]["expected_pnl_week"]
    assert by["high"]["conservative_pnl_week"] > 50  # still meaningful
    assert rep["verdict"] == "HIGH_INCOME_VIA_SIZE"
    assert rep.get("verified") is True


def test_session_cap_gate():
    import os
    from polymarket.research.local_lab.weather_ladder_real import _session_cap
    from polymarket.research.local_lab.weather_ladder_paper import load_cfg

    cfg = load_cfg(HI)
    os.environ.pop("POLY_LADDER_HIGH_INCOME", None)
    assert _session_cap(cfg) == 5.0
    os.environ["POLY_LADDER_HIGH_INCOME"] = "1"
    assert _session_cap(cfg) == 50.0
    os.environ.pop("POLY_LADDER_HIGH_INCOME", None)
