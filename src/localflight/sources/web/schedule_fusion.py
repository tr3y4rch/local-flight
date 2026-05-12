from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_FILL_FIELDS = (
    "gate",
    "terminal",
    "stand",
    "aircraft_type",
    "aircraft_registration",
    "airline_name",
    "airline_iata",
    "airline_icao",
    "flight_number",
    "codeshares",
    "origin_iata",
    "origin_icao",
    "destination_iata",
    "destination_icao",
)
_EMPTY_FILL_FIELDS = ("scheduled", "estimated", "actual", "status", "delay_minutes")
_CONFLICT_FIELDS = ("scheduled", "estimated", "actual", "status")


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _same_value(first: Any, second: Any) -> bool:
    if isinstance(first, str) or isinstance(second, str):
        return _text(first).lower() == _text(second).lower()
    return first == second


def _minute_stamp(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(second=0, microsecond=0).isoformat()
    except Exception:
        return text[:16]


def _aliases(record: Dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("callsign", "flight_number"):
        value = _text(record.get(key)).replace(" ", "").upper()
        if value and value not in values:
            values.append(value)
    codeshares = record.get("codeshares")
    if isinstance(codeshares, str):
        codeshares = [codeshares]
    if isinstance(codeshares, Iterable):
        for item in codeshares:
            value = _text(item).replace(" ", "").upper()
            if value and value not in values:
                values.append(value)
    return values


def _route_key(record: Dict[str, Any]) -> tuple[str, str]:
    origin = _text(record.get("origin_iata") or record.get("origin_icao")).upper()
    dest = _text(record.get("destination_iata") or record.get("destination_icao")).upper()
    return origin, dest


def _identity_keys(record: Dict[str, Any]) -> list[tuple[str, str, str, str, str]]:
    direction = _text(record.get("direction")).upper()
    origin, dest = _route_key(record)
    stamp = _minute_stamp(record.get("scheduled") or record.get("estimated") or record.get("actual"))
    if not direction or not stamp:
        return []
    return [(direction, alias, origin, dest, stamp) for alias in _aliases(record)]


def _record_sort_key(record: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        _minute_stamp(record.get("scheduled") or record.get("estimated") or record.get("actual")),
        _text(record.get("direction")).upper(),
        _text(record.get("callsign") or record.get("flight_number")).upper(),
    )


def schedule_records_need_fill(records: list[Dict[str, Any]]) -> bool:
    if not records:
        return True
    if len(records) < 8:
        return True
    sample = records[: min(20, len(records))]
    missing_identity = sum(1 for row in sample if not _present(row.get("callsign") or row.get("flight_number")))
    missing_route_or_time = sum(
        1
        for row in sample
        if not _present(row.get("scheduled") or row.get("estimated") or row.get("actual"))
        or not _present(row.get("origin_iata") or row.get("origin_icao"))
        or not _present(row.get("destination_iata") or row.get("destination_icao"))
    )
    missing_ops = sum(
        1
        for row in sample
        if not _present(row.get("gate"))
        and not _present(row.get("terminal"))
        and not _present(row.get("aircraft_type"))
    )
    return bool(missing_identity or missing_route_or_time or (missing_ops / max(1, len(sample))) >= 0.35)


def merge_schedule_records(
    primary_records: list[Dict[str, Any]],
    fill_records: list[Dict[str, Any]],
    *,
    primary_provider: str = "aerodatabox",
    fill_provider: str = "aviationstack",
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    merged = [dict(row) for row in primary_records]
    index: dict[tuple[str, str, str, str, str], int] = {}
    for idx, row in enumerate(merged):
        for key in _identity_keys(row):
            index.setdefault(key, idx)

    filled_fields = 0
    appended_records = 0
    conflict_count = 0
    conflict_fields: dict[str, int] = {}

    for source in fill_records:
        source_copy = dict(source)
        match_idx: Optional[int] = None
        for key in _identity_keys(source_copy):
            if key in index:
                match_idx = index[key]
                break

        if match_idx is None:
            merged.append(source_copy)
            appended_records += 1
            for key in _identity_keys(source_copy):
                index.setdefault(key, len(merged) - 1)
            continue

        target = merged[match_idx]
        for field in _FILL_FIELDS:
            if not _present(target.get(field)) and _present(source_copy.get(field)):
                target[field] = source_copy.get(field)
                filled_fields += 1
        for field in _EMPTY_FILL_FIELDS:
            if not _present(target.get(field)) and _present(source_copy.get(field)):
                target[field] = source_copy.get(field)
                filled_fields += 1
        for field in _CONFLICT_FIELDS:
            if _present(target.get(field)) and _present(source_copy.get(field)) and not _same_value(target.get(field), source_copy.get(field)):
                conflict_count += 1
                conflict_fields[field] = conflict_fields.get(field, 0) + 1

    merged.sort(key=_record_sort_key)
    providers_used = [primary_provider] if primary_records else []
    if fill_records:
        providers_used.append(fill_provider)
    return merged, {
        "providers_used": providers_used,
        "provider_record_counts": {
            primary_provider: len(primary_records),
            fill_provider: len(fill_records),
            "merged": len(merged),
        },
        "primary_provider": primary_provider,
        "fill_provider": fill_provider,
        "filled_fields": filled_fields,
        "appended_records": appended_records,
        "conflict_count": conflict_count,
        "conflict_fields": conflict_fields,
    }
