"""Shared radar presentation rules.

The schedule and track classifiers decide what a target represents. This
module only decides how that target is presented by the Qt, LAN, and mobile
radar surfaces.
"""
from __future__ import annotations

import math
import re
from typing import Any


RADAR_PRESENTATION_VERSION = 1
RADAR_REVOLUTION_MS = 15_000
RADAR_DEGREES_PER_SECOND = 24.0
RADAR_FRAME_INTERVAL_MS = 80
RADAR_TRAIL_DEGREES = 72.0
RADAR_FLASH_DEGREES = 6.0
RADAR_FOCUSED_MIN_OPACITY = 0.86
RADAR_INTERACTIVE_MIN_OPACITY = 0.08

_STALE_PATTERN = re.compile(r"\b(stale|lost|missing|invalid|expired)\b", re.IGNORECASE)
_PHASE_PRIORITY = {
    "final": 700,
    "approach": 600,
    "departing": 500,
    "descending": 400,
    "enroute": 300,
    "taxi": 200,
    "on_ground": 100,
    "unknown": 250,
}


def normalize_angle(value: float) -> float:
    """Normalize a bearing to north-zero, clockwise degrees."""
    return float(value) % 360.0


def sweep_angle_after(start_angle: float, elapsed_ms: float) -> float:
    """Advance a sweep from elapsed monotonic time, not timer tick counts."""
    elapsed = max(0.0, float(elapsed_ms))
    return normalize_angle(start_angle + elapsed * 360.0 / RADAR_REVOLUTION_MS)


def bearing_from_offset(x_nm: float, y_nm: float) -> float:
    """Return clockwise bearing where positive ``y_nm`` points north."""
    return normalize_angle(math.degrees(math.atan2(float(x_nm), float(y_nm))))


def angular_age(sweep_angle: float, target_bearing: float) -> float:
    """Return degrees travelled since the leading line crossed a target."""
    return normalize_angle(float(sweep_angle) - float(target_bearing))


def blip_opacity(target_bearing: float, sweep_angle: float, *, focused: bool = False) -> float:
    """Return phosphor opacity for a target at the current sweep angle."""
    age = angular_age(sweep_angle, target_bearing)
    if age <= RADAR_FLASH_DEGREES:
        opacity = 1.0
    elif age < RADAR_TRAIL_DEGREES:
        fade_span = RADAR_TRAIL_DEGREES - RADAR_FLASH_DEGREES
        opacity = 1.0 - ((age - RADAR_FLASH_DEGREES) / fade_span)
    else:
        opacity = 0.0
    if focused:
        opacity = max(opacity, RADAR_FOCUSED_MIN_OPACITY)
    return max(0.0, min(1.0, opacity))


def normalize_radar_phase(blip: dict[str, Any]) -> str:
    """Normalize presentation phases without consulting passenger board state."""
    raw = str(blip.get("radar_phase") or blip.get("radar_status") or "").strip().lower()
    raw = raw.replace("-", "_").replace(" ", "_")
    if raw in {"final", "approach", "departing", "descending", "enroute", "taxi", "on_ground"}:
        return raw
    if raw in {"arrival", "arriving", "landing"}:
        return "approach"
    if raw in {"departure", "climb", "climbing"}:
        return "departing"
    if raw in {"descent", "descend"}:
        return "descending"
    if raw in {"airborne", "cruise", "cruising"}:
        return "enroute"
    if raw in {"ground", "surface", "parked", "gate"} or blip.get("on_ground") is True:
        return "on_ground"
    return "unknown"


def target_is_stale(blip: dict[str, Any]) -> bool:
    if blip.get("position_stale") is True:
        return True
    quality = " ".join(
        str(blip.get(key) or "")
        for key in ("source_quality", "track_freshness", "freshness", "radar_quality")
    )
    return bool(_STALE_PATTERN.search(quality))


def target_tone_role(blip: dict[str, Any]) -> str:
    """Return a semantic palette role, never a hardcoded color."""
    if target_is_stale(blip):
        return "stale"
    phase = normalize_radar_phase(blip)
    if phase in {"on_ground", "taxi"}:
        return "ground"
    if phase == "departing":
        return "departure"
    if phase in {"approach", "final"}:
        return "approach"
    return "accent"


def target_shape(blip: dict[str, Any]) -> str:
    if target_is_stale(blip):
        return "hollow"
    if normalize_radar_phase(blip) in {"on_ground", "taxi"}:
        return "diamond"
    return "dot"


def radar_phase_label(blip: dict[str, Any]) -> str:
    phase = normalize_radar_phase(blip)
    return {
        "on_ground": "GROUND",
        "taxi": "TAXI",
        "departing": "DEP",
        "enroute": "EN ROUTE",
        "descending": "DESC",
        "approach": "APPROACH",
        "final": "FINAL",
        "unknown": "",
    }[phase]


def label_priority(blip: dict[str, Any], *, focused: bool = False) -> tuple[int, float, float]:
    """Return a stable descending priority tuple for scope label culling."""
    phase = normalize_radar_phase(blip)
    freshness = 0.0 if target_is_stale(blip) else 1.0
    try:
        distance = float(blip.get("distance_nm"))
    except (TypeError, ValueError):
        distance = 10_000.0
    return (10_000 if focused else _PHASE_PRIORITY[phase], freshness, -distance)


def target_is_interactive(target_bearing: float, sweep_angle: float, *, focused: bool = False) -> bool:
    return blip_opacity(target_bearing, sweep_angle, focused=focused) >= RADAR_INTERACTIVE_MIN_OPACITY
