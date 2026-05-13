from __future__ import annotations

import re
from typing import Any


_SHORT_CODE_RE = re.compile(r"^[A-Z0-9]{2,5}$")

_MODEL_TO_ICAO = (
    (re.compile(r"\bA350[-\s]?(?:1000|10\d{2})\b|\b350[-\s]?(?:1000|10\d{2})\b", re.I), "A35K"),
    (re.compile(r"\bA350[-\s]?(?:900|9\d{2})\b|\b350[-\s]?(?:900|9\d{2})\b", re.I), "A359"),
    (re.compile(r"\bA380[-\s]?800\b|\b380[-\s]?800\b", re.I), "A388"),
    (re.compile(r"\bA330[-\s]?(?:900|9\d{2})\b|\b330[-\s]?(?:900|9\d{2})\b", re.I), "A339"),
    (re.compile(r"\bA330[-\s]?(?:300|3\d{2})\b|\b330[-\s]?(?:300|3\d{2})\b", re.I), "A333"),
    (re.compile(r"\bA330[-\s]?(?:200|2\d{2})\b|\b330[-\s]?(?:200|2\d{2})\b", re.I), "A332"),
    (re.compile(r"\bA321\s?NEO\b|\bA321[-\s]?2\d{2}N\b", re.I), "A21N"),
    (re.compile(r"\bA320\s?NEO\b|\bA320[-\s]?2\d{2}N\b", re.I), "A20N"),
    (re.compile(r"\bA319\s?NEO\b|\bA319[-\s]?1\d{2}N\b", re.I), "A19N"),
    (re.compile(r"\bA321(?:[-\s]?\d{3})?\b", re.I), "A321"),
    (re.compile(r"\bA320(?:[-\s]?\d{3})?\b", re.I), "A320"),
    (re.compile(r"\bA319(?:[-\s]?\d{3})?\b", re.I), "A319"),
    (re.compile(r"\b777[-\s]?300ER\b|\bB777[-\s]?300ER\b", re.I), "B77W"),
    (re.compile(r"\b777[-\s]?200\b|\bB777[-\s]?200\b", re.I), "B772"),
    (re.compile(r"\b787[-\s]?10\b|\bB787[-\s]?10\b", re.I), "B78X"),
    (re.compile(r"\b787[-\s]?9\b|\bB787[-\s]?9\b", re.I), "B789"),
    (re.compile(r"\b787[-\s]?8\b|\bB787[-\s]?8\b", re.I), "B788"),
    (re.compile(r"\b737\s?MAX\s?8\b|\b737[-\s]?8\s?MAX\b", re.I), "B38M"),
    (re.compile(r"\b737[-\s]?(?:800|8[A-Z0-9]{2})\b|\bB737[-\s]?(?:800|8[A-Z0-9]{2})\b", re.I), "B738"),
    (re.compile(r"\bE190\b|\bEMBRAER\s+190\b", re.I), "E190"),
    (re.compile(r"\bATR\s?72[-\s]?600\b|\bAT76\b", re.I), "AT76"),
    (re.compile(r"\bDASH\s?8[-\s]?400\b|\bQ400\b|\bDH8D\b", re.I), "DH8D"),
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def clean_aircraft_code(value: Any) -> str:
    """Return a compact ICAO-like aircraft code, or an empty string."""
    text = _text(value)
    if not text:
        return ""
    compact = text.upper().replace(" ", "")
    if "/" in compact:
        compact = compact.split("/", 1)[0]
    compact = compact.strip("-_")
    return compact if _SHORT_CODE_RE.fullmatch(compact) else ""


def short_aircraft_type(*values: Any) -> str:
    """Pick a compact board-safe aircraft type from provider values."""
    for value in values:
        code = clean_aircraft_code(value)
        if code:
            return code
    for value in values:
        text = _text(value)
        if not text:
            continue
        for pattern, code in _MODEL_TO_ICAO:
            if pattern.search(text):
                return code
    return ""


def aircraft_full_label(*values: Any, short_code: str | None = None) -> str:
    """Pick a human-friendly aircraft model label for detail views."""
    short = clean_aircraft_code(short_code)
    for value in values:
        text = _text(value)
        if not text:
            continue
        code = clean_aircraft_code(text)
        if code and (not short or code == short):
            continue
        return text
    return ""
