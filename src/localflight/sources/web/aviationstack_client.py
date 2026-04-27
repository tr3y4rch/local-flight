from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import requests

# ── NOTE: env vars are read lazily at call time, NOT at import time.
# This ensures _load_dotenv() in __main__.py has already run before
# we check any env var. Do NOT use module-level `_X = os.getenv(...)` here.

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1/flights"

_DEFAULT_BYOK_LIMIT  = 10_000
_DEFAULT_RELAY_LIMIT = 60
_RELAY_DEFAULT_URL   = "https://relay.localflight.app/v1/flights"


class AviationstackError(RuntimeError):
    pass


class AviationstackBudgetExceeded(AviationstackError):
    pass


# ── Mode detection ─────────────────────────────────────────────────────────────

def _has_api_key() -> bool:
    return bool(os.getenv("AVIATIONSTACK_API_KEY", "").strip())


def _is_relay_mode() -> bool:
    """True when no user-supplied API key is configured."""
    return not _has_api_key()


def _get_api_key() -> str:
    key = os.getenv("AVIATIONSTACK_API_KEY", "").strip()
    if not key:
        raise AviationstackError("AVIATIONSTACK_API_KEY not set")
    return key


def _is_enabled() -> bool:
    """Kill switch for the BYOK path only."""
    return os.getenv("LOCALFLIGHT_AVIATIONSTACK_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _get_byok_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT", str(_DEFAULT_BYOK_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_BYOK_LIMIT


def _get_relay_url() -> str:
    return os.getenv("LOCALFLIGHT_RELAY_URL", _RELAY_DEFAULT_URL).rstrip("/")


def _get_relay_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_RELAY_MONTHLY_LIMIT", str(_DEFAULT_RELAY_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_RELAY_LIMIT


# ── Usage counter (shared file for both modes) ─────────────────────────────────

def _usage_path() -> Path:
    from localflight.storage.config import config_path
    return config_path().parent / "api_usage.json"


def _load_usage() -> Dict[str, Any]:
    p = _usage_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_usage(data: Dict[str, Any]) -> None:
    try:
        _usage_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _increment_budget(bucket: str, limit: int, n_calls: int = 1) -> None:
    """Increment counter for `bucket` in api_usage.json; raise if over limit."""
    usage      = _load_usage()
    month      = _month_key()
    month_data = usage.setdefault(bucket, {})
    current    = month_data.get(month, 0)

    if current + n_calls > limit:
        if bucket == "relay":
            raise AviationstackBudgetExceeded(
                f"Community relay quota exceeded: {current}/{limit} calls used "
                f"this month ({month}). Add AVIATIONSTACK_API_KEY to your .env "
                f"for your own subscription."
            )
        raise AviationstackBudgetExceeded(
            f"AviationStack monthly budget exceeded: {current}/{limit} calls used "
            f"this month ({month}). Set LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=N "
            f"to increase, or wait until next month."
        )

    month_data[month] = current + n_calls
    for old in sorted(month_data.keys(), reverse=True)[3:]:
        del month_data[old]
    _save_usage(usage)


def _sync_relay_quota_from_headers(headers: Any) -> None:
    """
    If the relay returns X-LF-Quota-Used, sync it into the local counter.
    This keeps the local budget display accurate without a second API call.
    """
    used_str = headers.get("X-LF-Quota-Used") if headers else None
    if used_str is None:
        return
    try:
        used     = int(used_str)
        usage    = _load_usage()
        month    = _month_key()
        md       = usage.setdefault("relay", {})
        md[month] = used
        _save_usage(usage)
    except Exception:
        pass


# ── BYOK fetch (original path) ─────────────────────────────────────────────────

def _fetch_byok(
    *,
    airport_iata: str,
    limit: int,
    mode: str,
    dep_iata: Optional[str],
    arr_iata: Optional[str],
    timeout_s: int,
) -> Dict[str, Any]:
    if not _is_enabled():
        raise AviationstackError(
            "AviationStack client is DISABLED. "
            "Set LOCALFLIGHT_AVIATIONSTACK_ENABLED=1 to enable."
        )

    airport = airport_iata.upper().strip()
    if not airport:
        raise AviationstackError("airport_iata is empty")

    _increment_budget("aviationstack", _get_byok_limit())

    dep = dep_iata.upper().strip() if dep_iata else None
    arr = arr_iata.upper().strip() if arr_iata else None
    if dep is None and arr is None:
        if mode == "departures":
            dep = airport
        else:
            arr = airport

    params: Dict[str, Any] = {"access_key": _get_api_key(), "limit": int(limit)}
    if dep:
        params["dep_iata"] = dep
    if arr:
        params["arr_iata"] = arr

    try:
        r = requests.get(
            AVIATIONSTACK_BASE_URL,
            params=params,
            headers={
                "User-Agent": "local-flight/1.0 (+https://localflight.invalid)",
                "Accept":     "application/json",
            },
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        raise AviationstackError(f"AviationStack request failed: {e}") from e

    if r.status_code >= 400:
        msg = f"AviationStack HTTP {r.status_code}"
        try:
            err = r.json().get("error") if isinstance(r.json(), dict) else None
            if isinstance(err, dict):
                msg += f" ({err.get('code')}): {err.get('info')}"
        except Exception:
            pass
        raise AviationstackError(msg)

    data = r.json()
    if not isinstance(data, dict) or "data" not in data:
        raise AviationstackError("AviationStack response missing 'data' field")
    return data


# ── Relay fetch (community path) ───────────────────────────────────────────────

def _fetch_relay(
    *,
    airport_iata: str,
    limit: int,
    mode: str,
    dep_iata: Optional[str],
    arr_iata: Optional[str],
    timeout_s: int,
) -> Dict[str, Any]:
    from localflight.storage.install import get_install_id

    airport = airport_iata.upper().strip()
    if not airport:
        raise AviationstackError("airport_iata is empty")

    _increment_budget("relay", _get_relay_limit())

    dep = dep_iata.upper().strip() if dep_iata else None
    arr = arr_iata.upper().strip() if arr_iata else None
    if dep is None and arr is None:
        if mode == "departures":
            dep = airport
        else:
            arr = airport

    params: Dict[str, Any] = {"install_id": get_install_id(), "limit": int(limit)}
    if dep:
        params["dep_iata"] = dep
    if arr:
        params["arr_iata"] = arr

    try:
        r = requests.get(
            _get_relay_url(),
            params=params,
            headers={
                "User-Agent": "local-flight/1.0 (+https://localflight.invalid)",
                "Accept":     "application/json",
            },
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        raise AviationstackError(f"Community relay request failed: {e}") from e

    if r.status_code == 429:
        raise AviationstackBudgetExceeded(
            "Community relay quota exceeded. "
            "Add AVIATIONSTACK_API_KEY to your .env for your own subscription."
        )
    if r.status_code >= 400:
        msg = f"Community relay HTTP {r.status_code}"
        try:
            err = r.json().get("error") if isinstance(r.json(), dict) else None
            if isinstance(err, dict):
                msg += f" ({err.get('code')}): {err.get('info')}"
        except Exception:
            pass
        raise AviationstackError(msg)

    data = r.json()
    _sync_relay_quota_from_headers(r.headers)

    if not isinstance(data, dict) or "data" not in data:
        raise AviationstackError("Community relay response missing 'data' field")
    return data


# ── Public fetch entry point ───────────────────────────────────────────────────

def fetch_flights_once(
    *,
    airport_iata: str,
    limit: int = 10,
    mode: Literal["departures", "arrivals"] = "departures",
    dep_iata: Optional[str] = None,
    arr_iata: Optional[str] = None,
    timeout_s: int = 20,
) -> Dict[str, Any]:
    """
    Fetch one page of flight data.

    Routing:
      - AVIATIONSTACK_API_KEY set → BYOK path (your key, your quota)
      - No key                    → community relay (bundled quota, install_id token)

    Both paths return the same AviationStack-shaped dict.
    """
    if _is_relay_mode():
        return _fetch_relay(
            airport_iata=airport_iata,
            limit=limit,
            mode=mode,
            dep_iata=dep_iata,
            arr_iata=arr_iata,
            timeout_s=timeout_s,
        )
    return _fetch_byok(
        airport_iata=airport_iata,
        limit=limit,
        mode=mode,
        dep_iata=dep_iata,
        arr_iata=arr_iata,
        timeout_s=timeout_s,
    )


# ── Usage stats (surfaced in /api/admin/budget) ────────────────────────────────

def get_usage_stats() -> Dict[str, Any]:
    """Current usage stats. Includes mode so the admin UI can label correctly."""
    usage = _load_usage()
    month = _month_key()

    if _is_relay_mode():
        limit = _get_relay_limit()
        calls = usage.get("relay", {}).get(month, 0)
        return {
            "mode":             "relay",
            "relay_url":        _get_relay_url(),
            "month":            month,
            "calls_this_month": calls,
            "monthly_limit":    limit,
            "remaining":        max(0, limit - calls),
            "budget_ok":        calls < limit,
            "enabled":          True,
        }

    # BYOK mode
    limit = _get_byok_limit()
    calls = usage.get("aviationstack", {}).get(month, 0)
    return {
        "mode":             "byok",
        "month":            month,
        "calls_this_month": calls,
        "monthly_limit":    limit,
        "remaining":        max(0, limit - calls),
        "budget_ok":        calls < limit,
        "enabled":          _is_enabled(),
    }
