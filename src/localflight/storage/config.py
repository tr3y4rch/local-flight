from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List

from localflight.core.settings_options import (
    DIAGNOSTICS_IDS,
    OUTPUT_IDS,
    REFRESH_SECONDS,
    SKIN_IDS,
    SOURCE_IDS,
)

ALLOWED_REFRESH_SECONDS = set(REFRESH_SECONDS)
DEFAULT_REFRESH_SECONDS = 3600

ALLOWED_SOURCES = set(SOURCE_IDS)
DEFAULT_SOURCE  = "real"

ALLOWED_SKINS = set(SKIN_IDS)
DEFAULT_SKIN  = "standard"

ALLOWED_OUTPUTS = set(OUTPUT_IDS)
DEFAULT_OUTPUTS  = ["web"]

ALLOWED_DIAGNOSTICS_MODES = set(DIAGNOSTICS_IDS)
DEFAULT_DIAGNOSTICS_MODE = "unset"
DEFAULT_WEB_ROW_LIMIT = 20
DEFAULT_WEB_ROTATION_SECONDS = 8
DEFAULT_DISPLAY_GRACE_MINUTES = 30
DEFAULT_DISPLAY_HORIZON_HOURS = 12
DEFAULT_RADAR_SURFACE_ENABLED = False


@dataclass(frozen=True)
class AppConfig:
    airport_icao:    str       = "LSZH"
    airport_iata:    str       = "ZRH"
    refresh_seconds: int       = DEFAULT_REFRESH_SECONDS
    display_name:    str       = "Local Flight"
    theme:           str       = "dark"
    source:          str       = DEFAULT_SOURCE
    timezone:        str       = "Europe/Zurich"
    skin:            str       = DEFAULT_SKIN
    display_outputs: List[str] = field(default_factory=lambda: list(DEFAULT_OUTPUTS))
    diagnostics_mode: str      = DEFAULT_DIAGNOSTICS_MODE
    web_row_limit: int         = DEFAULT_WEB_ROW_LIMIT
    web_rotation_seconds: int  = DEFAULT_WEB_ROTATION_SECONDS
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS
    radar_surface_enabled: bool = DEFAULT_RADAR_SURFACE_ENABLED


def config_path() -> Path:
    home_override = os.getenv("LOCALFLIGHT_HOME") or os.getenv("HOME")
    base_home = Path(home_override) if home_override else Path.home()
    base = base_home / ".localflight"
    base.mkdir(parents=True, exist_ok=True)
    return base / "config.json"


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    clean = str(value).strip().lower()
    if clean in {"1", "true", "yes", "on"}:
        return True
    if clean in {"0", "false", "no", "off"}:
        return False
    return default


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()

    airport_icao = str(raw.get("airport_icao", "LSZH")).upper().strip()
    airport_iata = str(raw.get("airport_iata", "ZRH")).upper().strip()
    timezone     = str(raw.get("timezone", "Europe/Zurich")).strip()

    if len(airport_icao) != 4:
        airport_icao = "LSZH"
    if len(airport_iata) != 3:
        airport_iata = "ZRH"

    refresh = _to_int(raw.get("refresh_seconds", DEFAULT_REFRESH_SECONDS), default=DEFAULT_REFRESH_SECONDS)
    if refresh not in ALLOWED_REFRESH_SECONDS:
        refresh = DEFAULT_REFRESH_SECONDS

    theme = str(raw.get("theme", "dark")).strip() or "dark"
    if theme not in {"dark", "light"}:
        theme = "dark"

    source = str(raw.get("source", DEFAULT_SOURCE)).strip().lower() or DEFAULT_SOURCE
    if source not in ALLOWED_SOURCES:
        source = DEFAULT_SOURCE

    skin = str(raw.get("skin", DEFAULT_SKIN)).strip().lower() or DEFAULT_SKIN
    if skin not in ALLOWED_SKINS:
        skin = DEFAULT_SKIN

    # ── display_outputs — migrate old configs gracefully ──────────────────────
    # Missing field (old config)  → default ["web"]
    # Plain string (broken save)  → wrap in list
    # Invalid values              → filter out, fallback to ["web"]
    raw_outputs = raw.get("display_outputs", DEFAULT_OUTPUTS)
    if isinstance(raw_outputs, str):
        raw_outputs = [raw_outputs]
    display_outputs = [o for o in raw_outputs if o in ALLOWED_OUTPUTS]
    if not display_outputs:
        display_outputs = list(DEFAULT_OUTPUTS)

    diagnostics_mode = str(raw.get("diagnostics_mode", DEFAULT_DIAGNOSTICS_MODE)).strip().lower() or DEFAULT_DIAGNOSTICS_MODE
    if diagnostics_mode not in ALLOWED_DIAGNOSTICS_MODES:
        diagnostics_mode = DEFAULT_DIAGNOSTICS_MODE

    web_row_limit = _to_int(raw.get("web_row_limit", DEFAULT_WEB_ROW_LIMIT), default=DEFAULT_WEB_ROW_LIMIT)
    web_row_limit = max(5, min(40, web_row_limit))

    web_rotation_seconds = _to_int(
        raw.get("web_rotation_seconds", DEFAULT_WEB_ROTATION_SECONDS),
        default=DEFAULT_WEB_ROTATION_SECONDS,
    )
    web_rotation_seconds = max(3, min(60, web_rotation_seconds))

    display_grace_minutes = _to_int(
        raw.get("display_grace_minutes", DEFAULT_DISPLAY_GRACE_MINUTES),
        default=DEFAULT_DISPLAY_GRACE_MINUTES,
    )
    display_grace_minutes = max(0, min(180, display_grace_minutes))

    display_horizon_hours = _to_int(
        raw.get("display_horizon_hours", DEFAULT_DISPLAY_HORIZON_HOURS),
        default=DEFAULT_DISPLAY_HORIZON_HOURS,
    )
    display_horizon_hours = max(1, min(24, display_horizon_hours))

    radar_surface_enabled = _to_bool(
        raw.get("radar_surface_enabled", DEFAULT_RADAR_SURFACE_ENABLED),
        DEFAULT_RADAR_SURFACE_ENABLED,
    )

    return AppConfig(
        airport_icao=airport_icao,
        airport_iata=airport_iata,
        refresh_seconds=refresh,
        display_name=str(raw.get("display_name", "Local Flight")).strip()[:40] or "Local Flight",
        theme=theme,
        source=source,
        timezone=timezone,
        skin=skin,
        display_outputs=display_outputs,
        diagnostics_mode=diagnostics_mode,
        web_row_limit=web_row_limit,
        web_rotation_seconds=web_rotation_seconds,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        radar_surface_enabled=radar_surface_enabled,
    )


def save_config(cfg: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
