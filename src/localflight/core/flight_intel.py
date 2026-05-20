from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any

from localflight.core.models import Flight, FlightDirection, FlightPosition


SCHEMA_VERSION = "flight-intel-v1"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _age_seconds(value: datetime | None) -> int | None:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - value).total_seconds()))


def _feet_from_m(value: Any) -> int | None:
    try:
        return None if value is None else round(float(value) * 3.28084)
    except (TypeError, ValueError):
        return None


def _knots_from_ms(value: Any) -> int | None:
    try:
        return None if value is None else round(float(value) * 1.94384)
    except (TypeError, ValueError):
        return None


def _fpm_from_ms(value: Any) -> int | None:
    try:
        return None if value is None else round(float(value) * 196.8504)
    except (TypeError, ValueError):
        return None


def _delay_bucket(delay: Any) -> str:
    try:
        minutes = int(delay)
    except (TypeError, ValueError):
        return "unknown"
    if minutes <= -5:
        return "early"
    if -4 <= minutes <= 4:
        return "on_time"
    if 5 <= minutes <= 15:
        return "delayed_warn"
    return "delayed_bad"


def _airport_dict(flight: Flight | None, which: str) -> dict[str, Any]:
    ref = None
    if flight:
        if which == "origin":
            ref = flight.origin
        elif which == "destination":
            ref = flight.destination
        elif which == "airport":
            ref = flight.airport
    return {
        "iata": getattr(ref, "iata", None),
        "icao": getattr(ref, "icao", None),
        "name": getattr(ref, "name", None),
        "code": ref.code() if ref else None,
    }


def _route_display(flight: Flight | None) -> str | None:
    if not flight:
        return None
    try:
        return flight.display_route()
    except Exception:
        origin = _airport_dict(flight, "origin").get("code") or "???"
        dest = _airport_dict(flight, "destination").get("code") or "???"
        return f"{origin} -> {dest}"


def _history_summary(history_rows: list[dict[str, Any]]) -> dict[str, Any]:
    delays: list[int] = []
    buckets = {"early": 0, "on_time": 0, "delayed_warn": 0, "delayed_bad": 0, "unknown": 0}
    recent: list[dict[str, Any]] = []

    for row in history_rows:
        delay = row.get("delay_minutes")
        bucket = _delay_bucket(delay)
        buckets[bucket] += 1
        if isinstance(delay, int):
            delays.append(delay)
        recent.append(
            {
                "date": row.get("date") or str(row.get("snapshot_ts") or "")[:10] or None,
                "status": row.get("status"),
                "delay_minutes": delay,
                "delay_bucket": bucket,
                "gate": row.get("gate"),
            }
        )

    return {
        "records": len(history_rows),
        "movements": len(history_rows),
        "last_seen": recent[0]["date"] if recent else None,
        "avg_delay_minutes": round(mean(delays), 1) if delays else None,
        "early_count": buckets["early"],
        "on_time_count": buckets["on_time"],
        "late_count": buckets["delayed_warn"] + buckets["delayed_bad"],
        "delay_buckets": buckets,
        "recent": recent[:5],
    }


