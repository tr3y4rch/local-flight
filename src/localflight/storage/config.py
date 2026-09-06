from __future__ import annotations

import json
import os
import sys
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

ALLOWED_DATA_ROUTES = {"relay", "byok", "vatsim"}
DEFAULT_DATA_ROUTE = "relay"

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
ALLOWED_RADAR_SURFACE_MODES = {"off", "estimated", "relay"}
DEFAULT_RADAR_SURFACE_MODE = "off"


@dataclass(frozen=True)
class AppConfig:
    airport_icao:    str       = "LSZH"
    airport_iata:    str       = "ZRH"
    refresh_seconds: int       = DEFAULT_REFRESH_SECONDS
    display_name:    str       = "Local Flight"
    theme:           str       = "dark"
    source:          str       = DEFAULT_SOURCE
    # ``source`` remains the scheduler-facing real/virtual switch. ``data_route``
    # is the user-facing, additive route contract and distinguishes hosted real
    # data from direct provider keys.
    data_route:      str       = ""
    timezone:        str       = "Europe/Zurich"
    skin:            str       = DEFAULT_SKIN
    display_outputs: List[str] = field(default_factory=lambda: list(DEFAULT_OUTPUTS))
    diagnostics_mode: str      = DEFAULT_DIAGNOSTICS_MODE
    web_row_limit: int         = DEFAULT_WEB_ROW_LIMIT
    web_rotation_seconds: int  = DEFAULT_WEB_ROTATION_SECONDS
    display_grace_minutes: int = DEFAULT_DISPLAY_GRACE_MINUTES
    display_horizon_hours: int = DEFAULT_DISPLAY_HORIZON_HOURS
    radar_surface_enabled: bool = DEFAULT_RADAR_SURFACE_ENABLED
    radar_surface_mode: str = DEFAULT_RADAR_SURFACE_MODE
    remote_companion_enabled: bool = False

    def __post_init__(self) -> None:
        route = str(self.data_route or "").strip().lower()
        if route not in ALLOWED_DATA_ROUTES:
            route = "vatsim" if str(self.source or "").strip().lower() == "virtual" else DEFAULT_DATA_ROUTE
        object.__setattr__(self, "data_route", route)
        object.__setattr__(self, "source", "virtual" if route == "vatsim" else "real")
        surface_mode = str(self.radar_surface_mode or "").strip().lower()
        if surface_mode not in ALLOWED_RADAR_SURFACE_MODES:
            surface_mode = "relay" if self.radar_surface_enabled else DEFAULT_RADAR_SURFACE_MODE
        elif self.radar_surface_enabled and surface_mode == "off":
            # Preserve older call sites/tests that only toggled the legacy boolean.
            surface_mode = "relay"
        object.__setattr__(self, "radar_surface_mode", surface_mode)
        object.__setattr__(self, "radar_surface_enabled", surface_mode != "off")


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


def _legacy_data_route(path: Path, *, source: str) -> str:
    """Infer the additive route for configs written before ``data_route``.

    Provider configuration historically lived beside the config in packaged
    builds and at the repository root in source checkouts. Environment values
    are also considered because startup may already have loaded that file.
    """
    if source == "virtual":
        return "vatsim"

    values = dict(os.environ)
    env_file = path.parent / ".env" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[3] / ".env"
    try:
        for raw_line in env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    except Exception:
        pass

    disabled = {"0", "false", "no", "off"}
    direct_enabled = any(
        str(values.get(key) or "").strip()
        and str(values.get(enabled_key) or "").strip().lower() not in disabled
        for key, enabled_key in (
            ("AERODATABOX_API_KEY", "LOCALFLIGHT_AERODATABOX_ENABLED"),
            ("AVIATIONSTACK_API_KEY", "LOCALFLIGHT_AVIATIONSTACK_ENABLED"),
        )
    )
    if direct_enabled:
        return "byok"
    if (path.parent / "activation_token").exists() or str(values.get("LOCALFLIGHT_ACTIVATION_TOKEN") or "").strip():
        return "relay"
    return DEFAULT_DATA_ROUTE


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig(data_route=_legacy_data_route(path, source=DEFAULT_SOURCE))

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

    legacy_surface_enabled = _to_bool(
        raw.get("radar_surface_enabled", DEFAULT_RADAR_SURFACE_ENABLED),
        DEFAULT_RADAR_SURFACE_ENABLED,
    )
    radar_surface_mode = str(raw.get("radar_surface_mode") or "").strip().lower()
    if not radar_surface_mode:
        radar_surface_mode = "relay" if legacy_surface_enabled else DEFAULT_RADAR_SURFACE_MODE
    if radar_surface_mode not in ALLOWED_RADAR_SURFACE_MODES:
        radar_surface_mode = DEFAULT_RADAR_SURFACE_MODE
    radar_surface_enabled = radar_surface_mode != "off"
    remote_companion_enabled = _to_bool(raw.get("remote_companion_enabled", False), False)
    raw_data_route = str(raw.get("data_route") or "").strip().lower()
    migrated_data_route = raw_data_route if raw_data_route in ALLOWED_DATA_ROUTES else _legacy_data_route(path, source=source)

    cfg = AppConfig(
        airport_icao=airport_icao,
        airport_iata=airport_iata,
        refresh_seconds=refresh,
        display_name=str(raw.get("display_name", "Local Flight")).strip()[:40] or "Local Flight",
        theme=theme,
        source=source,
        data_route=migrated_data_route,
        timezone=timezone,
        skin=skin,
        display_outputs=display_outputs,
        diagnostics_mode=diagnostics_mode,
        web_row_limit=web_row_limit,
        web_rotation_seconds=web_rotation_seconds,
        display_grace_minutes=display_grace_minutes,
        display_horizon_hours=display_horizon_hours,
        radar_surface_enabled=radar_surface_enabled,
        radar_surface_mode=radar_surface_mode,
        remote_companion_enabled=remote_companion_enabled,
    )
    if raw_data_route not in ALLOWED_DATA_ROUTES:
        try:
            raw["data_route"] = cfg.data_route
            path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return cfg


def save_config(cfg: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
