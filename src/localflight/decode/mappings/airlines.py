from __future__ import annotations

import re
from typing import Optional

_AIRLINES: tuple[tuple[str, str, str], ...] = (
    ("AA", "AAL", "American Airlines"),
    ("AC", "ACA", "Air Canada"),
    ("AF", "AFR", "Air France"),
    ("AI", "AIC", "Air India"),
    ("AM", "AMX", "Aeromexico"),
    ("AS", "ASA", "Alaska Airlines"),
    ("AT", "RAM", "Royal Air Maroc"),
    ("AY", "FIN", "Finnair"),
    ("AZ", "ITY", "ITA Airways"),
    ("A3", "AEE", "Aegean Airlines"),
    ("B2", "BRU", "Belavia"),
    ("BA", "BAW", "British Airways"),
    ("BR", "EVA", "EVA Air"),
    ("BT", "BTI", "airBaltic"),
    ("B6", "JBU", "JetBlue"),
    ("CA", "CCA", "Air China"),
    ("CI", "CAL", "China Airlines"),
    ("CM", "CMP", "Copa Airlines"),
    ("CX", "CPA", "Cathay Pacific"),
    ("CZ", "CSN", "China Southern"),
    ("DE", "CFG", "Condor"),
    ("DL", "DAL", "Delta Air Lines"),
    ("DY", "NOZ", "Norwegian"),
    ("EI", "EIN", "Aer Lingus"),
    ("EK", "UAE", "Emirates"),
    ("ET", "ETH", "Ethiopian Airlines"),
    ("EW", "EWG", "Eurowings"),
    ("EY", "ETD", "Etihad Airways"),
    ("F9", "FFT", "Frontier Airlines"),
    ("FI", "ICE", "Icelandair"),
    ("FR", "RYR", "Ryanair"),
    ("FZ", "FDB", "flydubai"),
    ("G4", "AAY", "Allegiant Air"),
    ("GA", "GIA", "Garuda Indonesia"),
    ("GF", "GFA", "Gulf Air"),
    ("HO", "DKH", "Juneyao Air"),
    ("HU", "CHH", "Hainan Airlines"),
    ("HV", "TRA", "Transavia"),
    ("HY", "UZB", "Uzbekistan Airways"),
    ("IB", "IBE", "Iberia"),
    ("J2", "AHY", "Azerbaijan Airlines"),
    ("JL", "JAL", "Japan Airlines"),
    ("JQ", "JST", "Jetstar"),
    ("JU", "ASL", "Air Serbia"),
    ("KC", "KZR", "Air Astana"),
    ("KE", "KAL", "Korean Air"),
    ("KL", "KLM", "KLM"),
    ("KQ", "KQA", "Kenya Airways"),
    ("KU", "KAC", "Kuwait Airways"),
    ("LA", "LAN", "LATAM Airlines"),
    ("LH", "DLH", "Lufthansa"),
    ("LO", "LOT", "LOT Polish Airlines"),
    ("LX", "SWR", "SWISS"),
    ("LY", "ELY", "El Al"),
    ("ME", "MEA", "Middle East Airlines"),
    ("MF", "CXA", "XiamenAir"),
    ("MH", "MAS", "Malaysia Airlines"),
    ("MK", "MAU", "Air Mauritius"),
    ("MS", "MSR", "Egyptair"),
    ("MU", "CES", "China Eastern"),
    ("NH", "ANA", "All Nippon Airways"),
    ("NK", "NKS", "Spirit Airlines"),
    ("NZ", "ANZ", "Air New Zealand"),
    ("OK", "CSA", "Czech Airlines"),
    ("OS", "AUA", "Austrian Airlines"),
    ("OZ", "AAR", "Asiana Airlines"),
    ("PC", "PGT", "Pegasus Airlines"),
    ("PG", "BKP", "Bangkok Airways"),
    ("PR", "PAL", "Philippine Airlines"),
    ("PS", "AUI", "Ukraine International"),
    ("QF", "QFA", "Qantas"),
    ("QR", "QTR", "Qatar Airways"),
    ("RJ", "RJA", "Royal Jordanian"),
    ("RO", "ROT", "TAROM"),
    ("SA", "SAA", "South African Airways"),
    ("S7", "SBI", "S7 Airlines"),
    ("SK", "SAS", "SAS Scandinavian Airlines"),
    ("SN", "BEL", "Brussels Airlines"),
    ("SQ", "SIA", "Singapore Airlines"),
    ("SU", "AFL", "Aeroflot"),
    ("SV", "SVA", "Saudia"),
    ("TG", "THA", "Thai Airways"),
    ("TK", "THY", "Turkish Airlines"),
    ("TP", "TAP", "TAP Air Portugal"),
    ("TR", "TGW", "Scoot"),
    ("TS", "TSC", "Air Transat"),
    ("TU", "TAR", "Tunisair"),
    ("UK", "VTI", "Vistara"),
    ("UA", "UAL", "United Airlines"),
    ("U2", "EZY", "easyJet"),
    ("VA", "VOZ", "Virgin Australia"),
    ("VN", "HVN", "Vietnam Airlines"),
    ("VS", "VIR", "Virgin Atlantic"),
    ("VY", "VLG", "Vueling"),
    ("W6", "WZZ", "Wizz Air"),
    ("WN", "SWA", "Southwest Airlines"),
    ("WY", "OMA", "Oman Air"),
    ("WS", "WJA", "WestJet"),
    ("UX", "AEA", "Air Europa"),
    ("XQ", "SXS", "SunExpress"),
    ("Y4", "VOI", "Volaris"),
)

