from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from localflight.core.aircraft import short_aircraft_type
from localflight.decode.mappings.airports import format_airport
from localflight.core.ops_location import display_location_fields

FidsView = Literal["arrivals", "departures"]
_ZRH_TZ = ZoneInfo("Europe/Zurich")


@dataclass(frozen=True, slots=True)
class FIDSRow:
    id: str
    view: FidsView

    display_time:   str   # "12:10 (+15)"
    flight_display: str   # "LX 333"
    route_display:  str   # "London (LHR)"
    status_display: str   # "DELAYED +23M" / "APPR 18NM" / "BOARDING" …
    status_class:   str   # CSS category: delayed | approaching | boarding | departed | landed | cancelled | diverted | scheduled
    gate:           str   # "A12" or "-"
    aircraft_type:  str   # "A320" or "-"
    callsign:       str = ""
    airline_display: str = ""  # "SWISS"
    codeshare_display: str = ""  # "Also UA 123 / AC 456"
    flight_number: str = ""
    airline_iata: str = ""
    airline_icao: str = ""
    codeshares: tuple[str, ...] = ()
    sold_as: tuple[str, ...] = ()
    marketing_airline_name: str = ""
    marketing_airline_iata: str = ""
    marketing_airline_icao: str = ""
    marketing_flight_number: str = ""
    operating_callsign: str = ""
    identity_source: str = ""
    provider_codeshare_status: str = ""
    provider_movement_key: str = ""
    identity_evidence: tuple[str, ...] = ()
    delay_minutes: Optional[int] = None
    delay_class: str = ""  # early | warn | bad
    time_primary: str = ""
    time_delta_label: str = ""
    time_delta_text: str = ""
    delay_kind: str = "none"  # none | early | warn | bad
    status_kind: str = "scheduled"
    tone: str = "neutral"  # neutral | green | amber | red | orange | dim
    gate_display: str = ""
    terminal_display: str = ""
    terminal_gate_display: str = ""
    gate_source: str = ""
    terminal_source: str = ""
    gate_confidence: str = ""
    terminal_confidence: str = ""
    ops_location_notes: tuple[str, ...] = ()
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


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # handle "Z" suffix
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _to_local_hhmm(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_ZRH_TZ)
    return dt.astimezone(_ZRH_TZ).strftime("%H:%M")


def _delay_minutes(scheduled: Optional[datetime], estimated: Optional[datetime]) -> int:
    if not scheduled or not estimated:
        return 0

    s = scheduled if scheduled.tzinfo else scheduled.replace(tzinfo=_ZRH_TZ)
    e = estimated if estimated.tzinfo else estimated.replace(tzinfo=_ZRH_TZ)

    s = s.astimezone(_ZRH_TZ)
    e = e.astimezone(_ZRH_TZ)

    return int(round((e - s).total_seconds() / 60.0))


def _delay_class(minutes: int) -> str:
    if abs(minutes) < 5:
        return ""
    if minutes < 0:
        return "early"
    if minutes > 15:
        return "bad"
    return "warn"


def delay_kind_from_minutes(minutes: Optional[int]) -> str:
    if not isinstance(minutes, int) or abs(minutes) < 5:
        return "none"
    if minutes < 0:
        return "early"
    if minutes > 15:
        return "bad"
    return "warn"


def split_display_time(value: Any, delay_minutes: Optional[int] = None) -> tuple[str, str, str]:
    text = str(value or "").strip()
    match = re.match(r"^(.+?)\s*\(([+-]?\d+)\)\s*$", text)
    if match:
        primary = match.group(1).strip()
        label = match.group(2).strip()
    else:
        primary = text or "--:--"
        label = ""
    if not label and isinstance(delay_minutes, int) and abs(delay_minutes) >= 5:
        sign = "+" if delay_minutes > 0 else "-"
        label = f"{sign}{abs(delay_minutes)}"
    delta_text = ""
    if label:
        try:
            minutes = int(label)
        except ValueError:
            minutes = delay_minutes
        if isinstance(minutes, int):
            delta_text = f"{abs(minutes)} min early" if minutes < 0 else f"{minutes} min late"
    return primary, label, delta_text


def split_route_display(value: Any) -> tuple[str, str, str]:
    text = str(value or "").strip()
    if not text or text == "-":
        return "-", "", ""
    match = re.search(r"\(([A-Z0-9]{3,4})\)\s*$", text.upper())
    if match:
        code = match.group(1)
        primary = re.sub(r"\s*\([A-Za-z0-9]{3,4}\)\s*$", "", text).strip() or code
        return primary, code, code
    upper = text.upper()
    if re.fullmatch(r"[A-Z0-9]{3,4}", upper):
        return upper, upper, ""
    tail = re.search(r"\b([A-Z0-9]{3,4})$", upper)
    code = tail.group(1) if tail else ""
    return text, code, code


