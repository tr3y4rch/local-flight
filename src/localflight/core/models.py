from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class FlightDirection(str, Enum):
    ARRIVAL   = "ARR"
    DEPARTURE = "DEP"


class FlightStatus(str, Enum):
    SCHEDULED = "Scheduled"
    BOARDING  = "Boarding"
    DELAYED   = "Delayed"
    DEPARTED  = "Departed"
    ARRIVED   = "Arrived"
    CANCELLED = "Cancelled"
    DIVERTED  = "Diverted"
    UNKNOWN   = "Unknown"


@dataclass(frozen=True)
class AirportRef:
    iata: Optional[str] = None
    icao: Optional[str] = None
    name: Optional[str] = None

    def code(self) -> str:
        return (self.iata or self.icao or "???").upper()


@dataclass(frozen=True)
class AirlineRef:
    name: Optional[str] = None
    iata: Optional[str] = None
    icao: Optional[str] = None

    def code(self) -> str:
        return (self.iata or self.icao or "").upper()


@dataclass(frozen=True)
class FlightTime:
    scheduled: Optional[datetime] = None
    estimated: Optional[datetime] = None
    actual:    Optional[datetime] = None


@dataclass(frozen=True)
class FlightPosition:
    """
    Live position data — populated from OpenSky enrichment or VATSIM.
    All fields optional since schedule-only sources won't have position.
    """
    lat:           Optional[float]    = None   # decimal degrees
    lon:           Optional[float]    = None   # decimal degrees
    altitude_baro: Optional[float]    = None   # metres (barometric)
    altitude_geo:  Optional[float]    = None   # metres (geometric/GPS)
    heading:       Optional[float]    = None   # degrees true (0=N, clockwise)
    speed_ms:      Optional[float]    = None   # ground speed m/s
    vertical_rate: Optional[float]    = None   # m/s, positive = climbing
    on_ground:     Optional[bool]     = None
    icao24:        Optional[str]      = None   # ICAO 24-bit transponder hex
    squawk:        Optional[str]      = None   # transponder squawk code
    last_contact:  Optional[datetime] = None   # last ADS-B contact


@dataclass(frozen=True)
class Flight:
    """
    Canonical flight object used across the whole app.
    Everything from any source gets normalised into this.
    Position fields come from OpenSky enrichment or VATSIM.
    """
    direction:    FlightDirection
    airport:      AirportRef
    callsign:     str

    airline:      AirlineRef    = field(default_factory=AirlineRef)
    flight_number: Optional[str] = None
    codeshares:   tuple[str, ...] = field(default_factory=tuple)
    sold_as:      tuple[str, ...] = field(default_factory=tuple)
    marketing_airline_name: Optional[str] = None
    marketing_airline_iata: Optional[str] = None
    marketing_airline_icao: Optional[str] = None
    marketing_flight_number: Optional[str] = None
    operating_callsign: Optional[str] = None
    identity_source: Optional[str] = None
    origin:       Optional[AirportRef] = None
    destination:  Optional[AirportRef] = None
    aircraft_type: Optional[str] = None
    aircraft_type_full: Optional[str] = None
    aircraft_registration: Optional[str] = None
    gate:         Optional[str]  = None
    terminal:     Optional[str]  = None
    stand:        Optional[str]  = None
    status:       FlightStatus   = FlightStatus.UNKNOWN
    times:        FlightTime     = field(default_factory=FlightTime)
    delay_minutes: Optional[int] = None
    flight_rules: Optional[str] = None
    planned_route: Optional[str] = None
    planned_altitude: Optional[str] = None
    planned_departure: Optional[datetime] = None
    planned_arrival: Optional[datetime] = None
    planned_enroute_minutes: Optional[int] = None
    cruise_tas: Optional[int] = None
    alternate_icao: Optional[str] = None
    assigned_transponder: Optional[str] = None

    # ── Enrichment layer (OpenSky / VATSIM position data) ─────────────────────
    position:     Optional[FlightPosition] = None

    # ── Metadata ──────────────────────────────────────────────────────────────
    source:       Optional[str]      = None   # "aviationstack", "vatsim", etc.
    enriched_by:  Optional[str]      = None   # "opensky" if position was enriched
    updated_at:   Optional[datetime] = None

    def display_route(self) -> str:
        if self.direction == FlightDirection.DEPARTURE:
            a = self.airport.code()
            b = self.destination.code() if self.destination else "???"
            return f"{a} → {b}"
        else:
            a = self.origin.code() if self.origin else "???"
            b = self.airport.code()
            return f"{a} → {b}"

    def display_time(self) -> str:
        t = self.times.actual or self.times.estimated or self.times.scheduled
        if not t:
            return "--:--"
        return t.strftime("%H:%M")

    def is_airborne(self) -> bool:
        """Best-effort airborne check using position data if available."""
        if self.position:
            if self.position.on_ground is not None:
                return not self.position.on_ground
            if self.position.altitude_baro is not None:
                return self.position.altitude_baro > 150
        return self.status in (FlightStatus.DEPARTED,)

    def altitude_ft(self) -> Optional[int]:
        """Altitude in feet from position data, or None."""
        if not self.position:
            return None
        m = self.position.altitude_baro or self.position.altitude_geo
        if m is None:
            return None
        return int(m * 3.28084)

    def speed_kts(self) -> Optional[int]:
        """Ground speed in knots from position data, or None."""
        if not self.position or self.position.speed_ms is None:
            return None
        return int(self.position.speed_ms * 1.94384)
