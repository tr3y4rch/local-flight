"""
localflight/ui/api.py

JSON API layer for the FIDS system.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests as _req
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from localflight.core.airports import _load_index, lookup_airport
from localflight.core.models import Flight, FlightDirection, FlightPosition
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
from localflight.sources.web.relay_defaults import default_public_relay_url, relay_airport_surface_url

log = logging.getLogger(__name__)

router = APIRouter()

_COMPANION_STALE_SECONDS = 15 * 60
_COMPANION_RETENTION_DAYS = 30


def _network_tools_enabled() -> bool:
    import os
    return os.getenv("LOCALFLIGHT_ENABLE_NETWORK_TOOLS", "").strip().lower() in {"1", "true", "yes", "on"}

# In-memory caches for live radar sources. The UI polls frequently, so these
# prevent each browser tab or mobile companion from spending one API call.
_adsbx_radar_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_opensky_radar_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_DEFAULT_ADSBX_RADAR_CACHE_TTL_S = 300
_OPENSKY_RADAR_CACHE_TTL_S = 60
_MIN_PROVIDER_RADAR_RADIUS_NM = 5.0


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

    direction = FlightDirection(d["direction"])
    try:
        status = FlightStatus(d.get("status", "Unknown"))
    except ValueError:
        status = FlightStatus.UNKNOWN

    times_d   = d.get("times")   or {}
    airline_d = d.get("airline") or {}

    return Flight(
        direction=direction,
        airport=AirportRef(
            iata=(d.get("airport") or {}).get("iata"),
            icao=(d.get("airport") or {}).get("icao"),
        ),
        callsign=d["callsign"],
        airline=AirlineRef(
            name=airline_d.get("name"),
            iata=airline_d.get("iata"),
            icao=airline_d.get("icao"),
        ),
        flight_number=d.get("flight_number"),
        codeshares=_codeshares(d.get("codeshares")),
        origin=_airport(d.get("origin")),
        destination=_airport(d.get("destination")),
        aircraft_type=d.get("aircraft_type"),
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

    return flights, generated_at


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


class FIDSRowOut(BaseModel):
    id:             str
    view:           str
    display_time:   str
    flight_display: str
    airline_display: str = ""
    codeshare_display: str = ""
    route_display:  str
    status_display: str
    status_class:   str
    gate:           str
    aircraft_type:  str
    callsign:       str = ""


# â”€â”€ Config endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/api/health")
def api_health() -> Dict[str, Any]:
    return asdict(load_state())


@router.get("/api/config")
def api_get_config() -> Dict[str, Any]:
    return asdict(load_config())


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
    current_cfg = load_config()
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
    direction = FlightDirection.DEPARTURE if view == "departures" else FlightDirection.ARRIVAL
    flights = [f for f in flights if f.direction == direction]

    ctx = build_fids_context(
        cfg=cfg,
        view=view,
        refresh_seconds=cfg.refresh_seconds,
        flights=flights,
        last_refreshed=last_refreshed,
        reference_now=last_refreshed,
        source_status=cfg.source,
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
        )
        for r in rows
    ]


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
        detail = {
            "callsign":      flight.callsign,
            "flight_number": flight.flight_number,
            "flight_display": format_flight_identifier(
                flight_number=flight.flight_number,
                callsign=flight.callsign,
                airline_iata=flight.airline.iata if flight.airline else None,
                airline_icao=flight.airline.icao if flight.airline else None,
            ),
            "airline":       flight.airline.name if flight.airline else None,
            "airline_iata":  flight.airline.iata if flight.airline else None,
            "airline_icao":  flight.airline.icao if flight.airline else None,
            "codeshares":    list(flight.codeshares),
            "origin_iata":   flight.origin.iata        if flight.origin      else None,
            "origin_icao":   flight.origin.icao        if flight.origin      else None,
            "origin_name":   flight.origin.name        if flight.origin      else None,
            "dest_iata":     flight.destination.iata   if flight.destination else None,
            "dest_icao":     flight.destination.icao   if flight.destination else None,
            "dest_name":     flight.destination.name   if flight.destination else None,
            "sched_time":    flight.times.scheduled.isoformat() if flight.times.scheduled else None,
            "est_time":      flight.times.estimated.isoformat() if flight.times.estimated else None,
            "actual_time":   flight.times.actual.isoformat()    if flight.times.actual    else None,
            "delay_minutes": flight.delay_minutes,
            "gate":          flight.gate,
            "terminal":      flight.terminal,
            "aircraft_type": flight.aircraft_type,
            "aircraft_registration": flight.aircraft_registration,
            "direction":     flight.direction.value,
            "status":        flight.status.value,
            "source":        flight.source,
            "enriched_by":   flight.enriched_by,
            "updated_at":    _iso(flight.updated_at),
            "detail_mode":   "virtual" if (cfg.source == "virtual" or flight.source == "vatsim") else "real",
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
                "icao24":          pos.icao24,
                "squawk":          pos.squawk,
                "last_contact":    _iso(pos.last_contact),
            } if pos else None,
        }

    history_raw = query_flight_history(callsign.upper(), days=7)
    history = [
        {
            "date":          r["snapshot_ts"][:10],
            "status":        r["status"],
            "delay_minutes": r["delay_minutes"],
            "gate":          r["gate"],
        }
        for r in history_raw[:10]
    ]

    return {"detail": detail, "history": history}


# â”€â”€ Radar endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _radar_surface_cache_path(cfg: AppConfig) -> Path:
    from localflight.storage.config import config_path

    code = (cfg.airport_icao or cfg.airport_iata or "airport").upper()
    safe = re.sub(r"[^A-Z0-9_-]+", "_", code).strip("_") or "airport"
    return config_path().parent / "storage" / "radar_surface" / f"{safe}.json"


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

    if not cfg.radar_surface_enabled:
        return _surface_empty_payload(
            cfg=cfg,
            center_lat=center_lat,
            center_lon=center_lon,
            radius_nm=radius,
            cache_state="disabled",
            error="Airport surface overlay disabled",
        )

    cached = _load_local_surface_cache(cfg)
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
            timeout=12,
        )
        if response.status_code < 400:
            payload = response.json()
            if isinstance(payload, dict) and validate_surface_payload(payload):
                _save_local_surface_cache(cfg, payload)
                return payload
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
        return stale

    return build_estimated_surface_payload(
        airport_iata=cfg.airport_iata,
        airport_icao=cfg.airport_icao,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_nm=radius,
        error=relay_error or "No airport surface cache available",
    )


@router.get("/api/radar")
def api_radar(
    radius_nm: float = Query(20.0, ge=1.0, le=200.0),  # default 20nm
) -> Dict[str, Any]:
    """
    Returns aircraft positions for the radar display.
    Only shows aircraft with a filed flight plan to/from the configured airport.

    For source=real:    live ADS-B Exchange positions when RapidAPI is configured.
                        Falls back to snapshot positions, then live OpenSky.
    For source=virtual: live VATSIM, filtered to dep/arr at configured airport only.
    """
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
            from localflight.sources.web.vatsim_client import fetch_vatsim_data
            from localflight.sources.web.opensky_radar import bounding_box

            payload = fetch_vatsim_data()
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

                blips.append({
                    "callsign":   callsign,
                    "lat":        plat_f,
                    "lon":        plon_f,
                    "altitude_m": alt_ft * 0.3048 if alt_ft else None,
                    "heading":    float(hdg) if hdg is not None else None,
                    "speed_ms":   gs_kts * 0.514444 if gs_kts else None,
                    "on_ground":  (alt_ft < 100 and gs_kts < 50),
                    "icao24":     None,
                    "squawk":     pilot.get("transponder") or fp.get("assigned_transponder"),
                    "enriched":   False,
                    "source":     "vatsim",
                    "aircraft_type": aircraft_type,
                    "departure_icao": dep or None,
                    "arrival_icao": arr or None,
                    "flight_rules": fp.get("flight_rules"),
                    "route":      fp.get("route"),
                    "planned_altitude": fp.get("altitude"),
                    "cruise_tas": fp.get("cruise_tas"),
                    "distance_nm": round(distance_nm, 2),
                })

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
                blips.append({
                    "callsign":      f.callsign,
                    "lat":           f.position.lat,
                    "lon":           f.position.lon,
                    "altitude_m":    f.position.altitude_baro,
                    "heading":       f.position.heading,
                    "speed_ms":      f.position.speed_ms,
                    "on_ground":     f.position.on_ground,
                    "icao24":        f.position.icao24,
                    "squawk":        f.position.squawk,
                    "flight_number": f.flight_number,
                    "status":        f.status.value,
                    "source":        f.source,
                    "aircraft_type": f.aircraft_type,
                    "departure_icao": f.origin.icao if f.origin else None,
                    "arrival_icao": f.destination.icao if f.destination else None,
                    "distance_nm": round(_distance_nm(center_lat, center_lon, f.position.lat, f.position.lon), 2),
                    "enriched":      True,
                })

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
                log.info("No position data in snapshot â€” falling back to live OpenSky fetch")
                source_used = "opensky_live"
                try:
                    from localflight.sources.web.opensky_radar import fetch_radar_blips
                    raw_blips = fetch_radar_blips(
                        lat=center_lat, lon=center_lon, radius_nm=radius_nm,
                    )
                    for b in raw_blips:
                        b["enriched"] = False
                    blips = raw_blips
                    _opensky_radar_cache[cache_key] = (now_ts, blips)
                except Exception as exc:
                    log.warning("OpenSky live radar fallback failed: %s", exc)
                    raise HTTPException(status_code=503, detail=f"Radar data unavailable: {exc}")

    ground_filtered = 0
    airborne_filtered = 0
    radar_mode = "surface" if _surface_radar_mode(radius_nm) else "airborne"
    if radar_mode == "surface":
        blips, airborne_filtered = _filter_ground_radar_blips(blips)
    else:
        blips, ground_filtered = _filter_airborne_radar_blips(blips)

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
        "provider_radius_nm": provider_radius_nm if cfg.source != "virtual" and adsb_source else radius_nm,
        "raw_provider_count": adsbx_raw_count if cfg.source != "virtual" and adsb_source else len(blips),
        "blips":     blips,
    }

# â”€â”€ History endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
 
@router.get("/api/history")
def api_history(
    hours:     int = Query(24,  ge=1,   le=720),
    direction: str = Query("both"),
    limit:     int = Query(100, ge=1,   le=1000),
) -> Dict[str, Any]:
    """
    Returns recent flight history from the local SQLite database.
 
    hours:     how many hours back to look (default 24, max 720 = 30 days)
    direction: "dep", "arr", or "both"
    limit:     max rows to return
 
    Response:
    {
      "airport_iata": "ZRH",
      "hours":        24,
      "count":        42,
      "flights":      [ { ...row... }, ... ]
    }
    """
    from localflight.storage.history import query_recent
 
    cfg = load_config()
 
    dir_filter = None
    if direction == "dep":
        dir_filter = "DEP"
    elif direction == "arr":
        dir_filter = "ARR"
 
    rows = query_recent(
        airport_iata=cfg.airport_iata,
        hours=hours,
        direction=dir_filter,
        limit=limit,
    )
 
    return {
        "airport_iata": cfg.airport_iata,
        "hours":        hours,
        "count":        len(rows),
        "flights":      rows,
    }
 
 
@router.get("/api/history/flight")
def api_history_flight(
    callsign: str = Query(..., min_length=2, max_length=10),
    days:     int = Query(7, ge=1, le=90),
) -> Dict[str, Any]:
    """
    Returns history for a specific callsign over the last N days.
    Useful for seeing if a flight is consistently on time or delayed.
    """
    from localflight.storage.history import query_flight_history
 
    rows = query_flight_history(callsign=callsign.upper().strip(), days=days)
 
    return {
        "callsign": callsign.upper().strip(),
        "days":     days,
        "count":    len(rows),
        "flights":  rows,
    }
 
 
@router.get("/api/history/summary")
def api_history_summary(
    hours: int = Query(720, ge=1, le=2160),
) -> Dict[str, Any]:
    """Aggregated stats: top airlines, routes, aircraft, on-time rate."""
    from localflight.storage.history import query_summary
    cfg = load_config()
    return query_summary(airport_iata=cfg.airport_iata, hours=hours)


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
            from localflight.sources.web.vatsim_client import fetch_vatsim_data, vatsim_metar_for_airport

            raw_vatsim_metar = vatsim_metar_for_airport(fetch_vatsim_data(), airport_icao=icao_code)
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
        _ver = "0.2.5b4"

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
 
    try:
        from localflight.sources.web.aviationstack_client import get_usage_stats
        result["aviationstack"] = get_usage_stats(cfg.source)
    except Exception as exc:
        result["aviationstack"] = {"error": str(exc)}
 
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
        "companion_last_seen": companion_last_seen,
        "companion_count": len(companions),
        "companions": companions[:10],
    }
 
 
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
        current = "0.2.5b4"

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

_MATRIX_PRESETS: Dict[str, Dict[str, Any]] = {
    "classic_split_flap": {
        "id": "classic_split_flap",
        "label": "Classic Split-Flap",
        "renderer": "split_flap",
        "description": "Mechanical station-board rhythm with staggered character flips.",
        "options": {
            "palette": ["amber", "green", "white"],
            "animation_mode": ["split_flap", "slide_left", "slide_right", "static"],
            "animation_speed": {"min": 1, "max": 5, "default": 3},
            "row_stagger_ms": {"min": 0, "max": 800, "default": 120},
            "show_clock": True,
            "ticker": False,
        },
    },
    "modern_airport_fids": {
        "id": "modern_airport_fids",
        "label": "Modern Airport FIDS",
        "renderer": "modern_fids",
        "description": "Dark airport-screen layout with colored status accents.",
        "options": {
            "palette": ["standard", "technical", "cyan"],
            "animation_mode": ["slide_left", "split_flap", "static"],
            "animation_speed": {"min": 1, "max": 5, "default": 2},
            "show_clock": True,
            "show_metar": True,
            "row_pulse": True,
        },
    },
    "terminal_minimal": {
        "id": "terminal_minimal",
        "label": "Terminal Minimal",
        "renderer": "terminal_minimal",
        "description": "Readable next-flight hero with a compact queue.",
        "options": {
            "palette": ["standard", "white", "cyan"],
            "animation_mode": ["slide_left", "slide_right", "static"],
            "hero_flight": True,
            "queue_rows": {"min": 1, "max": 4, "default": 3},
            "ticker": True,
            "show_clock": True,
        },
    },
    "radar_strip": {
        "id": "radar_strip",
        "label": "Radar Strip",
        "renderer": "radar_strip",
        "description": "Compact scope/status display for nearby traffic.",
        "options": {
            "palette": ["technical", "green", "cyan"],
            "animation_mode": ["slide_left", "static"],
            "range_nm": {"min": 1, "max": 40, "default": 5},
            "sweep": True,
            "show_labels": True,
            "metar_footer": True,
        },
    },
}

_MATRIX_CONFIG_DEFAULTS: Dict[str, Any] = {
    "id": "default",
    "name": "Default Board",
    "preset": "classic_split_flap",
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
    "palette": "standard",
    "options": {},
}

_MATRIX_V1_FIELDS = {
    "brightness",
    "max_rows",
    "refresh_seconds",
    "default_view",
    "page_rotation_seconds",
    "animation_enabled",
}

_MATRIX_ANIMATION_MODES = {"split_flap", "slide_left", "slide_right", "static"}


def _matrix_config_path():
    from localflight.storage.config import config_path

    return config_path().parent / "matrix_config.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _matrix_clock_payload() -> Dict[str, Any]:
    cfg = load_config()
    now_utc = datetime.now(timezone.utc)
    timezone_name = cfg.timezone or "UTC"
    try:
        local_now = now_utc.astimezone(ZoneInfo(timezone_name))
    except Exception:
        timezone_name = "UTC"
        local_now = now_utc
    offset = local_now.utcoffset()
    offset_minutes = int(offset.total_seconds() // 60) if offset else 0
    return {
        "airport_iata": cfg.airport_iata,
        "timezone": timezone_name,
        "clock_utc_epoch": int(now_utc.timestamp()),
        "clock_utc": now_utc.strftime("%H:%M"),
        "clock_local": local_now.strftime("%H:%M"),
        "clock_local_offset_minutes": offset_minutes,
    }


def _matrix_slug(value: str, fallback: str = "matrix") -> str:
    clean = re.sub(r"[^a-z0-9_-]+", "-", str(value or "").strip().lower()).strip("-")
    return clean[:48] or fallback


def _matrix_default_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = {**_MATRIX_CONFIG_DEFAULTS, **(overrides or {})}
    return _normalize_matrix_config(data, fallback_id=str(data.get("id") or "default"))


def _normalize_matrix_config(raw: Dict[str, Any], *, fallback_id: str) -> Dict[str, Any]:
    preset = str(raw.get("preset") or _MATRIX_CONFIG_DEFAULTS["preset"])
    if preset not in _MATRIX_PRESETS:
        preset = _MATRIX_CONFIG_DEFAULTS["preset"]
    view = str(raw.get("default_view") or "departures").strip().lower()
    if view not in {"departures", "arrivals"}:
        view = "departures"
    options = raw.get("options") if isinstance(raw.get("options"), dict) else {}
    palette = str(raw.get("palette") or options.get("palette") or _MATRIX_CONFIG_DEFAULTS["palette"])
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
        "palette": palette[:32],
        "options": {**options, "palette": palette[:32], "animation_mode": animation_mode},
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
        devices.append({
            "device_id": device_id,
            "label": str(item.get("label") or device_id)[:80],
            "panel_w": max(32, min(4096, int(item.get("panel_w") or 256))),
            "panel_h": max(16, min(512, int(item.get("panel_h") or 64))),
            "firmware": str(item.get("firmware") or "")[:32],
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


def _load_matrix_config() -> Dict[str, Any]:
    store = _load_matrix_store()
    return _matrix_v1_from_config(_matrix_config_by_id(store, store.get("default_config_id")))


class MatrixConfigIn(BaseModel):
    brightness: float = Field(0.8, ge=0.0, le=1.0)
    max_rows: int = Field(4, ge=1, le=8)
    refresh_seconds: int = Field(60, ge=10, le=3600)
    default_view: str = Field("departures")
    page_rotation_seconds: int = Field(10, ge=3, le=120)
    animation_enabled: bool = True


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
    palette: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class MatrixDeviceCheckIn(BaseModel):
    device_id: Optional[str] = Field(None, max_length=80)
    label: Optional[str] = Field(None, max_length=80)
    panel_w: int = Field(256, ge=32, le=4096)
    panel_h: int = Field(64, ge=16, le=512)
    firmware: str = Field("", max_length=32)
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
        "brightness": round(float(body.brightness), 2),
        "max_rows": int(body.max_rows),
        "refresh_seconds": int(body.refresh_seconds),
        "default_view": body.default_view if body.default_view in ("departures", "arrivals") else "departures",
        "page_rotation_seconds": int(body.page_rotation_seconds),
        "animation_enabled": bool(body.animation_enabled),
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
    return {"presets": list(_MATRIX_PRESETS.values())}


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
    if not device:
        device = {
            "device_id": device_id,
            "label": (body.label or device_id)[:80],
            "assigned_config_id": store["default_config_id"],
        }
        store["devices"].append(device)
    device.update({
        "panel_w": int(body.panel_w),
        "panel_h": int(body.panel_h),
        "firmware": body.firmware[:32],
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


def _matrix_resolved_config(store: Dict[str, Any], device_id: Optional[str]) -> Dict[str, Any]:
    device = _matrix_device_by_id(store, _matrix_slug(device_id or "", "")) if device_id else None
    cfg = _matrix_config_by_id(store, device.get("assigned_config_id") if device else store.get("default_config_id"))
    preset = _MATRIX_PRESETS.get(cfg["preset"], _MATRIX_PRESETS["classic_split_flap"])
    return {
        **cfg,
        **_matrix_clock_payload(),
        "config_rev": int(Path(_matrix_config_path()).stat().st_mtime) if Path(_matrix_config_path()).exists() else 0,
        "renderer": preset["renderer"],
        "preset_label": preset["label"],
        "device_id": device["device_id"] if device else None,
    }


@router.get("/api/matrix/v2/devices/{device_id}/config")
def api_matrix_v2_device_config(device_id: str) -> Dict[str, Any]:
    store = _load_matrix_store()
    return _matrix_resolved_config(store, device_id)


def _matrix_row_payload(row: Any) -> Dict[str, Any]:
    data = row.model_dump() if hasattr(row, "model_dump") else row.dict() if hasattr(row, "dict") else dict(row)
    status = str(data.get("status_display") or "")
    lowered = status.lower()
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
    operator = data.get("airline_display") or ""
    codeshare = data.get("codeshare_display") or ""
    return {
        "id": data.get("id"),
        "time": data.get("display_time") or "--:--",
        "display_time": data.get("display_time") or "--:--",
        "flight": flight,
        "flight_display": flight,
        "flight_number": flight,
        "route": data.get("route_display") or "-",
        "route_display": data.get("route_display") or "-",
        "status": status or "-",
        "status_display": status or "-",
        "gate": data.get("gate") or "-",
        "aircraft": data.get("aircraft_type") or "",
        "aircraft_type": data.get("aircraft_type") or "",
        "callsign": data.get("callsign") or "",
        "operator": operator,
        "operating_airline": operator,
        "airline_display": operator,
        "codeshare": codeshare,
        "codeshare_display": codeshare,
        "sold_as": codeshare,
        "status_class": data.get("status_class") or kind,
        "status_kind": data.get("status_class") or kind,
    }


@router.get("/api/matrix/v2/devices/{device_id}/feed")
def api_matrix_v2_device_feed(device_id: str, view: Optional[str] = Query(None)) -> Dict[str, Any]:
    store = _load_matrix_store()
    resolved = _matrix_resolved_config(store, device_id)
    effective_view = view if view in {"departures", "arrivals"} else resolved["default_view"]
    rows = api_fids(view=effective_view, limit=min(max(1, resolved["max_rows"]) * 4, 32))
    payload: Dict[str, Any] = {
        "config_rev": resolved["config_rev"],
        "data_rev": int(time.time()),
        "view": effective_view,
        "generated_at": _utc_now_iso(),
        "airport_iata": load_config().airport_iata,
        "rows": [_matrix_row_payload(row) for row in rows],
    }
    try:
        metar = api_metar()
        payload["metar"] = {
            "category": metar.get("flight_cat"),
            "summary": metar.get("weather_label") or metar.get("decoded_summary"),
            "raw": metar.get("raw_text"),
            "wind": metar.get("wind_display") or metar.get("wind"),
        }
    except Exception:
        payload["metar"] = None
    if resolved["preset"] == "radar_strip":
        try:
            radar = api_radar(float(resolved.get("options", {}).get("range_nm") or 5.0))
            payload["radar"] = {
                "range_nm": resolved.get("options", {}).get("range_nm") or 5,
                "count": radar.get("count"),
                "source": radar.get("source"),
                "blips": list(radar.get("blips") or [])[:12],
            }
        except Exception:
            payload["radar"] = {"range_nm": resolved.get("options", {}).get("range_nm") or 5, "count": 0, "blips": []}
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
    }
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
