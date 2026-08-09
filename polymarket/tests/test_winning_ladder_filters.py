"""Champion ladder filters: SG/SH + underdispersion research freeze."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket.src.weather.ladder import BucketQuote, build_ladder_plan
from polymarket.src.weather.stations import get_station

CFG = Path(__file__).resolve().parents[1] / "config" / "weather_ladder_champion.json"


def test_champion_config_frozen():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    assert cfg["demo_label"] == "weather_ladder_champion"
    assert cfg["cities"] == ["singapore", "shanghai"]
    assert cfg["require_underdispersion"] is True
    assert cfg["max_basket_cost"] <= 0.5
    assert cfg["max_leg_price"] <= 0.39
    assert cfg["optimize_metrics"]["winrate"] >= 0.99
    assert cfg["optimize_metrics"]["total_pnl"] > 100


def test_stations_bias_for_champion_cities():
    sg = get_station("singapore")
    sh = get_station("shanghai")
    assert sg is not None and sh is not None
    assert sg.bias_c == 0.5
    assert sh.bias_c == 0.5


def test_underdispersion_required_skips_wide_ensemble():
    buckets = [
        BucketQuote("31°C", 0.25, 0.08, 31),
        BucketQuote("32°C", 0.40, 0.25, 32),
        BucketQuote("33°C", 0.20, 0.12, 33),
    ]
    plan = build_ladder_plan(
        buckets,
        center_temp=32,
        model_temps=[28.0, 32.0, 35.0],
        typical_spread=1.8,
        budget=12.0,
        max_basket_cost=0.5,
        max_leg_price=0.39,
        press_on_underdispersion=True,
    )
    assert plan.take is False
