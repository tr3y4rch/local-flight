"""
localflight/decode/opensky.py

Enriches a list of Flight objects with live position data from
OpenSky Network state vectors.

Matching strategy:
  1. Exact callsign match (most reliable)
  2. Flight number prefix match (handles minor callsign variations)

Merge priority:
  - AviationStack wins: status, times, gate, terminal, airline, flight_number
  - OpenSky wins: all position fields (lat, lon, altitude, heading, speed, etc.)
  - Status override: if OpenSky says on_ground=False but AviationStack says
    Scheduled, we upgrade to Departed (aircraft is airborne)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from localflight.core.models import (
    Flight,
    FlightPosition,
    FlightStatus,
)

log = logging.getLogger(__name__)


def _parse_state_vector(sv: list) -> Optional[Dict[str, Any]]:
    """
    Parse a single OpenSky state vector list into a dict.
    Returns None if the vector is malformed or has no position.

    State vector indices:
      0  icao24, 1  callsign, 2  origin_country,
      3  time_position, 4  last_contact,
      5  longitude, 6  latitude,
      7  baro_altitude, 8  on_ground, 9  velocity,
      10 true_track, 11 vertical_rate, 12 sensors,
      13 geo_altitude, 14 squawk, 15 spi, 16 position_source
    """
    if not isinstance(sv, list) or len(sv) < 17:
        return None

    lat = sv[6]
    lon = sv[5]
    if lat is None or lon is None:
        return None

    callsign = (sv[1] or "").strip().upper()
    icao24   = (sv[0] or "").strip().upper()

    last_contact: Optional[datetime] = None
    if sv[4] is not None:
        try:
            last_contact = datetime.fromtimestamp(float(sv[4]), tz=timezone.utc)
        except Exception:
            pass

    return {
        "callsign":     callsign or icao24,
        "icao24":       icao24,
        "lat":          float(lat),
        "lon":          float(lon),
        "altitude_baro": float(sv[7])  if sv[7]  is not None else None,
        "altitude_geo":  float(sv[13]) if sv[13] is not None else None,
        "heading":       float(sv[10]) if sv[10] is not None else None,
        "speed_ms":      float(sv[9])  if sv[9]  is not None else None,
        "vertical_rate": float(sv[11]) if sv[11] is not None else None,
        "on_ground":     bool(sv[8]),
        "squawk":        str(sv[14]).strip() if sv[14] is not None else None,
        "last_contact":  last_contact,
    }


def _build_lookup(state_vectors: List[list]) -> Dict[str, Dict[str, Any]]:
    """
    Build a callsign → parsed state vector lookup dict.
    Skips vectors with no position or no callsign.
    """
    lookup: Dict[str, Dict[str, Any]] = {}
    for sv in state_vectors:
        parsed = _parse_state_vector(sv)
        if not parsed:
            continue
        cs = parsed["callsign"]
        if cs:
            lookup[cs] = parsed
    return lookup


def _match_callsign(flight: Flight, lookup: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Try to find a matching state vector for a flight.

    Strategy:
    1. Exact callsign match (e.g. SWR184 == SWR184)
    2. Flight number as callsign (e.g. LX184 in lookup)
    3. Airline ICAO + flight number digits (e.g. SWR + 184 -> SWR184)
    """
    # 1 — exact callsign
    if flight.callsign in lookup:
        return lookup[flight.callsign]

    # 2 — flight number directly (some operators file IATA as callsign)
    if flight.flight_number:
        fn = flight.flight_number.replace(" ", "").upper()
        if fn in lookup:
            return lookup[fn]

    # 3 — reconstruct ICAO callsign from airline ICAO + number
    if flight.airline.icao and flight.flight_number:
        digits = "".join(c for c in flight.flight_number if c.isdigit())
        candidate = f"{flight.airline.icao.upper()}{digits}"
        if candidate in lookup:
            return lookup[candidate]

    return None


def _should_upgrade_status(flight: Flight, pos: Dict[str, Any]) -> FlightStatus:
    """
    Optionally upgrade flight status based on live position data.

    Rules:
    - Scheduled + airborne → Departed
    - Departed + on_ground + very slow → treat as arrived (rare edge case)
    - Everything else → keep AviationStack status
    """
    current = flight.status
    on_ground = pos.get("on_ground")
    alt = pos.get("altitude_baro") or 0
    spd = pos.get("speed_ms") or 0

    airborne = (on_ground is False) or (alt > 150 and spd > 30)

    if airborne and current == FlightStatus.SCHEDULED:
        return FlightStatus.DEPARTED
    if airborne and current == FlightStatus.BOARDING:
        return FlightStatus.DEPARTED

    return current


def enrich_flights_with_opensky(
    flights: List[Flight],
    state_vectors: List[list],
) -> List[Flight]:
    """
    Match each Flight to an OpenSky state vector by callsign and
    return a new list of Flight objects with position data populated.

    Unmatched flights are returned unchanged.
    Matched flights get a FlightPosition and enriched_by="opensky".
    """
    if not state_vectors:
        return flights

    lookup = _build_lookup(state_vectors)
    enriched: List[Flight] = []
    matched = 0

    for flight in flights:
        pos = _match_callsign(flight, lookup)

        if pos is None:
            enriched.append(flight)
            continue

        matched += 1
        new_status = _should_upgrade_status(flight, pos)

        position = FlightPosition(
            lat=pos["lat"],
            lon=pos["lon"],
            altitude_baro=pos["altitude_baro"],
            altitude_geo=pos["altitude_geo"],
            heading=pos["heading"],
            speed_ms=pos["speed_ms"],
            vertical_rate=pos["vertical_rate"],
            on_ground=pos["on_ground"],
            icao24=pos["icao24"],
            squawk=pos["squawk"],
            last_contact=pos["last_contact"],
        )

        # Build enriched flight — keep all AviationStack fields, add position
        enriched_flight = Flight(
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
            status=new_status,
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
            enriched_by="opensky",
            updated_at=flight.updated_at,
        )
        enriched.append(enriched_flight)

    log.info(
        "OpenSky enrichment: %d/%d flights matched with live position data",
        matched, len(flights),
    )
    return enriched
