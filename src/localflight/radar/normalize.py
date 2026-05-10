from __future__ import annotations

from typing import Any

from .geo import (
    feet_from_m,
    float_or_none,
    fpm_from_ms,
    knots_from_ms,
    distance_nm,
)

_PRIVATE_VATSIM_KEYS = {
    "cid",
    "name",
    "pilot_name",
    "controller_name",
    "server",
    "server_name",
    "real_name",
}


def _ft_to_m(value: Any) -> float | None:
    feet = float_or_none(value)
    return None if feet is None else feet * 0.3048


def _kt_to_ms(value: Any) -> float | None:
    knots = float_or_none(value)
    return None if knots is None else knots * 0.514444


def _fpm_to_ms(value: Any) -> float | None:
    fpm = float_or_none(value)
    return None if fpm is None else fpm * 0.00508


def _truthy_source_quality(item: dict[str, Any]) -> str:
    if item.get("mlat"):
        return "mlat"
    if item.get("tisb"):
        return "tisb"
    if item.get("nac_p") is not None or item.get("rc") is not None:
        return "adsb-quality"
    return "adsb"


def enrich_blip_display_fields(blip: dict[str, Any]) -> dict[str, Any]:
    """Add stable display fields while preserving existing meter/m/s keys."""
    item = dict(blip)
    if str(item.get("source") or "").lower().startswith("vatsim"):
        for key in _PRIVATE_VATSIM_KEYS:
            item.pop(key, None)
    altitude_ft = item.get("altitude_ft")
    if altitude_ft is None:
        altitude_ft = feet_from_m(item.get("altitude_m"))
    speed_kt = item.get("speed_kt")
    if speed_kt is None:
        speed_kt = knots_from_ms(item.get("speed_ms"))
    vertical_rate_fpm = item.get("vertical_rate_fpm")
    if vertical_rate_fpm is None:
        vertical_rate_fpm = fpm_from_ms(item.get("vertical_rate"))
    heading = item.get("heading")
    if item.get("track_deg") is None and heading is not None:
        item["track_deg"] = heading
    heading_deg = item.get("heading_deg") or item.get("track_deg") or heading
    if altitude_ft is not None:
        item["altitude_ft"] = round(float(altitude_ft))
    if speed_kt is not None:
        item["speed_kt"] = round(float(speed_kt))
    if vertical_rate_fpm is not None:
        item["vertical_rate_fpm"] = round(float(vertical_rate_fpm))
    if heading_deg is not None:
        try:
            item["heading_deg"] = round(float(heading_deg)) % 360
        except (TypeError, ValueError):
            pass
    item.setdefault("source_quality", "unknown")
    item["detail_mode"] = "virtual" if str(item.get("source") or "").lower().startswith("vatsim") else "real"

    dep = str(item.get("departure_iata") or item.get("departure_icao") or "").strip().upper()
    arr = str(item.get("arrival_iata") or item.get("arrival_icao") or "").strip().upper()
    if dep or arr:
        item["route_display"] = f"{dep or '???'} -> {arr or '???'}"

    title = str(item.get("callsign") or item.get("flight_number") or item.get("icao24") or "Traffic").strip().upper()
    item["display_title"] = title
    if item.get("altitude_ft") is not None:
        item["altitude_display"] = "GROUND" if item.get("on_ground") else f"{int(item['altitude_ft']):,} ft"
    elif item.get("on_ground"):
        item["altitude_display"] = "GROUND"
    if item.get("speed_kt") is not None:
        item["speed_display"] = f"{int(item['speed_kt'])} kt"
    if item.get("vertical_rate_fpm") is not None:
        vr = int(item["vertical_rate_fpm"])
        item["vertical_rate_display"] = f"{vr:+d} fpm"
    motion_parts = [
        item.get("altitude_display"),
        item.get("speed_display"),
        item.get("vertical_rate_display"),
    ]
    item["motion_display"] = " | ".join(str(part) for part in motion_parts if part)
    return item


def adsbx_aircraft_to_blips(
    aircraft: list[dict[str, Any]],
    center_lat: float,
    center_lon: float,
    radius_nm: float = 50.0,
) -> list[dict[str, Any]]:
    """Normalize ADS-B Exchange aircraft records without exposing raw payloads."""
    blips: list[dict[str, Any]] = []

    for ac in aircraft:
        lat = float_or_none(ac.get("lat"))
        lon = float_or_none(ac.get("lon"))
        if lat is None or lon is None:
            continue

        dist = distance_nm(center_lat, center_lon, lat, lon)
        if dist > radius_nm:
            continue

        callsign = (str(ac.get("flight") or "").strip().upper() or str(ac.get("hex") or "").upper())
        alt_baro = ac.get("alt_baro")
        alt_geom = ac.get("alt_geom")
        gs_kts = ac.get("gs")
        hdg = ac.get("track")
        baro_rate = ac.get("baro_rate")
        geom_rate = ac.get("geom_rate")
        nav_altitude = ac.get("nav_altitude_mcp", ac.get("nav_altitude_fms"))

        on_ground = alt_baro == "ground"
        altitude_m = None if on_ground else _ft_to_m(alt_baro)
        geo_altitude_m = _ft_to_m(alt_geom)
        vertical_rate = _fpm_to_ms(baro_rate if baro_rate is not None else geom_rate)

        blip = {
            "callsign": callsign,
            "lat": lat,
            "lon": lon,
            "altitude_m": altitude_m,
            "geo_altitude_m": geo_altitude_m,
            "heading": float_or_none(hdg),
            "track_deg": float_or_none(hdg),
            "nav_heading": float_or_none(ac.get("nav_heading")),
            "speed_ms": _kt_to_ms(gs_kts),
            "vertical_rate": vertical_rate,
            "on_ground": on_ground,
            "icao24": str(ac.get("hex") or "").upper(),
            "squawk": ac.get("squawk"),
            "emergency": ac.get("emergency"),
            "aircraft_type": ac.get("t"),
            "registration": ac.get("r"),
            "aircraft_category": ac.get("category"),
            "selected_altitude_ft": round(float(nav_altitude)) if float_or_none(nav_altitude) is not None else None,
            "nav_modes": ac.get("nav_modes") if isinstance(ac.get("nav_modes"), list) else None,
            "position_age_s": float_or_none(ac.get("seen_pos")),
            "source_quality": _truthy_source_quality(ac),
            "source": "adsbexchange",
            "enriched": True,
            "distance_nm": round(dist, 1),
        }
        if geo_altitude_m is not None:
            blip["geo_altitude_ft"] = round(geo_altitude_m * 3.28084)
        blips.append(enrich_blip_display_fields(blip))

    return blips
