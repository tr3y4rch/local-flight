from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from localflight.core.airports import get_airport_timezone, lookup_airport


def valid_timezone_name(value: str | None) -> str | None:
    """Return a valid IANA timezone name, or None when the value is unsafe."""
    name = str(value or "").strip()
    if not name:
        return None
    try:
        ZoneInfo(name)
    except Exception:
        return None
    return name


def airport_timezone_from_codes(*, airport_iata: str | None = None, airport_icao: str | None = None) -> str | None:
    """Resolve an airport's IANA timezone from the bundled airport index."""
    rec = lookup_airport(iata=airport_iata, icao=airport_icao)
    if rec is None:
        return None
    return valid_timezone_name(get_airport_timezone(rec.country or "", rec.region or ""))


def resolve_airport_timezone(
    timezone_name: str | None = None,
    *,
    airport_iata: str | None = None,
    airport_icao: str | None = None,
) -> str:
    """Concrete LT rule: configured airport timezone, airport-code rescue, then UTC."""
    return (
        valid_timezone_name(timezone_name)
        or airport_timezone_from_codes(airport_iata=airport_iata, airport_icao=airport_icao)
        or "UTC"
    )


def resolve_config_timezone(config: Any) -> str:
    """Resolve the display timezone from an AppConfig-like object or dict."""
    getter = config.get if isinstance(config, dict) else lambda key, default=None: getattr(config, key, default)
    return resolve_airport_timezone(
        getter("timezone", None),
        airport_iata=getter("airport_iata", None),
        airport_icao=getter("airport_icao", None),
    )


def airport_zoneinfo(config: Any) -> ZoneInfo:
    return ZoneInfo(resolve_config_timezone(config))


def airport_local_now(config: Any, *, now_utc: datetime | None = None) -> datetime:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(airport_zoneinfo(config))
