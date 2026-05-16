"""FIDS board style descriptors.

Each ``FidsStyle`` instance tells the FlightBoardModel which columns to show
and tells the delegate / FidsBoardView how to *paint* the rows.  The four
shipped styles are:

- ``classic`` — original Local Flight board: rounded cards with a status
  rail, blue/cyan accent, codeshare pills, generous row heights.
- ``pax``     — passenger-friendly: oversized rounded cards, warm amber +
  cyan accents, friendly status verbs, big gate badge.
- ``vatsim``  — ATC scope feel: flat green-on-charcoal rows with a thin
  grid, callsign-first, monospace tactical labels, square phase chip.
- ``nerd``    — operator dense: every column visible, monospace
  everywhere, tiny rows, dim palette with subtle separators.

Each style also carries layout primitives (font_scale, row_height_base,
font families, palette overrides, chrome / chip kinds) so the board can
scale geometrically with viewport size while keeping a distinct visual
identity per skin.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Column spec: (key, header_label, weight, min_w_px, hide_threshold_px)
# - weight: proportional width when there is leftover space after min widths
# - min_w_px: never go below this until the column is hidden
# - hide_threshold_px: if total viewport width is below this, drop the column
Column = tuple[str, str, float, int, int]


@dataclass(frozen=True)
class FidsStyle:
    key: str
    label: str
    emoji: str
    description: str
    columns: tuple[Column, ...]
    row_height: int = 76                # base row height before viewport scale
    row_height_min: int = 48
    row_height_max: int = 120
    row_gap: int = 8
    header_height: int = 38
    padding: int = 10
    font_scale: float = 1.0
    font_primary: str = "DM Sans"       # primary text font family
    font_mono: str = "Space Mono"       # monospace family for codes / time
    status_vocabulary: str = "standard"  # standard | friendly | code | phase
    color_intensity: str = "normal"      # high | normal | low
    show_codeshares: bool = True
    monospace_everywhere: bool = False
    header_kind: str = "pill"            # pill | tape | scope | mono
    row_chrome: str = "card"             # card | card-big | scope | grid
    status_chip: str = "pill"            # pill | pill-big | square | code
    palette: dict[str, str] = field(default_factory=dict)  # overlay on theme
    extra: dict[str, Any] = field(default_factory=dict)

    def with_palette_over(self, base: dict[str, str]) -> dict[str, str]:
        """Return ``base`` with this skin's palette overlay applied."""
        merged = dict(base or {})
        for key, value in self.palette.items():
            if value:
                merged[key] = value
        return merged

    @property
    def column_keys(self) -> tuple[str, ...]:
        return tuple(col[0] for col in self.columns)

    @property
    def model_columns(self) -> tuple[tuple[str, str], ...]:
        """Columns in the shape FlightBoardModel expects (key, label)."""
        return tuple((col[0], col[1]) for col in self.columns)


# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------

CLASSIC = FidsStyle(
    key="classic",
    label="Classic",
    emoji="\U0001F6EC",  # 🛬
    description="Classic Local Flight board — rounded cards, status rail, blue accent.",
    columns=(
        ("display_time",   "Time",   1.0, 120,   0),
        ("flight_cell",    "Flight", 1.6, 150,   0),
        ("route_display",  "Route",  2.0, 140,   0),
        ("status_display", "Status", 1.2, 130, 520),
        ("gate",           "Gate",   0.7,  82, 460),
        ("aircraft_type",  "A/C",    0.5,  76, 820),
    ),
    row_height=76,
    row_height_min=58,
    row_height_max=104,
    row_gap=8,
    header_height=38,
    padding=10,
    font_scale=1.0,
    status_vocabulary="standard",
    color_intensity="normal",
    show_codeshares=True,
    header_kind="pill",
    row_chrome="card",
    status_chip="pill",
)