def gate_fields(
    gate: Any,
    terminal: Any = "",
    gate_confidence: Any = "",
    terminal_confidence: Any = "",
    ops_location_notes: Any = (),
) -> tuple[str, str, str]:
    return display_location_fields(
        gate,
        terminal,
        gate_confidence_value=gate_confidence,
        terminal_confidence_value=terminal_confidence,
        notes=ops_location_notes,
    )


def normalize_status_kind(status_class: Any = "", status_display: Any = "", delay_kind: str = "none") -> str:
    raw = str(status_class or status_display or "scheduled")
    normalized = raw.strip().lower().replace("_", "-").replace(" ", "-")
    if normalized in {"delayed-warn", "delayed"} or delay_kind == "warn":
        return "delayed_warn"
    if normalized == "delayed-bad" or delay_kind == "bad":
        return "delayed_bad"
    if "cancel" in normalized:
        return "cancelled"
    if "divert" in normalized:
        return "diverted"
    if "board" in normalized:
        return "boarding"
    if "approach" in normalized or normalized.startswith("appr"):
        return "approaching"
    if "depart" in normalized:
        return "departed"
    if "land" in normalized or normalized == "arrived":
        return "landed"
    if "ground" in normalized:
        return "on_ground"
    return "scheduled"


def tone_for_status(status_kind: str, delay_kind: str = "none") -> str:
    if status_kind == "cancelled" or delay_kind == "bad" or status_kind == "delayed_bad":
        return "red"
    if status_kind == "diverted":
        return "orange"
    if status_kind in {"departed", "landed"}:
        return "dim"
    if delay_kind == "early" or status_kind == "boarding":
        return "green"
    if status_kind in {"approaching", "on_ground", "delayed_warn"} or delay_kind == "warn":
        return "amber"
    return "neutral"


def enrich_presentation_fields(row: dict[str, Any]) -> dict[str, Any]:
    shaped = dict(row)
    delay_minutes = shaped.get("delay_minutes")
    try:
        delay_i = int(delay_minutes) if delay_minutes is not None else None
    except (TypeError, ValueError):
        delay_i = None
    delay_kind = str(shaped.get("delay_kind") or delay_kind_from_minutes(delay_i))
    if delay_kind == "none" and shaped.get("delay_class"):
        delay_kind = {"early": "early", "warn": "warn", "bad": "bad"}.get(str(shaped.get("delay_class")).lower(), "none")
    time_primary, delta_label, delta_text = split_display_time(shaped.get("display_time"), delay_i)
    route_primary, route_code, route_caption = split_route_display(shaped.get("route_display"))
    gate_display, terminal_display, terminal_gate_display = gate_fields(
        shaped.get("gate_display") or shaped.get("gate"),
        shaped.get("terminal_display") or shaped.get("terminal"),
        shaped.get("gate_confidence"),
        shaped.get("terminal_confidence"),
        shaped.get("ops_location_notes"),
    )
    status_kind = normalize_status_kind(shaped.get("status_class"), shaped.get("status_display"), delay_kind)
    tone = tone_for_status(status_kind, delay_kind)
    shaped.update(
        {
            "time_primary": shaped.get("time_primary") or time_primary,
            "time_delta_label": shaped.get("time_delta_label") or delta_label,
            "time_delta_text": shaped.get("time_delta_text") or delta_text,
            "delay_kind": delay_kind,
            "status_kind": shaped.get("status_kind") or status_kind,
            "tone": shaped.get("tone") or tone,
            "gate_display": gate_display,
            "terminal_display": terminal_display,
            "terminal_gate_display": terminal_gate_display,
            "route_primary": shaped.get("route_primary") or route_primary,
            "route_code": shaped.get("route_code") or route_code,
            "route_caption": shaped.get("route_caption") or route_caption,
        }
    )
    return shaped


def _status_display(
    *,
    view: FidsView,
    flight_status: str,
    dep_actual: Optional[datetime],
    arr_actual: Optional[datetime],
    scheduled: Optional[datetime],
    estimated: Optional[datetime],
) -> str:
    fs = (flight_status or "").strip().lower()

    if fs in {"canceled", "cancelled"}:
        return "CANCELED"

    # Completed beats everything
    if view == "departures" and dep_actual is not None:
        return "DEPARTED"
    if view == "arrivals" and arr_actual is not None:
        return "LANDED"

    # Delay/early if meaningful
    mins = _delay_minutes(scheduled, estimated)
    if abs(mins) >= 5:
        return f"DELAYED {mins} MIN" if mins > 0 else f"EARLY {abs(mins)} MIN"

    return "ON TIME"


