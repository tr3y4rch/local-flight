from __future__ import annotations

import math
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from localflight.core.models import Flight, FlightDirection, FlightStatus
from localflight.decode.mappings.airlines import format_flight_identifier
from localflight.decode.mappings.airports import format_airport
from localflight.display.fids import FIDSRow, FidsView


def _resolve_tz(f: Flight) -> ZoneInfo:
    try:
        from localflight.storage.config import load_config
        tz_name = load_config().timezone or "Europe/Zurich"
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Europe/Zurich")


def _to_local_hhmm(dt: Optional[datetime], tz: ZoneInfo) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz).strftime("%H:%M")


def _best_time(f: Flight) -> Optional[datetime]:
    return f.times.actual or f.times.estimated or f.times.scheduled


def _route_display_from_code(code: str) -> str:
    c = (code or "").strip().upper()
    if not c:
        return "-"
    city = (format_airport(c, prefer="city") or "").strip()
    if city and city != c:
        return f"{city} ({c})"
    return c


def _format_flight_number(f: Flight) -> str:
    return format_flight_identifier(
        flight_number=f.flight_number,
        callsign=f.callsign,
        airline_iata=f.airline.iata if f.airline else None,
        airline_icao=f.airline.icao if f.airline else None,
    )


def _airline_display(f: Flight) -> str:
    if f.airline and f.airline.name:
        return f.airline.name
    if f.airline and f.airline.code():
        return f.airline.code()
    return ""


def _codeshare_display(f: Flight) -> str:
    values = [str(item or "").strip().upper() for item in f.codeshares]
    values = [item for item in values if item]
    if not values:
        return ""
    shown = values[:4]
    suffix = f" +{len(values) - len(shown)}" if len(values) > len(shown) else ""
    return "Also " + " / ".join(shown) + suffix


def _nm_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in nautical miles."""
    R = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _is_on_ground(f: Flight) -> Optional[bool]:
    """Best-effort on-ground check from position data."""
    pos = f.position
    if not pos:
        return None
    if pos.on_ground is not None:
        return pos.on_ground
    # Derive: below 50 m barometric AND slow (< 15 m/s ≈ 30 kts)
    if pos.altitude_baro is not None and pos.speed_ms is not None:
        return pos.altitude_baro < 50 and pos.speed_ms < 15
    return None


def _compute_status(
    f: Flight,
    airport_lat: Optional[float],
    airport_lon: Optional[float],
) -> tuple[str, str]:
    """
    Returns (status_display, status_class).

    Priority order:
      1. Approaching  — position within 50 nm, not on ground (arrivals only)
      2. On ground    — landed or taxiing
      3. Delayed      — delay_minutes >= 15 (real source only)
      4. Source status — boarding, departed, cancelled, diverted, etc.
      5. Scheduled    — fallback
    """
    pos = f.position
    on_ground = _is_on_ground(f)

    # 1. Approaching (arrivals only)
    if (
        f.direction == FlightDirection.ARRIVAL
        and not on_ground
        and pos and pos.lat is not None and pos.lon is not None
        and airport_lat is not None and airport_lon is not None
    ):
        nm = _nm_between(pos.lat, pos.lon, airport_lat, airport_lon)
        if nm <= 50:
            return f"APPR {int(nm)}NM", "approaching"

    # 2. On ground
    if on_ground:
        if f.direction == FlightDirection.ARRIVAL:
            return "LANDED", "landed"
        return "ON GROUND", "on-ground"

    # 3. Delayed (only meaningful when we have schedule data)
    dly = f.delay_minutes
    if isinstance(dly, int) and dly >= 15:
        return f"DELAYED +{dly}M", "delayed"

    # 4. Source-authoritative status
    _MAP: dict[FlightStatus, tuple[str, str]] = {
        FlightStatus.BOARDING:  ("BOARDING",  "boarding"),
        FlightStatus.DEPARTED:  ("DEPARTED",  "departed"),
        FlightStatus.ARRIVED:   ("ARRIVED",   "landed"),
        FlightStatus.CANCELLED: ("CANCELLED", "cancelled"),
        FlightStatus.DIVERTED:  ("DIVERTED",  "diverted"),
        FlightStatus.DELAYED:   ("DELAYED",   "delayed"),
        FlightStatus.SCHEDULED: ("SCHEDULED", "scheduled"),
        FlightStatus.UNKNOWN:   ("SCHEDULED", "scheduled"),
    }
    return _MAP.get(f.status, ("SCHEDULED", "scheduled"))


def flight_to_fids_row(
    f: Flight,
    *,
    view: FidsView,
    airport_lat: Optional[float] = None,
    airport_lon: Optional[float] = None,
    display_tz: Optional[ZoneInfo] = None,
) -> FIDSRow:
    tz = display_tz or _resolve_tz(f)
    t  = _best_time(f)
    display_time = _to_local_hhmm(t, tz) or "--:--"

    dly = getattr(f, "delay_minutes", None)
    if isinstance(dly, int) and abs(dly) >= 5 and display_time != "--:--":
        sign = "+" if dly > 0 else "-"
        display_time = f"{display_time} ({sign}{abs(dly)})"

    flight_display = _format_flight_number(f)
    airline_display = _airline_display(f)
    codeshare_display = _codeshare_display(f)

    other = f.destination if view == "departures" else f.origin
    route_display = _route_display_from_code(other.code() if other else "")

    gate          = f.gate or "-"
    aircraft_type = f.aircraft_type or "-"
    fid = f"{f.source or 'src'}:{f.callsign}:{t.isoformat() if t else 'notime'}"

    status_display, status_class = _compute_status(f, airport_lat, airport_lon)

    return FIDSRow(
        id=fid,
        view=view,
        display_time=display_time,
        flight_display=flight_display,
        airline_display=airline_display,
        codeshare_display=codeshare_display,
        route_display=route_display,
        status_display=status_display,
        status_class=status_class,
        gate=gate,
        aircraft_type=aircraft_type,
        callsign=f.callsign or "",
    )
