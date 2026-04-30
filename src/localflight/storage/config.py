from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, List

ALLOWED_REFRESH_SECONDS = {900, 1800, 2700, 3600, 7200, 14400, 28800, 43200, 86400}
DEFAULT_REFRESH_SECONDS = 3600

ALLOWED_SOURCES = {"real", "virtual"}
DEFAULT_SOURCE  = "real"

ALLOWED_SKINS = {"standard", "technical", "neon", "cyan", "crt"}
DEFAULT_SKIN  = "standard"

ALLOWED_OUTPUTS = {"web", "matrix", "hdmi"}
DEFAULT_OUTPUTS  = ["web"]

ALLOWED_DIAGNOSTICS_MODES = {"unset", "manual", "auto", "auto_logs"}
DEFAULT_DIAGNOSTICS_MODE = "unset"


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


def config_path() -> Path:
    base = Path.home() / ".localflight"
    base.mkdir(parents=True, exist_ok=True)
    return base / "config.json"


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
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
    )


def save_config(cfg: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), encoding="utf-8")
