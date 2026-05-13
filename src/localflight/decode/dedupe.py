from __future__ import annotations

import re
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


def _compact_identifier(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _identity_source_score(f: Flight) -> int:
    source = (f.identity_source or "").strip().lower()
    if source == "explicit_operating":
        return 5
    if source in {"callsign", "airport_codeshare_hint"}:
        return 4 if source == "callsign" else 3
    if source == "provider":
        return 3
    return 0


def _provider_main_score(f: Flight) -> int:
    primary = _compact_identifier(_marketing_identifier(f))
    marketed = _compact_identifier(f.marketing_flight_number or "")
    return 1 if primary and marketed and primary == marketed and not (f.sold_as or ()) else 0


def _completion_score(f: Flight) -> int:
    return sum(
        1
        for value in (
            f.gate,
            f.terminal,
            f.aircraft_type,
            f.aircraft_registration,
            f.times.actual,
            f.times.estimated,
            f.times.scheduled,
        )
        if value
    )


def _alias_values(f: Flight) -> list[str]:
    return [
        _marketing_identifier(f),
        f.callsign,
        f.operating_callsign or "",
        f.flight_number or "",
        f.marketing_flight_number or "",
        *(f.codeshares or ()),
        *(f.sold_as or ()),
    ]


def _identity_aliases(f: Flight) -> set[str]:
    return {
        compact
        for compact in (_compact_identifier(_format_codeshare_text(value)) for value in _alias_values(f))
        if compact
    }


def _codeshares_for(primary: Flight, items: list[Flight]) -> tuple[str, ...]:
    primary_id = _marketing_identifier(primary)
    primary_compact = _compact_identifier(primary_id)
    seen = {primary_compact}
    out: list[str] = []

    for existing in [*(primary.sold_as or ()), *(primary.codeshares or ())]:
        text = _format_codeshare_text(str(existing or "").strip())
        compact = _compact_identifier(text)
        if text and compact and compact not in seen:
            seen.add(compact)
            out.append(text)

    for item in items:
        for candidate in [_marketing_identifier(item), item.marketing_flight_number or "", *(item.sold_as or ()), *(item.codeshares or ())]:
            text = _format_codeshare_text(str(candidate or "").strip())
            compact = _compact_identifier(text)
            if not text or not compact or compact in seen:
                continue
            seen.add(compact)
            out.append(text)
    return tuple(out)


def _sold_as_for(primary: Flight, items: list[Flight]) -> tuple[str, ...]:
    primary_compact = _compact_identifier(_marketing_identifier(primary))
    seen = {primary_compact}
    out: list[str] = []
    for item in items:
        candidates = [*(item.sold_as or ())]
        if item is not primary:
            candidates.extend([item.marketing_flight_number or "", _marketing_identifier(item)])
        for candidate in candidates:
            text = _format_codeshare_text(str(candidate or "").strip())
            compact = _compact_identifier(text)
            if not text or not compact or compact in seen:
                continue
            seen.add(compact)
            out.append(text)
    return tuple(out)


def _linked_clusters(items: list[Flight]) -> list[list[Flight]]:
    clusters: list[tuple[set[str], list[Flight]]] = []
    for item in items:
        aliases = _identity_aliases(item)
        matched: list[int] = []
        for idx, (cluster_aliases, _cluster_items) in enumerate(clusters):
            if aliases and cluster_aliases.intersection(aliases):
                matched.append(idx)
        if not matched:
            clusters.append((set(aliases), [item]))
            continue

        first = matched[0]
        clusters[first][0].update(aliases)
        clusters[first][1].append(item)
        for idx in reversed(matched[1:]):
            clusters[first][0].update(clusters[idx][0])
            clusters[first][1].extend(clusters[idx][1])
            del clusters[idx]
    return [cluster_items for _aliases, cluster_items in clusters]


def dedupe_codeshares(
    flights: Iterable[Flight],
    *,
    preferred_airline_iata: Optional[List[str]] = None,
    time_bucket_minutes: int = 5,
) -> List[Flight]:
    """
    Drop linked codeshare duplicates and keep the operating identity as primary.

    Rows must share a resolved identity alias (flight number, callsign, explicit
    sold-as/codeshare value). Same route/time alone is not enough; this avoids
    collapsing two distinct flights that happen to leave together.
    """
    groups: dict[tuple, list[Flight]] = {}

    for f in flights:
        t_bucket = _bucket_time(_best_time(f), time_bucket_minutes)
        o, d = _route_key(f)
        key = (f.direction.value, o, d, t_bucket)
        groups.setdefault(key, []).append(f)

    out: List[Flight] = []

    for items in groups.values():
        for linked_items in _linked_clusters(items):
            if len(linked_items) == 1:
                out.append(linked_items[0])
                continue

            def score(x: Flight) -> tuple:
                has_actual = 1 if x.times.actual else 0
                has_est = 1 if x.times.estimated else 0
                explicit_secondary_count = len(x.codeshares or ()) + len(x.sold_as or ())
                return (
                    _identity_source_score(x),
                    _provider_main_score(x),
                    -explicit_secondary_count,
                    _completion_score(x),
                    has_actual,
                    has_est,
                    x.callsign,
                )

            primary = sorted(linked_items, key=score, reverse=True)[0]
            out.append(
                replace(
                    primary,
                    codeshares=_codeshares_for(primary, linked_items),
                    sold_as=_sold_as_for(primary, linked_items),
                )
            )

    # stable sort
    out.sort(key=lambda x: (_best_time(x) or datetime.min.replace(tzinfo=timezone.utc)))
    return out
