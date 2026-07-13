from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from localflight.core.aircraft import short_aircraft_type
from localflight.core.models import Flight, FlightDirection, FlightStatus
from localflight.decode.mappings.airlines import format_flight_identifier
from localflight.decode.mappings.airports import format_airport
from localflight.display.fids import (
    FIDSRow,
    FidsView,
    delay_kind_from_minutes,
    gate_fields,
    normalize_status_kind,
    split_display_time,
    split_route_display,
    tone_for_status,
)


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
    return _space_flight_token(format_flight_identifier(
        flight_number=f.flight_number,
        callsign=f.callsign,
        airline_iata=f.airline.iata if f.airline else None,
        airline_icao=f.airline.icao if f.airline else None,
    ))


def _airline_display(f: Flight) -> str:
    if f.airline and f.airline.name:
        return f.airline.name
    if f.airline and f.airline.code():
        return f.airline.code()
    return ""


def _codeshare_display(f: Flight) -> str:
    sold_as = [_format_secondary_identifier(item) for item in f.sold_as]
    sold_as = [item for item in sold_as if item]
    sold_compact = {item.replace(" ", "") for item in sold_as}
    also = [_format_secondary_identifier(item) for item in f.codeshares]
    also = [item for item in also if item and item.replace(" ", "") not in sold_compact]
    if not sold_as and not also:
        return ""
    if sold_as:
        shown_sold = sold_as[:3]
        suffix = f" +{len(sold_as) - len(shown_sold)}" if len(sold_as) > len(shown_sold) else ""
        if also:
            shown_also = also[:2]
            also_suffix = f" +{len(also) - len(shown_also)}" if len(also) > len(shown_also) else ""
            return "Sold as " + " / ".join(shown_sold) + suffix + " · Also " + " / ".join(shown_also) + also_suffix
        return "Sold as " + " / ".join(shown_sold) + suffix
    shown = also[:4]
    suffix = f" +{len(also) - len(shown)}" if len(also) > len(shown) else ""
    return "Also " + " / ".join(shown) + suffix


def _is_virtual_flight(f: Flight, *, virtual_mode: bool = False) -> bool:
    source = str(f.source or "").strip().lower()
    return bool(virtual_mode or source == "vatsim" or source.startswith("vatsim"))


def _format_secondary_identifier(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return _space_flight_token(format_flight_identifier(flight_number=raw).strip().upper())


def _space_flight_token(value: str) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"^([A-Z0-9]{2,3})\s*([0-9][A-Z0-9]*)$", r"\1 \2", text)