def _route_display_from_code(code: str) -> str:
    """
    Offline: derive city from our built-in airport index.
    Render as "City (CODE)" when possible, else "CODE" or "-".
    """
    c = (code or "").strip().upper()
    if not c:
        return "-"

    city = (format_airport(c, prefer="city") or "").strip()
    if city and city != c:
        return f"{city} ({c})"
    return c


def decoded_to_fids_row(decoded: dict[str, Any], *, view: FidsView) -> FIDSRow:
    """
    Input: a decoded/normalized dict produced by decode/mappings (NOT raw API).
    Formatting for display belongs here in display/.
    """
    dep: dict[str, Any] = decoded.get("departure") or {}
    arr: dict[str, Any] = decoded.get("arrival") or {}

    # Parse actual times once (used for status)
    dep_actual = _parse_dt(dep.get("actual"))
    arr_actual = _parse_dt(arr.get("actual"))

    # Select board-side fields based on view
    if view == "departures":
        sched = _parse_dt(dep.get("scheduled"))
        est = _parse_dt(dep.get("estimated"))

        # Prefer IATA, fall back to ICAO if your decoder provides it
        route_code = str(arr.get("iata") or arr.get("icao") or "").strip()
        gate = str(dep.get("gate") or "").strip()
    else:
        sched = _parse_dt(arr.get("scheduled"))
        est = _parse_dt(arr.get("estimated"))

        route_code = str(dep.get("iata") or dep.get("icao") or "").strip()
        gate = str(arr.get("gate") or "").strip()

    # Time display: "HH:MM" or "HH:MM (+15)"
    hhmm_sched = _to_local_hhmm(sched)
    hhmm_est = _to_local_hhmm(est)

    display_time = hhmm_sched or "--:--"
    mins = _delay_minutes(sched, est)
    if hhmm_sched and hhmm_est and abs(mins) >= 5:
        sign = "+" if mins > 0 else "-"
        display_time = f"{hhmm_sched} ({sign}{abs(mins)})"

    # Route display (offline mapping)
    route_display = _route_display_from_code(route_code)

    status_display = _status_display(
        view=view,
        flight_status=str(decoded.get("flight_status") or ""),
        dep_actual=dep_actual,
        arr_actual=arr_actual,
        scheduled=sched,
        estimated=est,
    )
    status_class = status_display.lower().replace(" ", "-")
    if status_class.startswith("delayed"):
        status_class = f"delayed-{_delay_class(mins) or 'warn'}"
    elif status_class.startswith("early"):
        status_class = "early"
    elif status_class == "on-time":
        status_class = "scheduled"

    aircraft_type = short_aircraft_type(decoded.get("aircraft_type")) or "-"
    flight_display = str(decoded.get("flight_display") or "").strip() or "-"
    flight_date = str(decoded.get("flight_date") or "").strip() or "unknown"
    flight_key = str(decoded.get("flight_key") or "").strip() or flight_display.replace(" ", "")
    terminal = str((dep if view == "departures" else arr).get("terminal") or "").strip()
    delay_kind = delay_kind_from_minutes(mins)
    time_primary, time_delta_label, time_delta_text = split_display_time(display_time, mins)
    route_primary, route_code, route_caption = split_route_display(route_display)
    gate_display, terminal_display, terminal_gate_display = gate_fields(gate, terminal)
    status_kind = normalize_status_kind(status_class, status_display, delay_kind)
    tone = tone_for_status(status_kind, delay_kind)

    fid = f"decoded:{flight_date}:{flight_key}"

    return FIDSRow(
        id=fid,
        view=view,
        display_time=display_time,
        flight_display=flight_display,
        route_display=route_display,
        status_display=status_display,
        status_class=status_class,
        gate=gate_display or "-",
        aircraft_type=aircraft_type,
        delay_minutes=mins,
        delay_class=_delay_class(mins),
        time_primary=time_primary,
        time_delta_label=time_delta_label,
        time_delta_text=time_delta_text,
        delay_kind=delay_kind,
        status_kind=status_kind,
        tone=tone,
        gate_display=gate_display,
        terminal_display=terminal_display,
        terminal_gate_display=terminal_gate_display,
        route_primary=route_primary,
        route_code=route_code,
        route_caption=route_caption,
    )
