"""Final long-term strategy freeze tests."""

from __future__ import annotations

import json
from pathlib import Path

CFG = Path(__file__).resolve().parents[1] / "config" / "weather_ladder_final_longterm.json"


def test_final_longterm_config_shape():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    assert cfg["demo_label"] == "weather_ladder_final_longterm_v1"
    assert cfg["require_underdispersion"] is True
    assert cfg["max_basket_cost"] <= 0.5
    assert cfg["max_leg_price"] <= 0.39
    assert cfg["max_per_city"] <= 3
    names = {s["name"] for s in cfg["sleeves"]}
    assert "core_press" in names
    assert "beijing_press" in names
    # no select tiers
    for s in cfg["sleeves"]:
        tiers = [t["name"] for t in s.get("tiers") or []]
        assert tiers == ["press_under"]
    lt = cfg.get("long_term") or {}
    cert = lt.get("certification") or {}
    verdict = cert.get("verdict") or lt.get("verdict")
    assert verdict == "LONG_TERM_ROBUST"
    assert (lt.get("overall") or {}).get("wr", 0) >= 0.9


def test_beijing_basket_not_looser_than_core():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    by = {s["name"]: s for s in cfg["sleeves"]}
    assert by["beijing_press"]["max_basket_cost"] <= by["core_press"]["max_basket_cost"]