def _delay_class(delay_minutes: Optional[int]) -> str:
    if not isinstance(delay_minutes, int) or abs(delay_minutes) < 5:
        return ""
    if delay_minutes < 0:
        return "early"
    if delay_minutes > 15:
        return "bad"
    return "warn"


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

    # 2. Delay/early (only meaningful when we have schedule data)
    # Keep this before completed/on-ground so early landings stay visible green.
    dly = f.delay_minutes
    delay_cls = _delay_class(dly)
    if delay_cls == "early":
        return f"EARLY {abs(dly)}M", "early"
    if delay_cls == "warn":
        return f"DELAYED +{dly}M", "delayed-warn"
    if delay_cls == "bad":
        return f"DELAYED +{dly}M", "delayed-bad"

    # 3. On ground
    if on_ground:
        if f.direction == FlightDirection.ARRIVAL:
            return "LANDED", "landed"
        return "ON GROUND", "on-ground"

    # 4. Source-authoritative status
    _MAP: dict[FlightStatus, tuple[str, str]] = {
        FlightStatus.BOARDING:  ("BOARDING",  "boarding"),
        FlightStatus.DEPARTED:  ("DEPARTED",  "departed"),
        FlightStatus.ARRIVED:   ("ARRIVED",   "landed"),
        FlightStatus.CANCELLED: ("CANCELLED", "cancelled"),
        FlightStatus.DIVERTED:  ("DIVERTED",  "diverted"),
        FlightStatus.DELAYED:   ("DELAYED",   "delayed-warn"),
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
    virtual_mode: bool = False,
) -> FIDSRow:
    is_virtual = _is_virtual_flight(f, virtual_mode=virtual_mode)
    tz = display_tz or _resolve_tz(f)
    t  = _best_time(f)
    display_time = _to_local_hhmm(t, tz) or "--:--"

    dly = None if is_virtual else getattr(f, "delay_minutes", None)
    delay_class = _delay_class(dly)
    if isinstance(dly, int) and abs(dly) >= 5 and display_time != "--:--":
        sign = "+" if dly > 0 else "-"
        display_time = f"{display_time} ({sign}{abs(dly)})"

    flight_display = str(f.callsign or f.flight_number or "").strip().upper() if is_virtual else _format_flight_number(f)
    airline_display = "" if is_virtual else _airline_display(f)
    codeshare_display = "" if is_virtual else _codeshare_display(f)

    other = f.destination if view == "departures" else f.origin
    route_display = _route_display_from_code(other.code() if other else "")

    aircraft_type = short_aircraft_type(f.aircraft_type) or "-"
    fid = f"{f.source or 'src'}:{f.callsign}:{t.isoformat() if t else 'notime'}"

    status_display, status_class = _compute_status(f, airport_lat, airport_lon)
    time_primary, time_delta_label, time_delta_text = split_display_time(display_time, dly if isinstance(dly, int) else None)
    delay_kind = delay_kind_from_minutes(dly if isinstance(dly, int) else None)
    route_primary, route_code, route_caption = split_route_display(route_display)
    gate_display, terminal_display, terminal_gate_display = ("", "", "") if is_virtual else gate_fields(
        f.gate,
        f.terminal,
        f.gate_confidence,
        f.terminal_confidence,
        f.ops_location_notes,
    )
    gate = "-" if is_virtual else (gate_display or "-")
    status_kind = normalize_status_kind(status_class, status_display, delay_kind)
    tone = tone_for_status(status_kind, delay_kind)
    live_hint = ""
    if status_class == "approaching":
        live_hint = status_display.replace("APPR", "Approaching").replace("NM", " NM")
    if is_virtual and not live_hint:
        live_hint = "VATSIM track" if f.position else "Filed plan"
    source_parts = [str(part) for part in (f.source, f.enriched_by) if part]
    source_hint = " + ".join(source_parts)
    squawk = str(f.assigned_transponder or (f.position.squawk if f.position else "") or "").strip()

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
        flight_number=f.flight_number or "",
        airline_iata="" if is_virtual else (f.airline.iata or ""),
        airline_icao="" if is_virtual else (f.airline.icao or ""),
        codeshares=() if is_virtual else tuple(f.codeshares or ()),
        sold_as=() if is_virtual else tuple(f.sold_as or ()),
        marketing_airline_name="" if is_virtual else (f.marketing_airline_name or ""),
        marketing_airline_iata="" if is_virtual else (f.marketing_airline_iata or ""),
        marketing_airline_icao="" if is_virtual else (f.marketing_airline_icao or ""),
        marketing_flight_number="" if is_virtual else (f.marketing_flight_number or ""),
        operating_callsign=f.operating_callsign or "",
        identity_source=f.identity_source or ("vatsim_callsign" if is_virtual else ""),
        provider_codeshare_status="" if is_virtual else (f.provider_codeshare_status or ""),
        provider_movement_key="" if is_virtual else (f.provider_movement_key or ""),
        identity_evidence=() if is_virtual else tuple(f.identity_evidence or ()),
        delay_minutes=dly if isinstance(dly, int) else None,
        delay_class=delay_class,
        time_primary=time_primary,
        time_delta_label=time_delta_label,
        time_delta_text=time_delta_text,
        delay_kind=delay_kind,
        status_kind=status_kind,
        tone=tone,
        gate_display=gate_display,
        terminal_display=terminal_display,
        terminal_gate_display=terminal_gate_display,
        gate_source="" if is_virtual else (f.gate_source or ""),
        terminal_source="" if is_virtual else (f.terminal_source or ""),
        gate_confidence="" if is_virtual else (f.gate_confidence or ""),
        terminal_confidence="" if is_virtual else (f.terminal_confidence or ""),
        ops_location_notes=() if is_virtual else tuple(f.ops_location_notes or ()),
        route_primary=route_primary,
        route_code=route_code,
        route_caption=route_caption,
        source_hint=source_hint,
        live_hint=live_hint,
        detail_mode="virtual" if is_virtual else "real",
        flight_rules=f.flight_rules or "",
        planned_altitude=f.planned_altitude or "",
        planned_route=f.planned_route or "",
        altitude_ft=f.altitude_ft(),
        ground_speed_kt=f.speed_kts(),
        squawk=squawk,
        transponder=squawk,
    )
