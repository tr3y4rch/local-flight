from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional, Tuple

from localflight.core.models import Flight, FlightDirection, FlightStatus, FlightTime
from localflight.decode.mappings.airlines import format_flight_identifier


_REGISTRATION_OPERATOR_HINTS: tuple[tuple[str, frozenset[str]], ...] = (
    ("OO-S", frozenset({"SN", "BEL"})),      # Brussels Airlines
    ("D-AEW", frozenset({"EW", "EWG"})),     # Eurowings
    ("D-AB", frozenset({"EW", "EWG"})),      # Eurowings/LH-group narrowbody pools
    ("OE-I", frozenset({"EC", "EJU"})),      # EasyJet Europe
    ("EI-S", frozenset({"SK", "SAS"})),      # SAS Connect / SAS Ireland
    ("A4O", frozenset({"WY", "OMA"})),       # Oman Air
    ("A6-E", frozenset({"EK", "UAE"})),      # Emirates
    ("HB-I", frozenset({"LX", "SWR"})),      # SWISS
    ("HB-J", frozenset({"LX", "SWR"})),      # SWISS
    ("YL-", frozenset({"BT", "BTI"})),       # airBaltic
    ("CS-T", frozenset({"TP", "TAP"})),      # TAP Air Portugal
)


def _best_time(f: Flight) -> Optional[datetime]:
    return f.times.actual or f.times.estimated or f.times.scheduled


def _movement_identity_time(f: Flight) -> Optional[datetime]:
    # Scheduled time is the stable movement identity. Estimated/actual times
    # can legitimately differ between codeshare rows while providers settle.
    return f.times.scheduled or f.times.estimated or f.times.actual


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
    if not f.flight_number:
        return ""
    return format_flight_identifier(
        flight_number=f.flight_number,
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


def _is_public_marketed_identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,3}0*[0-9]{1,5}[A-Z]?", _compact_identifier(value)))


def _provider_codeshare_status(f: Flight) -> str:
    return (f.provider_codeshare_status or "").strip().replace(" ", "").lower()


def _provider_codeshare_score(f: Flight) -> int:
    status = _provider_codeshare_status(f)
    if status == "isoperator":
        return 4
    if status == "iscodeshared":
        return -1
    return 0


def _registration_operator_codes(registration: str | None) -> frozenset[str]:
    reg = (registration or "").strip().upper().replace(" ", "")
    if not reg:
        return frozenset()
    for prefix, codes in _REGISTRATION_OPERATOR_HINTS:
        if reg.startswith(prefix):
            return codes
    return frozenset()


def _flight_airline_codes(f: Flight) -> set[str]:
    codes = {
        (f.airline.iata or "").strip().upper(),
        (f.airline.icao or "").strip().upper(),
        (f.marketing_airline_iata or "").strip().upper(),
        (f.marketing_airline_icao or "").strip().upper(),
    }
    callsign = _compact_identifier(f.callsign or "")
    if len(callsign) >= 3 and callsign[:3].isalpha():
        codes.add(callsign[:3])
    flight_number = _compact_identifier(f.flight_number or "")
    if len(flight_number) >= 2:
        codes.add(flight_number[:2])
        if len(flight_number) >= 3 and flight_number[:3].isalpha():
            codes.add(flight_number[:3])
    return {code for code in codes if code}


def _registration_operator_score(f: Flight) -> int:
    hints = _registration_operator_codes(f.aircraft_registration)
    if not hints:
        return 0
    return 6 if hints.intersection(_flight_airline_codes(f)) else 0


def _identity_source_score(f: Flight) -> int:
    source = (f.identity_source or "").strip().lower()
    if source == "provider_operator":
        return 5
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


def _has_public_flight_number(f: Flight) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,3}0*[0-9]{1,5}[A-Z]?", _compact_identifier(f.flight_number or "")))


