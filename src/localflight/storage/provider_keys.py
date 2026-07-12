from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from localflight.sources.web.relay_defaults import default_public_relay_url
from localflight.storage.config import load_config

AERODATABOX_DEFAULT_MONTHLY_UNITS = 24_000
AERODATABOX_DEFAULT_FIDS_UNITS = 2
AVIATIONSTACK_DEFAULT_MONTHLY_CALLS = 90
RAPIDAPI_DEFAULT_MONTHLY_CALLS = 10_000

VALID_AERODATABOX_MARKETPLACES = {"apimarket", "rapidapi"}

SECRET_KEYS = {
    "AERODATABOX_API_KEY",
    "AVIATIONSTACK_API_KEY",
    "RAPIDAPI_KEY",
    "OPENSKY_CLIENT_ID",
    "OPENSKY_CLIENT_SECRET",
}

DIRECT_PROVIDER_KEYS = {
    *SECRET_KEYS,
    "AERODATABOX_MARKETPLACE",
    "LOCALFLIGHT_AERODATABOX_MARKETPLACE",
    "LOCALFLIGHT_AERODATABOX_ENABLED",
    "LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT",
    "LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT",
    "LOCALFLIGHT_AERODATABOX_FIDS_TIER2_UNITS",
    "LOCALFLIGHT_AVIATIONSTACK_ENABLED",
    "LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT",
    "LOCALFLIGHT_AVIATIONSTACK_DAILY_LIMIT",
    "LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT",
    "LOCALFLIGHT_REAL_SCHEDULE_PROVIDER",
}

RELAY_KEYS = {
    "LOCALFLIGHT_ACTIVATION_TOKEN",
    "LOCALFLIGHT_RELAY_URL",
}

PROVIDER_ENV_KEYS = frozenset({*DIRECT_PROVIDER_KEYS, *RELAY_KEYS})


def env_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / ".localflight" / ".env"
    here = Path(__file__).resolve()
    return here.parents[3] / ".env"


def read_env(path: Path | None = None) -> Dict[str, str]:
    target = path or env_path()
    values: Dict[str, str] = {}
    if not target.exists():
        return values
    try:
        for raw_line in target.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key:
                values[key] = value.strip()
    except Exception:
        return {}
    return values


def provider_env_values(path: Path | None = None) -> Dict[str, str]:
    """Return effective environment with .env authoritative for provider keys."""
    target = path or env_path()
    file_values = read_env(target)
    values = {key: value for key, value in os.environ.items() if isinstance(value, str)}
    for key, value in file_values.items():
        if key in PROVIDER_ENV_KEYS or key not in values:
            values[key] = value
    if target.exists():
        for key in PROVIDER_ENV_KEYS:
            if key not in file_values:
                values.pop(key, None)
    return values


def apply_provider_env(values: Dict[str, str]) -> None:
    """Make Local Flight-owned provider/relay env mirror the supplied values."""
    for key in PROVIDER_ENV_KEYS:
        if key in values:
            os.environ[key] = values[key]
        else:
            os.environ.pop(key, None)


def reload_provider_env(path: Path | None = None) -> Path | None:
    """Reload provider/relay keys from .env, with .env authoritative when present."""
    target = path or env_path()
    if not target.exists():
        return None
    apply_provider_env(read_env(target))
    return target


def write_env(values: Dict[str, str], *, removed: Iterable[str] = (), path: Path | None = None) -> None:
    target = path or env_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Local Flight - environment variables\n"]
    for key, value in values.items():
        lines.append(f"{key}={value}\n")
    pending = target.with_name(f".{target.name}.tmp")
    pending.write_text("".join(lines), encoding="utf-8")
    try:
        pending.chmod(0o600)
    except OSError:
        pass
    os.replace(pending, target)
    for key in set(removed):
        if key not in PROVIDER_ENV_KEYS:
            os.environ.pop(key, None)
    apply_provider_env(values)
    for key, value in values.items():
        if key not in PROVIDER_ENV_KEYS and key not in os.environ:
            os.environ[key] = value


