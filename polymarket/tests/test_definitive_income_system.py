"""Definitive income system DNA + orchestration tests."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket.research.local_lab.definitive_income_system import (
    check_dna_alignment,
    compose_verdict,
)

POLY = Path(__file__).resolve().parents[1]
DEF = POLY / "config" / "weather_ladder_definitive_real.json"
FINAL = POLY / "config" / "weather_ladder_final_longterm.json"


def test_definitive_real_config_shape():
    cfg = json.loads(DEF.read_text(encoding="utf-8"))
    assert cfg["demo_label"] == "weather_ladder_definitive_real_v1"
    assert cfg["strategy"] == "temperature_ladder_definitive"
    assert cfg["require_underdispersion"] is True
    assert float(cfg["max_basket_cost"]) <= 0.5
    assert float(cfg["max_leg_price"]) <= 0.39
    assert int(cfg["max_markets_per_run"]) == 1
    assert float((cfg.get("live") or {})["max_capital_usdc"]) <= 5.0
    assert cfg.get("smoke_post_when_empty") is False
    assert cfg.get("open_only") is True
    for s in cfg["sleeves"]:
        assert [t["name"] for t in s["tiers"]] == ["press_under"]


def test_dna_alignment_passes():
    dna = check_dna_alignment()
    assert dna["passed"] is True, dna


def test_compose_verdict_go_path():
    dna = {"passed": True}
    research = {"passed": True}
    live = {
        "checks": {
            "signing_ready": True,
            "balance_readable": True,
            "env_safe": True,
            "geoblock_ok": True,
            "balance_gte_micro": True,
            "edge_open": True,
            "day_loss_ok": True,
        }
    }
    v = compose_verdict(dna, research, live)
    assert v["verdict"] == "REAL_INCOME_GO"
    assert v["go"] is True


def test_compose_verdict_operable_when_geoblocked():
    dna = {"passed": True}
    research = {"passed": True}
    live = {
        "checks": {
            "signing_ready": True,
            "balance_readable": True,
            "env_safe": True,
            "geoblock_ok": False,
            "balance_gte_micro": True,
            "edge_open": False,
            "day_loss_ok": True,
        }
    }
    v = compose_verdict(dna, research, live)
    assert v["verdict"] == "REAL_INCOME_OPERABLE"
    assert v["certified"] is True


def test_final_and_definitive_share_press_dna():
    final = json.loads(FINAL.read_text(encoding="utf-8"))
    real = json.loads(DEF.read_text(encoding="utf-8"))
    assert float(final["max_basket_cost"]) == float(real["max_basket_cost"])
    assert float(final["max_leg_price"]) == float(real["max_leg_price"])
    assert final["require_underdispersion"] == real["require_underdispersion"]