def _compatible_shadow_pair(group: list[Flight]) -> bool:
    """Recognize one provider shadow row without collapsing real simultaneity.

    Some schedule payloads emit the same movement once with its published
    flight number and once with only an operational callsign. The provider key
    already binds route and minute; this narrow rule additionally requires one
    public identity, one callsign-only identity, the same airline, and no
    conflicting aircraft/location evidence.
    """

    if len(group) != 2:
        return False
    public = [item for item in group if _has_public_flight_number(item)]
    shadows = [item for item in group if not _has_public_flight_number(item)]
    if len(public) != 1 or len(shadows) != 1:
        return False
    first, second = public[0], shadows[0]
    first_codes = _flight_airline_codes(first)
    second_codes = _flight_airline_codes(second)
    if not first_codes.intersection(second_codes):
        return False
    for left, right in (
        (first.aircraft_registration, second.aircraft_registration),
        (first.gate or first.stand, second.gate or second.stand),
        (first.aircraft_type, second.aircraft_type),
    ):
        if left and right and _compact_identifier(left) != _compact_identifier(right):
            return False
    return True


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


def _identity_aliases(f: Flight, *, provider_link_keys: set[str] | None = None) -> set[str]:
    aliases = {
        compact
        for compact in (_compact_identifier(_format_codeshare_text(value)) for value in _alias_values(f))
        if compact
    }
    provider_key = str(f.provider_movement_key or "").strip()
    if (
        provider_link_keys
        and provider_key in provider_link_keys
    ):
        aliases.add(f"PROVIDER:{provider_key}")
    strong_key = _strong_movement_key(f)
    if provider_link_keys and strong_key in provider_link_keys:
        aliases.add(f"MOVEMENT:{strong_key}")
    return aliases


def _strong_movement_key(f: Flight) -> str:
    reg = _compact_identifier(f.aircraft_registration or "")
    gate = _compact_identifier(f.gate or f.stand or "")
    terminal = _compact_identifier(f.terminal or "")
    aircraft = _compact_identifier(f.aircraft_type or "")
    if not reg and not (gate and aircraft):
        return ""
    t_bucket = _bucket_time(_movement_identity_time(f), 1)
    if not t_bucket:
        return ""
    origin, destination = _route_key(f)
    evidence = f"REG:{reg}" if reg else f"GATE:{gate}|TERM:{terminal}|AC:{aircraft}"
    return "|".join((f.direction.value, origin, destination, t_bucket.isoformat(), evidence))


def _safe_provider_link_keys(items: list[Flight]) -> set[str]:
    grouped: dict[str, list[Flight]] = {}
    for item in items:
        key = str(item.provider_movement_key or "").strip()
        if key:
            grouped.setdefault(key, []).append(item)

    safe: set[str] = set()
    for key, group in grouped.items():
        operators = [item for item in group if _provider_codeshare_status(item) == "isoperator"]
        marketed = [item for item in group if _provider_codeshare_status(item) == "iscodeshared"]
        if len(operators) == 1 and marketed:
            safe.add(key)
        elif _compatible_shadow_pair(group):
            safe.add(key)

    strong_groups: dict[str, list[Flight]] = {}
    for item in items:
        key = _strong_movement_key(item)
        if key:
            strong_groups.setdefault(key, []).append(item)
    for key, group in strong_groups.items():
        if len(group) < 2:
            continue
        operators = [item for item in group if _provider_codeshare_status(item) == "isoperator"]
        if len(operators) > 1:
            continue
        safe.add(key)
    return safe


def _codeshares_for(primary: Flight, items: list[Flight]) -> tuple[str, ...]:
    primary_id = _marketing_identifier(primary)
    primary_compact = _compact_identifier(primary_id)
    seen = {primary_compact}
    out: list[str] = []

    for existing in [*(primary.sold_as or ()), *(primary.codeshares or ())]:
        text = _format_codeshare_text(str(existing or "").strip())
        compact = _compact_identifier(text)
        if text and compact and _is_public_marketed_identifier(text) and compact not in seen:
            seen.add(compact)
            out.append(text)

    for item in items:
        for candidate in [_marketing_identifier(item), item.marketing_flight_number or "", *(item.sold_as or ()), *(item.codeshares or ())]:
            text = _format_codeshare_text(str(candidate or "").strip())
            compact = _compact_identifier(text)
            if not text or not compact or not _is_public_marketed_identifier(text) or compact in seen:
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
            if not text or not compact or not _is_public_marketed_identifier(text) or compact in seen:
                continue
            seen.add(compact)
            out.append(text)
    return tuple(out)