_BY_IATA = {iata: {"iata": iata, "icao": icao, "name": name} for iata, icao, name in _AIRLINES}
_BY_ICAO = {icao: {"iata": iata, "icao": icao, "name": name} for iata, icao, name in _AIRLINES}
_ICAO_FLIGHT_RE = re.compile(r"^([A-Z]{3})(0*[0-9]{1,5}[A-Z]?)$")
_IATA_FLIGHT_RE = re.compile(r"^([A-Z0-9]{2})(0*[0-9]{1,5}[A-Z]?)$")
_GENERIC_FLIGHT_RE = re.compile(r"^([A-Z0-9]{3})(0*[0-9]{1,5}[A-Z]?)$")


def lookup_airline(*, iata: str | None = None, icao: str | None = None) -> dict[str, str] | None:
    iata_code = (iata or "").strip().upper()
    icao_code = (icao or "").strip().upper()
    if iata_code and iata_code in _BY_IATA:
        return dict(_BY_IATA[iata_code])
    if icao_code and icao_code in _BY_ICAO:
        return dict(_BY_ICAO[icao_code])
    return None


def parse_flight_identifier(value: str | None) -> tuple[str, str] | None:
    text = (value or "").strip().upper().replace(" ", "")
    if not text:
        return None
    for pattern in (_ICAO_FLIGHT_RE, _IATA_FLIGHT_RE, _GENERIC_FLIGHT_RE):
        match = pattern.match(text)
        if match:
            number = match.group(2).lstrip("0") or "0"
            return match.group(1), number
    return None


def airline_from_identifier(value: str | None) -> dict[str, str] | None:
    parsed = parse_flight_identifier(value)
    if not parsed:
        return None
    prefix, _number = parsed
    return airline_from_prefix(prefix)


def airline_from_prefix(prefix: str | None) -> dict[str, str] | None:
    code = (prefix or "").strip().upper()
    if len(code) == 2:
        return lookup_airline(iata=code)
    if len(code) == 3:
        return lookup_airline(icao=code)
    return lookup_airline(iata=code) or lookup_airline(icao=code)


def normalize_airline(
    *,
    name: str | None = None,
    iata: str | None = None,
    icao: str | None = None,
    callsign: str | None = None,
    flight_number: str | None = None,
) -> dict[str, Optional[str]]:
    known = lookup_airline(iata=iata, icao=icao) or airline_from_identifier(flight_number) or airline_from_identifier(callsign)
    return {
        "name": (name or "").strip() or (known or {}).get("name"),
        "iata": (iata or "").strip().upper() or (known or {}).get("iata"),
        "icao": (icao or "").strip().upper() or (known or {}).get("icao"),
    }


def format_flight_identifier(
    *,
    flight_number: str | None = None,
    callsign: str | None = None,
    airline_iata: str | None = None,
    airline_icao: str | None = None,
) -> str:
    parsed = parse_flight_identifier(flight_number) or parse_flight_identifier(callsign)
    if parsed:
        prefix, number = parsed
        known = lookup_airline(iata=airline_iata, icao=airline_icao) or airline_from_prefix(prefix)
        code = (known or {}).get("iata") or airline_iata or prefix
        return f"{code.upper()} {number}"
    fallback = (flight_number or callsign or "").strip().upper()
    if len(fallback) > 3 and fallback[:3].isalpha() and fallback[3:].isdigit():
        return f"{fallback[:3]} {fallback[3:]}"
    if len(fallback) > 2 and fallback[:2].isalnum() and fallback[2:].isdigit():
        return f"{fallback[:2]} {fallback[2:]}"
    return fallback or "-"
