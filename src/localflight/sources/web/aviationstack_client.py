from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal, Optional

import requests

AVIATIONSTACK_BASE_URL = "https://api.aviationstack.com/v1/flights"

# ── NOTE: env vars are read lazily at call time, NOT at import time.
# This ensures _load_dotenv() in __main__.py has already run before
# we check LOCALFLIGHT_AVIATIONSTACK_ENABLED or AVIATIONSTACK_API_KEY.
# Do NOT use module-level `_ENABLED = os.getenv(...)` here.

_DEFAULT_MONTHLY_LIMIT = 90


class AviationstackError(RuntimeError):
    pass


class AviationstackBudgetExceeded(AviationstackError):
    pass


# ── Enabled check (lazy) ───────────────────────────────────────────────────────

def _is_enabled() -> bool:
    return os.getenv("LOCALFLIGHT_AVIATIONSTACK_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _get_api_key() -> str:
    key = os.getenv("AVIATIONSTACK_API_KEY", "").strip()
    if not key:
        raise AviationstackError("AVIATIONSTACK_API_KEY not set")
    return key


def _get_monthly_limit() -> int:
    try:
        return int(os.getenv("LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT", str(_DEFAULT_MONTHLY_LIMIT)))
    except (ValueError, TypeError):
        return _DEFAULT_MONTHLY_LIMIT


# ── Usage counter ──────────────────────────────────────────────────────────────

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


def _check_and_increment_budget(n_calls: int = 1) -> None:
    usage      = _load_usage()
    month      = _month_key()
    limit      = _get_monthly_limit()
    month_data = usage.setdefault("aviationstack", {})
    current    = month_data.get(month, 0)

    if current + n_calls > limit:
        raise AviationstackBudgetExceeded(
            f"AviationStack monthly budget exceeded: {current}/{limit} calls used "
            f"this month ({month}). Set LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=N "
            f"to increase, or wait until next month."
        )

    month_data[month] = current + n_calls

    # Prune old months — keep last 3
    for old in sorted(month_data.keys(), reverse=True)[3:]:
        del month_data[old]

    _save_usage(usage)


def get_usage_stats() -> Dict[str, Any]:
    """Returns current AviationStack usage stats. Safe to call anytime."""
    usage  = _load_usage()
    month  = _month_key()
    limit  = _get_monthly_limit()
    calls  = usage.get("aviationstack", {}).get(month, 0)
    return {
        "month":            month,
        "calls_this_month": calls,
        "monthly_limit":    limit,
        "remaining":        max(0, limit - calls),
        "budget_ok":        calls < limit,
        "enabled":          _is_enabled(),
    }


# ── Main fetch ─────────────────────────────────────────────────────────────────

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
    Perform ONE AviationStack API request.

    Kill switch:  LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
    Budget limit: LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90 (default)
    Both are read lazily at call time so .env loading order doesn't matter.
    """
    # ── Kill switch check ──────────────────────────────────────────────────────
    if not _is_enabled():
        raise AviationstackError(
            "AviationStack client is DISABLED. "
            "Set LOCALFLIGHT_AVIATIONSTACK_ENABLED=1 to enable."
        )

    airport = airport_iata.upper().strip()
    if not airport:
        raise AviationstackError("airport_iata is empty")

    # ── Budget check (before request) ─────────────────────────────────────────
    _check_and_increment_budget(n_calls=1)

    # ── Build request params ───────────────────────────────────────────────────
    dep = dep_iata.upper().strip() if dep_iata else None
    arr = arr_iata.upper().strip() if arr_iata else None

    if dep is None and arr is None:
        if mode == "departures":
            dep = airport
        else:
            arr = airport

    params: Dict[str, Any] = {
        "access_key": _get_api_key(),
        "limit":      int(limit),
    }
    if dep:
        params["dep_iata"] = dep
    if arr:
        params["arr_iata"] = arr

    headers = {
        "User-Agent": "local-flight/1.0 (+https://localflight.invalid)",
        "Accept":     "application/json",
    }

    # ── HTTP request ───────────────────────────────────────────────────────────
    try:
        r = requests.get(
            AVIATIONSTACK_BASE_URL,
            params=params,
            headers=headers,
            timeout=timeout_s,
        )
    except requests.RequestException as e:
        raise AviationstackError(f"AviationStack request failed: {e}") from e

    if r.status_code >= 400:
        msg = f"AviationStack HTTP {r.status_code}"
        try:
            body = r.json()
            err  = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                msg += f" ({err.get('code')}): {err.get('info')}"
        except Exception:
            pass
        raise AviationstackError(msg)

    data = r.json()

    if not isinstance(data, dict) or "data" not in data:
        raise AviationstackError("AviationStack response missing 'data' field")

    return data