def _linked_clusters(items: list[Flight], *, provider_link_keys: set[str] | None = None) -> list[list[Flight]]:
    clusters: list[tuple[set[str], list[Flight]]] = []
    for item in items:
        aliases = _identity_aliases(item, provider_link_keys=provider_link_keys)
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
        t_bucket = _bucket_time(_movement_identity_time(f), time_bucket_minutes)
        o, d = _route_key(f)
        key = (f.direction.value, o, d, t_bucket)
        groups.setdefault(key, []).append(f)

    out: List[Flight] = []

    for items in groups.values():
        provider_link_keys = _safe_provider_link_keys(items)
        for linked_items in _linked_clusters(items, provider_link_keys=provider_link_keys):
            if len(linked_items) == 1:
                out.append(linked_items[0])
                continue

            def score(x: Flight) -> tuple:
                has_actual = 1 if x.times.actual else 0
                has_est = 1 if x.times.estimated else 0
                explicit_secondary_count = len(x.codeshares or ()) + len(x.sold_as or ())
                return (
                    _provider_codeshare_score(x),
                    _registration_operator_score(x),
                    _identity_source_score(x),
                    _provider_main_score(x),
                    -explicit_secondary_count,
                    _completion_score(x),
                    has_actual,
                    has_est,
                    x.callsign,
                )

            primary = sorted(linked_items, key=score, reverse=True)[0]
            ranked = sorted(linked_items, key=score, reverse=True)

            def first_value(name: str):
                return next((getattr(item, name) for item in ranked if getattr(item, name)), None)

            times = FlightTime(
                scheduled=next((item.times.scheduled for item in ranked if item.times.scheduled), None),
                estimated=next((item.times.estimated for item in ranked if item.times.estimated), None),
                actual=next((item.times.actual for item in ranked if item.times.actual), None),
            )
            status = primary.status
            if status == FlightStatus.UNKNOWN:
                status = next((item.status for item in ranked if item.status != FlightStatus.UNKNOWN), status)
            out.append(
                replace(
                    primary,
                    codeshares=_codeshares_for(primary, linked_items),
                    sold_as=_sold_as_for(primary, linked_items),
                    origin=primary.origin or first_value("origin"),
                    destination=primary.destination or first_value("destination"),
                    aircraft_type=primary.aircraft_type or first_value("aircraft_type"),
                    aircraft_type_full=primary.aircraft_type_full or first_value("aircraft_type_full"),
                    aircraft_registration=primary.aircraft_registration or first_value("aircraft_registration"),
                    gate=primary.gate or first_value("gate"),
                    terminal=primary.terminal or first_value("terminal"),
                    stand=primary.stand or first_value("stand"),
                    gate_source=primary.gate_source or first_value("gate_source"),
                    terminal_source=primary.terminal_source or first_value("terminal_source"),
                    gate_confidence=primary.gate_confidence or first_value("gate_confidence"),
                    terminal_confidence=primary.terminal_confidence or first_value("terminal_confidence"),
                    times=times,
                    delay_minutes=primary.delay_minutes if primary.delay_minutes is not None else next(
                        (item.delay_minutes for item in ranked if item.delay_minutes is not None),
                        None,
                    ),
                    status=status,
                    position=primary.position or first_value("position"),
                    enriched_by=primary.enriched_by or first_value("enriched_by"),
                    updated_at=primary.updated_at or first_value("updated_at"),
                )
            )

    # stable sort
    out.sort(key=lambda x: (_best_time(x) or datetime.min.replace(tzinfo=timezone.utc)))
    return out
