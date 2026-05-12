from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from localflight.decode.mappings.aerodatabox import aerodatabox_to_raw_records
from localflight.sources.web.aviationstack_plan import (
    DEFAULT_DISPLAY_GRACE_MINUTES,
    DEFAULT_DISPLAY_HORIZON_HOURS,
)

AERODATABOX_BASE_URL = "https://aerodatabox.p.rapidapi.com"
_DEFAULT_MONTHLY_UNITS_LIMIT = 24_000
_DEFAULT_FIDS_TIER2_UNITS = 2


class AeroDataBoxError(RuntimeError):
    pass


class AeroDataBoxBudgetExceeded(AeroDataBoxError):
    pass


def _usage_path() -> Path:
    from localflight.storage.config import config_path

    return config_path().parent / "api_usage.json"


def _load_usage() -> Dict[str, Any]:
    path = _usage_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_usage(data: Dict[str, Any]) -> None:
    try:
        _usage_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _api_key() -> str:
    key = os.getenv("AERODATABOX_API_KEY", "").strip()
    if not key:
        raise AeroDataBoxError("AERODATABOX_API_KEY not set")
    return key


def has_enabled_key() -> bool:
    key_present = bool(os.getenv("AERODATABOX_API_KEY", "").strip())
    if not key_present:
        return False
    raw = os.getenv("LOCALFLIGHT_AERODATABOX_ENABLED", "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def _monthly_units_limit() -> int:
    try:
        return max(0, int(os.getenv("LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT", str(_DEFAULT_MONTHLY_UNITS_LIMIT))))
    except (TypeError, ValueError):
        return _DEFAULT_MONTHLY_UNITS_LIMIT


def _daily_from_monthly(monthly_limit: int) -> int:
    return max(0, (max(0, int(monthly_limit)) + 29) // 30)


def _daily_units_limit() -> int:
    monthly = _monthly_units_limit()
    try:
        return max(0, int(os.getenv("LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT", str(_daily_from_monthly(monthly)))))
    except (TypeError, ValueError):
        return _daily_from_monthly(monthly)


def _fids_units() -> int:
    try:
        return max(1, int(os.getenv("LOCALFLIGHT_AERODATABOX_FIDS_TIER2_UNITS", str(_DEFAULT_FIDS_TIER2_UNITS))))
    except (TypeError, ValueError):
        return _DEFAULT_FIDS_TIER2_UNITS


def _increment_units(units: int) -> None:
    limit = _monthly_units_limit()
    usage = _load_usage()
    month = _month_key()
    bucket = usage.setdefault("aerodatabox_units", {})
    current = int(bucket.get(month, 0) or 0)
    request_bucket = usage.setdefault("aerodatabox_requests", {})
    request_current = int(request_bucket.get(month, 0) or 0)

    try:
        from localflight.sources.web import local_usage
    except Exception:
        local_usage = None

    if local_usage is not None:
        try:
            local_usage.ensure_counter_at_least("aerodatabox_units", month, current)
            local_usage.ensure_counter_at_least("aerodatabox_requests", month, request_current)
            counts = local_usage.check_and_increment_many(
                [
                    {
                        "service": "aerodatabox_units",
                        "amount": units,
                        "monthly_limit": limit,
                        "daily_limit": _daily_units_limit(),
                    },
                    {
                        "service": "aerodatabox_requests",
                        "amount": 1,
                        "monthly_limit": None,
                        "daily_limit": None,
                    },
                ]
            )
            current = max(current, int(counts.get("aerodatabox_units", 0) or 0) - int(units))
            request_current = max(request_current, int(counts.get("aerodatabox_requests", 0) or 0) - 1)
        except local_usage.LocalBudgetExceeded as exc:
            raise AeroDataBoxBudgetExceeded(
                f"AeroDataBox {exc.period} unit budget exceeded: "
                f"{exc.current}/{exc.limit} units used, {exc.requested} requested."
            ) from exc
        except Exception:
            pass

    if current + units > limit:
        raise AeroDataBoxBudgetExceeded(
            f"AeroDataBox monthly unit budget exceeded: {current}/{limit} units used this month ({month})."
        )
    bucket[month] = max(int(bucket.get(month, 0) or 0), current + units)
    request_bucket[month] = max(int(request_bucket.get(month, 0) or 0), request_current + 1)
    for name in ("aerodatabox_units", "aerodatabox_requests"):
        data = usage.get(name)
        if isinstance(data, dict):
            for old in sorted(data.keys(), reverse=True)[3:]:
                del data[old]
    _save_usage(usage)


def _request_payload(
    *,
    airport_iata: str,
    display_grace_minutes: int,
    display_horizon_hours: int,
    timeout_s: int,
) -> Dict[str, Any]:
    if not has_enabled_key():
        raise AeroDataBoxError(
            "AeroDataBox client is disabled. Set AERODATABOX_API_KEY and LOCALFLIGHT_AERODATABOX_ENABLED=1 to enable."
        )

    offset_minutes = -max(0, int(display_grace_minutes))
    duration_minutes = max(60, max(0, int(display_grace_minutes)) + max(1, int(display_horizon_hours)) * 60)
    _increment_units(_fids_units())
    try:
        response = requests.get(
            f"{AERODATABOX_BASE_URL}/flights/airports/iata/{airport_iata.upper().strip()}",
            params={
                "offsetMinutes": offset_minutes,
                "durationMinutes": duration_minutes,
                "direction": "Both",
                "withLeg": "true",
                "withCancelled": "true",
                "withCodeshared": "true",
                "withCargo": "false",
                "withPrivate": "false",
                "withLocation": "false",
            },
            headers={
                "X-RapidAPI-Key": _api_key(),
                "X-RapidAPI-Host": "aerodatabox.p.rapidapi.com",
                "Accept": "application/json",
                "User-Agent": "local-flight/1.0 (+https://localflight.invalid)",
            },
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise AeroDataBoxError(f"AeroDataBox request failed: {exc}") from exc

    if response.status_code == 204:
        return {"departures": [], "arrivals": []}
    if response.status_code == 429:
        raise AeroDataBoxBudgetExceeded("AeroDataBox provider quota exceeded upstream.")
    if response.status_code >= 400:
        raise AeroDataBoxError(f"AeroDataBox HTTP {response.status_code}")
    try:
        payload = response.json()
    except Exception as exc:
        raise AeroDataBoxError(f"AeroDataBox returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise AeroDataBoxError("AeroDataBox response shape invalid")
    return payload


def fetch_schedule_records(
    *,
    airport_iata: str,
    airport_icao: str = "",
    timezone_name: str = "UTC",
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES,
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS,
    timeout_s: int = 25,
    now: Optional[datetime] = None,
    return_meta: bool = False,
) -> Any:
    payload = _request_payload(
        airport_iata=airport_iata,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        timeout_s=timeout_s,
    )
    records = aerodatabox_to_raw_records(
        payload,
        airport_iata=airport_iata,
        airport_icao=airport_icao,
        mode="both",
    )
    meta = {
        "provider": "aerodatabox",
        "timezone": timezone_name,
        "requested_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "units_spent": _fids_units(),
        "request_count": 1,
        "raw_rows": len(payload.get("departures") or []) + len(payload.get("arrivals") or []),
        "record_count": len(records),
    }
    if return_meta:
        return records, meta
    return records
