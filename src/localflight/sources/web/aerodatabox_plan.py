"""Shared, credential-free AeroDataBox FIDS planning and response validation."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


class InvalidFidsPayload(ValueError):
    """Safe error: the response cannot be published as a flight board."""


@dataclass(frozen=True)
class FidsWindow:
    start: datetime
    end: datetime

    def params(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        # Floor against the request clock. The planner overlaps adjacent slices
        # by a minute to accommodate rounding as the endpoint clock moves.
        offset = math.floor((self.start - current).total_seconds() / 60)
        return {
            "offsetMinutes": offset,
            "durationMinutes": int((self.end - self.start).total_seconds() / 60),
            "direction": "Both", "withLeg": "true", "withCancelled": "true",
            "withCodeshared": "true", "withCargo": "false",
            "withPrivate": "false", "withLocation": "false",
        }


def plan_fids(*, grace_minutes: int, horizon_hours: int, max_minutes: int = 720,
              margin_minutes: int = 15, now: datetime | None = None) -> list[FidsWindow]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    if not 60 <= max_minutes <= 2880:
        raise ValueError("Invalid FIDS subscription window")
    if not 0 <= grace_minutes <= 180 or not 1 <= horizon_hours <= 24:
        raise ValueError("Invalid FIDS display window")
    start = current - timedelta(minutes=grace_minutes + 1)
    # Pad rounding at both ends; the relay reports a conservative end boundary.
    end = current + timedelta(hours=horizon_hours, minutes=max(0, margin_minutes) + 2)
    windows = []
    while start < end:
        stop = min(end, start + timedelta(minutes=max_minutes))
        windows.append(FidsWindow(start, stop))
        start = stop if stop == end else stop - timedelta(minutes=1)
    return windows


def validate_fids(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidFidsPayload("Flight information response is invalid")
    result: dict[str, Any] = {}
    for section in ("departures", "arrivals"):
        rows = payload.get(section, payload.get(section.title()))
        if not isinstance(rows, list):
            raise InvalidFidsPayload("Flight information response is incomplete")
        for row in rows:
            if not isinstance(row, dict) or not (row.get("number") or row.get("flightNumber") or row.get("callSign") or row.get("callsign")):
                raise InvalidFidsPayload("Flight information contains an invalid movement")
            movement = row.get("departure" if section == "departures" else "arrival") or row.get("movement")
            if not isinstance(movement, dict):
                raise InvalidFidsPayload("Flight information contains an invalid movement")
            for field in ("scheduledTime", "revisedTime", "actualTime", "runwayTime"):
                value = movement.get(field)
                if value is None:
                    continue
                stamp = value.get("utc") or value.get("local") if isinstance(value, dict) else value
                try:
                    dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        raise ValueError("Time zone missing")
                except (ValueError, TypeError):
                    raise InvalidFidsPayload("Flight information contains an invalid time") from None
        result[section] = rows
    return result


def combine_fids(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"departures": [], "arrivals": []}
    for section in result:
        seen = set()
        for payload in payloads:
            for row in payload[section]:
                key = json.dumps(row, sort_keys=True, separators=(",", ":"))
                if key not in seen:
                    result[section].append(row)
                    seen.add(key)
    return result
