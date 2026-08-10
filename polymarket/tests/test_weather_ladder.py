from __future__ import annotations

from datetime import date

from polymarket.src.weather.forecast import build_day_forecast
from polymarket.src.weather.ladder import (
    BucketQuote,
    calc_ev,
    gaussian_bucket_probs,
    ladder_ev,
    select_adjacent_cluster,
    size_ladder,
    truncate_temp,
    underdispersion_signal,
    build_ladder_plan,
)
from polymarket.src.weather.markets import parse_bucket_label, parse_event_slug
from polymarket.src.weather.stations import get_station


def test_calc_ev_and_ladder_ev_singapore_shape():
    # Article-ish cluster: 29@2c, 30@6c, 31@39c with optimistic probs
    buckets = [
        ("29C", 0.15, 0.02),
        ("30C", 0.25, 0.06),
        ("31C", 0.45, 0.39),
    ]
    assert calc_ev(0.45, 0.39) > 0
    total, per = ladder_ev(buckets)
    assert "31C" in per
    assert sum(p for _, p, _ in buckets) > 0.8
    assert total != 0.0


def test_size_ladder_weights_center():
    buckets = [("29C", 0.2, 0.05), ("30C", 0.5, 0.20), ("31C", 0.3, 0.15)]
    plan = size_ladder(buckets, budget=50.0)
    by_name = {n: d for n, d, _ in plan}
    assert by_name["30C"] > by_name["29C"]
    assert abs(sum(d for _, d, _ in plan) - 50.0) < 0.05


def test_underdispersion_tight_vs_wide():
    tight = underdispersion_signal([30.1, 30.3, 30.2], typical_spread=1.8)
    wide = underdispersion_signal([28.0, 32.5, 30.0], typical_spread=1.8)
    assert tight["underdispersed"] is True
    assert wide["underdispersed"] is False


def test_truncate_not_round():
    assert truncate_temp(31.9) == 31
    assert truncate_temp(32.0) == 32


def test_select_adjacent_cluster_three():
    buckets = [
        BucketQuote("29°C", 0.1, 0.05, 29),
        BucketQuote("30°C", 0.3, 0.12, 30),
        BucketQuote("31°C", 0.4, 0.35, 31),
        BucketQuote("32°C", 0.15, 0.20, 32),
    ]
    cluster = select_adjacent_cluster(buckets, center_temp=31, width=3)
    temps = [b.temp_c for b in cluster]
    assert temps == [30, 31, 32]


def test_build_ladder_plan_take_on_cheap_cluster():
    buckets = [
        BucketQuote("31°C", 0.25, 0.08, 31),
        BucketQuote("32°C", 0.40, 0.25, 32),
        BucketQuote("33°C", 0.20, 0.12, 33),
    ]
    plan = build_ladder_plan(
        buckets,
        center_temp=32,
        model_temps=[31.8, 32.0, 32.1],
        typical_spread=1.8,
        budget=10.0,
        max_basket_cost=0.55,
        min_cluster_prob=0.50,
        min_basket_ev=0.01,
        width=3,
    )
    assert plan.take is True
    assert plan.underdispersed is True
    assert plan.basket_cost < 0.55
    assert len(plan.legs) == 3


def test_build_ladder_plan_skips_wide_ensemble():
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
        budget=10.0,
        width=3,
        press_on_underdispersion=True,
    )
    assert plan.take is False
    assert "not_underdispersed" in plan.reason


def test_parse_bucket_and_slug():
    assert parse_bucket_label("32°C") == ("32°C", 32)
    assert parse_bucket_label("35°C or higher")[1] is None
    parsed = parse_event_slug("highest-temperature-in-singapore-on-august-10-2026")
    assert parsed == ("singapore", date(2026, 8, 10))


def test_gaussian_probs_sum_and_peak():
    probs = gaussian_bucket_probs(31.6, 1.0, range(28, 36))
    assert abs(sum(probs.values()) - 1.0) < 1e-6
    peak = max(probs, key=probs.get)
    assert peak in {31, 32}


def test_build_day_forecast_uses_bias_and_models():
    st = get_station("singapore")
    assert st is not None
    fc = build_day_forecast(
        st,
        date(2026, 8, 10),
        {"icon_seamless": 31.9, "gfs_seamless": 31.6, "ecmwf_ifs025": 30.9},
        bucket_temps=list(range(28, 36)),
    )
    assert fc is not None
    assert fc.truncated_center in {30, 31, 32}
    assert abs(sum(fc.bucket_probs.values()) - 1.0) < 1e-6


def test_skip_center_below_ladder_floor():
    """Beijing-style open-low trap: center 27 with buckets starting at 28."""
    buckets = [
        BucketQuote("28°C", 0.40, 0.28, 28),
        BucketQuote("29°C", 0.30, 0.07, 29),
        BucketQuote("30°C", 0.20, 0.08, 30),
    ]
    plan = build_ladder_plan(
        buckets,
        center_temp=27,
        model_temps=[27.3, 27.7, 25.9],
        typical_spread=2.6,
        budget=12.0,
        max_basket_cost=0.55,
        min_cluster_prob=0.30,
        min_basket_ev=0.01,
        width=3,
        press_on_underdispersion=False,
        max_leg_price=0.39,
    )
    assert plan.take is False
    assert "center_below_ladder_floor" in plan.reason
