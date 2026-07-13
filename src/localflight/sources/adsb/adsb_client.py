"""
localflight/sources/adsb/adsb_client.py

ADS-B data source via dump1090's JSON endpoint.

dump1090 runs as a separate process on the Pi and exposes aircraft data at:
  http://localhost:8080/data/aircraft.json

Installation on Pi:
  sudo apt install dump1090-fa
  sudo systemctl enable dump1090-fa
  sudo systemctl start dump1090-fa

Or run manually:
  dump1090 --net --quiet

The aircraft.json endpoint returns live position data updated every second.
We use it as a high-quality position enrichment source — same role as OpenSky
but local, free, no rate limits, and updates every few seconds.

Aircraft data fields (from dump1090):
  hex       - ICAO 24-bit address
  flight    - callsign (may have trailing spaces)
  lat, lon  - position
  altitude  - feet (barometric)
  speed     - knots ground speed
  track     - degrees true heading
  vert_rate - ft/min vertical rate
  squawk    - transponder code
  seen      - seconds since last message
  messages  - total messages received
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

# Default dump1090 endpoint — works locally on the Pi
DUMP1090_URL = "http://localhost:8080/data/aircraft.json"

# Aircraft older than this are considered stale and filtered out
MAX_SEEN_SECONDS = 60


class ADSBError(RuntimeError):
    pass


def fetch_aircraft(
    url: str = DUMP1090_URL,
    timeout_s: int = 5,
) -> List[Dict[str, Any]]:
    """
    Fetch all aircraft from dump1090's JSON endpoint.
    Returns a list of raw aircraft dicts.
    Raises ADSBError on failure.
    """
    try:
        r = requests.get(url, timeout=timeout_s)
    except requests.RequestException as exc:
        raise ADSBError(f"dump1090 request failed: {exc}") from exc

    if r.status_code >= 400:
        raise ADSBError(f"dump1090 HTTP {r.status_code}")

    try:
        data = r.json()
    except Exception as exc:
        raise ADSBError(f"dump1090 response not valid JSON: {exc}") from exc

    aircraft = data.get("aircraft") or []
    log.debug("dump1090: %d aircraft total", len(aircraft))
    return aircraft


def aircraft_to_blips(
    aircraft: List[Dict[str, Any]],
    *,
    center_lat: float,
    center_lon: float,
    radius_nm: float = 50.0,
    max_seen: int = MAX_SEEN_SECONDS,
) -> List[Dict[str, Any]]:
    """
    Convert dump1090 aircraft list to radar blip dicts.
    Filters by:
      - Has position (lat/lon)
      - Within radius_nm of center
      - Last seen within max_seen seconds

    Returns blip dicts compatible with /api/radar response format.
    """
    blips: List[Dict[str, Any]] = []
    NM_PER_DEG = 60.0

    for ac in aircraft:
        lat = ac.get("lat")
        lon = ac.get("lon")
        if lat is None or lon is None:
            continue

        seen = ac.get("seen", 999)
        if seen > max_seen:
            continue

        # Distance check
        dlat = (lat - center_lat) * NM_PER_DEG
        dlon = (lon - center_lon) * NM_PER_DEG * math.cos(math.radians(center_lat))
        dist = math.sqrt(dlat**2 + dlon**2)
        if dist > radius_nm:
            continue

        callsign = (ac.get("flight") or "").strip().upper() or ac.get("hex", "").upper()
        alt_ft   = ac.get("altitude") or 0
        gs_kts   = ac.get("speed")    or 0
        hdg      = ac.get("track")

        blips.append({
            "callsign":   callsign,
            "lat":        float(lat),
            "lon":        float(lon),
            "altitude_m": float(alt_ft) * 0.3048 if alt_ft else None,
            "heading":    float(hdg)    if hdg is not None else None,
            "speed_ms":   float(gs_kts) * 0.514444 if gs_kts else None,
            "vertical_rate": float(ac["vert_rate"]) * 0.00508 if ac.get("vert_rate") else None,
            "on_ground":  ac.get("altitude") == "ground" or (alt_ft < 100 and gs_kts < 30),
            "icao24":     ac.get("hex", "").upper(),
            "squawk":     ac.get("squawk"),
            "source":     "adsb",
            "enriched":   True,
            "distance_nm": round(dist, 1),
        })

    log.info("ADS-B: %d blips within %.0fnm of (%.4f, %.4f)", len(blips), radius_nm, center_lat, center_lon)
    return blips


def enrich_flights_with_adsb(
    flights: List[Any],
    *,
    url: str = DUMP1090_URL,
    timeout_s: int = 5,
) -> List[Any]:
    """
    Enrich a list of Flight objects with ADS-B position data.
    Same interface as enrich_flights_with_opensky() — drop-in replacement.

    Matches by callsign. Returns unchanged flights if dump1090 unavailable.
    """
    from localflight.core.models import Flight, FlightPosition
    from datetime import datetime, timezone

    try:
        aircraft = fetch_aircraft(url=url, timeout_s=timeout_s)
    except ADSBError as exc:
        log.warning("ADS-B enrichment skipped (dump1090 unavailable): %s", exc)
        return flights

    # Build callsign → aircraft lookup
    lookup: Dict[str, Dict] = {}
    for ac in aircraft:
        cs = (ac.get("flight") or "").strip().upper()
        hx = (ac.get("hex")    or "").strip().upper()
        if cs:
            lookup[cs] = ac
        if hx and hx not in lookup:
            lookup[hx] = ac

    enriched = []
    matched  = 0

    for flight in flights:
        ac = lookup.get(flight.callsign)
        if ac is None and flight.flight_number:
            fn = flight.flight_number.replace(" ", "").upper()
            ac = lookup.get(fn)

        if ac is None:
            enriched.append(flight)
            continue

        matched += 1
        alt_ft  = ac.get("altitude") or 0
        gs_kts  = ac.get("speed")    or 0

        if ac.get("altitude") == "ground":
            on_ground = True
            alt_m     = 0.0
        else:
            alt_m     = float(alt_ft) * 0.3048 if alt_ft else None
            on_ground = (alt_ft < 50 and gs_kts < 30)

        position = FlightPosition(
            lat=ac.get("lat"),
            lon=ac.get("lon"),
            altitude_baro=alt_m,
            altitude_geo=None,
            heading=float(ac["track"])     if ac.get("track")     is not None else None,
            speed_ms=float(gs_kts) * 0.514444 if gs_kts else None,
            vertical_rate=float(ac["vert_rate"]) * 0.00508 if ac.get("vert_rate") else None,
            on_ground=on_ground,
            icao24=(ac.get("hex") or "").upper(),
            squawk=ac.get("squawk"),
            last_contact=datetime.now(timezone.utc),
        )

        enriched.append(Flight(
            direction=flight.direction,
            airport=flight.airport,
            callsign=flight.callsign,
            airline=flight.airline,
            flight_number=flight.flight_number,
            codeshares=flight.codeshares,
            sold_as=flight.sold_as,
            marketing_airline_name=flight.marketing_airline_name,
            marketing_airline_iata=flight.marketing_airline_iata,
            marketing_airline_icao=flight.marketing_airline_icao,
            marketing_flight_number=flight.marketing_flight_number,
            operating_callsign=flight.operating_callsign,
            identity_source=flight.identity_source,
            provider_codeshare_status=flight.provider_codeshare_status,
            provider_movement_key=flight.provider_movement_key,
            identity_evidence=flight.identity_evidence,
            origin=flight.origin,
            destination=flight.destination,
            aircraft_type=flight.aircraft_type,
            aircraft_type_full=flight.aircraft_type_full,
            aircraft_registration=flight.aircraft_registration,
            gate=flight.gate,
            terminal=flight.terminal,
            stand=flight.stand,
            gate_source=flight.gate_source,
            terminal_source=flight.terminal_source,
            gate_confidence=flight.gate_confidence,
            terminal_confidence=flight.terminal_confidence,
            ops_location_notes=flight.ops_location_notes,
            status=flight.status,
            times=flight.times,
            delay_minutes=flight.delay_minutes,
            flight_rules=flight.flight_rules,
            planned_route=flight.planned_route,
            planned_altitude=flight.planned_altitude,
            planned_departure=flight.planned_departure,
            planned_arrival=flight.planned_arrival,
            planned_enroute_minutes=flight.planned_enroute_minutes,
            cruise_tas=flight.cruise_tas,
            alternate_icao=flight.alternate_icao,
            assigned_transponder=flight.assigned_transponder,
            position=position,
            source=flight.source,
            enriched_by="adsb",
            updated_at=flight.updated_at,
        ))

    log.info("ADS-B enrichment: %d/%d flights matched", matched, len(flights))
    return enriched


def is_dump1090_available(url: str = DUMP1090_URL, timeout_s: int = 3) -> bool:
    """Quick health check for dump1090 availability."""
    try:
        r = requests.get(url, timeout=timeout_s)
        return r.status_code == 200
    except Exception:
        return False
