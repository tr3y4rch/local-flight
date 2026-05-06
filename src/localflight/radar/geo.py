from __future__ import annotations

import math
from typing import Any

NM_PER_DEG_LAT = 60.0
FT_PER_M = 3.28084
KT_PER_MS = 1.943844
FPM_PER_MS = 196.850394


def float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def distance_nm(center_lat: float, center_lon: float, lat: float, lon: float) -> float:
    dlat = (lat - center_lat) * NM_PER_DEG_LAT
    dlon = (lon - center_lon) * NM_PER_DEG_LAT * math.cos(math.radians(center_lat))
    return math.sqrt((dlat * dlat) + (dlon * dlon))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    y_nm = (lat2 - lat1) * NM_PER_DEG_LAT
    x_nm = (lon2 - lon1) * NM_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2.0))
    if abs(x_nm) < 0.0000001 and abs(y_nm) < 0.0000001:
        return 0.0
    return (math.degrees(math.atan2(x_nm, y_nm)) + 360.0) % 360.0


def heading_delta_deg(a: Any, b: Any) -> float | None:
    left = float_or_none(a)
    right = float_or_none(b)
    if left is None or right is None:
        return None
    return abs(((left - right + 180.0) % 360.0) - 180.0)


def offset_point(lat: float, lon: float, *, north_nm: float = 0.0, east_nm: float = 0.0) -> list[float]:
    cos_lat = max(0.15, abs(math.cos(math.radians(lat))))
    return [
        round(lat + (north_nm / NM_PER_DEG_LAT), 7),
        round(lon + (east_nm / (NM_PER_DEG_LAT * cos_lat)), 7),
    ]


def point_on_heading(lat: float, lon: float, heading: float, distance_nm_value: float) -> list[float]:
    radians = math.radians(heading)
    return offset_point(
        lat,
        lon,
        north_nm=math.cos(radians) * distance_nm_value,
        east_nm=math.sin(radians) * distance_nm_value,
    )


def feet_from_m(value: Any) -> float | None:
    meters = float_or_none(value)
    return None if meters is None else meters * FT_PER_M


def knots_from_ms(value: Any) -> float | None:
    meters_s = float_or_none(value)
    return None if meters_s is None else meters_s * KT_PER_MS


def fpm_from_ms(value: Any) -> float | None:
    meters_s = float_or_none(value)
    return None if meters_s is None else meters_s * FPM_PER_MS
