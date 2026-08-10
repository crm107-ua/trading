"""Champion ladder filters: multi-sleeve v3 freeze + underdispersion gate."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket.src.weather.ladder import BucketQuote, build_ladder_plan
from polymarket.src.weather.stations import get_station

CFG = Path(__file__).resolve().parents[1] / "config" / "weather_ladder_champion.json"
CFG_V2 = Path(__file__).resolve().parents[1] / "config" / "weather_ladder_champion_v2.json"


def test_champion_config_frozen():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    assert cfg["demo_label"] == "weather_ladder_champion"
    assert set(cfg["cities"]) >= {"singapore", "shanghai", "hong-kong", "beijing"}
    assert cfg["max_basket_cost"] <= 0.5
    assert cfg["max_leg_price"] <= 0.39
    assert cfg.get("max_per_city", 3) <= 3
    metrics = cfg.get("research") or cfg.get("optimize_metrics") or {}
    # Pointer may carry optimize_metrics or research depending on sync
    wr = metrics.get("winrate") or (metrics.get("union") or {}).get("winrate")
    pnl = metrics.get("total_pnl") or (metrics.get("union") or {}).get("total_pnl")
    if wr is not None:
        assert float(wr) >= 0.75
    if pnl is not None:
        assert float(pnl) > 100


def test_champion_v2_sleeves():
    cfg = json.loads(CFG_V2.read_text(encoding="utf-8"))
    assert cfg["demo_label"] == "weather_ladder_champion_v3"
    names = {s["name"] for s in cfg["sleeves"]}
    assert names == {"core", "beijing"}
    assert cfg["research"]["union"]["winrate"] == 1.0
    assert cfg["research"]["union"]["total_pnl"] > 500


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


def test_floor_trap_skips_center_below_buckets():
    buckets = [
        BucketQuote("28°C", 0.30, 0.12, 28),
        BucketQuote("29°C", 0.35, 0.20, 29),
        BucketQuote("30°C", 0.25, 0.15, 30),
    ]
    plan = build_ladder_plan(
        buckets,
        center_temp=27,
        model_temps=[27.0, 27.2, 27.4],
        typical_spread=2.6,
        budget=12.0,
        max_basket_cost=0.55,
        max_leg_price=0.39,
        press_on_underdispersion=False,
    )
    assert plan.take is False
    assert "center_below_ladder_floor" in plan.reason
