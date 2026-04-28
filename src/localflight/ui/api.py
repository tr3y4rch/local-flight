"""
localflight/ui/api.py

JSON API layer for the FIDS system.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from localflight.core.airports import _load_index, lookup_airport
from localflight.core.models import Flight, FlightDirection, FlightPosition
from localflight.render.fids import build_fids_context
from localflight.storage.config import (
    ALLOWED_REFRESH_SECONDS,
    ALLOWED_SKINS,
    ALLOWED_SOURCES,
    AppConfig,
    load_config,
    save_config,
)
from localflight.storage.flights_store import load_latest_snapshot_path, snapshot_store_root
from localflight.storage.state import load_state

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
        origin=_airport(d.get("origin")),
        destination=_airport(d.get("destination")),
        aircraft_type=d.get("aircraft_type"),
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


class FIDSRowOut(BaseModel):
    id:             str
    view:           str
    display_time:   str
    flight_display: str
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
    current_cfg = load_config()
    current = asdict(current_cfg)
    scheduler_fields = {"airport_iata", "airport_icao", "refresh_seconds", "source"}
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
    limit: int = Query(20, ge=1, le=100),
) -> List[FIDSRowOut]:
    cfg = load_config()
    flights, last_refreshed = _load_latest_flights(cfg.airport_iata)
    direction = FlightDirection.DEPARTURE if view == "departures" else FlightDirection.ARRIVAL
    flights = [f for f in flights if f.direction == direction]

    def _sort_key(f: Flight):
        t = f.times.actual or f.times.estimated or f.times.scheduled
        return t if t else datetime.min.replace(tzinfo=timezone.utc)

    flights.sort(key=_sort_key)
    flights = flights[:limit]

    ctx = build_fids_context(
        cfg=cfg,
        view=view,
        refresh_seconds=cfg.refresh_seconds,
        flights=flights,
        last_refreshed=last_refreshed,
        source_status=cfg.source,
    )

    return [
        FIDSRowOut(
            id=r.id, view=r.view, display_time=r.display_time,
            flight_display=r.flight_display, route_display=r.route_display,
            status_display=r.status_display, status_class=r.status_class,
            gate=r.gate, aircraft_type=r.aircraft_type,
            callsign=r.callsign,
        )
        for r in ctx["rows"]
    ]


@router.get("/api/fids/detail")
def api_fids_detail(callsign: str = Query(..., min_length=1, max_length=20)) -> Dict[str, Any]:
    from localflight.storage.history import query_flight_history

    cfg = load_config()
    flights, _ = _load_latest_flights(cfg.airport_iata)
    flight = next((f for f in flights if (f.callsign or "").upper() == callsign.upper()), None)

    detail: Dict[str, Any] = {}
    if flight:
        pos = flight.position
        detail = {
            "callsign":      flight.callsign,
            "flight_number": flight.flight_number,
            "airline":       flight.airline.name if flight.airline else None,
            "airline_iata":  flight.airline.iata if flight.airline else None,
            "origin_iata":   flight.origin.iata        if flight.origin      else None,
            "origin_name":   flight.origin.name        if flight.origin      else None,
            "dest_iata":     flight.destination.iata   if flight.destination else None,
            "dest_name":     flight.destination.name   if flight.destination else None,
            "sched_time":    flight.times.scheduled.isoformat() if flight.times.scheduled else None,
            "est_time":      flight.times.estimated.isoformat() if flight.times.estimated else None,
            "actual_time":   flight.times.actual.isoformat()    if flight.times.actual    else None,
            "delay_minutes": flight.delay_minutes,
            "gate":          flight.gate,
            "terminal":      flight.terminal,
            "aircraft_type": flight.aircraft_type,
            "direction":     flight.direction.value,
            "status":        flight.status.value,
            "source":        flight.source,
            "enriched_by":   flight.enriched_by,
            "position": {
                "lat":           pos.lat,
                "lon":           pos.lon,
                "altitude_m":    pos.altitude_baro,
                "speed_ms":      pos.speed_ms,
                "heading":       pos.heading,
                "on_ground":     pos.on_ground,
                "vertical_rate": pos.vertical_rate,
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

@router.get("/api/radar")
def api_radar(
    radius_nm: float = Query(20.0, ge=5.0, le=200.0),  # default 20nm
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

                # â”€â”€ Filter: within bounding box â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if not (lamin <= plat <= lamax and lomin <= plon <= lomax):
                    continue

                callsign = (pilot.get("callsign") or "").strip().upper()
                if not callsign:
                    continue

                alt_ft = float(pilot.get("altitude")    or 0)
                gs_kts = float(pilot.get("groundspeed") or 0)
                hdg    = pilot.get("heading")

                blips.append({
                    "callsign":   callsign,
                    "lat":        float(plat),
                    "lon":        float(plon),
                    "altitude_m": alt_ft * 0.3048 if alt_ft else None,
                    "heading":    float(hdg) if hdg is not None else None,
                    "speed_ms":   gs_kts * 0.514444 if gs_kts else None,
                    "on_ground":  (alt_ft < 100 and gs_kts < 50),
                    "icao24":     None,
                    "squawk":     None,
                    "enriched":   False,
                })

        except Exception as exc:
            log.warning("VATSIM radar fetch failed: %s", exc)
            raise HTTPException(status_code=503, detail=f"VATSIM radar unavailable: {exc}")

    else:
        # Real source: ADS-B Exchange first, then local snapshot/OpenSky fallback.
        now_ts = time.monotonic()
        adsbx_cache_key = f"{cfg.airport_iata}:{round(radius_nm, 1)}"
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
                    blips = cached[1]
                    source_used = "adsbexchange_cached"
                    log.debug("ADS-B Exchange radar: serving cached blips for %s", adsbx_cache_key)
                else:
                    source_used = "adsbexchange_live"
                    aircraft = fetch_aircraft(
                        lat=center_lat,
                        lon=center_lon,
                        radius_nm=radius_nm,
                    )
                    blips = aircraft_to_blips(
                        aircraft=aircraft,
                        center_lat=center_lat,
                        center_lon=center_lon,
                        radius_nm=radius_nm,
                    )
                    _adsbx_radar_cache[adsbx_cache_key] = (now_ts, blips)
                    log.info("ADS-B Exchange radar: fetched %d blips for %s", len(blips), adsbx_cache_key)
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

    return {
        "center":    {"lat": center_lat, "lon": center_lon},
        "radius_nm": radius_nm,
        "source":    source_used,
        "refresh_after_s": _radar_refresh_after_s(source_used),
        "count":     len(blips),
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
    """
    from localflight.sources.web.metar_client import fetch_metar
 
    cfg        = load_config()
    icao_code  = (icao or cfg.airport_icao or "LSZH").upper().strip()
 
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
        _ver = "0.2.3b2"

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
        result["client"] = {
            "mode": usage.get("active_mode") or usage.get("mode") or "virtual",
            "relay_url": managed.get("relay_url") or community.get("relay_url"),
            "activation_token_present": bool(managed.get("token_present")),
            "activation_token_prefix": managed.get("token_prefix") or "",
            "community_key_present": bool(community.get("key_present")),
            "managed_verified": bool(managed.get("status_ok")),
            "managed_status": managed.get("status_error") or "",
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
        current = "0.2.3b2"

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


@router.post("/api/feedback")
def api_submit_feedback(body: FeedbackIn) -> Dict[str, Any]:
    """Submit a bug report / feedback to the Local Flight developer's Linear board."""
    from localflight.sources.web.bug_reporter import submit_report
    result = submit_report(body.title, body.description, client_context=body.client_context)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result.get("error", "Submission failed"))
    return {"ok": True, "url": result.get("url")}


class FeedbackCrashIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    traceback: str = Field("", max_length=5000)
    context: str = Field("mobile", max_length=120)
    client_context: str = Field("", max_length=2000)


@router.post("/api/feedback/crash")
def api_submit_feedback_crash(body: FeedbackCrashIn) -> Dict[str, Any]:
    """Submit an auto-filed mobile crash report to the developer's Linear board."""
    from localflight.sources.web.bug_reporter import submit_crash

    result = submit_crash(
        body.message,
        traceback_str=body.traceback,
        context=body.context or "mobile",
        client_context=body.client_context,
    )
    if not result["ok"]:
        error = result.get("error", "Crash submission failed")
        status = 409 if "duplicate" in error.lower() else 502
        raise HTTPException(status_code=status, detail=error)
    return {"ok": True, "url": result.get("url")}


# â”€â”€ Standalone app â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

try:
    from fastapi import FastAPI as _FastAPI
    from fastapi.middleware.cors import CORSMiddleware as _CORS
    app = _FastAPI(title="LocalFlight API", docs_url="/api/docs")
    app.add_middleware(_CORS, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
except ImportError:
    app = None  # type: ignore
