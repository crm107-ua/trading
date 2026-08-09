"""Multi-model daily-max forecasts via Open-Meteo (station-centered)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from polymarket.src.weather.ladder import gaussian_bucket_probs, truncate_temp
from polymarket.src.weather.stations import Station

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
DEFAULT_MODELS = ("icon_seamless", "gfs_seamless", "ecmwf_ifs025")


@dataclass(frozen=True)
class DayForecast:
    day: date
    models: dict[str, float]  # raw model max °C
    corrected_center: float
    truncated_center: int
    sigma: float
    bucket_probs: dict[int, float]


def fetch_model_maxes(
    station: Station,
    *,
    days: int = 3,
    models: tuple[str, ...] = DEFAULT_MODELS,
    timeout_s: float = 20.0,
) -> dict[str, dict[str, float]]:
    """
    Returns {ISO date: {model_name: temp_max}}.
    Uses separate calls per model for reliability.
    """
    out: dict[str, dict[str, float]] = {}
    with httpx.Client(timeout=timeout_s) as client:
        for model in models:
            params = {
                "latitude": station.lat,
                "longitude": station.lon,
                "daily": "temperature_2m_max",
                "timezone": station.timezone,
                "forecast_days": max(1, min(7, int(days))),
                "models": model,
            }
            r = client.get(OPEN_METEO, params=params)
            r.raise_for_status()
            daily = r.json().get("daily") or {}
            times = daily.get("time") or []
            vals = daily.get("temperature_2m_max") or []
            for t, v in zip(times, vals, strict=False):
                if v is None:
                    continue
                out.setdefault(str(t), {})[model] = float(v)
    return out


def build_day_forecast(
    station: Station,
    day: date,
    model_maxes: dict[str, float],
    *,
    bucket_temps: list[int],
) -> DayForecast | None:
    if not model_maxes:
        return None
    vals = list(model_maxes.values())
    mean = sum(vals) / len(vals)
    corrected = mean + float(station.bias_c)
    # sigma from model disagreement + floor (miss of 1–3° is normal)
    if len(vals) >= 2:
        spread = max(vals) - min(vals)
        sigma = max(0.8, spread / 2.0)
    else:
        sigma = 1.2
    truncated = truncate_temp(corrected)
    probs = gaussian_bucket_probs(corrected, sigma, bucket_temps)
    return DayForecast(
        day=day,
        models=dict(model_maxes),
        corrected_center=round(corrected, 3),
        truncated_center=truncated,
        sigma=round(sigma, 3),
        bucket_probs=probs,
    )


def forecast_for_station(
    station: Station,
    *,
    target: date | None = None,
    bucket_temps: list[int] | None = None,
    days: int = 3,
) -> DayForecast | None:
    raw = fetch_model_maxes(station, days=days)
    if not raw:
        return None
    if target is None:
        # Prefer D+1 (second day if available), else first
        keys = sorted(raw.keys())
        key = keys[1] if len(keys) > 1 else keys[0]
    else:
        key = target.isoformat()
        if key not in raw:
            return None
    temps = bucket_temps or list(range(20, 42))
    return build_day_forecast(station, date.fromisoformat(key), raw[key], bucket_temps=temps)


def parse_forecast_payload(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    """Test helper: accept pre-baked {date: {model: temp}}."""
    return {str(k): {str(m): float(v) for m, v in d.items()} for k, d in payload.items()}