PAX = FidsStyle(
    key="pax",
    label="PAX",
    emoji="\U0001F9F3",  # 🧳
    description="Passenger view — oversized rounded cards, friendly status, warm accents.",
    columns=(
        ("display_time",   "Departs / Arrives", 1.0, 150,   0),
        ("flight_cell",    "Flight",            1.6, 170,   0),
        ("route_display",  "Route",             2.2, 180,   0),
        ("status_display", "Status",            1.4, 160,   0),
        ("gate",           "Gate",              0.8, 110, 460),
    ),
    row_height=104,
    row_height_min=82,
    row_height_max=140,
    row_gap=12,
    header_height=46,
    padding=14,
    font_scale=1.18,
    status_vocabulary="friendly",
    color_intensity="high",
    show_codeshares=True,
    header_kind="tape",
    row_chrome="card-big",
    status_chip="pill-big",
    palette={
        # Warm passenger palette — amber/cyan accents on a deep panel
        "blue":  "#7cc8ff",
        "cyan":  "#fbbf24",
        "panel": "#0e1722",
    },
)

VATSIM = FidsStyle(
    key="vatsim",
    label="VATSIM",
    emoji="\U0001F6E9",  # 🛩
    description="ATC scope — flat green-on-charcoal grid, callsign-first, square phase chips.",
    columns=(
        ("display_time",  "Z TIME",  1.0, 100,   0),
        ("callsign",      "CALL",    1.2, 110,   0),
        ("aircraft_type", "A/C",     0.6,  80,   0),
        ("flight_rules",  "R",       0.3,  44,   0),
        ("route_display", "ROUTE",   1.8, 150,   0),
        ("alt_speed",     "ALT/GS",  0.9, 110, 720),
        ("phase",         "PHASE",   0.9, 100,   0),
    ),
    row_height=58,
    row_height_min=44,
    row_height_max=78,
    row_gap=2,
    header_height=32,
    padding=8,
    font_scale=0.96,
    font_primary="Space Mono",
    font_mono="Space Mono",
    status_vocabulary="phase",
    color_intensity="normal",
    show_codeshares=False,
    monospace_everywhere=True,
    header_kind="scope",
    row_chrome="scope",
    status_chip="square",
    palette={
        "blue":  "#3ddc84",   # ATC green
        "cyan":  "#5cffae",
        "panel": "#06120c",
        "panel_2": "#04100a",
    },
)

NERD = FidsStyle(
    key="nerd",
    label="Nerd",
    emoji="\U0001F913",  # 🤓
    description="Operator dense — every column, monospace, tiny rows, low-intensity color.",
    columns=(
        ("display_time",    "TIME",  0.7,  76,   0),
        ("callsign",        "CALL",  0.9,  84,   0),
        ("flight_display",  "FLT",   0.7,  72, 720),
        ("aircraft_type",   "A/C",   0.5,  60,   0),
        ("registration",    "REG",   0.6,  70, 820),
        ("route_display",   "ROUTE", 1.4, 130,   0),
        ("altitude_ft",     "ALT",   0.5,  60,   0),
        ("ground_speed_kt", "GS",    0.4,  54, 640),
        ("squawk",          "SQK",   0.4,  54, 880),
        ("gate",            "GATE",  0.5,  64, 540),
        ("status_display",  "ST",    0.5,  58,   0),
        ("delay_label",     "DLY",   0.4,  54, 640),
        ("source",          "SRC",   0.4,  54, 960),
    ),
    row_height=36,
    row_height_min=28,
    row_height_max=52,
    row_gap=1,
    header_height=26,
    padding=6,
    font_scale=0.86,
    font_primary="Space Mono",
    font_mono="Space Mono",
    status_vocabulary="code",
    color_intensity="low",
    show_codeshares=False,
    monospace_everywhere=True,
    header_kind="mono",
    row_chrome="grid",
    status_chip="code",
    palette={
        "panel":   "#080c12",
        "panel_2": "#05080c",
    },
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
