"""FIDS board style descriptors.

Each ``FidsStyle`` instance tells the FlightBoardModel which columns to show
and tells the delegate how to size / colour / phrase the rows. The four
shipped styles are:

- ``classic`` — original Local Flight board (default for upgrades + fresh
  installs so behaviour is unchanged unless the user opts in).
- ``pax``     — passenger-friendly variant: bigger rows, larger fonts,
  warm colour palette, plain-English status verbs.
- ``vatsim``  — sim-network flavour: callsign-first, flight rules, phase,
  altitude+groundspeed compact field.
- ``nerd``    — dense operator view: every available column, smaller
  rows, monospace, code-style status tokens.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FidsStyle:
    key: str
    label: str
    emoji: str
    description: str
    columns: tuple[tuple[str, str], ...]
    row_height: int = 48
    font_scale: float = 1.0
    status_vocabulary: str = "standard"   # standard | friendly | code | phase
    color_intensity: str = "normal"        # high | normal | low
    show_codeshares: bool = True
    monospace_everywhere: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


CLASSIC = FidsStyle(
    key="classic",
    label="Classic",
    emoji="\U0001F6EC",  # 🛬
    description="The original board — balanced rows, board font, codeshare-aware.",
    columns=(
        ("display_time", "Time"),
        ("flight_cell", "Flight"),
        ("route_display", "Route"),
        ("status_display", "Status"),
        ("gate", "Gate"),
        ("aircraft_type", "A/C"),
    ),
    row_height=48,
    font_scale=1.0,
    status_vocabulary="standard",
    color_intensity="normal",
    show_codeshares=True,
)

PAX = FidsStyle(
    key="pax",
    label="PAX",
    emoji="\U0001F9F3",  # 🧳
    description="Passenger-friendly board — big rows, friendly status, gate badge.",
    columns=(
        ("display_time", "Time"),
        ("flight_cell", "Flight"),
        ("route_display", "Route"),
        ("status_display", "Status"),
        ("gate", "Gate"),
    ),
    row_height=62,
    font_scale=1.15,
    status_vocabulary="friendly",
    color_intensity="high",
    show_codeshares=True,
)

VATSIM = FidsStyle(
    key="vatsim",
    label="VATSIM",
    emoji="\U0001F6E9",  # 🛩
    description="Network view — callsign-first, flight rules, phase, alt+GS.",
    columns=(
        ("display_time", "Time"),
        ("callsign", "Callsign"),
        ("aircraft_type", "A/C"),
        ("flight_rules", "R"),
        ("route_display", "Route"),
        ("alt_speed", "Alt / GS"),
        ("phase", "Phase"),
    ),
    row_height=44,
    font_scale=1.0,
    status_vocabulary="phase",
    color_intensity="normal",
    show_codeshares=False,
)

NERD = FidsStyle(
    key="nerd",
    label="Nerd",
    emoji="\U0001F913",  # 🤓
    description="Operator view — every field, monospace, tight rows.",
    columns=(
        ("display_time", "Time"),
        ("callsign", "Callsign"),
        ("flight_display", "Flight"),
        ("aircraft_type", "A/C"),
        ("registration", "Reg"),
        ("route_display", "Route"),
        ("altitude_ft", "Alt"),
        ("ground_speed_kt", "GS"),
        ("squawk", "SQK"),
        ("gate", "Gate"),
        ("status_display", "Status"),
        ("delay_label", "Delay"),
        ("source", "Src"),
    ),
    row_height=32,
    font_scale=0.92,
    status_vocabulary="code",
    color_intensity="low",
    show_codeshares=False,
    monospace_everywhere=True,
)


STYLES: tuple[FidsStyle, ...] = (CLASSIC, PAX, VATSIM, NERD)
DEFAULT_STYLE: FidsStyle = CLASSIC


def style_for(key: str | None) -> FidsStyle:
    """Look up a style by key. Falls back to the default on unknown keys."""
    if not key:
        return DEFAULT_STYLE
    target = str(key).strip().lower()
    for style in STYLES:
        if style.key == target:
            return style
    return DEFAULT_STYLE


def translate_status(text: str, status_class: str, *, vocabulary: str) -> str:
    """Map raw status text to the active style's vocabulary."""
    if not text and not status_class:
        return ""
    raw = (text or status_class or "").strip()
    cls = (status_class or "").strip().lower()
    if vocabulary == "friendly":
        mapping = {
            "boarding": "Boarding now",
            "approaching": "Final approach",
            "departed": "Departed",
            "landed": "Landed",
            "delayed": "Delayed",
            "delayed-warn": "Running late",
            "delayed-bad": "Significantly late",
            "cancelled": "Cancelled",
            "diverted": "Diverted",
            "scheduled": "On time",
            "early": "Ahead of schedule",
            "on-ground": "On the ground",
        }
        return mapping.get(cls, raw.title() or "On time")
    if vocabulary == "phase":
        mapping = {
            "boarding": "TAXI",
            "approaching": "DESCENT",
            "departed": "CLIMB",
            "landed": "ARRIVED",
            "delayed": "DELAY",
            "delayed-warn": "DELAY",
            "delayed-bad": "DELAY",
            "cancelled": "CXLD",
            "diverted": "DIVRT",
            "scheduled": "PLAN",
            "early": "EARLY",
            "on-ground": "GND",
        }
        return mapping.get(cls, raw.upper() or "PLAN")
    if vocabulary == "code":
        mapping = {
            "boarding": "BRD",
            "approaching": "APP",
            "departed": "DEP",
            "landed": "LND",
            "delayed": "DLY",
            "delayed-warn": "DLY",
            "delayed-bad": "DLY",
            "cancelled": "CXL",
            "diverted": "DIV",
            "scheduled": "SCH",
            "early": "ERL",
            "on-ground": "GND",
        }
        return mapping.get(cls, (raw[:3].upper() or "SCH"))
    return raw  # standard vocabulary returns unchanged


__all__ = [
    "FidsStyle",
    "CLASSIC",
    "PAX",
    "VATSIM",
    "NERD",
    "STYLES",
    "DEFAULT_STYLE",
    "style_for",
    "translate_status",
]
