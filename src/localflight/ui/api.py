"""
localflight/ui/api.py

JSON API layer for the FIDS system.
"""
from __future__ import annotations

import json
import importlib
import logging
import math
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests as _req
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from localflight.core.aircraft import aircraft_full_label, short_aircraft_type
from localflight.core.airports import _load_index, best_label, lookup_airport
from localflight.core.flight_intel import build_flight_intel
from localflight.core.models import Flight, FlightDirection, FlightPosition
from localflight.core.timezones import resolve_config_timezone
from localflight.decode.identity import resolve_flight_identity
from localflight.decode.dedupe import dedupe_codeshares
from localflight.display.fids import enrich_presentation_fields
from localflight.render.fids import build_fids_context
from localflight.storage.config import (
    ALLOWED_REFRESH_SECONDS,
    ALLOWED_DIAGNOSTICS_MODES,
    ALLOWED_SKINS,
    ALLOWED_SOURCES,
    AppConfig,
    DEFAULT_DISPLAY_GRACE_MINUTES,
    DEFAULT_DISPLAY_HORIZON_HOURS,
    DEFAULT_WEB_ROTATION_SECONDS,
    DEFAULT_WEB_ROW_LIMIT,
    load_config,
    save_config,
)
from localflight.storage.flights_store import load_latest_snapshot_path, snapshot_store_root
from localflight.storage.state import load_state
from localflight.sources.web.airport_surface import (
    AIRPORT_SURFACE_PROVIDER,
    build_estimated_surface_payload,
    build_surface_payload,
    clamp_surface_radius_nm,
    validate_surface_payload,
)
from localflight.sources.web.airport_map_context import (
    build_map_context_payload,
    fetch_overpass_map_context,
    normalize_overpass_map_context,
    validate_map_context_payload,
)
from localflight.sources.web.terrain_context import (
    build_terrain_payload,
    fetch_terrain_context,
    validate_terrain_payload,
)
from localflight.radar import annotate_blips, build_radar_map, enrich_blip_display_fields
from localflight.sources.web.relay_defaults import default_public_relay_url, relay_airport_surface_url

log = logging.getLogger(__name__)

router = APIRouter()

_COMPANION_STALE_SECONDS = 15 * 60
_COMPANION_RETENTION_DAYS = 30


def _schedule_policy_for_config(source: Optional[str] = None) -> Dict[str, Any]:
    try:
        from localflight.sources.web.aviationstack_client import schedule_policy

        return schedule_policy(source or load_config().source)
    except Exception:
        allowed = sorted(ALLOWED_REFRESH_SECONDS)
        return {
            "shared_relay": False,
            "active_mode": "unknown",
            "community_shared": False,
            "min_refresh_seconds": min(allowed) if allowed else 900,
            "allowed_refresh_seconds": allowed,
            "reason": "",
            "cooldown_remaining_seconds": 0,
        }


def _coerce_refresh_for_schedule_policy(refresh_seconds: int, source: Optional[str] = None) -> int:
    policy = _schedule_policy_for_config(source)
    allowed = [int(value) for value in (policy.get("allowed_refresh_seconds") or []) if int(value) in ALLOWED_REFRESH_SECONDS]
    if not allowed:
        allowed = sorted(ALLOWED_REFRESH_SECONDS)
    refresh = int(refresh_seconds)
    if refresh in allowed:
        return refresh
    minimum = int(policy.get("min_refresh_seconds") or min(allowed))
    for value in sorted(allowed):
        if value >= max(refresh, minimum):
            return value
    return max(allowed)


def client_polling_policy() -> Dict[str, Any]:
    return {
        "mode": "event_first",
        "jitter_ratio": 0.2,
        "fids_fallback_seconds": 300,
        "admin_fallback_seconds": 60,
        "hidden_fallback_seconds": 900,
        "radar_visible_min_seconds": 60,
        "radar_hidden_min_seconds": 300,
        "mobile_min_fallback_seconds": 300,
    }


