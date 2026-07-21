from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from localflight.decode.mappings.airlines import (
    airline_from_prefix,
    format_flight_identifier,
    lookup_airline,
    normalize_airline,
    parse_flight_identifier,
)


_CALLSIGN_RE = re.compile(r"^([A-Z]{3})([A-Z0-9]{1,6})$")
_PUBLIC_FLIGHT_SUFFIX_RE = re.compile(r"^0*[0-9]{1,5}[A-Z]?$")
_CALLSIGN_DERIVED_FLIGHT_SUFFIX_RE = re.compile(r"^0*[0-9]{1,5}$")
_DXB_CODESHARE_AIRPORTS = {"DXB", "OMDB"}


@dataclass(frozen=True)
class ResolvedFlightIdentity:
    callsign: str
    airline_name: str | None
    airline_iata: str | None
    airline_icao: str | None
    flight_number: str | None
    codeshares: tuple[str, ...]
    sold_as: tuple[str, ...]
    marketing_airline_name: str | None
    marketing_airline_iata: str | None
    marketing_airline_icao: str | None
    marketing_flight_number: str | None
    operating_callsign: str | None
    identity_source: str


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _compact_identifier(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", _text(value).upper())


def _identifier_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, Iterable):
        raw_items = list(value)
    else:
        raw_items = [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        compact = _compact_identifier(item)
        if compact and compact not in seen:
            seen.add(compact)
            out.append(compact)
    return out


def _airline_from_identifier(value: Any) -> dict[str, str] | None:
    text = _compact_identifier(value)
    if not text:
        return None
    parsed = parse_flight_identifier(text)
    if parsed:
        return airline_from_prefix(parsed[0])
    match = _CALLSIGN_RE.match(text)
    if match:
        return lookup_airline(icao=match.group(1))
    if len(text) >= 3:
        return airline_from_prefix(text[:3]) or airline_from_prefix(text[:2])
    return None


def _airlines_differ(first: dict[str, Any] | None, second: dict[str, Any] | None) -> bool:
    if not first or not second:
        return False
    first_iata = _text(first.get("iata")).upper()
    first_icao = _text(first.get("icao")).upper()
    second_iata = _text(second.get("iata")).upper()
    second_icao = _text(second.get("icao")).upper()
    if first_iata and second_iata:
        return first_iata != second_iata
    if first_icao and second_icao:
        return first_icao != second_icao
    return bool((first_iata or first_icao) and (second_iata or second_icao) and {first_iata, first_icao}.isdisjoint({second_iata, second_icao}))


def _identifier_matches_airline(identifier: str, airline: dict[str, Any] | None) -> bool:
    if not identifier or not airline:
        return False
    compact = _compact_identifier(identifier)
    iata = _text(airline.get("iata")).upper()
    icao = _text(airline.get("icao")).upper()
    return bool((iata and compact.startswith(iata)) or (icao and compact.startswith(icao)))


def _number_for_airline(identifier: str, airline: dict[str, Any]) -> str | None:
    compact = _compact_identifier(identifier)
    parsed = parse_flight_identifier(compact)
    iata = _text(airline.get("iata")).upper()
    icao = _text(airline.get("icao")).upper()
    if parsed:
        prefix, number = parsed
        if iata and prefix == iata:
            return f"{iata}{number}"
        if icao and prefix == icao:
            return f"{iata or icao}{number}"
    match = _CALLSIGN_RE.match(compact)
    if (
        match
        and icao
        and match.group(1) == icao
        and _CALLSIGN_DERIVED_FLIGHT_SUFFIX_RE.fullmatch(match.group(2))
    ):
        number = match.group(2).lstrip("0") or "0"
        return f"{iata or icao}{number}"
    return None


def _public_flight_identifier(value: Any, airline: dict[str, Any] | None = None) -> str | None:
    """Return a marketed flight identifier, never an arbitrary ADS-B callsign.

    Published flight numbers contain digits and at most one trailing letter.
    Operational callsigns such as SWR9GD or SWR1LK deliberately remain in the
    callsign field rather than being presented as fictional LX flight numbers.
    """

    compact = _compact_identifier(value)
    if not compact:
        return None
    parsed = parse_flight_identifier(compact)
    if parsed:
        prefix, number = parsed
        known = airline_from_prefix(prefix)
        code = _text((airline or known or {}).get("iata")).upper() or prefix
        return f"{code}{number}"
    if airline and _PUBLIC_FLIGHT_SUFFIX_RE.fullmatch(compact):
        code = _text(airline.get("iata") or airline.get("icao")).upper()
        number = compact.lstrip("0") or "0"
        return f"{code}{number}" if code else number
    return None


def _identifier_for_airline(
    airline: dict[str, Any] | None,
    identifiers: list[str],
) -> str | None:
    if not airline:
        return None
    for identifier in identifiers:
        if _identifier_matches_airline(identifier, airline):
            number = _number_for_airline(identifier, airline)
            if number:
                return number
    return None


def _explicit_operating_airline(record: dict[str, Any]) -> dict[str, str | None] | None:
    airline = normalize_airline(
        name=record.get("operating_airline_name"),
        iata=record.get("operating_airline_iata"),
        icao=record.get("operating_airline_icao"),
    )
    if airline.get("iata") or airline.get("icao") or airline.get("name"):
        return airline
    return None


def _dxb_operating_hint(
    *,
    airport_iata: str,
    airport_icao: str,
    identifiers: list[str],
    provider_airline: dict[str, Any] | None,
) -> dict[str, str] | None:
    airport_codes = {_text(airport_iata).upper(), _text(airport_icao).upper()}
    if not airport_codes.intersection(_DXB_CODESHARE_AIRPORTS):
        return None
    fz = lookup_airline(iata="FZ")
    if not fz or not any(_identifier_matches_airline(identifier, fz) for identifier in identifiers):
        return None
    if provider_airline and _text(provider_airline.get("iata")).upper() == "FZ":
        return None
    return fz


def _format_secondary(identifier: str) -> str:
    return _compact_identifier(format_flight_identifier(flight_number=identifier))


def _merge_identifiers(*groups: Iterable[str]) -> tuple[str, ...]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            compact = _format_secondary(item)
            if compact and compact not in seen:
                seen.add(compact)
                out.append(compact)
    return tuple(out)


def resolve_flight_identity(
    record: dict[str, Any],
    *,
    airport_iata: str = "",
    airport_icao: str = "",
) -> ResolvedFlightIdentity:
    """Resolve the display identity for a schedule row using operating-first rules."""

    callsign = _compact_identifier(record.get("operating_callsign") or record.get("callsign"))
    provider_airline = normalize_airline(
        name=record.get("airline_name"),
        iata=record.get("airline_iata"),
        icao=record.get("airline_icao"),
        callsign=callsign,
        flight_number=record.get("flight_number"),
    )
    marketing_airline = normalize_airline(
        name=record.get("marketing_airline_name") or record.get("airline_name"),
        iata=record.get("marketing_airline_iata") or record.get("airline_iata"),
        icao=record.get("marketing_airline_icao") or record.get("airline_icao"),
        callsign=callsign,
        flight_number=record.get("marketing_flight_number") or record.get("flight_number"),
    )
    marketing_flight = _public_flight_identifier(
        record.get("marketing_flight_number") or record.get("flight_number"),
        marketing_airline,
    )
    raw_codeshares = [
        public
        for item in _identifier_list(record.get("codeshares"))
        if (public := _public_flight_identifier(item))
    ]
    raw_sold_as = [
        public
        for item in _identifier_list(record.get("sold_as"))
        if (public := _public_flight_identifier(item))
    ]
    identifiers = _merge_identifiers([marketing_flight], raw_codeshares, raw_sold_as)

    explicit_airline = _explicit_operating_airline(record)
    callsign_airline = _airline_from_identifier(callsign)
    hint_airline = _dxb_operating_hint(
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        identifiers=list(identifiers),
        provider_airline=provider_airline,
    )
    provider_codeshare_status = _text(record.get("provider_codeshare_status")).replace(" ", "").lower()

    identity_source = "provider"
    operating_airline = provider_airline
    if provider_codeshare_status == "isoperator":
        operating_airline = explicit_airline or provider_airline
        identity_source = "provider_operator"
    elif explicit_airline:
        operating_airline = explicit_airline
        identity_source = "explicit_operating"
    elif callsign_airline and _airlines_differ(callsign_airline, provider_airline):
        operating_airline = callsign_airline
        identity_source = "callsign"
    elif hint_airline:
        operating_airline = hint_airline
        identity_source = "airport_codeshare_hint"

    # Operational callsigns are evidence for the carrier/codeshare relationship,
    # never a source from which to manufacture a marketed flight number.
    primary_flight = _identifier_for_airline(operating_airline, list(identifiers))
    if not primary_flight and marketing_flight and (
        not operating_airline or _identifier_matches_airline(marketing_flight, operating_airline)
    ):
        primary_flight = marketing_flight
    primary_compact = _compact_identifier(primary_flight)
    marketed_compact = _compact_identifier(marketing_flight)
    sold_as = list(raw_sold_as)
    if marketed_compact and marketed_compact != primary_compact:
        sold_as.insert(0, marketed_compact)
    secondaries = [identifier for identifier in raw_codeshares if _compact_identifier(identifier) != primary_compact]
    codeshares = _merge_identifiers(sold_as, secondaries)
    sold_as_tuple = _merge_identifiers(sold_as)

    return ResolvedFlightIdentity(
        callsign=callsign,
        airline_name=operating_airline.get("name") if operating_airline else None,
        airline_iata=operating_airline.get("iata") if operating_airline else None,
        airline_icao=operating_airline.get("icao") if operating_airline else None,
        flight_number=primary_flight,
        codeshares=codeshares,
        sold_as=sold_as_tuple,
        marketing_airline_name=marketing_airline.get("name"),
        marketing_airline_iata=marketing_airline.get("iata"),
        marketing_airline_icao=marketing_airline.get("icao"),
        marketing_flight_number=marketing_flight or None,
        operating_callsign=callsign or None,
        identity_source=identity_source,
    )