def _motion_from_position(pos: FlightPosition | None, radar_blip: dict[str, Any] | None = None) -> dict[str, Any]:
    radar_blip = radar_blip or {}
    altitude_m = pos.altitude_baro if pos else radar_blip.get("altitude_m")
    geo_altitude_m = pos.altitude_geo if pos else radar_blip.get("geo_altitude_m")
    speed_ms = pos.speed_ms if pos else radar_blip.get("speed_ms")
    vertical_rate = pos.vertical_rate if pos else radar_blip.get("vertical_rate")
    heading = pos.heading if pos else (radar_blip.get("heading") or radar_blip.get("track_deg"))
    on_ground = pos.on_ground if pos else radar_blip.get("on_ground")
    last_contact = pos.last_contact if pos else None

    return {
        "has_position": bool(pos or radar_blip.get("lat") is not None),
        "lat": pos.lat if pos else radar_blip.get("lat"),
        "lon": pos.lon if pos else radar_blip.get("lon"),
        "altitude_m": altitude_m,
        "altitude_ft": radar_blip.get("altitude_ft") or _feet_from_m(altitude_m),
        "geo_altitude_m": geo_altitude_m,
        "geo_altitude_ft": radar_blip.get("geo_altitude_ft") or _feet_from_m(geo_altitude_m),
        "speed_ms": speed_ms,
        "speed_kt": radar_blip.get("speed_kt") or _knots_from_ms(speed_ms),
        "vertical_rate_ms": vertical_rate,
        "vertical_rate_fpm": radar_blip.get("vertical_rate_fpm") or _fpm_from_ms(vertical_rate),
        "heading": heading,
        "heading_deg": radar_blip.get("heading_deg") or heading,
        "on_ground": on_ground,
        "last_contact": _iso(last_contact),
        "position_age_seconds": _age_seconds(last_contact) if last_contact else radar_blip.get("position_age_s"),
        "distance_nm": radar_blip.get("distance_nm"),
        "radar_status": radar_blip.get("radar_status_label"),
        "radar_phase": radar_blip.get("radar_phase"),
        "phase_reason": radar_blip.get("phase_reason"),
        "source_quality": radar_blip.get("source_quality"),
    }


def _source_confidence(flight: Flight | None, pos: FlightPosition | None) -> str:
    if not flight:
        return "missing"
    if pos and flight.enriched_by:
        return "live_position_matched"
    if pos:
        return "position_from_snapshot"
    return "schedule_only"


