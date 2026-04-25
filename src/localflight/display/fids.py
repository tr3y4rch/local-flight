from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo

from localflight.decode.mappings.airports import format_airport

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

    aircraft_type = str(decoded.get("aircraft_type") or "").strip() or "-"
    flight_display = str(decoded.get("flight_display") or "").strip() or "-"
    flight_date = str(decoded.get("flight_date") or "").strip() or "unknown"
    flight_key = str(decoded.get("flight_key") or "").strip() or flight_display.replace(" ", "")

    fid = f"decoded:{flight_date}:{flight_key}"

    return FIDSRow(
        id=fid,
        view=view,
        display_time=display_time,
        flight_display=flight_display,
        route_display=route_display,
        status_display=status_display,
        gate=gate or "-",
        aircraft_type=aircraft_type,
    )