def _network_tools_enabled() -> bool:
    import os
    return os.getenv("LOCALFLIGHT_ENABLE_NETWORK_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}

# In-memory caches for live radar sources. The UI polls frequently, so these
# prevent each browser tab or mobile companion from spending one API call.
_adsbx_radar_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_opensky_radar_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_radar_map_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
_radar_fetch_locks: Dict[str, Lock] = {}
_radar_fetch_locks_lock = Lock()
_DEFAULT_ADSBX_RADAR_CACHE_TTL_S = 300
_OPENSKY_RADAR_CACHE_TTL_S = 60
_RADAR_MAP_CACHE_TTL_S = 300
_SURFACE_CACHE_TTL_S = 60 * 60 * 24 * 14
_SURFACE_MISS_TTL_S = 60 * 60
_MIN_PROVIDER_RADAR_RADIUS_NM = 5.0
_SURFACE_RELAY_TIMEOUT_S = 3.0
_MAP_CONTEXT_TIMEOUT_S = 8.0
_MAP_CONTEXT_CACHE_TTL_S = 60 * 60 * 24 * 14
_MAP_CONTEXT_MISS_TTL_S = 60 * 2
_map_context_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lf-map-context")
_map_context_refreshing: set[str] = set()
_map_context_refresh_lock = Lock()
_terrain_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lf-terrain")
_terrain_refreshing: set[str] = set()
_terrain_refresh_lock = Lock()
_TERRAIN_CACHE_TTL_S = 60 * 60 * 24 * 30
_TERRAIN_MISS_TTL_S = 60 * 60


def _adsbx_radar_cache_ttl_s() -> int:
    try:
        return max(
            60,
            int(os.getenv("LOCALFLIGHT_RADAR_ADSB_REFRESH_SECONDS", str(_DEFAULT_ADSBX_RADAR_CACHE_TTL_S))),
        )
    except ValueError:
        return _DEFAULT_ADSBX_RADAR_CACHE_TTL_S


def _radar_refresh_after_s(source_used: str) -> int:
    source_name = (source_used or "").strip().lower()
    if source_name.startswith("adsbexchange"):
        return _adsbx_radar_cache_ttl_s()
    if source_name.startswith("opensky"):
        return _OPENSKY_RADAR_CACHE_TTL_S
    if source_name == "snapshot_positions":
        return 60
    return 15


def _get_radar_fetch_lock(cache_key: str) -> Lock:
    with _radar_fetch_locks_lock:
        lock = _radar_fetch_locks.get(cache_key)
        if lock is None:
            lock = Lock()
            _radar_fetch_locks[cache_key] = lock
        return lock


def _vatsim_client_module():
    return importlib.import_module("localflight.sources.web.vatsim_client")


def _fetch_vatsim_payload() -> Dict[str, Any]:
    vatsim_client = _vatsim_client_module()
    fetch_vatsim = getattr(vatsim_client, "fetch_vatsim_data_cached", None)
    if fetch_vatsim is None:
        fetch_vatsim = vatsim_client.fetch_vatsim_data
    return fetch_vatsim()


def _provider_radar_radius_nm(radius_nm: float) -> float:
    """Use the smallest upstream-supported radar circle, then crop locally."""
    return max(_MIN_PROVIDER_RADAR_RADIUS_NM, float(math.ceil(float(radius_nm) / 5.0) * 5.0))


def _distance_nm(center_lat: float, center_lon: float, lat: float, lon: float) -> float:
    dlat = (lat - center_lat) * 60.0
    dlon = (lon - center_lon) * 60.0 * math.cos(math.radians(center_lat))
    return math.sqrt((dlat * dlat) + (dlon * dlon))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_ground_radar_blip(blip: Dict[str, Any]) -> bool:
    if blip.get("on_ground") is True:
        return True

    altitude_m = _float_or_none(blip.get("altitude_m"))
    speed_ms = _float_or_none(blip.get("speed_ms"))

    if altitude_m is not None and speed_ms is not None:
        return altitude_m < 75 and speed_ms < 25
    if altitude_m is not None:
        return altitude_m < 30
    return False


def _filter_airborne_radar_blips(blips: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    airborne = [b for b in blips if not _is_ground_radar_blip(b)]
    return airborne, len(blips) - len(airborne)


def _filter_ground_radar_blips(blips: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], int]:
    ground = [b for b in blips if _is_ground_radar_blip(b)]
    return ground, len(blips) - len(ground)


def _surface_radar_mode(radius_nm: float) -> bool:
    return float(radius_nm) <= 5.0


def _radar_blip_phase(blip: Dict[str, Any], *, airport_icao: str) -> Dict[str, str]:
    airport_code = (airport_icao or "").strip().upper()
    dep = str(blip.get("departure_icao") or "").strip().upper()
    arr = str(blip.get("arrival_icao") or "").strip().upper()
    distance_nm = _float_or_none(blip.get("distance_nm"))
    altitude_m = _float_or_none(blip.get("altitude_m"))
    speed_ms = _float_or_none(blip.get("speed_ms"))
    vertical_rate = _float_or_none(blip.get("vertical_rate"))
    on_ground = _is_ground_radar_blip(blip)

    is_arrival = bool(airport_code and arr == airport_code)
    is_departure = bool(airport_code and dep == airport_code)
    low_near = distance_nm is not None and distance_nm <= 5.0 and (altitude_m is None or altitude_m <= 900)
    approach_near = distance_nm is not None and distance_nm <= 15.0 and (altitude_m is None or altitude_m <= 2500)

    if on_ground:
        phase = "ground"
        label = "On ground"
    elif is_arrival and low_near and (speed_ms is None or speed_ms >= 35):
        phase = "final"
        label = "On final"
    elif is_arrival and approach_near:
        phase = "approach"
        label = "On approach"
    elif vertical_rate is not None and vertical_rate < -0.75:
        phase = "descending"
        label = "Descending"
    elif is_departure and distance_nm is not None and distance_nm <= 15.0:
        phase = "departure"
        label = "Departing"
    elif vertical_rate is not None and vertical_rate > 0.75:
        phase = "climbing"
        label = "Climbing"
    else:
        phase = "enroute"
        label = "Enroute"

    return {"radar_phase": phase, "radar_status": phase, "radar_status_label": label}


def _annotate_radar_blips(
    blips: List[Dict[str, Any]],
    *,
    airport_icao: str,
    runways: list[dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    return annotate_blips(blips, airport_icao=airport_icao, runways=runways or [])


def _filter_radar_blips_for_view(
    blips: list[dict[str, Any]],
    *,
    traffic: str = "all",
    min_alt_ft: float | None = None,
    max_alt_ft: float | None = None,
) -> list[dict[str, Any]]:
    requested = (traffic or "all").strip().lower()
    filtered: list[dict[str, Any]] = []
    for blip in blips:
        role = str(blip.get("traffic_role") or "").lower()
        phase = str(blip.get("radar_phase") or blip.get("radar_status") or "").lower()
        on_ground = _is_ground_radar_blip(blip)
        altitude_ft = _float_or_none(blip.get("altitude_ft"))
        if altitude_ft is None:
            altitude_m = _float_or_none(blip.get("altitude_m"))
            altitude_ft = altitude_m * 3.28084 if altitude_m is not None else None
        if min_alt_ft is not None and altitude_ft is not None and altitude_ft < min_alt_ft:
            continue
        if max_alt_ft is not None and altitude_ft is not None and altitude_ft > max_alt_ft:
            continue
        if requested in {"arrival", "arrivals"} and role != "arrival":
            continue
        if requested in {"departure", "departures"} and role != "departure":
            continue
        if requested == "final" and phase != "final":
            continue
        if requested == "ground" and not on_ground:
            continue
        if requested == "airborne" and on_ground:
            continue
        filtered.append(blip)
    return filtered


def _companion_presence_path():
    from localflight.storage.config import config_path

    return config_path().parent / "companion_clients.json"


def _load_companion_presence() -> Dict[str, Any]:
    path = _companion_presence_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_companion_presence(data: Dict[str, Any]) -> None:
    try:
        path = _companion_presence_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# â”€â”€ Airport search â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

SEARCH_TYPES = {"large_airport", "medium_airport"}


def _score(rec: dict, q: str) -> int:
    q     = q.upper()
    iata  = (rec.get("iata")  or "").upper()
    icao  = (rec.get("icao")  or "").upper()
    city  = (rec.get("city")  or "").upper()
    name  = (rec.get("name")  or "").upper()
    atype = (rec.get("type")  or "")

    if q == iata or q == icao:                   return 100
    if iata.startswith(q) or icao.startswith(q): return 80
    if q == city:                                return 70
    if city.startswith(q):                       return 60 if atype == "large_airport" else 50
    if q in name:                                return 40 if atype == "large_airport" else 30
    if q in city:                                return 20
    return 0


@router.get("/api/airports/search")
def airport_search(
    q:         str  = Query(..., min_length=2, max_length=20),
    limit:     int  = Query(8, ge=1, le=20),
    all_types: bool = Query(False),
) -> List[Dict[str, Any]]:
    q_clean = q.strip().upper()
    if not q_clean:
        return []

    idx     = _load_index()
    by_iata = idx.get("by_iata") or {}
    by_icao = idx.get("by_icao") or {}

    seen: set[str] = set()
    candidates: list[tuple[int, dict]] = []

    for rec in list(by_iata.values()) + list(by_icao.values()):
        if not isinstance(rec, dict):
            continue
        key = (rec.get("icao") or rec.get("iata") or "").upper()
        if key in seen:
            continue
        seen.add(key)

        atype = rec.get("type") or ""
        if not all_types and atype not in SEARCH_TYPES:
            continue

        score = _score(rec, q_clean)
        if score > 0:
            candidates.append((score, rec))

    candidates.sort(key=lambda x: (
        -x[0],
        0 if x[1].get("type") == "large_airport" else 1,
        x[1].get("name") or "",
    ))

    from localflight.core.airports import get_airport_timezone

    return [
        {
            "iata":     r.get("iata") or "",
            "icao":     r.get("icao") or "",
            "name":     r.get("name") or "",
            "city":     r.get("city") or "",
            "country":  r.get("country") or "",
            "type":     r.get("type") or "",
            "timezone": get_airport_timezone(r.get("country") or "", r.get("region") or ""),
        }
        for _, r in candidates[:limit]
    ]


@router.get("/api/airports/resolve")
def airport_resolve(
    q: str = Query(..., min_length=2, max_length=10),
) -> Dict[str, Any]:
    q_clean = q.strip().upper()
    rec = lookup_airport(
        iata=q_clean if len(q_clean) == 3 else None,
        icao=q_clean if len(q_clean) == 4 else None,
    )
    if not rec:
        raise HTTPException(status_code=404, detail=f"Airport not found: {q}")
    from localflight.core.airports import get_airport_timezone
    return {
        "iata":     rec.iata    or "",
        "icao":     rec.icao    or "",
        "name":     rec.name    or "",
        "city":     rec.city    or "",
        "country":  rec.country or "",
        "lat":      rec.lat,
        "lon":      rec.lon,
        "timezone": get_airport_timezone(rec.country or "", rec.region or ""),
    }


# â”€â”€ Snapshot loader â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _dict_to_position(d: Optional[dict]) -> Optional[FlightPosition]:
    if not d:
        return None

    def _dt(v: Any) -> Optional[datetime]:
        if not v:
            return None
        try:
            return datetime.fromisoformat(str(v))
        except Exception:
            return None

    return FlightPosition(
        lat=d.get("lat"),
        lon=d.get("lon"),
        altitude_baro=d.get("altitude_baro"),
        altitude_geo=d.get("altitude_geo"),
        heading=d.get("heading"),
        speed_ms=d.get("speed_ms"),
        vertical_rate=d.get("vertical_rate"),
        on_ground=d.get("on_ground"),
        icao24=d.get("icao24"),
        squawk=d.get("squawk"),
        last_contact=_dt(d.get("last_contact")),
    )


def _dict_to_flight(d: dict) -> Flight:
    from localflight.core.models import AirlineRef, AirportRef, FlightStatus, FlightTime

    def _dt(v: Any) -> Optional[datetime]:
        if not v:
            return None
        try:
            return datetime.fromisoformat(str(v))
        except Exception:
            return None

    def _airport(x: Optional[dict]) -> Optional[AirportRef]:
        if not x:
            return None
        return AirportRef(iata=x.get("iata"), icao=x.get("icao"), name=x.get("name"))

    def _codeshares(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            return ()
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = str(item or "").strip().upper()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return tuple(out)

    def _text_tuple(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            return ()
        out: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = str(item or "").strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return tuple(out)

    direction = FlightDirection(d["direction"])
    try:
        status = FlightStatus(d.get("status", "Unknown"))
    except ValueError:
        status = FlightStatus.UNKNOWN

    times_d   = d.get("times")   or {}
    airline_d = d.get("airline") or {}
    airport_d = d.get("airport") or {}
    identity = resolve_flight_identity(
        {
            "callsign": d.get("operating_callsign") or d.get("callsign"),
            "airline_name": airline_d.get("name"),
            "airline_iata": airline_d.get("iata"),
            "airline_icao": airline_d.get("icao"),
            "flight_number": d.get("flight_number"),
            "codeshares": d.get("codeshares"),
            "sold_as": d.get("sold_as"),
            "marketing_airline_name": d.get("marketing_airline_name"),
            "marketing_airline_iata": d.get("marketing_airline_iata"),
            "marketing_airline_icao": d.get("marketing_airline_icao"),
            "marketing_flight_number": d.get("marketing_flight_number"),
            "operating_callsign": d.get("operating_callsign"),
            "identity_source": d.get("identity_source"),
            "provider_codeshare_status": d.get("provider_codeshare_status"),
        },
        airport_iata=airport_d.get("iata") or "",
        airport_icao=airport_d.get("icao") or "",
    )
    aircraft_short = short_aircraft_type(d.get("aircraft_type"))
    aircraft_full = d.get("aircraft_type_full") or aircraft_full_label(
        d.get("aircraft_type"),
        short_code=aircraft_short,
    )

    return Flight(
        direction=direction,
        airport=AirportRef(
            iata=(d.get("airport") or {}).get("iata"),
            icao=(d.get("airport") or {}).get("icao"),
        ),
        callsign=identity.callsign or d["callsign"],
        airline=AirlineRef(
            name=identity.airline_name,
            iata=identity.airline_iata,
            icao=identity.airline_icao,
        ),
        flight_number=identity.flight_number,
        codeshares=identity.codeshares,
        sold_as=identity.sold_as,
        marketing_airline_name=identity.marketing_airline_name,
        marketing_airline_iata=identity.marketing_airline_iata,
        marketing_airline_icao=identity.marketing_airline_icao,
        marketing_flight_number=identity.marketing_flight_number,
        operating_callsign=identity.operating_callsign,
        identity_source=identity.identity_source,
        provider_codeshare_status=d.get("provider_codeshare_status"),
        provider_movement_key=d.get("provider_movement_key"),
        identity_evidence=_text_tuple(d.get("identity_evidence")),
        origin=_airport(d.get("origin")),
        destination=_airport(d.get("destination")),
        aircraft_type=aircraft_short or None,
        aircraft_type_full=aircraft_full or None,
        aircraft_registration=d.get("aircraft_registration"),
        gate=d.get("gate"),
        terminal=d.get("terminal"),
        stand=d.get("stand"),
        status=status,
        times=FlightTime(
            scheduled=_dt(times_d.get("scheduled")),
            estimated=_dt(times_d.get("estimated")),
            actual=_dt(times_d.get("actual")),
        ),
        delay_minutes=d.get("delay_minutes"),
        flight_rules=d.get("flight_rules"),
        planned_route=d.get("planned_route"),
        planned_altitude=d.get("planned_altitude"),
        planned_departure=_dt(d.get("planned_departure")),
        planned_arrival=_dt(d.get("planned_arrival")),
        planned_enroute_minutes=d.get("planned_enroute_minutes"),
        cruise_tas=d.get("cruise_tas"),
        alternate_icao=d.get("alternate_icao"),
        assigned_transponder=d.get("assigned_transponder"),
        position=_dict_to_position(d.get("position")),
        source=d.get("source"),
        enriched_by=d.get("enriched_by"),
        updated_at=_dt(d.get("updated_at")),
    )


def _load_latest_flights(airport_iata: str) -> tuple[List[Flight], Optional[datetime]]:
    path = load_latest_snapshot_path(airport_iata)
    if not path:
        return [], None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Could not read snapshot %s: %s", path, exc)
        return [], None

    generated_at: Optional[datetime] = None
    try:
        generated_at = datetime.fromisoformat(raw["generated_at"])
    except Exception:
        pass

    flights: List[Flight] = []
    for f in (raw.get("flights") or []):
        try:
            flights.append(_dict_to_flight(f))
        except Exception as exc:
            log.debug("Skipping malformed flight: %s", exc)

    return dedupe_codeshares(flights), generated_at


# â”€â”€ Pydantic schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ConfigPatch(BaseModel):
    airport_icao:    Optional[str] = None
    airport_iata:    Optional[str] = None
    refresh_seconds: Optional[int] = Field(None, ge=900, le=86400)
    display_name:    Optional[str] = Field(None, max_length=40)
    theme:           Optional[Literal["dark", "light"]] = None
    source:          Optional[Literal["real", "virtual"]] = None
    timezone:        Optional[str] = None
    skin:            Optional[str] = None
    diagnostics_mode: Optional[str] = None
    web_row_limit: Optional[int] = Field(None, ge=5, le=40)
    web_rotation_seconds: Optional[int] = Field(None, ge=3, le=60)
    display_grace_minutes: Optional[int] = Field(None, ge=0, le=180)
    display_horizon_hours: Optional[int] = Field(None, ge=1, le=24)
    radar_surface_enabled: Optional[bool] = None
    radar_surface_mode: Optional[Literal["off", "estimated", "relay"]] = None


class FIDSRowOut(BaseModel):
    id:             str
    view:           str
    display_time:   str
    flight_display: str
    airline_display: str = ""
    codeshare_display: str = ""
    flight_number: str = ""
    airline_iata: str = ""
    airline_icao: str = ""
    codeshares: List[str] = Field(default_factory=list)
    sold_as: List[str] = Field(default_factory=list)
    marketing_airline_name: str = ""
    marketing_airline_iata: str = ""
    marketing_airline_icao: str = ""
    marketing_flight_number: str = ""
    operating_callsign: str = ""
    identity_source: str = ""
    provider_codeshare_status: str = ""
    provider_movement_key: str = ""
    identity_evidence: List[str] = Field(default_factory=list)
    route_display:  str
    status_display: str
    status_class:   str
    gate:           str
    aircraft_type:  str
    callsign:       str = ""
    delay_minutes: Optional[int] = None
    delay_class: str = ""
    time_primary: str = ""
    time_delta_label: str = ""
    time_delta_text: str = ""
    delay_kind: str = "none"
    status_kind: str = "scheduled"
    tone: str = "neutral"
    gate_display: str = ""
    terminal_display: str = ""
    terminal_gate_display: str = ""
    route_primary: str = ""
    route_code: str = ""
    route_caption: str = ""
    source_hint: str = ""
    live_hint: str = ""
    detail_mode: str = "real"
    flight_rules: str = ""
    planned_altitude: str = ""
    planned_route: str = ""
    altitude_ft: Optional[int] = None
    ground_speed_kt: Optional[int] = None
    squawk: str = ""
    transponder: str = ""


def _fids_rows_from_flights(
    *,
    cfg: AppConfig,
    flights: List[Flight],
    view: Literal["departures", "arrivals"],
    limit: int,
    last_refreshed: Optional[datetime],
    source_status: Optional[str] = None,
) -> List[FIDSRowOut]:
    direction = FlightDirection.DEPARTURE if view == "departures" else FlightDirection.ARRIVAL
    filtered = [f for f in flights if f.direction == direction]
    ctx = build_fids_context(
        cfg=cfg,
        view=view,
        refresh_seconds=cfg.refresh_seconds,
        flights=filtered,
        last_refreshed=last_refreshed,
        reference_now=last_refreshed,
        source_status=source_status or cfg.source,
    )
    rows = list(ctx["rows"])[:limit]
    return [
        FIDSRowOut(
            id=r.id, view=r.view, display_time=r.display_time,
            flight_display=r.flight_display, airline_display=r.airline_display,
            codeshare_display=r.codeshare_display, route_display=r.route_display,
            status_display=r.status_display, status_class=r.status_class,
            gate=r.gate, aircraft_type=r.aircraft_type,
            callsign=r.callsign,
            flight_number=r.flight_number,
            airline_iata=r.airline_iata,
            airline_icao=r.airline_icao,
            codeshares=list(r.codeshares),
            sold_as=list(r.sold_as),
            marketing_airline_name=r.marketing_airline_name,
            marketing_airline_iata=r.marketing_airline_iata,
            marketing_airline_icao=r.marketing_airline_icao,
            marketing_flight_number=r.marketing_flight_number,
            operating_callsign=r.operating_callsign,
            identity_source=r.identity_source,
            provider_codeshare_status=r.provider_codeshare_status,
            provider_movement_key=r.provider_movement_key,
            identity_evidence=list(r.identity_evidence),
            delay_minutes=r.delay_minutes,
            delay_class=r.delay_class,
            time_primary=r.time_primary,
            time_delta_label=r.time_delta_label,
            time_delta_text=r.time_delta_text,
            delay_kind=r.delay_kind,
            status_kind=r.status_kind,
            tone=r.tone,
            gate_display=r.gate_display,
            terminal_display=r.terminal_display,
            terminal_gate_display=r.terminal_gate_display,
            route_primary=r.route_primary,
            route_code=r.route_code,
            route_caption=r.route_caption,
            source_hint=r.source_hint,
            live_hint=r.live_hint,
            detail_mode=r.detail_mode,
            flight_rules=r.flight_rules,
            planned_altitude=r.planned_altitude,
            planned_route=r.planned_route,
            altitude_ft=r.altitude_ft,
            ground_speed_kt=r.ground_speed_kt,
            squawk=r.squawk,
            transponder=r.transponder,
        )
        for r in rows
    ]


# â”€â”€ Config endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/health")
def api_health() -> Dict[str, Any]:
    return asdict(load_state())


@router.get("/api/config")
def api_get_config() -> Dict[str, Any]:
    cfg = load_config()
    return {**asdict(cfg), **_matrix_clock_payload(cfg)}


@router.patch("/api/config")
def api_patch_config(patch: ConfigPatch, background_tasks: BackgroundTasks) -> Dict[str, Any]:
    data = patch.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields provided")
    if "refresh_seconds" in data and data["refresh_seconds"] not in ALLOWED_REFRESH_SECONDS:
        raise HTTPException(status_code=422, detail=f"refresh_seconds must be one of {sorted(ALLOWED_REFRESH_SECONDS)}")
    if "diagnostics_mode" in data:
        mode = str(data["diagnostics_mode"]).strip().lower()
        if mode not in ALLOWED_DIAGNOSTICS_MODES:
            raise HTTPException(status_code=422, detail=f"diagnostics_mode must be one of {sorted(ALLOWED_DIAGNOSTICS_MODES)}")
        data["diagnostics_mode"] = mode
    if "radar_surface_mode" in data:
        data["radar_surface_enabled"] = str(data["radar_surface_mode"]).strip().lower() != "off"
    current_cfg = load_config()
    source_for_policy = str(data.get("source") or current_cfg.source)
    if "refresh_seconds" in data:
        data["refresh_seconds"] = _coerce_refresh_for_schedule_policy(int(data["refresh_seconds"]), source_for_policy)
    else:
        coerced_refresh = _coerce_refresh_for_schedule_policy(int(current_cfg.refresh_seconds), source_for_policy)
        if coerced_refresh != int(current_cfg.refresh_seconds):
            data["refresh_seconds"] = coerced_refresh
    current = asdict(current_cfg)
    scheduler_fields = {
        "airport_iata",
        "airport_icao",
        "refresh_seconds",
        "source",
        "timezone",
        "display_grace_minutes",
        "display_horizon_hours",
    }
    restart_needed = any(key in data and data[key] != current.get(key) for key in scheduler_fields)
    current.update(data)
    new_cfg = AppConfig(**current)
    save_config(new_cfg)
    log.info("Config updated via API: %s", data)
    from localflight.ui.events import notify_config_updated, restart_scheduler_and_notify

    notify_config_updated(new_cfg, reason="api_config")
    if restart_needed:
        background_tasks.add_task(restart_scheduler_and_notify, "api_config")
    return asdict(new_cfg)


# â”€â”€ Flight endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/flights")
def api_flights(
    direction: Literal["dep", "arr", "both"] = Query("both"),
) -> List[Dict[str, Any]]:
    cfg = load_config()
    flights, _ = _load_latest_flights(cfg.airport_iata)
    if direction == "dep":
        flights = [f for f in flights if f.direction == FlightDirection.DEPARTURE]
    elif direction == "arr":
        flights = [f for f in flights if f.direction == FlightDirection.ARRIVAL]
    return [asdict(f) for f in flights]


@router.get("/api/fids", response_model=List[FIDSRowOut])
def api_fids(
    view:  Literal["departures", "arrivals"] = Query("departures"),
    limit: int = Query(DEFAULT_WEB_ROW_LIMIT, ge=1, le=100),
) -> List[FIDSRowOut]:
    cfg = load_config()
    flights, last_refreshed = _load_latest_flights(cfg.airport_iata)
    return _fids_rows_from_flights(
        cfg=cfg,
        flights=flights,
        view=view,
        limit=limit,
        last_refreshed=last_refreshed,
        source_status=cfg.source,
    )


@router.get("/api/fids/detail")
def api_fids_detail(callsign: str = Query(..., min_length=1, max_length=20)) -> Dict[str, Any]:
    from localflight.storage.history import query_flight_history
    from localflight.decode.mappings.airlines import format_flight_identifier

    cfg = load_config()
    flights, generated_at = _load_latest_flights(cfg.airport_iata)
    flight = next((f for f in flights if (f.callsign or "").upper() == callsign.upper()), None)

    def _iso(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    def _age_seconds(value: Optional[datetime]) -> Optional[int]:
        if not value:
            return None
        now = datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return max(0, int((now - value).total_seconds()))

    def _source_confidence() -> str:
        if not flight:
            return "missing"
        if flight.position and flight.enriched_by:
            return "live_position_matched"
        if flight.position:
            return "position_from_snapshot"
        return "schedule_only"

    detail: Dict[str, Any] = {}
    if flight:
        pos = flight.position
        snapshot_age = _age_seconds(generated_at)
        position_age = _age_seconds(pos.last_contact if pos else None)
        is_virtual = str(cfg.source or "").lower() == "virtual" or str(flight.source or "").lower().startswith("vatsim")
        xpdr = flight.assigned_transponder or (pos.squawk if pos else None)
        flight_display = (
            (flight.callsign or flight.flight_number or "").upper()
            if is_virtual
            else format_flight_identifier(
                flight_number=flight.flight_number,
                callsign=flight.callsign,
                airline_iata=flight.airline.iata if flight.airline else None,
                airline_icao=flight.airline.icao if flight.airline else None,
            )
        )
        detail = {
            "callsign":      flight.callsign,
            "flight_number": flight.flight_number,
            "flight_display": flight_display,
            "airline":       None if is_virtual else (flight.airline.name if flight.airline else None),
            "airline_iata":  None if is_virtual else (flight.airline.iata if flight.airline else None),
            "airline_icao":  None if is_virtual else (flight.airline.icao if flight.airline else None),
            "codeshares":    [] if is_virtual else list(flight.codeshares),
            "sold_as":       [] if is_virtual else list(flight.sold_as),
            "marketing_airline_name": None if is_virtual else flight.marketing_airline_name,
            "marketing_airline_iata": None if is_virtual else flight.marketing_airline_iata,
            "marketing_airline_icao": None if is_virtual else flight.marketing_airline_icao,
            "marketing_flight_number": None if is_virtual else flight.marketing_flight_number,
            "operating_callsign": flight.operating_callsign,
            "identity_source": flight.identity_source or ("vatsim_callsign" if is_virtual else None),
            "provider_codeshare_status": None if is_virtual else flight.provider_codeshare_status,
            "provider_movement_key": None if is_virtual else flight.provider_movement_key,
            "identity_evidence": [] if is_virtual else list(flight.identity_evidence or ()),
            "origin_iata":   flight.origin.iata        if flight.origin      else None,
            "origin_icao":   flight.origin.icao        if flight.origin      else None,
            "origin_name":   flight.origin.name        if flight.origin      else None,
            "dest_iata":     flight.destination.iata   if flight.destination else None,
            "dest_icao":     flight.destination.icao   if flight.destination else None,
            "dest_name":     flight.destination.name   if flight.destination else None,
            "sched_time":    flight.times.scheduled.isoformat() if flight.times.scheduled else None,
            "est_time":      flight.times.estimated.isoformat() if flight.times.estimated else None,
            "actual_time":   flight.times.actual.isoformat()    if flight.times.actual    else None,
            "delay_minutes": None if is_virtual else flight.delay_minutes,
            "gate":          None if is_virtual else flight.gate,
            "terminal":      None if is_virtual else flight.terminal,
            "stand":         None if is_virtual else flight.stand,
            "aircraft_type": flight.aircraft_type,
            "aircraft_type_full": flight.aircraft_type_full,
            "aircraft_registration": None if is_virtual else flight.aircraft_registration,
            "direction":     flight.direction.value,
            "status":        flight.status.value,
            "source":        flight.source,
            "enriched_by":   flight.enriched_by,
            "updated_at":    _iso(flight.updated_at),
            "detail_mode":   "virtual" if is_virtual else "real",
            "flight_plan": {
                "flight_rules": flight.flight_rules,
                "route": flight.planned_route,
                "cruise_altitude": flight.planned_altitude,
                "planned_departure": _iso(flight.planned_departure),
                "planned_arrival": _iso(flight.planned_arrival),
                "enroute_minutes": flight.planned_enroute_minutes,
                "cruise_tas": flight.cruise_tas,
                "alternate_icao": flight.alternate_icao,
                "assigned_transponder": flight.assigned_transponder,
            },
            "data_sources": {
                "schedule":              flight.source,
                "enrichment":            flight.enriched_by,
                "confidence":            _source_confidence(),
                "snapshot_generated_at": _iso(generated_at),
                "snapshot_age_seconds":  snapshot_age,
                "position_last_contact": _iso(pos.last_contact if pos else None),
                "position_age_seconds":  position_age,
            },
            "position": {
                "lat":             pos.lat,
                "lon":             pos.lon,
                "altitude_m":      pos.altitude_baro,
                "altitude_baro_m": pos.altitude_baro,
                "altitude_geo_m":  pos.altitude_geo,
                "speed_ms":        pos.speed_ms,
                "heading":         pos.heading,
                "on_ground":       pos.on_ground,
                "vertical_rate":   pos.vertical_rate,
                "icao24":          None if is_virtual else pos.icao24,
                "squawk":          xpdr if is_virtual else pos.squawk,
                "last_contact":    _iso(pos.last_contact),
            } if pos else None,
        }

    history_raw = query_flight_history(callsign.upper(), days=7)
    virtual_history = bool(detail and detail.get("detail_mode") == "virtual")
    history = [
        ({
            "date":          str(r.get("event_time") or r.get("snapshot_ts") or "")[:10],
            "status":        r["status"],
            "source":        r.get("source"),
            "observations":  r.get("observation_count") or r.get("raw_observation_rows") or 1,
        } if virtual_history else {
            "date":          str(r.get("event_time") or r.get("snapshot_ts") or "")[:10],
            "status":        r["status"],
            "delay_minutes": r["delay_minutes"],
            "gate":          r["gate"],
            "observations":  r.get("observation_count") or r.get("raw_observation_rows") or 1,
        })
        for r in history_raw[:10]
    ]

    intel = build_flight_intel(
        flight,
        history,
        generated_at=generated_at,
    )
    if detail:
        detail["intel"] = intel

    return {"detail": detail, "history": history, "intel": intel}


# â”€â”€ Radar endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _radar_surface_cache_path(cfg: AppConfig) -> Path:
    from localflight.storage.config import config_path

    code = (cfg.airport_icao or cfg.airport_iata or "airport").upper()
    safe = re.sub(r"[^A-Z0-9_-]+", "_", code).strip("_") or "airport"
    return config_path().parent / "storage" / "radar_surface" / f"{safe}.json"


def _radar_map_context_cache_path(cfg: AppConfig) -> Path:
    from localflight.storage.config import config_path

    code = (cfg.airport_icao or cfg.airport_iata or "airport").upper()
    safe = re.sub(r"[^A-Z0-9_-]+", "_", code).strip("_") or "airport"
    return config_path().parent / "storage" / "radar_map" / f"{safe}.json"


def _radar_terrain_cache_path(cfg: AppConfig) -> Path:
    from localflight.storage.config import config_path

    code = (cfg.airport_icao or cfg.airport_iata or "airport").upper()
    safe = re.sub(r"[^A-Z0-9_-]+", "_", code).strip("_") or "airport"
    return config_path().parent / "storage" / "radar_terrain" / f"{safe}.json"


def _load_local_surface_cache(cfg: AppConfig) -> Optional[Dict[str, Any]]:
    path = _radar_surface_cache_path(cfg)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict) and validate_surface_payload(payload):
        return payload
    return None


def _load_local_map_context_cache(cfg: AppConfig) -> Optional[Dict[str, Any]]:
    path = _radar_map_context_cache_path(cfg)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict) and validate_map_context_payload(payload):
        return payload
    return None


def _load_local_terrain_cache(cfg: AppConfig) -> Optional[Dict[str, Any]]:
    path = _radar_terrain_cache_path(cfg)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict) and validate_terrain_payload(payload):
        return payload
    return None


def _save_local_surface_cache(cfg: AppConfig, payload: Dict[str, Any]) -> None:
    if not validate_surface_payload(payload):
        return
    if payload.get("provider") != AIRPORT_SURFACE_PROVIDER:
        return
    try:
        path = _radar_surface_cache_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.debug("Could not persist radar surface cache: %s", exc)


def _save_local_map_context_cache(cfg: AppConfig, payload: Dict[str, Any]) -> None:
    if not validate_map_context_payload(payload):
        return
    try:
        path = _radar_map_context_cache_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.debug("Could not persist radar map context cache: %s", exc)


def _save_local_terrain_cache(cfg: AppConfig, payload: Dict[str, Any]) -> None:
    if not validate_terrain_payload(payload):
        return
    try:
        path = _radar_terrain_cache_path(cfg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        log.debug("Could not persist radar terrain cache: %s", exc)


def _map_context_cache_fresh(payload: Dict[str, Any]) -> bool:
    generated = str(payload.get("generated_at") or "")
    if not generated:
        return False
    try:
        generated_dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        if generated_dt.tzinfo is None:
            generated_dt = generated_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age_s = (datetime.now(timezone.utc) - generated_dt).total_seconds()
    if str(payload.get("cache_state") or "").strip().lower() == "miss":
        return age_s <= _MAP_CONTEXT_MISS_TTL_S
    return age_s <= _MAP_CONTEXT_CACHE_TTL_S


def _timed_cache_fresh(payload: Dict[str, Any], *, ttl_s: int, miss_ttl_s: int) -> bool:
    generated = str(payload.get("generated_at") or "")
    if not generated:
        return False
    try:
        generated_dt = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        if generated_dt.tzinfo is None:
            generated_dt = generated_dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    age_s = (datetime.now(timezone.utc) - generated_dt).total_seconds()
    if str(payload.get("cache_state") or "").strip().lower() == "miss":
        return age_s <= miss_ttl_s
    return age_s <= ttl_s


def _map_context_miss_payload(
    cfg: AppConfig,
    airport: Any,
    *,
    radius_nm: float,
    error: str = "OSM map context is loading in the background",
) -> Dict[str, Any]:
    return build_map_context_payload(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=float(airport.lat),
        center_lon=float(airport.lon),
        radius_nm=clamp_surface_radius_nm(min(5.0, radius_nm)),
        features=[],
        cache_state="miss",
        error=error,
    )


def _terrain_miss_payload(
    cfg: AppConfig,
    airport: Any,
    *,
    radius_nm: float,
    error: str = "Terrain relief is loading in the background",
) -> Dict[str, Any]:
    return build_terrain_payload(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=float(airport.lat),
        center_lon=float(airport.lon),
        radius_nm=clamp_surface_radius_nm(min(5.0, radius_nm)),
        features=[],
        cache_state="miss",
        error=error,
    )


def _fetch_and_save_map_context(cfg: AppConfig, airport: Any, *, radius_nm: float) -> Dict[str, Any]:
    center_lat = float(airport.lat)
    center_lon = float(airport.lon)
    context_radius = clamp_surface_radius_nm(min(5.0, radius_nm))
    raw = fetch_overpass_map_context(
        lat=center_lat,
        lon=center_lon,
        radius_nm=context_radius,
        timeout_s=_MAP_CONTEXT_TIMEOUT_S,
    )
    features = normalize_overpass_map_context(raw)
    payload = build_map_context_payload(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=context_radius,
        features=features,
        cache_state="fresh",
    )
    _save_local_map_context_cache(cfg, payload)
    return payload


def _fetch_and_save_terrain_context(cfg: AppConfig, airport: Any, *, radius_nm: float) -> Dict[str, Any]:
    payload = fetch_terrain_context(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=float(airport.lat),
        center_lon=float(airport.lon),
        radius_nm=radius_nm,
    )
    _save_local_terrain_cache(cfg, payload)
    return payload


def _schedule_map_context_refresh(cfg: AppConfig, airport: Any, *, radius_nm: float) -> None:
    cache_key = str(_radar_map_context_cache_path(cfg))
    with _map_context_refresh_lock:
        if cache_key in _map_context_refreshing:
            return
        _map_context_refreshing.add(cache_key)

    def _task() -> None:
        try:
            _fetch_and_save_map_context(cfg, airport, radius_nm=radius_nm)
        except Exception as exc:
            log.debug("OSM map context refresh failed: %s", exc)
            try:
                cached = _load_local_map_context_cache(cfg)
                if cached and cached.get("features"):
                    log.debug("Keeping existing OSM map context cache after refresh failure")
                else:
                    _save_local_map_context_cache(
                        cfg,
                        _map_context_miss_payload(
                            cfg,
                            airport,
                            radius_nm=radius_nm,
                            error=f"OSM map context unavailable: {exc}",
                        ),
                    )
            except Exception:
                pass
        finally:
            with _map_context_refresh_lock:
                _map_context_refreshing.discard(cache_key)

    _map_context_executor.submit(_task)


def _schedule_terrain_refresh(cfg: AppConfig, airport: Any, *, radius_nm: float) -> None:
    cache_key = str(_radar_terrain_cache_path(cfg))
    with _terrain_refresh_lock:
        if cache_key in _terrain_refreshing:
            return
        _terrain_refreshing.add(cache_key)

    def _task() -> None:
        try:
            _fetch_and_save_terrain_context(cfg, airport, radius_nm=radius_nm)
        except Exception as exc:
            log.debug("Terrain relief refresh failed: %s", exc)
            try:
                _save_local_terrain_cache(
                    cfg,
                    _terrain_miss_payload(
                        cfg,
                        airport,
                        radius_nm=radius_nm,
                        error=f"Terrain relief unavailable: {exc}",
                    ),
                )
            except Exception:
                pass
        finally:
            with _terrain_refresh_lock:
                _terrain_refreshing.discard(cache_key)

    _terrain_executor.submit(_task)


def _surface_empty_payload(
    *,
    cfg: AppConfig,
    center_lat: float,
    center_lon: float,
    radius_nm: float,
    cache_state: str,
    error: str = "",
) -> Dict[str, Any]:
    return build_surface_payload(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius_nm,
        features=[],
        cache_state=cache_state,
        error=error or None,
        meta={"local_surface_enabled": bool(cfg.radar_surface_enabled)},
    )


def _surface_runway_heading(points: list[Any]) -> float | None:
    if len(points) < 2:
        return None
    first = points[0]
    last = points[-1]
    if not isinstance(first, list | tuple) or not isinstance(last, list | tuple) or len(first) < 2 or len(last) < 2:
        return None
    try:
        lat1, lon1 = float(first[0]), float(first[1])
        lat2, lon2 = float(last[0]), float(last[1])
    except (TypeError, ValueError):
        return None
    y_nm = (lat2 - lat1) * 60.0
    x_nm = (lon2 - lon1) * 60.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
    if abs(x_nm) < 0.00001 and abs(y_nm) < 0.00001:
        return None
    return round((math.degrees(math.atan2(x_nm, y_nm)) + 360.0) % 360.0, 1)


def _surface_feature_center(points: list[Any]) -> tuple[float, float] | None:
    coords: list[tuple[float, float]] = []
    for point in points:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        try:
            coords.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if not coords:
        return None
    return sum(lat for lat, _lon in coords) / len(coords), sum(lon for _lat, lon in coords) / len(coords)


def _with_surface_validation(cfg: AppConfig, payload: Dict[str, Any], airport: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return payload
    center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
    center_lat = _float_or_none(center.get("lat")) or _float_or_none(getattr(airport, "lat", None))
    center_lon = _float_or_none(center.get("lon")) or _float_or_none(getattr(airport, "lon", None))
    if center_lat is None or center_lon is None:
        return payload

    source = str(payload.get("provider") or "").strip()
    validated_by = ["ourairports-center"]
    if source == AIRPORT_SURFACE_PROVIDER:
        validated_by.insert(0, "openstreetmap")
    elif source:
        validated_by.insert(0, source)

    features = []
    runway_count = 0
    building_count = 0
    max_distance = 0.0
    for feature in payload.get("features") or []:
        if not isinstance(feature, dict):
            continue
        item = dict(feature)
        kind = str(item.get("kind") or "").lower()
        points = item.get("points") if isinstance(item.get("points"), list) else []
        midpoint = _surface_feature_center(points)
        distance = None
        if midpoint is not None:
            distance = round(_distance_nm(center_lat, center_lon, midpoint[0], midpoint[1]), 2)
            max_distance = max(max_distance, distance)
        if kind == "runway":
            runway_count += 1
            heading = _surface_runway_heading(points)
            item["validation"] = {
                "validated_by": validated_by,
                "airport_center_distance_nm": distance,
                "heading_deg": heading,
                "confidence": "osm+ourairports" if source == AIRPORT_SURFACE_PROVIDER else "estimated",
            }
        elif kind in {"building", "terminal", "hangar"}:
            building_count += 1
        features.append(item)

    enriched = dict(payload)
    enriched["features"] = features
    meta = dict(enriched.get("meta") if isinstance(enriched.get("meta"), dict) else {})
    meta.update(
        {
            "validation": {
                "validated_by": validated_by,
                "airport_iata": cfg.airport_iata,
                "airport_icao": cfg.airport_icao,
                "runway_count": runway_count,
                "building_count": building_count,
                "max_feature_distance_nm": round(max_distance, 2),
                "note": "Runway geometry comes from OSM when available and is sanity-checked against the OurAirports airport center.",
            }
        }
    )
    enriched["meta"] = meta
    return enriched


@router.get("/api/radar/surface")
def api_radar_surface(
    radius_nm: float = Query(5.0, ge=1.0, le=5.0),
) -> Dict[str, Any]:
    cfg = load_config()
    airport = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)

    if not airport or airport.lat is None or airport.lon is None:
        raise HTTPException(
            status_code=404,
            detail=f"No coordinates for {cfg.airport_iata}/{cfg.airport_icao}",
        )

    center_lat = float(airport.lat)
    center_lon = float(airport.lon)
    radius = clamp_surface_radius_nm(radius_nm)

    surface_mode = str(getattr(cfg, "radar_surface_mode", "relay" if cfg.radar_surface_enabled else "off") or "off").lower()
    if surface_mode == "off":
        return _surface_empty_payload(
            cfg=cfg,
            center_lat=center_lat,
            center_lon=center_lon,
            radius_nm=radius,
            cache_state="disabled",
            error="Airport surface overlay disabled",
        )
    if surface_mode == "estimated":
        return _with_surface_validation(
            cfg,
            build_estimated_surface_payload(
                airport_iata=cfg.airport_iata,
                airport_icao=cfg.airport_icao,
                center_lat=center_lat,
                center_lon=center_lon,
                radius_nm=radius,
                error="Estimated-only surface mode; relay surface cache disabled",
            ),
            airport,
        )

    cached = _load_local_surface_cache(cfg)
    if cached and _timed_cache_fresh(cached, ttl_s=_SURFACE_CACHE_TTL_S, miss_ttl_s=_SURFACE_MISS_TTL_S):
        payload = dict(cached)
        payload["cache_state"] = "fresh"
        payload.setdefault("meta", {})
        if isinstance(payload["meta"], dict):
            payload["meta"]["served_via"] = "local-surface-cache"
        return _with_surface_validation(cfg, payload, airport)

    relay_error = ""
    try:
        response = _req.get(
            relay_airport_surface_url(default_public_relay_url()),
            params={
                "airport_iata": cfg.airport_iata,
                "airport_icao": cfg.airport_icao,
                "lat": center_lat,
                "lon": center_lon,
                "radius_nm": radius,
            },
            headers={"Accept": "application/json"},
            timeout=_SURFACE_RELAY_TIMEOUT_S,
        )
        if response.status_code < 400:
            payload = response.json()
            if isinstance(payload, dict) and validate_surface_payload(payload):
                _save_local_surface_cache(cfg, payload)
                return _with_surface_validation(cfg, payload, airport)
            relay_error = "Relay returned invalid radar surface payload"
        else:
            relay_error = f"Relay surface HTTP {response.status_code}"
    except Exception as exc:
        relay_error = f"Relay surface unavailable: {exc}"

    if cached:
        stale = dict(cached)
        stale["cache_state"] = "stale"
        stale["error"] = relay_error
        stale.setdefault("meta", {})
        if isinstance(stale["meta"], dict):
            stale["meta"]["served_via"] = "local-stale-cache"
        return _with_surface_validation(cfg, stale, airport)

    return _with_surface_validation(cfg, build_estimated_surface_payload(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius,
        error=relay_error or "No airport surface cache available",
    ), airport)


def _radar_surface_payload_for_map(cfg: AppConfig, airport: Any, *, radius_nm: float) -> Dict[str, Any]:
    center_lat = float(airport.lat)
    center_lon = float(airport.lon)
    surface_radius = clamp_surface_radius_nm(min(5.0, radius_nm))
    surface_mode = str(getattr(cfg, "radar_surface_mode", "relay" if cfg.radar_surface_enabled else "off") or "off").lower()
    if surface_mode == "relay":
        try:
            return api_radar_surface(surface_radius)
        except Exception as exc:
            log.debug("Radar map surface lookup failed, using cache/estimate: %s", exc)
    if surface_mode == "estimated":
        return _with_surface_validation(
            cfg,
            build_estimated_surface_payload(
                airport_iata=cfg.airport_iata,
                airport_icao=cfg.airport_icao,
                center_lat=center_lat,
                center_lon=center_lon,
                radius_nm=surface_radius,
                error="Estimated-only surface mode; relay surface cache disabled",
            ),
            airport,
        )
    if surface_mode == "off":
        return _surface_empty_payload(
            cfg=cfg,
            center_lat=center_lat,
            center_lon=center_lon,
            radius_nm=surface_radius,
            cache_state="disabled",
            error="Airport surface overlay disabled",
        )
    cached = _load_local_surface_cache(cfg)
    if cached:
        payload = dict(cached)
        payload["cache_state"] = "stale"
        return _with_surface_validation(cfg, payload, airport)
    return _with_surface_validation(
        cfg,
        build_estimated_surface_payload(
            airport_iata=cfg.airport_iata,
            airport_icao=cfg.airport_icao,
            center_lat=center_lat,
            center_lon=center_lon,
            radius_nm=surface_radius,
            error="No runway/surface cache available",
        ),
        airport,
    )


def _radar_map_context_payload_for_map(cfg: AppConfig, airport: Any, *, radius_nm: float) -> Dict[str, Any]:
    cached = _load_local_map_context_cache(cfg)
    if cached and _map_context_cache_fresh(cached):
        return dict(cached)
    _schedule_map_context_refresh(cfg, airport, radius_nm=radius_nm)
    if cached:
        stale = dict(cached)
        stale["cache_state"] = "stale"
        stale["error"] = "OSM map context is refreshing in the background"
        return stale
    miss = _map_context_miss_payload(cfg, airport, radius_nm=radius_nm)
    _save_local_map_context_cache(cfg, miss)
    return miss


def _radar_terrain_payload_for_map(cfg: AppConfig, airport: Any, *, radius_nm: float) -> Dict[str, Any]:
    cached = _load_local_terrain_cache(cfg)
    if cached and _timed_cache_fresh(cached, ttl_s=_TERRAIN_CACHE_TTL_S, miss_ttl_s=_TERRAIN_MISS_TTL_S):
        return dict(cached)
    _schedule_terrain_refresh(cfg, airport, radius_nm=radius_nm)
    if cached:
        stale = dict(cached)
        stale["cache_state"] = "stale"
        stale["error"] = "Terrain relief is refreshing in the background"
        return stale
    miss = _terrain_miss_payload(cfg, airport, radius_nm=radius_nm)
    _save_local_terrain_cache(cfg, miss)
    return miss


def _radar_map_cache_key(cfg: AppConfig, airport: Any, *, radius_nm: float, terrain: bool, include_map_context: bool) -> str:
    try:
        cfg_sig = json.dumps(asdict(cfg), sort_keys=True, default=str)
    except Exception:
        cfg_sig = repr(cfg)
    return "|".join(
        [
            str(cfg_sig),
            str(getattr(airport, "icao", "") or cfg.airport_icao or ""),
            f"{float(getattr(airport, 'lat', 0.0) or 0.0):.6f}",
            f"{float(getattr(airport, 'lon', 0.0) or 0.0):.6f}",
            f"{float(radius_nm):.2f}",
            "terrain" if terrain else "no-terrain",
            "map-context" if include_map_context else "no-map-context",
            str(id(_radar_surface_payload_for_map)),
            str(id(_radar_map_context_payload_for_map)),
            str(id(_radar_terrain_payload_for_map)),
        ]
    )


def _radar_map_payload_for_request(
    cfg: AppConfig,
    airport: Any,
    *,
    radius_nm: float,
    terrain: bool = False,
    refresh_runways: bool = False,
    include_map_context: bool = True,
) -> Dict[str, Any]:
    cache_key = _radar_map_cache_key(cfg, airport, radius_nm=radius_nm, terrain=terrain, include_map_context=include_map_context)
    now_ts = time.monotonic()
    if not refresh_runways:
        cached = _radar_map_cache.get(cache_key)
        if cached and (now_ts - cached[0]) < _RADAR_MAP_CACHE_TTL_S:
            return dict(cached[1])
    surface = _radar_surface_payload_for_map(cfg, airport, radius_nm=radius_nm)
    map_context = _radar_map_context_payload_for_map(cfg, airport, radius_nm=radius_nm) if include_map_context else None
    terrain_context = _radar_terrain_payload_for_map(cfg, airport, radius_nm=radius_nm) if terrain else None
    payload = build_radar_map(
        airport_iata=cfg.airport_iata,
        airport_icao=(airport.icao or cfg.airport_icao or "").upper(),
        center_lat=float(airport.lat),
        center_lon=float(airport.lon),
        radius_nm=radius_nm,
        surface_payload=surface,
        map_payload=map_context,
        terrain_payload=terrain_context,
        terrain_enabled=terrain,
        refresh_runways=bool(refresh_runways),
    )
    map_state = str((map_context or {}).get("cache_state") or "").strip().lower()
    terrain_state = str((terrain_context or {}).get("cache_state") or "").strip().lower()
    if map_state not in {"miss", "stale"} and terrain_state not in {"miss", "stale"}:
        _radar_map_cache[cache_key] = (now_ts, dict(payload))
    return payload


@router.get("/api/radar/map")
def api_radar_map(
    radius_nm: float = Query(20.0, ge=1.0, le=200.0),
    terrain: bool = Query(False),
    refresh_runways: bool = Query(False),
) -> Dict[str, Any]:
    terrain_enabled = terrain if isinstance(terrain, bool) else False
    refresh_requested = refresh_runways if isinstance(refresh_runways, bool) else False
    cfg = load_config()
    airport = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)
    if not airport or airport.lat is None or airport.lon is None:
        raise HTTPException(
            status_code=404,
            detail=f"No coordinates for {cfg.airport_iata}/{cfg.airport_icao}",
        )
    return _radar_map_payload_for_request(
        cfg,
        airport,
        radius_nm=radius_nm,
        terrain=terrain_enabled,
        refresh_runways=refresh_requested,
    )


@router.get("/api/radar")
def api_radar(
    radius_nm: float = Query(20.0, ge=1.0, le=200.0),  # default 20nm
    traffic: Literal["all", "arrivals", "departures", "final", "ground", "airborne"] = Query("all"),
    min_alt_ft: Optional[float] = Query(None),
    max_alt_ft: Optional[float] = Query(None),
) -> Dict[str, Any]:
    """
    Returns aircraft positions for the radar display.
    Only shows aircraft with a filed flight plan to/from the configured airport.

    For source=real:    live ADS-B Exchange positions when RapidAPI is configured.
                        Falls back to snapshot positions, then live OpenSky.
    For source=virtual: live VATSIM, filtered to dep/arr at configured airport only.
    """
    traffic = traffic if isinstance(traffic, str) else "all"
    min_alt_ft = _float_or_none(min_alt_ft)
    max_alt_ft = _float_or_none(max_alt_ft)
    cfg     = load_config()
    airport = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)

    if not airport or airport.lat is None or airport.lon is None:
        raise HTTPException(
            status_code=404,
            detail=f"No coordinates for {cfg.airport_iata}/{cfg.airport_icao}",
        )

    center_lat  = airport.lat
    center_lon  = airport.lon
    airport_icao = (airport.icao or cfg.airport_icao or "").upper()
    blips: List[Dict[str, Any]] = []
    source_used = "unknown"

    if cfg.source == "virtual":
        try:
            from localflight.sources.web.opensky_radar import bounding_box

            payload = _fetch_vatsim_payload()
            pilots  = payload.get("pilots") or []
            lamin, lomin, lamax, lomax = bounding_box(center_lat, center_lon, radius_nm)
            source_used = "vatsim"

            for pilot in pilots:
                # â”€â”€ Filter: only aircraft going to/from our airport â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                fp  = pilot.get("flight_plan") or {}
                dep = (fp.get("departure") or "").strip().upper()
                arr = (fp.get("arrival")   or "").strip().upper()
                if dep != airport_icao and arr != airport_icao:
                    continue

                plat = pilot.get("latitude")
                plon = pilot.get("longitude")
                if plat is None or plon is None:
                    continue
                try:
                    plat_f = float(plat)
                    plon_f = float(plon)
                except (TypeError, ValueError):
                    continue

                # â”€â”€ Filter: within bounding box â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if not (lamin <= plat_f <= lamax and lomin <= plon_f <= lomax):
                    continue
                if _distance_nm(center_lat, center_lon, plat_f, plon_f) > radius_nm:
                    continue

                callsign = (pilot.get("callsign") or "").strip().upper()
                if not callsign:
                    continue

                alt_ft = float(pilot.get("altitude")    or 0)
                gs_kts = float(pilot.get("groundspeed") or 0)
                hdg    = pilot.get("heading")
                distance_nm = _distance_nm(center_lat, center_lon, plat_f, plon_f)
                aircraft_type = (
                    fp.get("aircraft_short")
                    or fp.get("aircraft_icao")
                    or fp.get("aircraft_faa")
                    or None
                )

                blips.append(enrich_blip_display_fields({
                    "callsign":   callsign,
                    "lat":        plat_f,
                    "lon":        plon_f,
                    "altitude_m": alt_ft * 0.3048 if alt_ft else None,
                    "altitude_ft": round(alt_ft) if alt_ft else None,
                    "heading":    float(hdg) if hdg is not None else None,
                    "track_deg":   float(hdg) if hdg is not None else None,
                    "speed_ms":   gs_kts * 0.514444 if gs_kts else None,
                    "speed_kt":   round(gs_kts) if gs_kts else None,
                    "on_ground":  (alt_ft < 100 and gs_kts < 50),
                    "icao24":     None,
                    "squawk":     pilot.get("transponder") or fp.get("assigned_transponder"),
                    "enriched":   False,
                    "source":     "vatsim",
                    "source_quality": "vatsim-flight-plan" if fp else "vatsim-position",
                    "aircraft_type": aircraft_type,
                    "departure_icao": dep or None,
                    "arrival_icao": arr or None,
                    "flight_rules": fp.get("flight_rules"),
                    "route":      fp.get("route"),
                    "planned_altitude": fp.get("altitude"),
                    "cruise_tas": fp.get("cruise_tas"),
                    "distance_nm": round(distance_nm, 2),
                }))

        except Exception as exc:
            log.warning("VATSIM radar fetch failed: %s", exc)
            raise HTTPException(status_code=503, detail=f"VATSIM radar unavailable: {exc}")

    else:
        # Real source: ADS-B Exchange first, then local snapshot/OpenSky fallback.
        now_ts = time.monotonic()
        provider_radius_nm = _provider_radar_radius_nm(radius_nm)
        adsbx_cache_key = f"{cfg.airport_iata}:{round(provider_radius_nm, 1)}"
        adsbx_raw_count = 0
        try:
            from localflight.sources.web.adsbexchange_client import (
                aircraft_to_blips,
                fetch_aircraft,
                is_available as adsbx_is_available,
            )

            if adsbx_is_available():
                cached = _adsbx_radar_cache.get(adsbx_cache_key)
                ttl_s = _adsbx_radar_cache_ttl_s()
                if cached and (now_ts - cached[0]) < ttl_s:
                    aircraft = cached[1]
                    adsbx_raw_count = len(aircraft)
                    blips = aircraft_to_blips(
                        aircraft=aircraft,
                        center_lat=center_lat,
                        center_lon=center_lon,
                        radius_nm=radius_nm,
                    )
                    source_used = "adsbexchange_cached"
                    log.debug(
                        "ADS-B Exchange radar: serving cached %dnm payload for %.1fnm view",
                        provider_radius_nm,
                        radius_nm,
                    )
                else:
                    lock = _get_radar_fetch_lock(f"adsbx:{adsbx_cache_key}")
                    with lock:
                        now_ts = time.monotonic()
                        cached = _adsbx_radar_cache.get(adsbx_cache_key)
                        if cached and (now_ts - cached[0]) < ttl_s:
                            aircraft = cached[1]
                            adsbx_raw_count = len(aircraft)
                            blips = aircraft_to_blips(
                                aircraft=aircraft,
                                center_lat=center_lat,
                                center_lon=center_lon,
                                radius_nm=radius_nm,
                            )
                            source_used = "adsbexchange_cached"
                        else:
                            source_used = "adsbexchange_live"
                            aircraft = fetch_aircraft(
                                lat=center_lat,
                                lon=center_lon,
                                radius_nm=provider_radius_nm,
                            )
                            adsbx_raw_count = len(aircraft)
                            blips = aircraft_to_blips(
                                aircraft=aircraft,
                                center_lat=center_lat,
                                center_lon=center_lon,
                                radius_nm=radius_nm,
                            )
                            _adsbx_radar_cache[adsbx_cache_key] = (now_ts, aircraft)
                            log.info(
                                "ADS-B Exchange radar: fetched %d raw aircraft at %.1fnm provider radius; %d visible at %.1fnm",
                                adsbx_raw_count,
                                provider_radius_nm,
                                len(blips),
                                radius_nm,
                            )
        except Exception as exc:
            log.warning("ADS-B Exchange live radar unavailable, trying fallback: %s", exc)

        flights: List[Flight] = []
        if not blips:
            flights, _ = _load_latest_flights(cfg.airport_iata)
            source_used = "snapshot_positions"

        for f in flights:
            if f.position and f.position.lat is not None:
                blips.append(enrich_blip_display_fields({
                    "callsign":      f.callsign,
                    "lat":           f.position.lat,
                    "lon":           f.position.lon,
                    "altitude_m":    f.position.altitude_baro,
                    "heading":       f.position.heading,
                    "track_deg":     f.position.heading,
                    "speed_ms":      f.position.speed_ms,
                    "vertical_rate": f.position.vertical_rate,
                    "on_ground":     f.position.on_ground,
                    "icao24":        f.position.icao24,
                    "squawk":        f.position.squawk,
                    "flight_number": f.flight_number,
                    "airline_name":  f.airline.name,
                    "airline_iata":  f.airline.iata,
                    "airline_icao":  f.airline.icao,
                    "codeshares":    list(f.codeshares),
                    "sold_as":       list(f.sold_as),
                    "operating_callsign": f.operating_callsign,
                    "marketing_flight_number": f.marketing_flight_number,
                    "identity_source": f.identity_source,
                    "status":        f.status.value,
                    "source":        f.source,
                    "aircraft_type": f.aircraft_type,
                    "departure_icao": f.origin.icao if f.origin else None,
                    "arrival_icao": f.destination.icao if f.destination else None,
                    "distance_nm": round(_distance_nm(center_lat, center_lon, f.position.lat, f.position.lon), 2),
                    "source_quality": "snapshot-position",
                    "enriched":      True,
                }))

        # Fallback to live OpenSky if snapshot has no positions.
        # Cached per airport for 60 s so that multiple tabs/mobile polling
        # don't each trigger a live fetch on every 15-second radar poll.
        if not blips:
            cache_key = f"{cfg.airport_iata}:{round(radius_nm, 1)}"
            cached = _opensky_radar_cache.get(cache_key)
            now_ts  = time.monotonic()
            if cached and (now_ts - cached[0]) < _OPENSKY_RADAR_CACHE_TTL_S:
                blips = cached[1]
                source_used = "opensky_live_cached"
                log.debug("OpenSky radar: serving cached blips for %s", cache_key)
            else:
                lock = _get_radar_fetch_lock(f"opensky:{cache_key}")
                with lock:
                    now_ts = time.monotonic()
                    cached = _opensky_radar_cache.get(cache_key)
                    if cached and (now_ts - cached[0]) < _OPENSKY_RADAR_CACHE_TTL_S:
                        blips = cached[1]
                        source_used = "opensky_live_cached"
                        log.debug("OpenSky radar: serving cached blips for %s", cache_key)
                    else:
                        log.info("No position data in snapshot â€” falling back to live OpenSky fetch")
                        source_used = "opensky_live"
                        try:
                            from localflight.sources.web.opensky_radar import fetch_radar_blips
                            raw_blips = fetch_radar_blips(
                                lat=center_lat, lon=center_lon, radius_nm=radius_nm,
                            )
                            for b in raw_blips:
                                b["enriched"] = False
                                b["source"] = b.get("source") or "opensky"
                                b["source_quality"] = "opensky-state-vector"
                            blips = [enrich_blip_display_fields(b) for b in raw_blips]
                            _opensky_radar_cache[cache_key] = (now_ts, blips)
                        except Exception as exc:
                            log.warning("OpenSky live radar fallback failed: %s", exc)
                            raise HTTPException(status_code=503, detail=f"Radar data unavailable: {exc}")

    ground_filtered = 0
    airborne_filtered = 0
    radar_mode = "surface" if _surface_radar_mode(radius_nm) else "airborne"
    if radar_mode != "surface":
        blips, ground_filtered = _filter_airborne_radar_blips(blips)
    try:
        map_payload = _radar_map_payload_for_request(cfg, airport, radius_nm=radius_nm, terrain=False, include_map_context=False)
        runways = map_payload.get("runways") if isinstance(map_payload.get("runways"), list) else []
    except Exception as exc:
        log.debug("Radar classification runway map unavailable: %s", exc)
        runways = []
    blips = _annotate_radar_blips(blips, airport_icao=airport_icao, runways=runways)
    before_user_filter_count = len(blips)
    blips = _filter_radar_blips_for_view(
        blips,
        traffic=traffic,
        min_alt_ft=min_alt_ft,
        max_alt_ft=max_alt_ft,
    )

    adsb_source = source_used.startswith("adsbexchange")

    return {
        "center":    {"lat": center_lat, "lon": center_lon},
        "radius_nm": radius_nm,
        "source":    source_used,
        "refresh_after_s": _radar_refresh_after_s(source_used),
        "count":     len(blips),
        "radar_mode": radar_mode,
        "ground_filtered": ground_filtered,
        "airborne_filtered": airborne_filtered,
        "hidden_ground_count": ground_filtered,
        "hidden_airborne_count": airborne_filtered,
        "traffic_filter": traffic,
        "altitude_filter": {"min_alt_ft": min_alt_ft, "max_alt_ft": max_alt_ft},
        "user_filtered_count": before_user_filter_count - len(blips),
        "provider_radius_nm": provider_radius_nm if cfg.source != "virtual" and adsb_source else radius_nm,
        "raw_provider_count": adsbx_raw_count if cfg.source != "virtual" and adsb_source else len(blips),
        "blips":     blips,
    }

# â”€â”€ History endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
 
@router.get("/api/history")
def api_history(
    hours:     int = Query(24,  ge=1,   le=2160),
    direction: str = Query("both"),
    limit:     int = Query(100, ge=1,   le=1000),
    status:    Optional[str] = Query(None, max_length=32),
    callsign:  Optional[str] = Query(None, max_length=16),
    airline_iata: Optional[str] = Query(None, max_length=3),
) -> Dict[str, Any]:
    """
    Returns recent deduped flight movements from the local SQLite database.
 
    hours:     how many hours back to look (default 24, max 720 = 30 days)
    direction: "dep", "arr", or "both"
    limit:     max rows to return
 
    Response:
    {
      "airport_iata": "ZRH",
      "hours":        24,
      "count":        42,
      "raw_observation_rows": 96,
      "flights":      [ { ...row... }, ... ]
    }
    """
    from localflight.storage.history import query_recent
 
    cfg = load_config()
 
    dir_filter = None
    direction_clean = direction.lower().strip()
    if direction_clean == "dep":
        dir_filter = "DEP"
    elif direction_clean == "arr":
        dir_filter = "ARR"
 
    rows = query_recent(
        airport_iata=cfg.airport_iata,
        hours=hours,
        direction=dir_filter,
        limit=limit,
        status=status,
        callsign=callsign,
        airline_iata=airline_iata,
    )
 
    raw_observation_rows = sum(int(row.get("observation_count") or 1) for row in rows)

    return {
        "airport_iata": cfg.airport_iata,
        "hours":        hours,
        "direction":    direction,
        "filters": {
            "status": status or "",
            "callsign": (callsign or "").upper().strip(),
            "airline_iata": (airline_iata or "").upper().strip(),
        },
        "count":        len(rows),
        "movement_count": len(rows),
        "raw_observation_rows": raw_observation_rows,
        "flights":      rows,
    }
 
 
@router.get("/api/history/flight")
def api_history_flight(
    callsign: str = Query(..., min_length=2, max_length=10),
    days:     int = Query(7, ge=1, le=90),
) -> Dict[str, Any]:
    """
    Returns deduped movement history for a callsign over the last N days.
    Useful for seeing if a flight is consistently on time or delayed.
    """
    from localflight.storage.history import query_flight_history
 
    rows = query_flight_history(callsign=callsign.upper().strip(), days=days)
 
    return {
        "callsign": callsign.upper().strip(),
        "days":     days,
        "count":    len(rows),
        "movement_count": len(rows),
        "raw_observation_rows": sum(int(row.get("observation_count") or 1) for row in rows),
        "flights":  rows,
    }
 
 
@router.get("/api/history/summary")
def api_history_summary(
    hours: int = Query(720, ge=1, le=2160),
    direction: str = Query("both"),
    status: Optional[str] = Query(None, max_length=32),
    callsign: Optional[str] = Query(None, max_length=16),
    airline_iata: Optional[str] = Query(None, max_length=3),
) -> Dict[str, Any]:
    """Aggregated stats: top airlines, routes, aircraft, on-time rate."""
    from localflight.storage.history import query_summary
    cfg = load_config()
    dir_filter = None
    direction_clean = direction.lower().strip()
    if direction_clean == "dep":
        dir_filter = "DEP"
    elif direction_clean == "arr":
        dir_filter = "ARR"
    return query_summary(
        airport_iata=cfg.airport_iata,
        hours=hours,
        direction=dir_filter,
        status=status,
        callsign=callsign,
        airline_iata=airline_iata,
    )


@router.get("/api/history/stats")
def api_history_stats() -> Dict[str, Any]:
    """
    Returns stats about the local history database.
    Useful for the settings page to show DB size and age.
    """
    from localflight.storage.history import db_stats
    return db_stats()

# â”€â”€ METAR endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
 
@router.get("/api/metar")
def api_metar(
    icao: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """
    Returns decoded METAR for the configured airport (or ?icao=XXXX override).
    Cached for 30 minutes. Free, no API key required.
 
    Response includes:
      raw_text        - original METAR string (for radar display)
      decoded_summary - human readable string (for FIDS display)
      flight_cat      - VFR / MVFR / IFR / LIFR
      flight_cat_color- hex color for the category
      wind_dir_deg, wind_speed_kt, wind_gust_kt
      visibility_m, ceiling_ft
      temp_c, dewpoint_c, altimeter_hpa
      weather_*      - Local Flight semantic weather mood/icon fields
    """
    from localflight.sources.web.metar_client import decode_raw_metar, fetch_metar

    cfg        = load_config()
    icao_param = icao if isinstance(icao, str) else None
    icao_code  = (icao_param or cfg.airport_icao or "LSZH").upper().strip()

    data = None
    if not icao_param and (cfg.source or "").strip().lower() == "virtual":
        try:
            vatsim_client = _vatsim_client_module()
            raw_vatsim_metar = vatsim_client.vatsim_metar_for_airport(_fetch_vatsim_payload(), airport_icao=icao_code)
            if raw_vatsim_metar:
                data = decode_raw_metar(icao_code, raw_vatsim_metar, source="vatsim")
        except Exception as exc:
            log.debug("VATSIM METAR/ATIS weather unavailable, falling back to real METAR: %s", exc)

    if data is None:
        data = fetch_metar(icao_code)
    if not data:
        raise HTTPException(
            status_code=503,
            detail=f"METAR unavailable for {icao_code}",
        )
    return data

# â”€â”€ Admin endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
 
@router.get("/api/admin/system")
def api_admin_system() -> Dict[str, Any]:
    """System info for the admin hub."""
    import platform
    import sys
    import time
    from pathlib import Path

    try:
        from importlib.metadata import version as _pkg_version
        _ver = _pkg_version("localflight")
    except Exception:
        _ver = "0.2.8"

    result: Dict[str, Any] = {
        "version":  _ver,
        "python":   sys.version.split()[0],
        "platform": platform.system() + " " + platform.release(),
    }
 
    # Uptime via process start time
    try:
        import psutil
        proc    = psutil.Process()
        uptime  = int(time.time() - proc.create_time())
        h, rem  = divmod(uptime, 3600)
        m, s    = divmod(rem, 60)
        result["uptime"]    = f"{h}h {m}m {s}s"
        result["memory_mb"] = round(proc.memory_info().rss / 1_048_576, 1)
        result["cpu_pct"]   = round(proc.cpu_percent(interval=0.1), 1)
    except ImportError:
        result["uptime"]    = "install psutil for uptime"
        result["memory_mb"] = None
        result["cpu_pct"]   = None
    except Exception as exc:
        result["uptime"]    = str(exc)
 
    # Snapshot directory
    try:
        result["snapshot_dir"] = str(snapshot_store_root())
    except Exception:
        result["snapshot_dir"] = "~/.localflight/storage/data"

    # Install fingerprint. The raw relay token is not exposed through Admin/mobile APIs.
    try:
        from localflight.storage.install import get_install_fingerprint
        result["install_id"] = get_install_fingerprint()
    except Exception:
        result["install_id"] = None

    try:
        from localflight.sources.web.aviationstack_client import get_usage_stats

        usage = get_usage_stats(load_config().source)
        managed = usage.get("managed") or {}
        community = usage.get("community") or {}
        cost_estimate = usage.get("cost_estimate") or {}
        shared_snapshot = usage.get("shared_snapshot") or managed.get("shared_snapshot") or community.get("shared_snapshot") or {}
        result["client"] = {
            "mode": usage.get("active_mode") or usage.get("mode") or "virtual",
            "relay_url": managed.get("relay_url") or community.get("relay_url"),
            "activation_token_present": bool(managed.get("token_present")),
            "activation_token_prefix": managed.get("token_prefix") or "",
            "community_key_present": bool(community.get("key_present")),
            "managed_verified": bool(managed.get("status_ok")),
            "managed_status": managed.get("status_error") or "",
            "diagnostics_mode": load_config().diagnostics_mode,
            "cost_estimate": cost_estimate,
            "shared_snapshot": shared_snapshot,
        }
    except Exception:
        result["client"] = {
            "mode": "unknown",
            "relay_url": None,
            "activation_token_present": False,
            "activation_token_prefix": "",
            "community_key_present": False,
            "managed_verified": False,
            "managed_status": "",
            "diagnostics_mode": load_config().diagnostics_mode,
            "cost_estimate": {
                "enabled": False,
                "usage_model": "unknown",
                "dates_touched": 0,
                "page_size": 100,
                "recent_avg_pages_per_direction": 0.0,
                "estimated_calls_per_refresh": 0,
                "estimated_calls_per_month": 0,
                "refreshes_per_30_days": 0,
                "cadence_warning": "",
            },
            "shared_snapshot": {},
        }

    return result
 
 
@router.get("/api/admin/budget")
def api_admin_budget() -> Dict[str, Any]:
    """User-facing budget status for the admin hub."""
 
    result: Dict[str, Any] = {}
    cfg = load_config()
    result["client_polling_policy"] = client_polling_policy()
 
    try:
        from localflight.sources.web.aviationstack_client import get_usage_stats, schedule_policy
        usage_stats = get_usage_stats(cfg.source)
        result["aviationstack"] = usage_stats
        result["schedule_policy"] = schedule_policy(cfg.source)
        result["shared_schedule_budget"] = usage_stats.get("shared_schedule_budget") if isinstance(usage_stats, dict) else {}
        result["schedule_access_budget"] = usage_stats.get("schedule_access_budget") if isinstance(usage_stats, dict) else {}
    except Exception as exc:
        result["aviationstack"] = {"error": str(exc)}
        result["schedule_policy"] = _schedule_policy_for_config(cfg.source)
        result["shared_schedule_budget"] = {"available": False, "error": "Shared budget unavailable"}
        result["schedule_access_budget"] = {}
 
    return result
 
 
@router.get("/api/admin/connections")
def api_admin_connections() -> Dict[str, Any]:
    """WebSocket connection count and device ping status."""
    count = 0
    try:
        import localflight.ui.server as srv
        mgr = getattr(srv, "_ws_manager", None)
        if mgr:
            count = len(mgr._connections)
    except Exception:
        pass
 
    # Matrix last seen (from ping endpoint log)
    matrix_last_seen = None
    try:
        from localflight.storage.config import config_path
        ping_path = config_path().parent / "device_pings.json"
        if ping_path.exists():
            import json as _json
            pings = _json.loads(ping_path.read_text())
            matrix_last_seen = pings.get("matrix")
    except Exception:
        pass

    matrix_devices: List[Dict[str, Any]] = []
    matrix_last_seen_v2 = None
    try:
        from datetime import timedelta

        store = _load_matrix_store()
        now = datetime.now(timezone.utc)
        online_cutoff = now - timedelta(minutes=15)
        latest_dt = None
        for raw_device in store.get("devices", []):
            if not isinstance(raw_device, dict):
                continue
            last_seen = str(raw_device.get("last_seen") or "")
            last_dt = None
            try:
                last_dt = datetime.fromisoformat(last_seen)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
            except Exception:
                last_dt = None
            if last_dt and (latest_dt is None or last_dt > latest_dt):
                latest_dt = last_dt
                matrix_last_seen_v2 = last_seen
            brand = str(raw_device.get("brand") or raw_device.get("vendor") or "").strip()
            model = str(raw_device.get("model") or raw_device.get("hardware") or raw_device.get("label") or "LED matrix").strip()
            hardware_name = str(raw_device.get("hardware_name") or " ".join(part for part in (brand, model) if part) or model).strip()
            renderers = raw_device.get("renderers") if isinstance(raw_device.get("renderers"), list) else []
            configured_panel_w = int(raw_device.get("configured_panel_w") or raw_device.get("panel_w") or 0)
            configured_panel_h = int(raw_device.get("configured_panel_h") or raw_device.get("panel_h") or 0)
            actual_panel_w = int(raw_device.get("actual_panel_w") or raw_device.get("panel_w") or configured_panel_w)
            actual_panel_h = int(raw_device.get("actual_panel_h") or raw_device.get("panel_h") or configured_panel_h)
            geometry_mismatch = bool(raw_device.get("geometry_mismatch")) or (
                bool(configured_panel_w and actual_panel_w and configured_panel_w != actual_panel_w)
                or bool(configured_panel_h and actual_panel_h and configured_panel_h != actual_panel_h)
            )
            matrix_devices.append(
                {
                    "device_id": str(raw_device.get("device_id") or ""),
                    "label": str(raw_device.get("label") or hardware_name),
                    "kind": str(raw_device.get("kind") or "led_matrix"),
                    "brand": brand,
                    "model": model,
                    "hardware_name": hardware_name,
                    "panel_w": actual_panel_w,
                    "panel_h": actual_panel_h,
                    "configured_panel_w": configured_panel_w,
                    "configured_panel_h": configured_panel_h,
                    "actual_panel_w": actual_panel_w,
                    "actual_panel_h": actual_panel_h,
                    "display_panels": int(raw_device.get("display_panels") or 0),
                    "geometry_mismatch": geometry_mismatch,
                    "geometry_warning": str(raw_device.get("geometry_warning") or ""),
                    "firmware": str(raw_device.get("firmware") or ""),
                    "renderer_revision": str(raw_device.get("renderer_revision") or ""),
                    "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
                    "renderer_status": "current" if str(raw_device.get("renderer_revision") or "").strip() == _MATRIX_EXPECTED_RENDERER_REV else ("unknown" if not str(raw_device.get("renderer_revision") or "").strip() else "stale"),
                    "renderers": [str(item) for item in renderers],
                    "assigned_config_id": str(raw_device.get("assigned_config_id") or ""),
                    "last_seen": last_seen,
                    "online": bool(last_dt and last_dt >= online_cutoff),
                }
            )
        matrix_devices.sort(key=lambda item: str(item.get("last_seen") or ""), reverse=True)
    except Exception:
        matrix_devices = []

    if matrix_last_seen_v2:
        if matrix_last_seen:
            try:
                old_dt = datetime.fromisoformat(str(matrix_last_seen))
                new_dt = datetime.fromisoformat(str(matrix_last_seen_v2))
                if old_dt.tzinfo is None:
                    old_dt = old_dt.replace(tzinfo=timezone.utc)
                if new_dt.tzinfo is None:
                    new_dt = new_dt.replace(tzinfo=timezone.utc)
                if new_dt > old_dt:
                    matrix_last_seen = matrix_last_seen_v2
            except Exception:
                matrix_last_seen = matrix_last_seen_v2
        else:
            matrix_last_seen = matrix_last_seen_v2

    matrix_hardware_counts: Dict[str, int] = {}
    for device in matrix_devices:
        name = str(device.get("hardware_name") or device.get("model") or "LED matrix")
        matrix_hardware_counts[name] = matrix_hardware_counts.get(name, 0) + 1
    matrix_online_count = sum(1 for device in matrix_devices if device.get("online"))
    matrix_device_count = len(matrix_devices)

    companions: List[Dict[str, Any]] = []
    companion_last_seen = None
    try:
        from datetime import timedelta

        raw = _load_companion_presence()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=_COMPANION_RETENTION_DAYS)
        dirty = False

        for companion_id, entry in list(raw.items()):
            if not isinstance(entry, dict):
                dirty = True
                raw.pop(companion_id, None)
                continue
            last_seen = str(entry.get("last_seen") or "")
            try:
                last_dt = datetime.fromisoformat(last_seen)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
            except Exception:
                last_dt = None
            if not last_dt or last_dt < cutoff:
                dirty = True
                raw.pop(companion_id, None)
                continue

            server_platform = entry.get("server_platform") or "Unknown server"
            mobile_os = entry.get("mobile_os") or "Unknown mobile"
            platform_pair = f"{server_platform} / {mobile_os}"
            companions.append(
                {
                    "companion_id": str(entry.get("companion_id") or companion_id),
                    "client_name": str(entry.get("client_name") or "Local Flight Companion"),
                    "app_version": str(entry.get("app_version") or ""),
                    "mobile_os": mobile_os,
                    "device_type": str(entry.get("device_type") or "unknown"),
                    "platform_pair": platform_pair,
                    "last_seen": last_seen,
                }
            )
        if dirty:
            _save_companion_presence(raw)
        companions.sort(key=lambda item: str(item.get("last_seen") or ""), reverse=True)
        if companions:
            companion_last_seen = companions[0]["last_seen"]
    except Exception:
        companions = []

    return {
        "count":            count,
        "matrix_last_seen": matrix_last_seen,
        "matrix_device_count": matrix_device_count,
        "matrix_online_count": matrix_online_count,
        "matrix_devices": matrix_devices[:10],
        "matrix_hardware_counts": matrix_hardware_counts,
        "companion_last_seen": companion_last_seen,
        "companion_count": len(companions),
        "companions": companions[:10],
    }


def _mobile_summary_payload() -> Dict[str, Any]:
    """Compact host summary tuned for the mobile companion shell."""
    try:
        state = api_health()
    except Exception:
        state = {}

    try:
        config = api_config()
    except Exception:
        config = {}

    try:
        system = api_admin_system()
    except Exception:
        system = {}

    try:
        connections = api_admin_connections()
    except Exception:
        connections = {}

    try:
        updates = api_admin_updates()
    except Exception:
        updates = {}

    try:
        budget = api_admin_budget()
    except Exception:
        budget = {}

    try:
        scheduler = api_admin_scheduler_status()
    except Exception:
        scheduler = {}

    metar = None
    try:
        metar = api_metar()
    except Exception:
        metar = None

    return {
        "state": state,
        "config": config,
        "system": system,
        "connections": connections,
        "updates": updates,
        "budget": budget,
        "scheduler": scheduler,
        "metar": metar,
    }


@router.get("/api/mobile/summary")
def api_mobile_summary() -> Dict[str, Any]:
    """Compact mobile-companion summary for control and glance views."""
    return _mobile_summary_payload()
 
 
@router.get("/api/admin/scheduler")
def api_admin_scheduler_status() -> Dict[str, Any]:
    """Scheduler thread status for desktop/mobile controls."""
    from localflight.scheduler.control import scheduler_status
    return scheduler_status()


_RESTART_COOLDOWN_S = 60  # prevent rapid-fire thread restarts from multiple clients


@router.post("/api/admin/scheduler/restart")
def api_admin_scheduler_restart() -> Dict[str, Any]:
    """
    Stop the sleeping scheduler loop, reload config/env, and start a fresh cycle.
    Rate-limited to one restart per 60 seconds. The actual fetch is also gated
    by run_snapshot_job._fetch_is_due â€” a restart never burns an API call if the
    snapshot is already fresh.
    """
    state = load_state()
    if state.last_attempt_utc:
        try:
            from datetime import timezone as _tz
            last = datetime.fromisoformat(state.last_attempt_utc.replace("Z", "+00:00"))
            age_s = (datetime.now(_tz.utc) - last).total_seconds()
            if age_s < _RESTART_COOLDOWN_S:
                return {
                    "ok": False,
                    "status": "rate_limited",
                    "message": f"Last fetch was {int(age_s)}s ago â€” wait {int(_RESTART_COOLDOWN_S - age_s)}s before restarting.",
                }
        except Exception:
            pass

    from localflight.ui.events import restart_scheduler_and_notify
    return restart_scheduler_and_notify("manual")


@router.post("/api/admin/ping")
def api_admin_ping(
    device:  str = Query(...),
    version: str = Query("unknown"),
) -> Dict[str, Any]:
    """
    Device ping endpoint â€” called by matrix client on boot and periodically.
    Records last-seen timestamp for each device.
    """
    import json as _json
    from datetime import datetime, timezone
    from localflight.storage.config import config_path
 
    ping_path = config_path().parent / "device_pings.json"
    try:
        pings = _json.loads(ping_path.read_text()) if ping_path.exists() else {}
    except Exception:
        pings = {}
 
    pings[device] = datetime.now(timezone.utc).isoformat()
    try:
        ping_path.write_text(_json.dumps(pings, indent=2))
    except Exception:
        pass

    log.info("Device ping: %s v%s", device, version)
    return {"ok": True, "device": device, "recorded_at": pings[device]}


class CompanionCheckinIn(BaseModel):
    companion_id: str = Field(..., min_length=8, max_length=80)
    client_name: str = Field("Local Flight Companion", max_length=80)
    app_version: str = Field("", max_length=40)
    mobile_os: str = Field(..., min_length=3, max_length=120)
    device_type: str = Field("unknown", max_length=20)


@router.post("/api/admin/companion/checkin")
def api_admin_companion_checkin(body: CompanionCheckinIn) -> Dict[str, Any]:
    import platform

    now = datetime.now(timezone.utc).isoformat()
    server_platform = platform.system() + " " + platform.release()
    entry = {
        "companion_id": body.companion_id.strip(),
        "client_name": body.client_name.strip() or "Local Flight Companion",
        "app_version": body.app_version.strip(),
        "mobile_os": body.mobile_os.strip(),
        "device_type": body.device_type.strip() or "unknown",
        "last_seen": now,
        "server_platform": server_platform,
    }
    companions = _load_companion_presence()
    companions[entry["companion_id"]] = entry
    _save_companion_presence(companions)

    server_install_id = None
    try:
        from localflight.storage.install import get_install_fingerprint

        server_install_id = get_install_fingerprint()
    except Exception:
        server_install_id = None

    log.info(
        "Companion check-in: %s %s %s",
        entry["companion_id"],
        entry["mobile_os"],
        entry["app_version"] or "unknown",
    )
    return {
        "ok": True,
        "recorded_at": now,
        "server_platform": server_platform,
        "server_install_id": server_install_id,
        "platform_pair": f"{server_platform} / {entry['mobile_os']}",
    }


@router.delete("/api/admin/companion")
def api_admin_companion_reset() -> Dict[str, Any]:
    """Clear remembered mobile companion check-ins for this local server."""
    companions = _load_companion_presence()
    removed = len(companions) if isinstance(companions, dict) else 0
    reset_at = datetime.now(timezone.utc).isoformat()
    _save_companion_presence({})
    log.info("Companion connections reset: %s remembered device(s) cleared", removed)
    return {"ok": True, "removed": removed, "reset_at": reset_at}

# â”€â”€ Traffic / request log â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/admin/requests")
def api_admin_requests(
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(200, ge=1, le=500),
    client_type: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Recent HTTP request log for the Traffic Hub."""
    if not _network_tools_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    from localflight.storage.request_log import query_recent, query_summary
    return {
        "requests": query_recent(hours=hours, limit=limit, client_type=client_type or None),
        "summary":  query_summary(hours=hours),
    }


# â”€â”€ Update check â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/admin/updates")
def api_admin_updates() -> Dict[str, Any]:
    """Check GitHub releases for a newer version. Cached 1 hour."""
    import time

    REPO = "tr3y4rch/local-flight"
    CACHE_TTL = 3600

    try:
        from importlib.metadata import version as _pkg_version
        current = _pkg_version("localflight")
    except Exception:
        current = "0.2.8"

    # Simple in-process cache to avoid hammering GitHub API
    cache = getattr(api_admin_updates, "_cache", None)
    if cache and time.time() - cache["ts"] < CACHE_TTL:
        cached = dict(cache)
        cached["current"] = current
        return cached

    try:
        import requests as _req
        r = _req.get(
            f"https://api.github.com/repos/{REPO}/releases/latest",
            headers={"Accept": "application/vnd.github+json"},
            timeout=6,
        )
        if r.status_code == 404:
            result: Dict[str, Any] = {"current": current, "latest": None, "update_available": False, "url": None}
        elif r.status_code != 200:
            result = {"current": current, "latest": None, "update_available": False, "url": None, "error": f"GitHub {r.status_code}"}
        else:
            data   = r.json()
            latest = (data.get("tag_name") or "").lstrip("v")
            url    = data.get("html_url")
            try:
                from packaging.version import Version
                newer = Version(latest) > Version(current)
            except Exception:
                newer = latest != current and bool(latest)
            result = {"current": current, "latest": latest, "update_available": newer, "url": url}
    except Exception as exc:
        result = {"current": current, "latest": None, "update_available": False, "url": None, "error": str(exc)}

    result["ts"] = time.time()
    api_admin_updates._cache = result  # type: ignore[attr-defined]
    return result



# â”€â”€ User feedback / bug report â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class FeedbackIn(BaseModel):
    title:       str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=4000)
    client_context: str = Field("", max_length=2000)


def _feedback_response(result: Dict[str, Any], *, default_message: str) -> Dict[str, Any]:
    message = str(result.get("message") or "").strip()
    if not message:
        if result.get("deduped"):
            message = "Report already received recently; no duplicate Linear issue was created."
        else:
            message = default_message
    return {
        "ok": True,
        "url": result.get("url"),
        "team": result.get("team"),
        "deduped": bool(result.get("deduped", False)),
        "message": message,
    }


@router.post("/api/feedback")
def api_submit_feedback(body: FeedbackIn) -> Dict[str, Any]:
    """Submit a bug report / feedback to the Local Flight developer's Linear board."""
    from localflight.sources.web.bug_reporter import submit_report
    result = submit_report(body.title, body.description, client_context=body.client_context)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result.get("error", "Submission failed"))
    return _feedback_response(result, default_message="Report sent. Thank you.")


class FeedbackCrashIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    traceback: str = Field("", max_length=5000)
    context: str = Field("mobile", max_length=120)
    client_context: str = Field("", max_length=2000)


@router.post("/api/feedback/crash")
def api_submit_feedback_crash(body: FeedbackCrashIn) -> Dict[str, Any]:
    """Submit an automatic crash report to the developer's Linear board."""
    from localflight.sources.web.bug_reporter import submit_crash

    result = submit_crash(
        body.message,
        traceback_str=body.traceback,
        context=body.context or "mobile",
        client_context=body.client_context,
    )
    if not result["ok"]:
        error = result.get("error", "Crash submission failed")
        lower_error = error.lower()
        if "duplicate" in lower_error:
            status = 409
        elif "disabled" in lower_error:
            status = 403
        else:
            status = 502
        raise HTTPException(status_code=status, detail=error)
    return _feedback_response(result, default_message="Crash report sent.")


# Matrix config -------------------------------------------------------------

_MATRIX_PALETTES: Dict[str, Dict[str, Any]] = {
    "pax_blue": {
        "id": "pax_blue",
        "label": "PAX Blue",
        "description": "Crisp passenger FIDS with blue headers, white routes, and soft cyan icons.",
        "colors": {"primary": "#1d8cff", "text": "#f6fbff", "dim": "#2c5f92", "warning": "#ffbd45", "danger": "#ff4d5f", "accent": "#65e7ff"},
    },
    "solari_amber": {
        "id": "solari_amber",
        "label": "Solari Amber",
        "description": "Warm split-flap amber with cream text and red disruption states.",
        "colors": {"primary": "#ffad2f", "text": "#ffe6a8", "dim": "#8c5a12", "warning": "#ffe15c", "danger": "#ff5538", "accent": "#ffd06c"},
    },
    "tower_scope": {
        "id": "tower_scope",
        "label": "Tower Scope",
        "description": "Controller-room green with cyan aircraft hints and amber advisories.",
        "colors": {"primary": "#38ff75", "text": "#d9ffe6", "dim": "#1b7a3c", "warning": "#ffd84a", "danger": "#ff4c4c", "accent": "#4deaff"},
    },
    "vatsim_scope": {
        "id": "vatsim_scope",
        "label": "VATSIM Scope",
        "description": "Virtual ops palette with radar green, phosphor text, and blue route details.",
        "colors": {"primary": "#74ff5f", "text": "#d8ffd0", "dim": "#2b7a2f", "warning": "#ffe066", "danger": "#ff5b5b", "accent": "#6bdcff"},
    },
    "night_ops": {
        "id": "night_ops",
        "label": "Night Ops",
        "description": "Dim ramp-room blue, teal text, and restrained gold highlights.",
        "colors": {"primary": "#4bb8ff", "text": "#d8f7ff", "dim": "#27506e", "warning": "#f4c95d", "danger": "#ff5d7a", "accent": "#49f0c8"},
    },
    "sunset_terminal": {
        "id": "sunset_terminal",
        "label": "Sunset Terminal",
        "description": "Punchy magenta-orange board for a warmer, showier installation.",
        "colors": {"primary": "#ff7a3d", "text": "#fff2e6", "dim": "#8e3f55", "warning": "#ffd166", "danger": "#ff3864", "accent": "#ff4fd8"},
    },
    "ice_white": {
        "id": "ice_white",
        "label": "Ice White",
        "description": "Bright white airport signage with blue accents and strong disruption color.",
        "colors": {"primary": "#bde9ff", "text": "#ffffff", "dim": "#6a8195", "warning": "#ffd35a", "danger": "#ff5252", "accent": "#66d9ff"},
    },
    "crt": {
        "id": "crt",
        "label": "CRT Amber",
        "description": "Warm CRT-style amber phosphor with soft warning highlights.",
        "colors": {"primary": "#ffcc44", "text": "#ffeeaa", "dim": "#7a5000", "warning": "#ffdd00", "danger": "#ff4020", "accent": "#ffaa00"},
    },
    "neon": {
        "id": "neon",
        "label": "Neon Green",
        "description": "High-energy green LED look for showpiece installs.",
        "colors": {"primary": "#00ff50", "text": "#dcffdc", "dim": "#007a28", "warning": "#aaff00", "danger": "#ff4040", "accent": "#aaff00"},
    },
    "amber": {
        "id": "amber",
        "label": "Amber",
        "description": "Classic warm amber board with gentle cream text.",
        "colors": {"primary": "#ffae2e", "text": "#ffebb4", "dim": "#7e5416", "warning": "#ffdf55", "danger": "#ff5738", "accent": "#ffc56b"},
    },
    "green": {
        "id": "green",
        "label": "Green",
        "description": "Clean green terminal display with cyan accent hints.",
        "colors": {"primary": "#28f76e", "text": "#dcffe6", "dim": "#227c3e", "warning": "#ffc94a", "danger": "#ff4d4d", "accent": "#55e7ff"},
    },
    "cyan": {
        "id": "cyan",
        "label": "Cyan",
        "description": "Cool cyan board with bright teal accents.",
        "colors": {"primary": "#00ccff", "text": "#d7fcff", "dim": "#006688", "warning": "#ffcc00", "danger": "#ff4060", "accent": "#00ffcc"},
    },
    "technical": {
        "id": "technical",
        "label": "Technical",
        "description": "Muted technical blue palette matching the app's engineering surfaces.",
        "colors": {"primary": "#4a9eda", "text": "#d2e6f8", "dim": "#507494", "warning": "#d4a020", "danger": "#c04040", "accent": "#7ce7ff"},
    },
    "phosphor": {
        "id": "phosphor",
        "label": "Phosphor",
        "description": "Bright green phosphor style with soft monochrome contrast.",
        "colors": {"primary": "#39ff14", "text": "#cdffc6", "dim": "#3a8a18", "warning": "#aaff00", "danger": "#ff3232", "accent": "#b4ffb4"},
    },
    "indigo_night": {
        "id": "indigo_night",
        "label": "Indigo Night",
        "description": "Deep violet-blue palette for dark rooms and ambient displays.",
        "colors": {"primary": "#8272ff", "text": "#d8d4ff", "dim": "#5548b8", "warning": "#ffd84a", "danger": "#ff6b8a", "accent": "#4deaff"},
    },
    "rose_gold": {
        "id": "rose_gold",
        "label": "Rose Gold",
        "description": "Warm rose-pink display for decorative board installs.",
        "colors": {"primary": "#ff7ecb", "text": "#ffd8ee", "dim": "#a04878", "warning": "#ffd166", "danger": "#ff3864", "accent": "#ffb8c8"},
    },
}

_MATRIX_PRESETS: Dict[str, Dict[str, Any]] = {
    "real_fids": {
        "id": "real_fids",
        "label": "Real FIDS",
        "renderer": "modern_fids",
        "description": "Real-world passenger FIDS board with compact weather, route-code preservation, glyphs, and readable small-panel rows.",
        "options": {
            "palette": ["pax_blue", "solari_amber", "ice_white", "sunset_terminal"],
            "animation_mode": ["slide_left", "split_flap", "static"],
            "animation_speed": {"min": 1, "max": 5, "default": 3},
            "show_clock": True,
            "show_metar": True,
            "show_gate_info": True,
            "show_glyphs": True,
            "weather_strip": True,
            "code_preserve": True,
        },
    },
    "vatsim_pilot": {
        "id": "vatsim_pilot",
        "label": "VATSIM Pilot",
        "renderer": "vatsim_pilot",
        "description": "Pilot-facing virtual board with VATSIM callsigns, aircraft, route codes, and quiet page refresh.",
        "options": {
            "palette": ["vatsim_scope", "tower_scope", "night_ops"],
            "animation_mode": ["slide_left", "static"],
            "animation_speed": {"min": 1, "max": 5, "default": 2},
            "show_clock": True,
            "show_metar": True,
            "show_gate_info": False,
            "show_glyphs": True,
            "vatsim_labels": True,
            "code_preserve": True,
            "requires_source": "virtual",
        },
    },
    "vatsim_atc": {
        "id": "vatsim_atc",
        "label": "VATSIM ATC",
        "renderer": "vatsim_atc",
        "description": "Controller-style VATSIM panel cycling departures, arrivals, and a decoded ATIS/METAR weather page.",
        "options": {
            "palette": ["tower_scope", "vatsim_scope", "night_ops"],
            "animation_mode": ["slide_left", "static"],
            "animation_speed": {"min": 1, "max": 5, "default": 2},
            "show_clock": True,
            "show_metar": True,
            "show_gate_info": False,
            "show_glyphs": True,
            "vatsim_labels": True,
            "weather_page": True,
            "page_cycle": ["departures", "arrivals", "weather"],
            "requires_source": "virtual",
        },
    },
}

_MATRIX_PRESET_ALIASES: Dict[str, str] = {}

_MATRIX_CONFIG_DEFAULTS: Dict[str, Any] = {
    "id": "default",
    "name": "Default Board",
    "preset": "real_fids",
    "panel_w": 256,
    "panel_h": 64,
    "brightness": 0.8,
    "max_rows": 4,
    "refresh_seconds": 60,
    "default_view": "departures",
    "page_rotation_seconds": 10,
    "animation_enabled": True,
    "animation_mode": "split_flap",
    "animation_speed": 3,
    "status_animation_enabled": True,
    "show_weather": True,
    "show_gate_info": True,
    "palette": "pax_blue",
    "options": {},
}

_MATRIX_V1_FIELDS = {
    "preset",
    "brightness",
    "max_rows",
    "refresh_seconds",
    "default_view",
    "page_rotation_seconds",
    "animation_enabled",
    "animation_mode",
    "animation_speed",
    "status_animation_enabled",
    "show_weather",
    "show_gate_info",
    "palette",
    "options",
}

_MATRIX_ANIMATION_MODES = {"split_flap", "typewriter", "cascade", "slide_left", "slide_right", "static"}
_MATRIX_EXPECTED_RENDERER_REV = "matrix-display-contract-v4"

_MATRIX_PANEL_PRESETS: List[Dict[str, Any]] = [
    {"id": "64x32", "label": "64 x 32", "group": "Other common HUB75 sizes", "panel_w": 64, "panel_h": 32},
    {"id": "128x32", "label": "128 x 32", "group": "Other common HUB75 sizes", "panel_w": 128, "panel_h": 32},
    {"id": "256x32", "label": "256 x 32", "group": "Other common HUB75 sizes", "panel_w": 256, "panel_h": 32},
    {"id": "64x64", "label": "64 x 64", "group": "Other common HUB75 sizes", "panel_w": 64, "panel_h": 64},
    {"id": "128x64", "label": "128 x 64 - 1 rectangular module", "group": "128x64 rectangular modules", "panel_w": 128, "panel_h": 64},
    {"id": "256x64", "label": "256 x 64 - 2 across", "group": "128x64 rectangular modules", "panel_w": 256, "panel_h": 64},
    {"id": "384x64", "label": "384 x 64 - 3 across", "group": "128x64 rectangular modules", "panel_w": 384, "panel_h": 64},
    {"id": "512x64", "label": "512 x 64 - 4 across", "group": "128x64 rectangular modules", "panel_w": 512, "panel_h": 64},
    {"id": "128x128", "label": "128 x 128 - 2 stacked", "group": "128x64 rectangular modules", "panel_w": 128, "panel_h": 128},
    {"id": "256x128", "label": "256 x 128 - 2 by 2", "group": "128x64 rectangular modules", "panel_w": 256, "panel_h": 128},
    {"id": "384x128", "label": "384 x 128 - 3 by 2", "group": "128x64 rectangular modules", "panel_w": 384, "panel_h": 128},
    {"id": "512x128", "label": "512 x 128 - 4 by 2", "group": "128x64 rectangular modules", "panel_w": 512, "panel_h": 128},
]


def _matrix_config_path():
    from localflight.storage.config import config_path

    return config_path().parent / "matrix_config.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matrix_clock_payload(cfg: Optional[AppConfig] = None) -> Dict[str, Any]:
    cfg = cfg or load_config()
    now_utc = datetime.now(timezone.utc)
    timezone_name = resolve_config_timezone(cfg)
    local_now = now_utc.astimezone(ZoneInfo(timezone_name))
    offset = local_now.utcoffset()
    offset_minutes = int(offset.total_seconds() // 60) if offset else 0
    airport_payload = _matrix_airport_payload(cfg)
    return {
        **airport_payload,
        "timezone": timezone_name,
        "clock_utc_epoch": int(now_utc.timestamp()),
        "clock_local_epoch": int(now_utc.timestamp()) + offset_minutes * 60,
        "clock_utc": now_utc.strftime("%H:%M"),
        "clock_local": local_now.strftime("%H:%M"),
        "clock_local_offset_minutes": offset_minutes,
    }


def _matrix_airport_payload(cfg: AppConfig) -> Dict[str, Any]:
    code = (cfg.airport_iata or cfg.airport_icao or "---").upper()
    rec = lookup_airport(iata=cfg.airport_iata, icao=cfg.airport_icao)
    city = (rec.city if rec else "") or ""
    name = (rec.name if rec else "") or ""
    label = best_label(iata=cfg.airport_iata, icao=cfg.airport_icao, prefer="city", include_code=False)
    label = (label or city or name or code).strip()
    return {
        "airport_iata": cfg.airport_iata,
        "airport_icao": cfg.airport_icao,
        "airport_city": city,
        "airport_name": name,
        "airport_label": label,
        "airport_display_name": label,
    }


def _matrix_slug(value: str, fallback: str = "matrix") -> str:
    clean = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return clean[:48] or fallback


def _matrix_default_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {**_MATRIX_CONFIG_DEFAULTS, **(overrides or {})}
    return _normalize_matrix_config(data, fallback_id=str(data.get("id") or "default"))


def _normalize_matrix_config(raw: Dict[str, Any], *, fallback_id: str) -> Dict[str, Any]:
    preset = str(raw.get("preset") or _MATRIX_CONFIG_DEFAULTS["preset"])
    preset = _MATRIX_PRESET_ALIASES.get(preset, preset)
    if preset not in _MATRIX_PRESETS:
        preset = _MATRIX_CONFIG_DEFAULTS["preset"]
    view = str(raw.get("default_view") or "departures").strip().lower()
    if view not in {"departures", "arrivals"}:
        view = "departures"
    options = dict(raw.get("options")) if isinstance(raw.get("options"), dict) else {}
    preset_options = _MATRIX_PRESETS[preset].get("options", {})
    if "show_weather" in raw:
        show_weather = bool(raw.get("show_weather"))
    elif "show_weather" in options:
        show_weather = bool(options.get("show_weather"))
    elif "show_metar" in options:
        show_weather = bool(options.get("show_metar"))
    else:
        show_weather = bool(preset_options.get("show_metar", True))
    if "show_gate_info" in raw:
        show_gate_info = bool(raw.get("show_gate_info"))
    elif "show_gate_info" in options:
        show_gate_info = bool(options.get("show_gate_info"))
    else:
        show_gate_info = bool(preset_options.get("show_gate_info", not _matrix_is_vatsim_preset(preset)))
    if _matrix_is_vatsim_preset(preset):
        show_gate_info = False
    palette = str(raw.get("palette") or options.get("palette") or _MATRIX_CONFIG_DEFAULTS["palette"]).strip().lower()
    if palette not in _MATRIX_PALETTES:
        palette = _MATRIX_CONFIG_DEFAULTS["palette"]
    animation_enabled = bool(raw.get("animation_enabled", True))
    animation_mode = str(raw.get("animation_mode") or options.get("animation_mode") or _MATRIX_CONFIG_DEFAULTS["animation_mode"])
    if animation_mode not in _MATRIX_ANIMATION_MODES:
        animation_mode = _MATRIX_CONFIG_DEFAULTS["animation_mode"]
    if not animation_enabled:
        animation_mode = "static"
    return {
        "id": _matrix_slug(str(raw.get("id") or fallback_id), fallback_id),
        "name": str(raw.get("name") or "Matrix Config").strip()[:80] or "Matrix Config",
        "preset": preset,
        "panel_w": max(32, min(4096, int(raw.get("panel_w") or 256))),
        "panel_h": max(16, min(512, int(raw.get("panel_h") or 64))),
        "brightness": round(max(0.05, min(1.0, float(raw.get("brightness", 0.8)))), 2),
        "max_rows": max(1, min(8, int(raw.get("max_rows") or 4))),
        "refresh_seconds": max(10, min(3600, int(raw.get("refresh_seconds") or 60))),
        "default_view": view,
        "page_rotation_seconds": max(3, min(120, int(raw.get("page_rotation_seconds") or 10))),
        "animation_enabled": animation_enabled,
        "animation_mode": animation_mode,
        "animation_speed": max(1, min(5, int(raw.get("animation_speed") or 3))),
        "status_animation_enabled": bool(raw.get("status_animation_enabled", True)),
        "show_weather": show_weather,
        "show_gate_info": show_gate_info,
        "palette": palette,
        "options": {
            **options,
            "palette": palette,
            "animation_mode": animation_mode,
            "show_metar": show_weather,
            "show_weather": show_weather,
            "show_gate_info": show_gate_info,
        },
    }


def _matrix_v1_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    return {key: config[key] for key in _MATRIX_V1_FIELDS if key in config}


def _matrix_config_from_v1(data: Dict[str, Any]) -> Dict[str, Any]:
    overrides = {key: data[key] for key in _MATRIX_V1_FIELDS if key in data}
    return _matrix_default_config(overrides)


def _empty_matrix_store() -> Dict[str, Any]:
    cfg = _matrix_default_config({"id": "default", "name": "Default Board"})
    return {"schema_version": 2, "default_config_id": cfg["id"], "configs": [cfg], "devices": []}


def _normalize_matrix_store(data: Dict[str, Any]) -> Dict[str, Any]:
    if int(data.get("schema_version") or 1) != 2:
        cfg = _matrix_config_from_v1(data)
        return {"schema_version": 2, "default_config_id": cfg["id"], "configs": [cfg], "devices": []}
    configs_raw = data.get("configs") if isinstance(data.get("configs"), list) else []
    configs = [
        _normalize_matrix_config(item, fallback_id=f"config-{idx + 1}")
        for idx, item in enumerate(configs_raw)
        if isinstance(item, dict)
    ]
    if not configs:
        configs = [_matrix_default_config({"id": "default", "name": "Default Board"})]
    seen: set[str] = set()
    unique_configs: list[Dict[str, Any]] = []
    for cfg in configs:
        original = cfg["id"]
        while cfg["id"] in seen:
            cfg = {**cfg, "id": f"{original}-{len(seen) + 1}"}
        seen.add(cfg["id"])
        unique_configs.append(cfg)
    default_id = str(data.get("default_config_id") or unique_configs[0]["id"])
    if default_id not in {cfg["id"] for cfg in unique_configs}:
        default_id = unique_configs[0]["id"]
    devices_raw = data.get("devices") if isinstance(data.get("devices"), list) else []
    devices: list[Dict[str, Any]] = []
    for item in devices_raw:
        if not isinstance(item, dict):
            continue
        device_id = _matrix_slug(str(item.get("device_id") or item.get("id") or ""), "")
        if not device_id:
            continue
        assigned = str(item.get("assigned_config_id") or default_id)
        if assigned not in {cfg["id"] for cfg in unique_configs}:
            assigned = default_id
        configured_panel_w = max(32, min(4096, int(item.get("configured_panel_w") or item.get("panel_w") or 256)))
        configured_panel_h = max(16, min(512, int(item.get("configured_panel_h") or item.get("panel_h") or 64)))
        actual_panel_w = max(32, min(4096, int(item.get("actual_panel_w") or item.get("panel_w") or configured_panel_w)))
        actual_panel_h = max(16, min(512, int(item.get("actual_panel_h") or item.get("panel_h") or configured_panel_h)))
        geometry_mismatch = bool(item.get("geometry_mismatch")) or (
            actual_panel_w != configured_panel_w or actual_panel_h != configured_panel_h
        )
        geometry_warning = str(item.get("geometry_warning") or "").strip()[:180]
        if geometry_mismatch and not geometry_warning:
            geometry_warning = f"Configured {configured_panel_w}x{configured_panel_h}; actual {actual_panel_w}x{actual_panel_h}."
        devices.append({
            "device_id": device_id,
            "label": str(item.get("label") or device_id)[:80],
            "kind": str(item.get("kind") or "led_matrix")[:40],
            "brand": str(item.get("brand") or item.get("vendor") or "")[:60],
            "model": str(item.get("model") or "")[:80],
            "hardware": str(item.get("hardware") or "")[:100],
            "hardware_name": str(item.get("hardware_name") or "")[:120],
            "panel_w": actual_panel_w,
            "panel_h": actual_panel_h,
            "configured_panel_w": configured_panel_w,
            "configured_panel_h": configured_panel_h,
            "actual_panel_w": actual_panel_w,
            "actual_panel_h": actual_panel_h,
            "display_panels": max(0, min(64, int(item.get("display_panels") or 0))),
            "geometry_mismatch": geometry_mismatch,
            "geometry_warning": geometry_warning,
            "firmware": str(item.get("firmware") or "")[:32],
            "renderer_revision": str(item.get("renderer_revision") or "")[:80],
            "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
            "renderer_status": "current" if str(item.get("renderer_revision") or "").strip() == _MATRIX_EXPECTED_RENDERER_REV else ("unknown" if not str(item.get("renderer_revision") or "").strip() else "stale"),
            "renderers": [str(v)[:40] for v in (item.get("renderers") or []) if isinstance(v, str)],
            "assigned_config_id": assigned,
            "last_seen": item.get("last_seen"),
        })
    return {"schema_version": 2, "default_config_id": default_id, "configs": unique_configs, "devices": devices}


def _load_matrix_store(*, persist_migration: bool = True) -> Dict[str, Any]:
    path = _matrix_config_path()
    if not path.exists():
        return _empty_matrix_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_matrix_store()
    if not isinstance(raw, dict):
        return _empty_matrix_store()
    store = _normalize_matrix_store(raw)
    if persist_migration and raw != store:
        _save_matrix_store(store)
    return store


def _save_matrix_store(store: Dict[str, Any]) -> None:
    path = _matrix_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_normalize_matrix_store(store), indent=2), encoding="utf-8")


def _matrix_config_by_id(store: Dict[str, Any], config_id: Optional[str]) -> Dict[str, Any]:
    wanted = str(config_id or store.get("default_config_id") or "")
    for cfg in store["configs"]:
        if cfg["id"] == wanted:
            return cfg
    return store["configs"][0]


def _matrix_device_by_id(store: Dict[str, Any], device_id: str) -> Optional[Dict[str, Any]]:
    for device in store["devices"]:
        if device["device_id"] == device_id:
            return device
    return None


def _matrix_renderer_status(device: Optional[Dict[str, Any]]) -> str:
    if not device:
        return "unknown"
    revision = str(device.get("renderer_revision") or "").strip()
    if not revision:
        return "unknown"
    return "current" if revision == _MATRIX_EXPECTED_RENDERER_REV else "stale"


def _matrix_device_meta(device: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not device:
        return {
            "device_id": None,
            "device_label": None,
            "assigned_config_id": None,
            "effective_panel_w": None,
            "effective_panel_h": None,
            "configured_panel_w": None,
            "configured_panel_h": None,
            "actual_panel_w": None,
            "actual_panel_h": None,
            "geometry_mismatch": False,
            "geometry_warning": "",
            "renderer_revision": "",
            "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
            "renderer_status": "unknown",
            "last_seen": None,
        }
    effective_w = int(device.get("actual_panel_w") or device.get("panel_w") or device.get("configured_panel_w") or 0)
    effective_h = int(device.get("actual_panel_h") or device.get("panel_h") or device.get("configured_panel_h") or 0)
    return {
        "device_id": device.get("device_id"),
        "device_label": device.get("label"),
        "assigned_config_id": device.get("assigned_config_id"),
        "effective_panel_w": effective_w or None,
        "effective_panel_h": effective_h or None,
        "configured_panel_w": device.get("configured_panel_w"),
        "configured_panel_h": device.get("configured_panel_h"),
        "actual_panel_w": device.get("actual_panel_w"),
        "actual_panel_h": device.get("actual_panel_h"),
        "geometry_mismatch": bool(device.get("geometry_mismatch")),
        "geometry_warning": str(device.get("geometry_warning") or ""),
        "renderer_revision": str(device.get("renderer_revision") or ""),
        "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
        "renderer_status": _matrix_renderer_status(device),
        "last_seen": device.get("last_seen"),
    }


def _load_matrix_config() -> Dict[str, Any]:
    store = _load_matrix_store()
    return _matrix_v1_from_config(_matrix_config_by_id(store, store.get("default_config_id")))


class MatrixConfigIn(BaseModel):
    preset: Optional[str] = None
    brightness: float = Field(0.8, ge=0.0, le=1.0)
    max_rows: int = Field(4, ge=1, le=8)
    refresh_seconds: int = Field(60, ge=10, le=3600)
    default_view: str = Field("departures")
    page_rotation_seconds: int = Field(10, ge=3, le=120)
    animation_enabled: bool = True
    animation_mode: str = "split_flap"
    animation_speed: int = Field(3, ge=1, le=5)
    status_animation_enabled: bool = True
    show_weather: bool = True
    show_gate_info: bool = True
    palette: str = "pax_blue"
    options: Dict[str, Any] = Field(default_factory=dict)


class MatrixV2ConfigIn(BaseModel):
    id: Optional[str] = Field(None, max_length=80)
    name: Optional[str] = Field(None, max_length=80)
    preset: Optional[str] = None
    panel_w: Optional[int] = Field(None, ge=32, le=4096)
    panel_h: Optional[int] = Field(None, ge=16, le=512)
    brightness: Optional[float] = Field(None, ge=0.05, le=1.0)
    max_rows: Optional[int] = Field(None, ge=1, le=8)
    refresh_seconds: Optional[int] = Field(None, ge=10, le=3600)
    default_view: Optional[str] = None
    page_rotation_seconds: Optional[int] = Field(None, ge=3, le=120)
    animation_enabled: Optional[bool] = None
    animation_mode: Optional[str] = None
    animation_speed: Optional[int] = Field(None, ge=1, le=5)
    status_animation_enabled: Optional[bool] = None
    show_weather: Optional[bool] = None
    show_gate_info: Optional[bool] = None
    palette: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class MatrixDeviceCheckIn(BaseModel):
    device_id: Optional[str] = Field(None, max_length=80)
    label: Optional[str] = Field(None, max_length=80)
    kind: str = Field("led_matrix", max_length=40)
    brand: str = Field("", max_length=60)
    model: str = Field("", max_length=80)
    hardware: str = Field("", max_length=100)
    hardware_name: str = Field("", max_length=120)
    panel_w: int = Field(256, ge=32, le=4096)
    panel_h: int = Field(64, ge=16, le=512)
    actual_panel_w: Optional[int] = Field(None, ge=32, le=4096)
    actual_panel_h: Optional[int] = Field(None, ge=16, le=512)
    display_panels: Optional[int] = Field(None, ge=1, le=64)
    firmware: str = Field("", max_length=32)
    renderer_revision: str = Field("", max_length=80)
    geometry_warning: str = Field("", max_length=180)
    renderers: List[str] = Field(default_factory=list)


class MatrixDevicePatchIn(BaseModel):
    label: Optional[str] = Field(None, max_length=80)
    assigned_config_id: Optional[str] = Field(None, max_length=80)


@router.get("/api/matrix/config")
def api_matrix_config_get() -> Dict[str, Any]:
    try:
        skin = load_config().skin
    except Exception:
        skin = "standard"
    return {**_load_matrix_config(), "skin": skin, **_matrix_clock_payload()}


@router.post("/api/matrix/config")
def api_matrix_config_post(body: MatrixConfigIn) -> Dict[str, Any]:
    store = _load_matrix_store()
    cfg = _matrix_config_by_id(store, store.get("default_config_id"))
    updates = {
        "preset": body.preset or cfg.get("preset") or _MATRIX_CONFIG_DEFAULTS["preset"],
        "brightness": round(float(body.brightness), 2),
        "max_rows": int(body.max_rows),
        "refresh_seconds": int(body.refresh_seconds),
        "default_view": body.default_view if body.default_view in ("departures", "arrivals") else "departures",
        "page_rotation_seconds": int(body.page_rotation_seconds),
        "animation_enabled": bool(body.animation_enabled),
        "animation_mode": body.animation_mode,
        "animation_speed": int(body.animation_speed),
        "status_animation_enabled": bool(body.status_animation_enabled),
        "show_weather": bool(body.show_weather),
        "show_gate_info": bool(body.show_gate_info),
        "palette": body.palette,
        "options": {**(cfg.get("options") if isinstance(cfg.get("options"), dict) else {}), **body.options},
    }
    merged = _normalize_matrix_config({**cfg, **updates}, fallback_id=cfg["id"])
    store["configs"] = [merged if item["id"] == cfg["id"] else item for item in store["configs"]]
    try:
        _save_matrix_store(store)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"ok": True, **_matrix_v1_from_config(merged)}


@router.get("/api/matrix/v2/presets")
def api_matrix_v2_presets() -> Dict[str, Any]:
    return {
        "presets": list(_MATRIX_PRESETS.values()),
        "palettes": list(_MATRIX_PALETTES.values()),
        "panel_presets": list(_MATRIX_PANEL_PRESETS),
    }


@router.get("/api/matrix/v2/configs")
def api_matrix_v2_configs() -> Dict[str, Any]:
    store = _load_matrix_store()
    return {
        "schema_version": 2,
        "default_config_id": store["default_config_id"],
        "configs": store["configs"],
    }


@router.post("/api/matrix/v2/configs")
def api_matrix_v2_config_create(body: MatrixV2ConfigIn) -> Dict[str, Any]:
    store = _load_matrix_store()
    base = _matrix_default_config({
        "id": body.id or body.name or f"matrix-{uuid4().hex[:8]}",
        "name": body.name or "New Matrix Config",
    })
    updates = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
    if isinstance(updates.get("options"), dict):
        updates["options"] = {**(base.get("options") if isinstance(base.get("options"), dict) else {}), **updates["options"]}
    cfg = _normalize_matrix_config({**base, **updates}, fallback_id=base["id"])
    existing = {item["id"] for item in store["configs"]}
    if cfg["id"] in existing:
        cfg["id"] = f"{cfg['id']}-{uuid4().hex[:4]}"
    store["configs"].append(cfg)
    _save_matrix_store(store)
    return {"ok": True, "config": cfg}


@router.get("/api/matrix/v2/configs/{config_id}")
def api_matrix_v2_config_get(config_id: str) -> Dict[str, Any]:
    store = _load_matrix_store()
    cfg = _matrix_config_by_id(store, config_id)
    if cfg["id"] != config_id:
        raise HTTPException(status_code=404, detail="Matrix config not found")
    return cfg


@router.patch("/api/matrix/v2/configs/{config_id}")
def api_matrix_v2_config_patch(config_id: str, body: MatrixV2ConfigIn) -> Dict[str, Any]:
    store = _load_matrix_store()
    cfg = _matrix_config_by_id(store, config_id)
    if cfg["id"] != config_id:
        raise HTTPException(status_code=404, detail="Matrix config not found")
    updates = body.model_dump(exclude_unset=True) if hasattr(body, "model_dump") else body.dict(exclude_unset=True)
    updates.pop("id", None)
    if isinstance(updates.get("options"), dict):
        updates["options"] = {**(cfg.get("options") if isinstance(cfg.get("options"), dict) else {}), **updates["options"]}
    merged = _normalize_matrix_config({**cfg, **updates}, fallback_id=cfg["id"])
    store["configs"] = [merged if item["id"] == cfg["id"] else item for item in store["configs"]]
    if bool(updates.get("set_default", False)):
        store["default_config_id"] = merged["id"]
    _save_matrix_store(store)
    return {"ok": True, "config": merged}


@router.delete("/api/matrix/v2/configs/{config_id}")
def api_matrix_v2_config_delete(config_id: str) -> Dict[str, Any]:
    store = _load_matrix_store()
    if len(store["configs"]) <= 1:
        raise HTTPException(status_code=422, detail="At least one matrix config is required")
    if config_id not in {cfg["id"] for cfg in store["configs"]}:
        raise HTTPException(status_code=404, detail="Matrix config not found")
    store["configs"] = [cfg for cfg in store["configs"] if cfg["id"] != config_id]
    if store["default_config_id"] == config_id:
        store["default_config_id"] = store["configs"][0]["id"]
    for device in store["devices"]:
        if device.get("assigned_config_id") == config_id:
            device["assigned_config_id"] = store["default_config_id"]
    _save_matrix_store(store)
    return {"ok": True, "default_config_id": store["default_config_id"]}


@router.post("/api/matrix/v2/configs/{config_id}/default")
def api_matrix_v2_config_set_default(config_id: str) -> Dict[str, Any]:
    store = _load_matrix_store()
    if config_id not in {cfg["id"] for cfg in store["configs"]}:
        raise HTTPException(status_code=404, detail="Matrix config not found")
    store["default_config_id"] = config_id
    _save_matrix_store(store)
    return {"ok": True, "default_config_id": config_id}


@router.get("/api/matrix/v2/devices")
def api_matrix_v2_devices() -> Dict[str, Any]:
    store = _load_matrix_store()
    return {"devices": store["devices"], "default_config_id": store["default_config_id"]}


@router.post("/api/matrix/v2/devices/checkin")
def api_matrix_v2_device_checkin(body: MatrixDeviceCheckIn) -> Dict[str, Any]:
    store = _load_matrix_store()
    device_id = _matrix_slug(body.device_id or f"matrix-{uuid4().hex[:8]}", "matrix")
    device = _matrix_device_by_id(store, device_id)
    configured_panel_w = int(body.panel_w)
    configured_panel_h = int(body.panel_h)
    actual_panel_w = int(body.actual_panel_w or configured_panel_w)
    actual_panel_h = int(body.actual_panel_h or configured_panel_h)
    geometry_mismatch = actual_panel_w != configured_panel_w or actual_panel_h != configured_panel_h
    geometry_warning = (body.geometry_warning or "").strip()[:180]
    if geometry_mismatch and not geometry_warning:
        geometry_warning = f"Configured {configured_panel_w}x{configured_panel_h}; actual {actual_panel_w}x{actual_panel_h}."
    if not device:
        device = {
            "device_id": device_id,
            "label": (body.label or device_id)[:80],
            "assigned_config_id": store["default_config_id"],
        }
        store["devices"].append(device)
    device.update({
        "kind": (body.kind or "led_matrix")[:40],
        "brand": body.brand[:60],
        "model": body.model[:80],
        "hardware": body.hardware[:100],
        "hardware_name": body.hardware_name[:120] or " ".join(part for part in (body.brand.strip(), body.model.strip()) if part)[:120],
        "panel_w": actual_panel_w,
        "panel_h": actual_panel_h,
        "configured_panel_w": configured_panel_w,
        "configured_panel_h": configured_panel_h,
        "actual_panel_w": actual_panel_w,
        "actual_panel_h": actual_panel_h,
        "display_panels": int(body.display_panels or 0),
        "geometry_mismatch": geometry_mismatch,
        "geometry_warning": geometry_warning,
        "firmware": body.firmware[:32],
        "renderer_revision": body.renderer_revision[:80],
        "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
        "renderer_status": "current" if body.renderer_revision.strip() == _MATRIX_EXPECTED_RENDERER_REV else ("unknown" if not body.renderer_revision.strip() else "stale"),
        "renderers": [str(v)[:40] for v in body.renderers],
        "last_seen": _utc_now_iso(),
    })
    _save_matrix_store(store)
    return {"ok": True, "device": device, "assigned_config_id": device["assigned_config_id"]}


@router.patch("/api/matrix/v2/devices/{device_id}")
def api_matrix_v2_device_patch(device_id: str, body: MatrixDevicePatchIn) -> Dict[str, Any]:
    store = _load_matrix_store()
    device = _matrix_device_by_id(store, _matrix_slug(device_id, "matrix"))
    if not device:
        raise HTTPException(status_code=404, detail="Matrix device not found")
    if body.label is not None:
        device["label"] = body.label.strip()[:80] or device["device_id"]
    if body.assigned_config_id is not None:
        if body.assigned_config_id not in {cfg["id"] for cfg in store["configs"]}:
            raise HTTPException(status_code=404, detail="Matrix config not found")
        device["assigned_config_id"] = body.assigned_config_id
    _save_matrix_store(store)
    return {"ok": True, "device": device}


def _matrix_resolved_config(
    store: Dict[str, Any],
    device_id: Optional[str],
    *,
    config_id: Optional[str] = None,
    preview_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    device = _matrix_device_by_id(store, _matrix_slug(device_id or "", "")) if device_id else None
    if config_id and config_id in {cfg["id"] for cfg in store["configs"]}:
        cfg = _matrix_config_by_id(store, config_id)
    else:
        cfg = _matrix_config_by_id(store, device.get("assigned_config_id") if device else store.get("default_config_id"))
    if preview_overrides:
        cfg = _normalize_matrix_config({**cfg, **preview_overrides}, fallback_id=cfg["id"])
    preset = _MATRIX_PRESETS.get(cfg["preset"], _MATRIX_PRESETS["real_fids"])
    meta = _matrix_device_meta(device)
    effective_w = meta.get("effective_panel_w") or cfg.get("panel_w")
    effective_h = meta.get("effective_panel_h") or cfg.get("panel_h")
    return {
        **cfg,
        **_matrix_clock_payload(),
        "config_rev": int(Path(_matrix_config_path()).stat().st_mtime) if Path(_matrix_config_path()).exists() else 0,
        "renderer": preset["renderer"],
        "preset_label": preset["label"],
        "device_id": device["device_id"] if device else None,
        "device_meta": meta,
        "effective_panel_w": effective_w,
        "effective_panel_h": effective_h,
        "geometry_mismatch": bool(meta.get("geometry_mismatch")),
        "geometry_warning": str(meta.get("geometry_warning") or ""),
        "renderer_revision": str(meta.get("renderer_revision") or ""),
        "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
        "renderer_status": str(meta.get("renderer_status") or "unknown"),
    }


@router.get("/api/matrix/v2/devices/{device_id}/config")
def api_matrix_v2_device_config(device_id: str) -> Dict[str, Any]:
    store = _load_matrix_store()
    return _matrix_resolved_config(store, device_id)


def _matrix_route_fields(route_display: Any) -> Dict[str, str]:
    text = str(route_display or "-").strip()
    if not text or text == "-":
        return {"route_city": "", "route_code": "", "route_matrix_label": "-"}
    code = ""
    city = text
    match = re.search(r"\(([A-Z0-9]{3,4})\)\s*$", text.upper())
    if match:
        code = match.group(1)
        city = re.sub(r"\s*\([A-Za-z0-9]{3,4}\)\s*$", "", text).strip()
    elif re.fullmatch(r"[A-Z0-9]{3,4}", text.upper()):
        code = text.upper()
        city = ""
    else:
        tail = re.search(r"\b([A-Z0-9]{3,4})\s*$", text.upper())
        if tail and text.upper().endswith(tail.group(1)):
            code = tail.group(1)
            city = text[: -len(tail.group(1))].strip(" -/()")
    safe_city = _matrix_ascii(city)
    label = " ".join(part for part in (safe_city, code) if part).strip() or _matrix_ascii(text)
    return {
        "route_city": safe_city,
        "route_code": code,
        "route_matrix_label": label.upper(),
    }


def _matrix_ascii(value: Any) -> str:
    text = str(value or "")
    replacements = {
        "\u00c4": "AE", "\u00d6": "OE", "\u00dc": "UE", "\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue",
        "\u00df": "ss", "\u00c6": "AE", "\u00e6": "ae", "\u0152": "OE", "\u0153": "oe",
        "\u00d8": "O", "\u00f8": "o", "\u0110": "D", "\u0111": "d", "\u0141": "L", "\u0142": "l",
    }
    text = "".join(replacements.get(ch, ch) for ch in text)
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").strip()


def _matrix_gate_label(
    data: Dict[str, Any],
    *,
    preset: Any = "real_fids",
    show_gate_info: bool = True,
) -> str:
    if _matrix_is_vatsim_preset(preset) or not show_gate_info:
        return ""
    for key in ("terminal_gate_display", "gate_display", "gate"):
        value = str(data.get(key) or "").strip()
        if value and value != "-":
            return value
    return ""


def _matrix_identifier_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            return []
        text = re.sub(r"\b(Sold\s+as|Also)\b", "", text, flags=re.IGNORECASE)
        text = text.replace("·", "/").replace("|", "/").replace(",", "/")
        raw_values = text.split("/")
    values: List[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        item = str(raw or "").strip()
        if not item or item == "-":
            continue
        compact = re.sub(r"[^A-Za-z0-9]", "", item).upper()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        values.append(item)
    return values


def _matrix_secondary_label(sold_as: List[str], codeshares: List[str]) -> str:
    if sold_as:
        shown = sold_as[:3]
        suffix = f" +{len(sold_as) - len(shown)}" if len(sold_as) > len(shown) else ""
        return "Sold as " + " / ".join(shown) + suffix
    if codeshares:
        shown = codeshares[:4]
        suffix = f" +{len(codeshares) - len(shown)}" if len(codeshares) > len(shown) else ""
        return "Also " + " / ".join(shown) + suffix
    return ""


def _matrix_operator_label(data: Dict[str, Any], *, is_virtual: bool = False) -> str:
    if is_virtual:
        return ""
    value = (
        data.get("operating_airline")
        or data.get("operator")
        or data.get("airline_display")
        or data.get("airline_name")
        or ""
    )
    text = _matrix_clean_display_label(value, fallback="")
    return f"OP {text}" if text else ""


def _matrix_codeshare_label(sold_as: List[str], codeshares: List[str]) -> str:
    if sold_as:
        shown = sold_as[:2]
        suffix = f" +{len(sold_as) - len(shown)}" if len(sold_as) > len(shown) else ""
        return "SOLD AS " + " / ".join(shown).upper() + suffix
    if codeshares:
        shown = codeshares[:2]
        suffix = f" +{len(codeshares) - len(shown)}" if len(codeshares) > len(shown) else ""
        return "ALSO " + " / ".join(shown).upper() + suffix
    return ""


def _matrix_detail_cycle(
    *,
    operator_label: str = "",
    codeshare_label: str = "",
    gate_label: str = "",
    aircraft_label: str = "",
) -> List[str]:
    values: List[str] = []
    for raw in (
        operator_label,
        codeshare_label,
        f"GATE {gate_label}" if gate_label else "",
        aircraft_label,
    ):
        text = _matrix_clean_display_label(raw, fallback="")
        if text and text not in values:
            values.append(text)
    return values


def _matrix_compact_time_label(data: Dict[str, Any]) -> str:
    for key in ("matrix_time_label", "display_time", "time", "time_primary"):
        text = _matrix_ascii(data.get(key)).strip()
        if not text:
            continue
        match = re.search(r"\b(\d{1,2})[:.](\d{2})\b", text)
        if match:
            return f"{int(match.group(1)):02d}:{match.group(2)}"
    return "--:--"


def _matrix_format_flight_label(value: Any, *, callsign: bool = False) -> str:
    text = _matrix_ascii(value).upper().strip()
    if not text or text == "-":
        return ""
    text = re.sub(r"\b(SOLD\s+AS|ALSO)\b", "", text, flags=re.IGNORECASE)
    text = text.replace("|", " ").replace(",", " ").replace("/", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text.startswith("+"):
        return ""
    compact = re.sub(r"[^A-Z0-9]", "", text)
    if callsign:
        return compact[:10]
    parts = text.split()
    if len(parts) >= 2 and re.fullmatch(r"[A-Z0-9]{2,3}", parts[0]) and re.match(r"\d", parts[1]):
        return f"{parts[0]} {parts[1]}"[:10].strip()
    match = re.fullmatch(r"([A-Z0-9]{2,3})(\d[A-Z0-9]*)", compact)
    if match:
        return f"{match.group(1)} {match.group(2)}"[:10].strip()
    return compact[:10]


def _matrix_flight_label(data: Dict[str, Any]) -> str:
    for key in ("matrix_flight_label", "flight_display", "flight_number", "flight"):
        label = _matrix_format_flight_label(data.get(key))
        if label:
            return label
    for key in ("operating_callsign", "callsign"):
        label = _matrix_format_flight_label(data.get(key), callsign=True)
        if label:
            return label
    return "-"


def _matrix_clean_display_label(value: Any, *, fallback: str = "-") -> str:
    text = _matrix_ascii(value).upper().strip()
    text = re.sub(r"\s+", " ", text)
    return text if text and text != "-" else fallback


def _matrix_status_label(data: Dict[str, Any]) -> str:
    status = _matrix_clean_display_label(data.get("status_display") or data.get("status"), fallback="-")
    delta = _matrix_clean_display_label(data.get("time_delta_label"), fallback="")
    lowered = status.lower()
    if delta and "delay" not in lowered and "early" not in lowered:
        status = f"{status} {delta}".strip()
    return status


_MATRIX_WEATHER_ICON_ALIASES = {
    "clear": "sun",
    "sun": "sun",
    "sunny": "sun",
    "vfr": "sun",
    "partly_cloudy": "cloud",
    "partly cloudy": "cloud",
    "cloud": "cloud",
    "cloudy": "cloud",
    "overcast": "cloud",
    "rain": "rain",
    "showers": "rain",
    "shower": "rain",
    "drizzle": "rain",
    "storm": "storm",
    "thunder": "storm",
    "thunderstorm": "storm",
    "mist": "mist",
    "fog": "mist",
    "haze": "mist",
    "snow": "snow",
}


def _matrix_weather_icon(value: Any) -> str:
    text = _matrix_ascii(value).lower().strip().replace("-", "_")
    if not text:
        return "cloud"
    if text in _MATRIX_WEATHER_ICON_ALIASES:
        return _MATRIX_WEATHER_ICON_ALIASES[text]
    for needle, icon in _MATRIX_WEATHER_ICON_ALIASES.items():
        if needle in text:
            return icon
    return "cloud"


def _matrix_row_payload(row: Any, *, preset: Any = "real_fids", show_gate_info: bool = True) -> Dict[str, Any]:
    if hasattr(row, "model_dump"):
        data = row.model_dump()
    elif hasattr(row, "dict"):
        data = row.dict()
    elif hasattr(row, "__dataclass_fields__"):
        data = asdict(row)
    else:
        data = dict(row)
    data = enrich_presentation_fields(data)
    status = str(data.get("status_display") or "")
    lowered = status.lower()
    kind = str(data.get("status_kind") or "").strip()
    if not kind:
        kind = (
        "delayed" if "delay" in lowered else
        "cancelled" if "cancel" in lowered else
        "boarding" if "board" in lowered else
        "at_gate" if "gate" in lowered or "ground" in lowered else
        "arriving" if "arriv" in lowered or "approach" in lowered else
        "departing" if "depart" in lowered else
        "landed" if "land" in lowered else
        "scheduled"
        )
    flight = data.get("flight_display") or data.get("callsign") or "-"
    mode_text = str(data.get("detail_mode") or data.get("source") or data.get("source_hint") or "").lower()
    is_virtual = "virtual" in mode_text or "vatsim" in mode_text
    operator = "" if is_virtual else (
        data.get("operating_airline")
        or data.get("operator")
        or data.get("airline_display")
        or data.get("airline_name")
        or ""
    )
    codeshares = [] if is_virtual else _matrix_identifier_list(data.get("codeshares"))
    sold_as = [] if is_virtual else _matrix_identifier_list(data.get("sold_as"))
    codeshare = str(data.get("codeshare_display") or "").strip() or _matrix_secondary_label(sold_as, codeshares)
    if is_virtual:
        codeshare = ""
    route_display = data.get("route_display") or "-"
    route_fields = _matrix_route_fields(route_display)
    hide_gate_fields = is_virtual or _matrix_is_vatsim_preset(preset)
    gate_value = "" if hide_gate_fields else data.get("gate_display") or data.get("gate") or ""
    if str(gate_value).strip() == "-":
        gate_value = ""
    gate_display = "" if hide_gate_fields else data.get("gate_display") or ""
    terminal_display = "" if hide_gate_fields else data.get("terminal_display") or ""
    terminal_gate_display = "" if hide_gate_fields else data.get("terminal_gate_display") or ""
    gate_label = _matrix_gate_label(
        {
            **data,
            "gate": gate_value,
            "gate_display": gate_display,
            "terminal_display": terminal_display,
            "terminal_gate_display": terminal_gate_display,
        },
        preset=preset,
        show_gate_info=show_gate_info,
    )
    matrix_time_label = _matrix_compact_time_label(data)
    matrix_flight = _matrix_flight_label(data)
    matrix_route = route_fields["route_matrix_label"]
    matrix_status = _matrix_status_label(data)
    matrix_gate = _matrix_clean_display_label(gate_label, fallback="") if gate_label else ""
    matrix_aircraft = _matrix_clean_display_label(data.get("aircraft_type") or data.get("aircraft"), fallback="")
    matrix_operator = _matrix_operator_label({**data, "operating_airline": operator}, is_virtual=is_virtual)
    matrix_codeshare = "" if is_virtual else _matrix_codeshare_label(sold_as, codeshares)
    matrix_details = [] if is_virtual else _matrix_detail_cycle(
        operator_label=matrix_operator,
        codeshare_label=matrix_codeshare,
        gate_label=matrix_gate,
        aircraft_label=matrix_aircraft,
    )
    return {
        "id": data.get("id"),
        "time": data.get("display_time") or "--:--",
        "display_time": data.get("display_time") or "--:--",
        "flight": flight,
        "flight_display": flight,
        "flight_number": data.get("flight_number") or flight,
        "route": route_display,
        "route_display": route_display,
        **route_fields,
        "status": status or "-",
        "status_display": status or "-",
        "time_primary": data.get("time_primary") or "",
        "time_delta_label": data.get("time_delta_label") or "",
        "time_delta_text": data.get("time_delta_text") or "",
        "delay_kind": data.get("delay_kind") or "none",
        "tone": data.get("tone") or "neutral",
        "gate": gate_value,
        "gate_display": gate_display,
        "terminal_display": terminal_display,
        "terminal_gate_display": terminal_gate_display,
        "gate_label": gate_label,
        "aircraft": data.get("aircraft_type") or "",
        "aircraft_type": data.get("aircraft_type") or "",
        "matrix_time_label": matrix_time_label,
        "matrix_flight_label": matrix_flight,
        "matrix_route_label": matrix_route,
        "matrix_status_label": matrix_status,
        "matrix_gate_label": matrix_gate,
        "matrix_aircraft_label": matrix_aircraft,
        "matrix_operator_label": matrix_operator,
        "matrix_codeshare_label": matrix_codeshare,
        "matrix_detail_cycle": matrix_details,
        "callsign": data.get("callsign") or "",
        "operator": operator,
        "operating_airline": operator,
        "airline_display": operator,
        "airline_iata": "" if is_virtual else (data.get("airline_iata") or ""),
        "airline_icao": "" if is_virtual else (data.get("airline_icao") or ""),
        "codeshares": codeshares,
        "codeshare": " / ".join(codeshares),
        "codeshare_display": codeshare,
        "sold_as": sold_as,
        "marketing_airline_name": "" if is_virtual else (data.get("marketing_airline_name") or ""),
        "marketing_airline_iata": "" if is_virtual else (data.get("marketing_airline_iata") or ""),
        "marketing_airline_icao": "" if is_virtual else (data.get("marketing_airline_icao") or ""),
        "marketing_flight_number": "" if is_virtual else (data.get("marketing_flight_number") or ""),
        "operating_callsign": data.get("operating_callsign") or "",
        "identity_source": data.get("identity_source") or "",
        "status_class": data.get("status_class") or kind,
        "status_kind": data.get("status_kind") or kind,
        "source_hint": data.get("source_hint") or "",
        "live_hint": data.get("live_hint") or "",
    }


def _matrix_is_vatsim_preset(preset: Any) -> bool:
    return str(preset or "").strip().lower().startswith("vatsim_")


def _matrix_option_enabled(resolved: Dict[str, Any], key: str, default: bool = True) -> bool:
    options = resolved.get("options") if isinstance(resolved.get("options"), dict) else {}
    if key in {"show_metar", "show_weather"} and "show_weather" in resolved:
        value = resolved.get("show_weather")
    elif key == "show_gate_info" and "show_gate_info" in resolved:
        value = resolved.get("show_gate_info")
    else:
        value = options.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _matrix_metar_payload(metar: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(metar, dict):
        return None
    temp = metar.get("temperature_c", metar.get("temp_c"))
    temp_display = metar.get("temperature_display") or (
        f"{temp} C" if temp is not None else None
    )
    temp_short = str(temp_display or "").replace(" C", "C").replace(" ", "")
    condition = (
        metar.get("weather_label")
        or metar.get("decoded_summary")
        or metar.get("weather_summary")
        or metar.get("wx_string")
        or metar.get("flight_cat")
    )
    condition = str(condition or "").strip()
    weather_icon = _matrix_weather_icon(metar.get("weather_icon") or condition or metar.get("flight_cat"))
    return {
        "category": metar.get("flight_cat"),
        "flight_cat": metar.get("flight_cat"),
        "flight_cat_color": metar.get("flight_cat_color"),
        "summary": metar.get("weather_label") or metar.get("decoded_summary"),
        "condition_display": condition,
        "weather_display": " ".join(part for part in (condition, temp_short) if part),
        "weather_label": metar.get("weather_label"),
        "weather_icon": metar.get("weather_icon"),
        "matrix_weather_icon": weather_icon,
        "matrix_weather_temp": temp_short or None,
        "matrix_weather_label": condition or None,
        "raw": metar.get("raw_text"),
        "raw_text": metar.get("raw_text"),
        "wind": metar.get("wind_display") or metar.get("wind"),
        "wind_display": metar.get("wind_display") or metar.get("wind"),
        "temp_c": metar.get("temp_c", metar.get("temperature_c")),
        "temperature_c": temp,
        "temperature_display": temp_display,
        "temperature_short": temp_short or None,
        "dewpoint_c": metar.get("dewpoint_c"),
        "visibility_m": metar.get("visibility_m"),
        "visibility_sm": metar.get("visibility_sm"),
        "ceiling_ft": metar.get("ceiling_ft"),
        "clouds": metar.get("clouds") or [],
        "wx_string": metar.get("wx_string"),
        "altimeter_hpa": metar.get("altimeter_hpa"),
        "source": metar.get("source"),
    }


def _matrix_weather_page(metar: Optional[Dict[str, Any]], *, airport_icao: str) -> Dict[str, Any]:
    payload = _matrix_metar_payload(metar)
    if not payload:
        return {
            "available": False,
            "source": "vatsim",
            "airport_icao": airport_icao,
            "title": "NO VATSIM ATIS",
            "lines": ["NO VATSIM ATIS", airport_icao or "----"],
            "icons": ["unknown"],
        }
    clouds = payload.get("clouds") if isinstance(payload.get("clouds"), list) else []
    cloud_line = "CLR"
    if clouds:
        parts = []
        for cloud in clouds[:3]:
            if not isinstance(cloud, dict):
                continue
            cover = str(cloud.get("cover") or "").upper()
            base = cloud.get("base_ft")
            parts.append(f"{cover}{base}" if base is not None else cover)
        cloud_line = " ".join(part for part in parts if part) or cloud_line
    visibility = payload.get("visibility_sm")
    if visibility is None and payload.get("visibility_m") is not None:
        try:
            visibility = round(float(payload["visibility_m"]) / 1609.34, 1)
        except Exception:
            visibility = None
    altimeter = payload.get("altimeter_hpa")
    lines = [
        f"{airport_icao} VATSIM WX".strip(),
        " ".join(part for part in (payload.get("flight_cat"), payload.get("weather_label")) if part),
        " ".join(part for part in (payload.get("temperature_display"), f"DP {payload.get('dewpoint_c')}C" if payload.get("dewpoint_c") is not None else "") if part),
        f"WIND {payload.get('wind_display') or '-'}",
        f"QNH {altimeter}" if altimeter is not None else "QNH -",
        f"VIS {visibility}SM" if visibility is not None else "VIS -",
        cloud_line,
    ]
    return {
        "available": True,
        "source": payload.get("source") or "vatsim",
        "airport_icao": airport_icao,
        "title": "VATSIM WX",
        "lines": [str(line).upper() for line in lines if str(line or "").strip()],
        "icons": ["sun", "cloud", "rain", "storm", "mist", "unknown"],
        **payload,
    }


def _matrix_vatsim_weather(cfg: AppConfig) -> Optional[Dict[str, Any]]:
    from localflight.sources.web.metar_client import decode_raw_metar
    vatsim_client = _vatsim_client_module()

    raw_metar = vatsim_client.vatsim_metar_for_airport(_fetch_vatsim_payload(), airport_icao=cfg.airport_icao)
    if not raw_metar:
        return None
    return decode_raw_metar(cfg.airport_icao, raw_metar, source="vatsim")


def _matrix_vatsim_rows(
    *,
    cfg: AppConfig,
    view: Literal["departures", "arrivals"],
    limit: int,
) -> List[FIDSRowOut]:
    from localflight.decode.normalize import normalize_flights
    vatsim_client = _vatsim_client_module()

    payload = _fetch_vatsim_payload()
    records = vatsim_client.vatsim_to_raw_records(payload, airport_icao=cfg.airport_icao, mode="both")
    flights = normalize_flights(
        records,
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        source_name="vatsim",
    )
    flights = [flight for flight in flights if flight.source == "vatsim"]
    return _fids_rows_from_flights(
        cfg=cfg,
        flights=flights,
        view=view,
        limit=limit,
        last_refreshed=datetime.now(timezone.utc),
        source_status="vatsim",
    )


@router.get("/api/matrix/v2/devices/{device_id}/feed")
def api_matrix_v2_device_feed(
    device_id: str,
    view: Optional[str] = Query(None),
    config_id: Optional[str] = Query(None),
    preset: Optional[str] = Query(None),
    max_rows: Optional[int] = Query(None, ge=1, le=8),
    show_weather: Optional[bool] = Query(None),
    show_gate_info: Optional[bool] = Query(None),
) -> Dict[str, Any]:
    store = _load_matrix_store()
    is_preview = _matrix_slug(device_id or "", "") == "preview"
    preview_overrides: Dict[str, Any] = {}
    if is_preview:
        if preset in _MATRIX_PRESETS:
            preview_overrides["preset"] = preset
        if max_rows is not None:
            preview_overrides["max_rows"] = int(max_rows)
        preview_options: Dict[str, Any] = {}
        if show_weather is not None:
            preview_options.update({"show_metar": bool(show_weather), "show_weather": bool(show_weather)})
            preview_overrides["show_weather"] = bool(show_weather)
        if show_gate_info is not None:
            preview_options["show_gate_info"] = bool(show_gate_info)
            preview_overrides["show_gate_info"] = bool(show_gate_info)
        if preview_options:
            preview_overrides["options"] = preview_options
    resolved = _matrix_resolved_config(
        store,
        None if is_preview else device_id,
        config_id=config_id if is_preview else None,
        preview_overrides=preview_overrides if is_preview else None,
    )
    requested_view = view if view in {"departures", "arrivals"} else resolved["default_view"]
    effective_view = requested_view
    cfg = load_config()
    limit = min(max(16, max(1, resolved["max_rows"]) * 4), 32)
    payload: Dict[str, Any] = {
        "config_rev": resolved["config_rev"],
        "data_rev": int(time.time()),
        "view": effective_view,
        "generated_at": _utc_now_iso(),
        "config_id": resolved.get("id"),
        "config_name": resolved.get("name"),
        "assigned_config_id": (resolved.get("device_meta") or {}).get("assigned_config_id"),
        "panel_w": resolved.get("panel_w"),
        "panel_h": resolved.get("panel_h"),
        "effective_panel_w": resolved.get("effective_panel_w") or resolved.get("panel_w"),
        "effective_panel_h": resolved.get("effective_panel_h") or resolved.get("panel_h"),
        "device_meta": resolved.get("device_meta"),
        "geometry_mismatch": bool(resolved.get("geometry_mismatch")),
        "geometry_warning": str(resolved.get("geometry_warning") or ""),
        "renderer_revision": str(resolved.get("renderer_revision") or ""),
        "expected_renderer_revision": _MATRIX_EXPECTED_RENDERER_REV,
        "renderer_status": str(resolved.get("renderer_status") or "unknown"),
        **_matrix_airport_payload(cfg),
    }
    show_metar = _matrix_option_enabled(resolved, "show_metar", True)
    show_gate = _matrix_option_enabled(
        resolved,
        "show_gate_info",
        not _matrix_is_vatsim_preset(resolved["preset"]),
    )
    if _matrix_is_vatsim_preset(resolved["preset"]):
        show_gate = False
    payload["show_gate_info"] = show_gate
    payload["show_weather"] = show_metar
    if _matrix_is_vatsim_preset(resolved["preset"]) and (cfg.source or "").strip().lower() != "virtual":
        message = "SET SOURCE TO VATSIM"
        return {
            **payload,
            "source_required": "virtual",
            "message": message,
            "rows": [],
            "metar": None,
            "weather_page": {
                "available": False,
                "source": "vatsim",
                "airport_icao": cfg.airport_icao,
                "title": message,
                "lines": [message, "SETTINGS SOURCE VIRTUAL"],
                "icons": ["unknown"],
            },
        }

    if _matrix_is_vatsim_preset(resolved["preset"]):
        dep_rows = [
            _matrix_row_payload(row, preset=resolved["preset"], show_gate_info=show_gate)
            for row in _matrix_vatsim_rows(cfg=cfg, view="departures", limit=limit)
        ]
        arr_rows = [
            _matrix_row_payload(row, preset=resolved["preset"], show_gate_info=show_gate)
            for row in _matrix_vatsim_rows(cfg=cfg, view="arrivals", limit=limit)
        ]
        rows = dep_rows if effective_view == "departures" else arr_rows
        if not rows:
            alternate_view = "arrivals" if effective_view == "departures" else "departures"
            alternate_rows = arr_rows if alternate_view == "arrivals" else dep_rows
            if alternate_rows:
                effective_view = alternate_view
                rows = alternate_rows
                payload["view"] = effective_view
                payload["requested_view"] = requested_view
                payload["fallback_view"] = True
        metar_payload = None
        weather_page = None
        if show_metar:
            try:
                metar = _matrix_vatsim_weather(cfg)
            except Exception as exc:
                log.debug("VATSIM matrix weather unavailable: %s", exc)
                metar = None
            metar_payload = _matrix_metar_payload(metar)
            weather_page = _matrix_weather_page(metar, airport_icao=cfg.airport_icao)
        payload.update({
            "rows": rows,
            "metar": metar_payload,
            "weather_page": weather_page,
        })
        if resolved["preset"] == "vatsim_atc":
            pages = {
                "departures": dep_rows,
                "arrivals": arr_rows,
            }
            if show_metar and weather_page:
                pages["weather"] = weather_page
            payload["pages"] = pages
        return payload

    rows = api_fids(view=effective_view, limit=limit)
    if not rows:
        alternate_view = "arrivals" if effective_view == "departures" else "departures"
        alternate_rows = api_fids(view=alternate_view, limit=limit)
        if alternate_rows:
            effective_view = alternate_view
            rows = alternate_rows
            payload["view"] = effective_view
            payload["requested_view"] = requested_view
            payload["fallback_view"] = True
    payload["rows"] = [
        _matrix_row_payload(row, preset=resolved["preset"], show_gate_info=show_gate)
        for row in rows
    ]
    if show_metar:
        try:
            payload["metar"] = _matrix_metar_payload(api_metar())
        except Exception:
            payload["metar"] = None
    else:
        payload["metar"] = None
    return payload


class MatrixScriptIn(BaseModel):
    wifi_ssid: str = Field(..., min_length=1, max_length=64)
    wifi_password: str = Field("", max_length=128)
    api_host: str = Field(..., min_length=1, max_length=253)
    api_port: int = Field(8000, ge=1, le=65535)
    device_label: str = Field("Interstate 75 W", max_length=80)
    panel_w: int = Field(256, ge=32, le=4096)
    panel_h: int = Field(64, ge=16, le=512)
    max_rows: int = Field(4, ge=1, le=8)
    refresh_seconds: int = Field(60, ge=10, le=3600)
    brightness: float = Field(0.8, ge=0.05, le=1.0)
    default_view: str = Field("departures")
    page_rotation_seconds: int = Field(10, ge=3, le=120)
    animation_enabled: bool = True
    animation_mode: str = "split_flap"
    animation_speed: int = Field(3, ge=1, le=5)
    status_animation_enabled: bool = True
    show_weather: bool = True
    show_gate_info: bool = True
    preset: str = "real_fids"
    palette: str = "pax_blue"


def _matrix_client_template_path() -> Path:
    return Path(__file__).resolve().parents[1] / "sources" / "matrix" / "client.py"


def _normalize_matrix_api_host(value: str) -> str:
    host = (value or "").strip().lower()
    if host in {"localhost", "127.0.0.1", "::1", "[::1]"}:
        raise HTTPException(
            status_code=422,
            detail="Use a LAN IP or mDNS host such as localflight.local, not localhost.",
        )
    if not re.fullmatch(r"[a-z0-9.-]+", host):
        raise HTTPException(
            status_code=422,
            detail="Server host must be a LAN IP or mDNS host using letters, numbers, dots, or hyphens.",
        )
    return host


def _matrix_assignment_line(name: str, value: str) -> str:
    return f"{name.ljust(max(14, len(name) + 1))}= {value}"


def _render_matrix_client_script(body: MatrixScriptIn) -> str:
    default_view = body.default_view if body.default_view in {"departures", "arrivals"} else "departures"
    animation_mode = body.animation_mode if body.animation_mode in _MATRIX_ANIMATION_MODES else "split_flap"
    if not body.animation_enabled:
        animation_mode = "static"
    palette = body.palette if body.palette in _MATRIX_PALETTES else "pax_blue"
    preset = body.preset if body.preset in _MATRIX_PRESETS else "real_fids"
    renderer = str(_MATRIX_PRESETS.get(preset, _MATRIX_PRESETS["real_fids"]).get("renderer") or "modern_fids")
    show_gate_info = bool(body.show_gate_info) and not _matrix_is_vatsim_preset(preset)
    host = _normalize_matrix_api_host(body.api_host)
    text = _matrix_client_template_path().read_text(encoding="utf-8")
    replacements = {
        "WIFI_SSID": json.dumps(body.wifi_ssid),
        "WIFI_PASSWORD": json.dumps(body.wifi_password),
        "API_HOST": json.dumps(host),
        "API_PORT": str(int(body.api_port)),
        "DEVICE_LABEL": json.dumps(body.device_label.strip() or "Interstate 75 W"),
        "PANEL_W": str(int(body.panel_w)),
        "PANEL_H": str(int(body.panel_h)),
        "MAX_ROWS": str(int(body.max_rows)),
        "REFRESH_S": str(int(body.refresh_seconds)),
        "PAGE_ROTATION_S": str(int(body.page_rotation_seconds)),
        "BRIGHTNESS": f"{float(body.brightness):.2f}",
        "DEFAULT_VIEW": json.dumps(default_view),
        "ANIMATION_ENABLED": "True" if body.animation_enabled else "False",
        "ANIMATION_MODE": json.dumps(animation_mode),
        "ANIMATION_SPEED": str(int(body.animation_speed)),
        "STATUS_ANIMATION_ENABLED": "True" if body.status_animation_enabled else "False",
        "SHOW_WEATHER": "True" if body.show_weather else "False",
        "SHOW_GATE_INFO": "True" if show_gate_info else "False",
        "PRESET": json.dumps(preset),
        "RENDERER": json.dumps(renderer),
    }
    replacements["PALETTE"] = json.dumps(palette)
    for key, value in replacements.items():
        text = re.sub(
            rf"^{key}\s*=.*$",
            _matrix_assignment_line(key, value),
            text,
            flags=re.MULTILINE,
        )
    return text


@router.post("/api/matrix/script", response_class=PlainTextResponse)
def api_matrix_script(body: MatrixScriptIn) -> PlainTextResponse:
    script = _render_matrix_client_script(body)
    return PlainTextResponse(
        script,
        headers={"Content-Disposition": 'attachment; filename="main.py"'},
    )


try:
    from fastapi import FastAPI as _FastAPI
    from fastapi.middleware.cors import CORSMiddleware as _CORS
    app = _FastAPI(title="LocalFlight API", docs_url="/api/docs")
    app.add_middleware(_CORS, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
except ImportError:
    app = None  # type: ignore