def truthy_env(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def aerodatabox_enabled(values: Dict[str, str] | None = None) -> bool:
    source = values if values is not None else os.environ
    if not str(source.get("AERODATABOX_API_KEY", "")).strip():
        return False
    raw = str(source.get("LOCALFLIGHT_AERODATABOX_ENABLED", "")).strip().lower()
    return not raw or raw in {"1", "true", "yes", "on"}


def aviationstack_enabled(values: Dict[str, str] | None = None) -> bool:
    source = values if values is not None else os.environ
    if not str(source.get("AVIATIONSTACK_API_KEY", "")).strip():
        return False
    raw = str(source.get("LOCALFLIGHT_AVIATIONSTACK_ENABLED", "")).strip().lower()
    return not raw or raw in {"1", "true", "yes", "on"}


def any_direct_schedule_key(values: Dict[str, str] | None = None) -> bool:
    return aerodatabox_enabled(values) or aviationstack_enabled(values)


def normalize_aerodatabox_marketplace(value: str | None) -> str:
    clean = (value or "apimarket").strip().lower().replace("_", "-")
    if clean in {"rapid", "rapid-api", "rapidapi"}:
        return "rapidapi"
    return "apimarket"


def positive_int(value: Any, default: int, *, minimum: int = 0, maximum: int | None = None) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def clear_direct_provider_values(values: Dict[str, str], *, clear_activation: bool = True) -> set[str]:
    removed: set[str] = set()
    for key in DIRECT_PROVIDER_KEYS:
        if key in values:
            values.pop(key, None)
            removed.add(key)
    values["LOCALFLIGHT_AERODATABOX_ENABLED"] = "0"
    values["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "0"
    if clear_activation:
        for key in RELAY_KEYS:
            if key in values:
                values.pop(key, None)
                removed.add(key)
    return removed


def apply_byok_values(
    values: Dict[str, str],
    *,
    aerodatabox_key: str = "",
    aerodatabox_marketplace: str = "apimarket",
    aerodatabox_monthly_units_limit: Any = AERODATABOX_DEFAULT_MONTHLY_UNITS,
    aerodatabox_daily_units_limit: Any = "",
    aviationstack_key: str = "",
    rapidapi_key: str = "",
    opensky_id: str = "",
    opensky_secret: str = "",
) -> set[str]:
    removed = clear_direct_provider_values(values, clear_activation=True)
    for key in RELAY_KEYS:
        values.pop(key, None)
        removed.add(key)
    values["LOCALFLIGHT_REAL_SCHEDULE_PROVIDER"] = "auto"

    adb_key = aerodatabox_key.strip()
    as_key = aviationstack_key.strip()
    if adb_key:
        values["AERODATABOX_API_KEY"] = adb_key
        values["LOCALFLIGHT_AERODATABOX_ENABLED"] = "1"
        values["LOCALFLIGHT_AERODATABOX_MARKETPLACE"] = normalize_aerodatabox_marketplace(aerodatabox_marketplace)
        monthly = positive_int(aerodatabox_monthly_units_limit, AERODATABOX_DEFAULT_MONTHLY_UNITS, minimum=0)
        values["LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT"] = str(monthly)
        if str(aerodatabox_daily_units_limit or "").strip():
            values["LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT"] = str(
                positive_int(aerodatabox_daily_units_limit, max(1, (monthly + 29) // 30), minimum=0)
            )
        values["LOCALFLIGHT_AERODATABOX_FIDS_TIER2_UNITS"] = str(AERODATABOX_DEFAULT_FIDS_UNITS)
    else:
        values["LOCALFLIGHT_AERODATABOX_ENABLED"] = "0"

    if as_key:
        values["AVIATIONSTACK_API_KEY"] = as_key
        values["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "1"
        values["LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT"] = str(AVIATIONSTACK_DEFAULT_MONTHLY_CALLS)
    else:
        values["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "0"

    if rapidapi_key.strip():
        values["RAPIDAPI_KEY"] = rapidapi_key.strip()
        values["LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT"] = str(RAPIDAPI_DEFAULT_MONTHLY_CALLS)
    if opensky_id.strip():
        values["OPENSKY_CLIENT_ID"] = opensky_id.strip()
    if opensky_secret.strip():
        values["OPENSKY_CLIENT_SECRET"] = opensky_secret.strip()
    return removed


def apply_relay_values(
    values: Dict[str, str],
    *,
    activation_token: str = "",
    relay_url: str = "",
    community: bool = False,
) -> set[str]:
    removed = clear_direct_provider_values(values, clear_activation=False if community else True)
    if activation_token.strip():
        values["LOCALFLIGHT_ACTIVATION_TOKEN"] = activation_token.strip()
    elif community:
        values.pop("LOCALFLIGHT_ACTIVATION_TOKEN", None)
        removed.add("LOCALFLIGHT_ACTIVATION_TOKEN")
    values["LOCALFLIGHT_RELAY_URL"] = (relay_url or default_public_relay_url()).strip().rstrip("/")
    return removed


def apply_virtual_values(values: Dict[str, str]) -> set[str]:
    removed = clear_direct_provider_values(values, clear_activation=True)
    values.pop("LOCALFLIGHT_RELAY_URL", None)
    removed.add("LOCALFLIGHT_RELAY_URL")
    return removed


def provider_status() -> Dict[str, Any]:
    values = provider_env_values()
    cfg = load_config()
    adb = aerodatabox_enabled(values)
    aviation = aviationstack_enabled(values)
    rapid = bool(str(values.get("RAPIDAPI_KEY", "")).strip())
    opensky = bool(str(values.get("OPENSKY_CLIENT_ID", "")).strip() or str(values.get("OPENSKY_CLIENT_SECRET", "")).strip())
    token = bool(str(values.get("LOCALFLIGHT_ACTIVATION_TOKEN", "")).strip())
    if (cfg.source or "").strip().lower() == "virtual":
        active_path = "VATSIM virtual traffic"
        privacy_posture = "virtual"
    elif adb and aviation:
        active_path = "AeroDataBox direct + AviationStack fill"
        privacy_posture = "direct_private"
    elif adb:
        active_path = "AeroDataBox direct"
        privacy_posture = "direct_private"
    elif aviation:
        active_path = "AviationStack direct"
        privacy_posture = "direct_private"
    elif token:
        active_path = "Managed Beacon Tools relay"
        privacy_posture = "relay"
    else:
        active_path = "Community relay"
        privacy_posture = "relay"
    return {
        "ok": True,
        "active_path": active_path,
        "privacy_posture": privacy_posture,
        "aerodatabox": {
            "configured": bool(str(values.get("AERODATABOX_API_KEY", "")).strip()),
            "enabled": adb,
            "marketplace": normalize_aerodatabox_marketplace(str(values.get("LOCALFLIGHT_AERODATABOX_MARKETPLACE", ""))),
            "monthly_units_limit": positive_int(
                values.get("LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT"),
                AERODATABOX_DEFAULT_MONTHLY_UNITS,
                minimum=0,
            ),
        },
        "aviationstack": {
            "configured": bool(str(values.get("AVIATIONSTACK_API_KEY", "")).strip()),
            "enabled": aviation,
        },
        "adsbexchange": {
            "configured": rapid,
            "mode": "direct RapidAPI" if rapid else "fallback only",
        },
        "opensky": {
            "configured": opensky,
        },
        "relay": {
            "activation_token": token,
            "url": str(values.get("LOCALFLIGHT_RELAY_URL", "") or default_public_relay_url()).rstrip("/"),
        },
    }


def show_provider_key_settings(status: Dict[str, Any] | None) -> bool:
    """Provider-key controls are only actionable for direct/BYOK installs."""
    if not isinstance(status, dict):
        return False
    return str(status.get("privacy_posture") or "").strip().lower() == "direct_private"


def save_provider_keys(
    *,
    aerodatabox_key: str = "",
    aerodatabox_marketplace: str = "apimarket",
    aerodatabox_monthly_units_limit: Any = AERODATABOX_DEFAULT_MONTHLY_UNITS,
    aerodatabox_daily_units_limit: Any = "",
    aviationstack_key: str = "",
    rapidapi_key: str = "",
    opensky_id: str = "",
    opensky_secret: str = "",
    path: Path | None = None,
) -> Tuple[Dict[str, str], set[str]]:
    values = read_env(path)
    existing = dict(values)
    saved_adb_key = existing.get("AERODATABOX_API_KEY", "") if aerodatabox_enabled(existing) else ""
    saved_as_key = existing.get("AVIATIONSTACK_API_KEY", "") if aviationstack_enabled(existing) else ""
    effective_adb_key = aerodatabox_key.strip() or saved_adb_key
    effective_as_key = aviationstack_key.strip() or saved_as_key
    if effective_adb_key or effective_as_key:
        removed = apply_byok_values(
            values,
            aerodatabox_key=effective_adb_key,
            aerodatabox_marketplace=aerodatabox_marketplace or existing.get("LOCALFLIGHT_AERODATABOX_MARKETPLACE", "apimarket"),
            aerodatabox_monthly_units_limit=aerodatabox_monthly_units_limit
            or existing.get("LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT", AERODATABOX_DEFAULT_MONTHLY_UNITS),
            aerodatabox_daily_units_limit=aerodatabox_daily_units_limit,
            aviationstack_key=effective_as_key,
            rapidapi_key=rapidapi_key or existing.get("RAPIDAPI_KEY", ""),
            opensky_id=opensky_id or existing.get("OPENSKY_CLIENT_ID", ""),
            opensky_secret=opensky_secret or existing.get("OPENSKY_CLIENT_SECRET", ""),
        )
    else:
        removed = set()
        values["LOCALFLIGHT_AERODATABOX_ENABLED"] = "0"
        values["LOCALFLIGHT_AVIATIONSTACK_ENABLED"] = "0"
        if rapidapi_key.strip():
            values["RAPIDAPI_KEY"] = rapidapi_key.strip()
            values.setdefault("LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT", str(RAPIDAPI_DEFAULT_MONTHLY_CALLS))
        if opensky_id.strip():
            values["OPENSKY_CLIENT_ID"] = opensky_id.strip()
        if opensky_secret.strip():
            values["OPENSKY_CLIENT_SECRET"] = opensky_secret.strip()
    write_env(values, removed=removed, path=path)
    return values, removed


def clear_provider_keys(path: Path | None = None) -> Dict[str, str]:
    values = read_env(path)
    removed = clear_direct_provider_values(values, clear_activation=False)
    write_env(values, removed=removed, path=path)
    return values
