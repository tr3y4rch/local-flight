from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

from localflight.core.models import Flight, FlightDirection
from localflight.decode.mappings.airlines import format_flight_identifier


def _best_time(f: Flight) -> Optional[datetime]:
    return f.times.actual or f.times.estimated or f.times.scheduled


def _route_key(f: Flight) -> Tuple[str, str]:
    """
    Returns (origin_code, destination_code) consistently for grouping.
    """
    if f.direction == FlightDirection.DEPARTURE:
        a = f.airport.code()
        b = f.destination.code() if f.destination else "???"
        return (a, b)
    else:
        a = f.origin.code() if f.origin else "???"
        b = f.airport.code()
        return (a, b)


def _bucket_time(dt: Optional[datetime], minutes: int) -> Optional[datetime]:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # round down to bucket
    discard = (dt.minute % minutes) * 60 + dt.second
    return dt.replace(second=0, microsecond=0) - timedelta(seconds=discard)


def _marketing_identifier(f: Flight) -> str:
    return format_flight_identifier(
        flight_number=f.flight_number,
        callsign=f.callsign,
        airline_iata=f.airline.iata if f.airline else None,
        airline_icao=f.airline.icao if f.airline else None,
    ).strip().upper()


def _format_codeshare_text(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return format_flight_identifier(flight_number=raw).strip().upper()


def _codeshares_for(primary: Flight, items: list[Flight]) -> tuple[str, ...]:
    primary_id = _marketing_identifier(primary)
    seen = {primary_id}
    out: list[str] = []

    for existing in primary.codeshares:
        text = _format_codeshare_text(str(existing or "").strip())
        if text and text not in seen:
            seen.add(text)
            out.append(text)

    for item in items:
        for candidate in [_marketing_identifier(item), *item.codeshares]:
            text = _format_codeshare_text(str(candidate or "").strip())
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
    return tuple(out)


def dedupe_codeshares(
    flights: Iterable[Flight],
    *,
    preferred_airline_iata: Optional[List[str]] = None,
    time_bucket_minutes: int = 5,
) -> List[Flight]:
    """
    Drop likely codeshare duplicates and keep a single 'primary' flight per group.
    """
    preferred = [x.upper() for x in (preferred_airline_iata or [])]
    groups: dict[tuple, list[Flight]] = {}

    for f in flights:
        t_bucket = _bucket_time(_best_time(f), time_bucket_minutes)
        o, d = _route_key(f)
        key = (f.direction.value, o, d, t_bucket)
        groups.setdefault(key, []).append(f)

    out: List[Flight] = []

    for items in groups.values():
        if len(items) == 1:
            out.append(items[0])
            continue

        def score(x: Flight) -> tuple:
            airline = (x.airline.iata or "").upper()
            pref = 1 if airline in preferred else 0
            has_actual = 1 if x.times.actual else 0
            has_est = 1 if x.times.estimated else 0
            return (pref, has_actual, has_est, x.callsign)

        primary = sorted(items, key=score, reverse=True)[0]
        out.append(replace(primary, codeshares=_codeshares_for(primary, items)))

    # stable sort
    out.sort(key=lambda x: (_best_time(x) or datetime.min.replace(tzinfo=timezone.utc)))
    return out
