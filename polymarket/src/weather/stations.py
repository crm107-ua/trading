"""Resolution stations for Polymarket daily high-temperature markets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    city: str
    icao: str
    lat: float
    lon: float
    timezone: str
    unit: str = "C"
    # Typical multi-model max-spread (°C) used by underdispersion filter
    typical_model_spread_c: float = 1.8
    # Additive bias correction applied to raw model max before truncation
    bias_c: float = 0.0
    volatile: bool = True


# Center coords near resolution airports (not city centroids).
STATIONS: dict[str, Station] = {
    "singapore": Station("singapore", "WSSS", 1.3644, 103.9915, "Asia/Singapore", typical_model_spread_c=1.4, volatile=True),
    "shanghai": Station("shanghai", "ZSPD", 31.1443, 121.8083, "Asia/Shanghai", typical_model_spread_c=2.2, volatile=True),
    "tokyo": Station("tokyo", "RJTT", 35.5494, 139.7798, "Asia/Tokyo", typical_model_spread_c=2.0, volatile=True),
    "seoul": Station("seoul", "RKSI", 37.4602, 126.4407, "Asia/Seoul", typical_model_spread_c=2.4, volatile=True),
    "hong-kong": Station("hong-kong", "VHHH", 22.3080, 113.9185, "Asia/Hong_Kong", typical_model_spread_c=1.6, volatile=True),
    "miami": Station("miami", "KMIA", 25.7959, -80.2870, "America/New_York", unit="F", typical_model_spread_c=3.0, volatile=True),
    "wellington": Station("wellington", "NZWN", -41.3276, 174.8050, "Pacific/Auckland", typical_model_spread_c=2.5, volatile=True),
    "beijing": Station("beijing", "ZBAA", 40.0799, 116.6031, "Asia/Shanghai", typical_model_spread_c=2.6, volatile=True),
    "taipei": Station("taipei", "RCSS", 25.0697, 121.5525, "Asia/Taipei", typical_model_spread_c=1.8, volatile=True),
    "paris": Station("paris", "LFPB", 48.9694, 2.4414, "Europe/Paris", typical_model_spread_c=2.2, volatile=False),
    "london": Station("london", "EGLC", 51.5053, 0.0553, "Europe/London", typical_model_spread_c=2.0, volatile=False),
}


def get_station(city: str) -> Station | None:
    key = city.strip().lower().replace(" ", "-").replace("_", "-")
    return STATIONS.get(key)