def build_flight_intel(
    flight: Flight | None,
    history_rows: list[dict[str, Any]] | None = None,
    *,
    generated_at: datetime | None = None,
    radar_blip: dict[str, Any] | None = None,
    weather: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one safe, UI-ready flight detail model from already-fetched data."""
    history_rows = history_rows or []
    pos = flight.position if flight else None
    virtual = bool(flight and str(flight.source or "").lower().startswith("vatsim"))
    detail_mode = "virtual" if virtual else ("real" if flight else "missing")
    airline = flight.airline if flight else None
    route = _route_display(flight)
    confidence = _source_confidence(flight, pos)
    weather = weather or {}
    squawk = (pos.squawk if pos else None) or (flight.assigned_transponder if flight else None)

    return {
        "schema_version": SCHEMA_VERSION,
        "detail_mode": detail_mode,
        "identity": {
            "callsign": flight.callsign if flight else None,
            "flight_number": flight.flight_number if flight else None,
            "flight_display": flight.callsign if flight and virtual else (flight.flight_number or flight.callsign if flight else None),
            "airline_name": None if virtual else (airline.name if airline else None),
            "airline_iata": None if virtual else (airline.iata if airline else None),
            "airline_icao": None if virtual else (airline.icao if airline else None),
            "codeshares": [] if virtual else (list(flight.codeshares) if flight else []),
            "sold_as": [] if virtual else (list(flight.sold_as) if flight else []),
            "marketing_airline_name": None if virtual else (flight.marketing_airline_name if flight else None),
            "marketing_airline_iata": None if virtual else (flight.marketing_airline_iata if flight else None),
            "marketing_airline_icao": None if virtual else (flight.marketing_airline_icao if flight else None),
            "marketing_flight_number": None if virtual else (flight.marketing_flight_number if flight else None),
            "operating_callsign": flight.operating_callsign if flight else None,
            "identity_source": (flight.identity_source or "vatsim_callsign") if flight and virtual else (flight.identity_source if flight else None),
            "provider_codeshare_status": None if virtual else (flight.provider_codeshare_status if flight else None),
            "provider_movement_key": None if virtual else (flight.provider_movement_key if flight else None),
            "identity_evidence": [] if virtual else (list(flight.identity_evidence) if flight else []),
        },
        "route": {
            "origin": _airport_dict(flight, "origin"),
            "destination": _airport_dict(flight, "destination"),
            "airport": _airport_dict(flight, "airport"),
            "direction": flight.direction.value if flight else None,
            "route_display": route,
        },
        "timing": {
            "scheduled": _iso(flight.times.scheduled) if flight else None,
            "estimated": _iso(flight.times.estimated) if flight else None,
            "actual": _iso(flight.times.actual) if flight else None,
            "delay_minutes": None if virtual else (flight.delay_minutes if flight else None),
            "delay_bucket": None if virtual else _delay_bucket(flight.delay_minutes if flight else None),
            "status": flight.status.value if flight else None,
        },
        "operations": {
            "terminal": None if virtual else (flight.terminal if flight else None),
            "gate": None if virtual else (flight.gate if flight else None),
            "stand": None if virtual else (flight.stand if flight else None),
            "direction": flight.direction.value if flight else None,
        },
        "aircraft": {
            "type": flight.aircraft_type if flight else None,
            "model": flight.aircraft_type_full if flight else None,
            "full_type": flight.aircraft_type_full if flight else None,
            "registration": flight.aircraft_registration if flight and not virtual else None,
            "icao24": pos.icao24 if pos and not virtual else None,
            "squawk": squawk,
            "selected_altitude_ft": (radar_blip or {}).get("selected_altitude_ft"),
            "nav_modes": (radar_blip or {}).get("nav_modes"),
            "category": (radar_blip or {}).get("aircraft_category"),
        },
        "motion": _motion_from_position(pos, radar_blip),
        "flight_plan": {
            "flight_rules": flight.flight_rules if flight else None,
            "route": flight.planned_route if flight else None,
            "cruise_altitude": flight.planned_altitude if flight else None,
            "planned_departure": _iso(flight.planned_departure) if flight else None,
            "planned_arrival": _iso(flight.planned_arrival) if flight else None,
            "enroute_minutes": flight.planned_enroute_minutes if flight else None,
            "cruise_tas": flight.cruise_tas if flight else None,
            "alternate_icao": flight.alternate_icao if flight else None,
            "assigned_transponder": flight.assigned_transponder if flight else None,
        },
        "weather": {
            "available": bool(weather),
            "summary": weather.get("decoded_summary") or weather.get("summary"),
            "flight_category": weather.get("flight_cat") or weather.get("flight_category"),
            "temperature_c": weather.get("temperature_c"),
            "wind": weather.get("wind"),
            "qnh": weather.get("qnh"),
            "icon": weather.get("weather_icon"),
            "source": weather.get("source"),
        },
        "history_summary": _history_summary(history_rows),
        "source_evidence": {
            "schedule_source": flight.source if flight else None,
            "position_source": flight.enriched_by or flight.source if flight else None,
            "confidence": confidence,
            "snapshot_generated_at": _iso(generated_at),
            "snapshot_age_seconds": _age_seconds(generated_at),
            "fields_available": _available_fields(flight, pos, weather, virtual=virtual),
        },
        "privacy": {
            "vatsim_personal_identifiers": False,
            "notes": "VATSIM personal identifiers are intentionally not included.",
        },
    }


def _available_fields(flight: Flight | None, pos: FlightPosition | None, weather: dict[str, Any], *, virtual: bool = False) -> list[str]:
    fields: list[str] = []
    if flight:
        fields.append("schedule")
        if not virtual and (flight.gate or flight.terminal or flight.stand):
            fields.append("airport_ops")
        if flight.flight_rules or flight.planned_route:
            fields.append("flight_plan")
        if flight.aircraft_type or flight.aircraft_type_full or (flight.aircraft_registration and not virtual):
            fields.append("aircraft")
    if pos:
        fields.append("live_motion")
    if weather:
        fields.append("weather")
    return fields
