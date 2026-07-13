from __future__ import annotations

import re
from typing import Any, Iterable


CONFIDENCE_ORDER = {
    "none": 0,
    "ambiguous": 1,
    "probable": 2,
    "high": 3,
    "confirmed": 4,
}


def clean_location_value(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"none", "null", "n/a", "na", "-"}:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^(?:terminal|term|gate)\s*[:#-]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^g\s+(?=\d+$)", "", text, flags=re.IGNORECASE)
    text = text.strip()
    if re.fullmatch(r"[A-Za-z]\s+\d+[A-Za-z]?", text):
        text = re.sub(r"\s+", "", text)
    return text.upper() if re.search(r"[A-Za-z]", text) else text


def _compact(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", clean_location_value(value).upper())


def _notes(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable):
        items = list(value)
    else:
        items = [value]
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text[:96])
    return out


def merge_notes(*values: Any) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        for note in _notes(value):
            if note not in out:
                out.append(note)
    return tuple(out)


def confidence_rank(value: Any) -> int:
    return CONFIDENCE_ORDER.get(str(value or "").strip().lower(), 0)


def gate_confidence(value: Any) -> str:
    text = clean_location_value(value)
    if not text:
        return "none"
    compact = _compact(text)
    if re.fullmatch(r"[A-Z]\d{1,4}[A-Z]?", compact):
        return "high"
    if re.fullmatch(r"[A-Z]{1,3}\d{1,4}[A-Z]?", compact) and any(ch.isdigit() for ch in compact):
        return "high"
    if re.fullmatch(r"\d{3,4}[A-Z]?", compact):
        return "probable"
    if re.fullmatch(r"\d{1,2}[A-Z]?", compact):
        return "ambiguous"
    if any(ch.isdigit() for ch in compact) and any(ch.isalpha() for ch in compact):
        return "probable"
    return "ambiguous"


def terminal_confidence(value: Any) -> str:
    text = clean_location_value(value)
    if not text:
        return "none"
    compact = _compact(text)
    if re.fullmatch(r"\d{1,2}|[A-Z]|[A-Z]\d{1,2}", compact):
        return "high"
    return "probable"


def displayable_gate(value: Any, confidence: Any = "") -> str:
    text = clean_location_value(value)
    if not text:
        return ""
    conf = str(confidence or gate_confidence(text)).strip().lower()
    if confidence_rank(conf) >= confidence_rank("probable"):
        return text
    return ""


def normalize_ops_location_record(record: dict[str, Any], *, provider: str = "") -> dict[str, Any]:
    shaped = dict(record)
    provider_name = str(provider or shaped.get("source") or "").strip().lower() or "schedule"

    gate = clean_location_value(shaped.get("gate"))
    terminal = clean_location_value(shaped.get("terminal"))
    gate_conf = str(shaped.get("gate_confidence") or gate_confidence(gate)).strip().lower() or "none"
    terminal_conf = str(shaped.get("terminal_confidence") or terminal_confidence(terminal)).strip().lower() or "none"
    notes = list(merge_notes(shaped.get("ops_location_notes")))

    if gate and terminal and _compact(gate) == _compact(terminal):
        notes.append("ops_location.duplicate_terminal_gate")
        if confidence_rank(gate_conf) < confidence_rank("probable"):
            gate_conf = "ambiguous"

    shaped["gate"] = gate or None
    shaped["terminal"] = terminal or None
    shaped["gate_confidence"] = gate_conf
    shaped["terminal_confidence"] = terminal_conf
    shaped["gate_source"] = shaped.get("gate_source") or (f"{provider_name}.gate" if gate else "")
    shaped["terminal_source"] = shaped.get("terminal_source") or (f"{provider_name}.terminal" if terminal else "")
    shaped["ops_location_notes"] = tuple(dict.fromkeys(notes))
    return shaped


def display_location_fields(
    gate: Any,
    terminal: Any = "",
    *,
    gate_confidence_value: Any = "",
    terminal_confidence_value: Any = "",
    notes: Any = (),
) -> tuple[str, str, str]:
    gate_text = displayable_gate(gate, gate_confidence_value)
    terminal_text = clean_location_value(terminal)
    if terminal_text and str(terminal_confidence_value or terminal_confidence(terminal_text)).lower() == "none":
        terminal_text = ""
    if gate_text and terminal_text and _compact(gate_text) == _compact(terminal_text):
        terminal_text = ""
    # Gate-first: compact display labels never join a terminal-like value to a gate.
    return gate_text, terminal_text, gate_text

