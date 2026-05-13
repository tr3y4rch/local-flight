"""Shared Qt design helpers for the native Local Flight shells.

The native UI intentionally does not use a webview. These helpers provide a
small Qt equivalent of the browser UI vocabulary: top bars, cards, chips,
tables, and airport-board colors.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

UI_FONT_FAMILY = "DM Sans"
BOARD_FONT_FAMILY = "Space Mono"
BRAND_FONT_FAMILY = "Audiowide"
UI_FONT_STACK = f'"{UI_FONT_FAMILY}", "Segoe UI", "Helvetica Neue", sans-serif'
BOARD_FONT_STACK = f'"{BOARD_FONT_FAMILY}", Consolas, monospace'
BRAND_FONT_STACK = f'"{BRAND_FONT_FAMILY}", {UI_FONT_STACK}'


@dataclass(frozen=True)
class ThemeTokens:
    bg: str
    panel: str
    panel_2: str
    card: str
    line: str
    line_soft: str
    input_bg: str
    text: str
    muted: str
    dim: str


@dataclass(frozen=True)
class SkinTokens:
    accent: str
    accent_2: str
    good: str
    warn: str
    bad: str
    sweep: str


@dataclass(frozen=True)
class SkinSurfaceTokens:
    bg: str
    panel: str
    text: str
    muted: str


THEME_TOKENS: dict[str, ThemeTokens] = {
    "dark": ThemeTokens(
        bg="#080c12",
        panel="#0d1520",
        panel_2="#0a121c",
        card="#101a26",
        line="#1e3a5a",
        line_soft="#17324d",
        input_bg="#0b141f",
        text="#e8f0fe",
        muted="#79a7c8",
        dim="#4a7aaa",
    ),
    "light": ThemeTokens(
        bg="#f4f7fb",
        panel="#ffffff",
        panel_2="#eaf0f7",
        card="#ffffff",
        line="#cbd8e6",
        line_soft="#dce6f1",
        input_bg="#ffffff",
        text="#101923",
        muted="#46657d",
        dim="#6d879e",
    ),
}


SKIN_TOKENS: dict[str, SkinTokens] = {
    "standard": SkinTokens("#4a9eda", "#7ce7ff", "#00c040", "#f0b429", "#ff6060", "#4a9eda"),
    "pax_blue": SkinTokens("#1d8cff", "#65e7ff", "#65e7ff", "#ffbd45", "#ff4d5f", "#65e7ff"),
    "solari_amber": SkinTokens("#ffad2f", "#ffd06c", "#ffd06c", "#ffe15c", "#ff5538", "#ffd06c"),
    "tower_scope": SkinTokens("#38ff75", "#4deaff", "#38ff75", "#ffd84a", "#ff4c4c", "#38ff75"),
    "vatsim_scope": SkinTokens("#74ff5f", "#6bdcff", "#74ff5f", "#ffe066", "#ff5b5b", "#74ff5f"),
    "night_ops": SkinTokens("#4bb8ff", "#49f0c8", "#4bb8ff", "#f4c95d", "#ff5d7a", "#49f0c8"),
    "sunset_terminal": SkinTokens("#ff7a3d", "#ff4fd8", "#ffb05f", "#ffd166", "#ff3864", "#ff4fd8"),
    "ice_white": SkinTokens("#1688bf", "#66d9ff", "#087f5b", "#a56500", "#b4233c", "#1688bf"),
    "technical": SkinTokens("#4a9eda", "#7ce7ff", "#3a9a6a", "#d4a020", "#c04040", "#7ce7ff"),
    "cyan": SkinTokens("#00ccff", "#00ffcc", "#00ffcc", "#ffcc00", "#ff4060", "#00ccff"),
    "crt": SkinTokens("#ffcc44", "#ffaa00", "#ffaa00", "#ffdd00", "#ff4020", "#ffcc44"),
    "neon": SkinTokens("#00ff50", "#aaff00", "#00ff50", "#aaff00", "#ff4040", "#00ff50"),
    "amber": SkinTokens("#ffae2e", "#ffc56b", "#ffae2e", "#ffdf55", "#ff5738", "#ffc56b"),
    "green": SkinTokens("#28f76e", "#55e7ff", "#28f76e", "#ffc94a", "#ff4d4d", "#28f76e"),
    "white": SkinTokens("#d8f1ff", "#8fdcff", "#d8f1ff", "#ffd35a", "#ff5757", "#8fdcff"),
}

SKIN_SURFACE_TOKENS: dict[str, SkinSurfaceTokens] = {
    "pax_blue": SkinSurfaceTokens("#071829", "#0b2137", "#d9f4ff", "#6aaed8"),
    "solari_amber": SkinSurfaceTokens("#201000", "#2a1703", "#fff0bf", "#c98d30"),
    "tower_scope": SkinSurfaceTokens("#06170d", "#0b2012", "#dfffe8", "#58a878"),
    "vatsim_scope": SkinSurfaceTokens("#07130b", "#0c1d12", "#e4ffe0", "#68a86b"),
    "night_ops": SkinSurfaceTokens("#07111f", "#0c1b2d", "#d8f3ff", "#619cc4"),
    "sunset_terminal": SkinSurfaceTokens("#20100b", "#2b1710", "#ffe8d8", "#c9825f"),
    "ice_white": SkinSurfaceTokens("#f5fbff", "#ffffff", "#0c2433", "#486d82"),
    "technical": SkinSurfaceTokens("#0a0e14", "#111820", "#c8d8e8", "#5a7a9a"),
    "cyan": SkinSurfaceTokens("#00080f", "#001220", "#00ccff", "#006688"),
    "crt": SkinSurfaceTokens("#0a0600", "#150c00", "#ffaa00", "#7a5000"),
    "neon": SkinSurfaceTokens("#000d00", "#001800", "#00ff50", "#007a28"),
}


def _normalized_theme(theme: str | None) -> str:
    value = (theme or "dark").strip().lower()
    return value if value in THEME_TOKENS else "dark"


def _normalized_skin(skin: str | None) -> str:
    value = (skin or "standard").strip().lower()
    return value if value in SKIN_TOKENS else "standard"


def _hex_to_rgb(hex_color: str, fallback: tuple[int, int, int] = (74, 158, 218)) -> tuple[int, int, int]:
    value = str(hex_color or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return fallback
    try:
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except ValueError:
        return fallback


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(channel)))) for channel in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _mix_hex(base: str, overlay: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    base_rgb = _hex_to_rgb(base)
    overlay_rgb = _hex_to_rgb(overlay)
    return _rgb_to_hex(
        tuple(base_channel * (1.0 - amount) + overlay_channel * amount for base_channel, overlay_channel in zip(base_rgb, overlay_rgb))
    )


def _relative_luminance(hex_color: str) -> float:
    def _linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    r, g, b = (_linear(channel) for channel in _hex_to_rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(foreground: str, background: str) -> float:
    light = max(_relative_luminance(foreground), _relative_luminance(background))
    dark = min(_relative_luminance(foreground), _relative_luminance(background))
    return (light + 0.05) / (dark + 0.05)


def contrast_ratio(foreground: str, background: str) -> float:
    """Return the WCAG contrast ratio for native palette validation."""
    return _contrast_ratio(foreground, background)


def _ensure_contrast(foreground: str, background: str, *, minimum: float = 4.5) -> str:
    if _contrast_ratio(foreground, background) >= minimum:
        return foreground
    dark = "#101923"
    light = "#f8fbff"
    return dark if _contrast_ratio(dark, background) >= _contrast_ratio(light, background) else light


def _skin_aware_theme_tokens(theme: str, skin: str, theme_tokens: ThemeTokens, skin_tokens: SkinTokens) -> ThemeTokens:
    if skin == "standard":
        return theme_tokens

    surface = SKIN_SURFACE_TOKENS.get(skin)
    if theme == "dark" and surface is not None and skin != "ice_white":
        bg = surface.bg
        panel = surface.panel
        panel_2 = _mix_hex(panel, bg, 0.38)
        card = _mix_hex(panel, "#ffffff", 0.02)
        line = _mix_hex(panel, skin_tokens.accent, 0.42)
        line_soft = _mix_hex(panel, skin_tokens.accent, 0.24)
        input_bg = _mix_hex(panel, bg, 0.46)
        text = _ensure_contrast(surface.text, bg)
        muted = _ensure_contrast(surface.muted, panel, minimum=3.0)
        dim = _ensure_contrast(_mix_hex(surface.muted, bg, 0.18), panel, minimum=3.0)
        return ThemeTokens(bg, panel, panel_2, card, line, line_soft, input_bg, text, muted, dim)

    if theme == "light" and skin == "ice_white" and surface is not None:
        bg = surface.bg
        panel = surface.panel
        panel_2 = "#eef6fc"
        card = surface.panel
        line = "#9ac7e2"
        line_soft = "#c8e0ee"
        input_bg = "#ffffff"
        text = _ensure_contrast(surface.text, bg)
        muted = _ensure_contrast(surface.muted, panel, minimum=3.0)
        dim = _ensure_contrast("#647b8a", panel, minimum=3.0)
        return ThemeTokens(bg, panel, panel_2, card, line, line_soft, input_bg, text, muted, dim)

    accent = skin_tokens.accent
    bg = _mix_hex(theme_tokens.bg, accent, 0.06)
    panel = _mix_hex(theme_tokens.panel, accent, 0.045)
    panel_2 = _mix_hex(theme_tokens.panel_2, accent, 0.075)
    card = _mix_hex(theme_tokens.card, accent, 0.035)
    line = _mix_hex(theme_tokens.line, accent, 0.28)
    line_soft = _mix_hex(theme_tokens.line_soft, accent, 0.18)
    input_bg = _mix_hex(theme_tokens.input_bg, accent, 0.025)
    text = _ensure_contrast(theme_tokens.text, bg)
    muted = _ensure_contrast(_mix_hex(theme_tokens.muted, accent, 0.10), panel, minimum=3.0)
    dim = _ensure_contrast(_mix_hex(theme_tokens.dim, accent, 0.10), panel, minimum=3.0)
    return ThemeTokens(bg, panel, panel_2, card, line, line_soft, input_bg, text, muted, dim)


def colors_for(theme: str | None = "dark", skin: str | None = "standard") -> dict[str, str]:
    """Return a Qt-friendly color map matching the browser theme/skin model."""
    normalized_theme = _normalized_theme(theme)
    normalized_skin = _normalized_skin(skin)
    base_theme_tokens = THEME_TOKENS[normalized_theme]
    skin_tokens = SKIN_TOKENS[normalized_skin]
    theme_tokens = _skin_aware_theme_tokens(normalized_theme, normalized_skin, base_theme_tokens, skin_tokens)
    return {
        "bg": theme_tokens.bg,
        "panel": theme_tokens.panel,
        "panel_2": theme_tokens.panel_2,
        "card": theme_tokens.card,
        "line": theme_tokens.line,
        "line_soft": theme_tokens.line_soft,
        "input_bg": theme_tokens.input_bg,
        "text": theme_tokens.text,
        "muted": theme_tokens.muted,
        "dim": theme_tokens.dim,
        "blue": skin_tokens.accent,
        "cyan": skin_tokens.accent_2,
        "green": skin_tokens.good,
        "amber": skin_tokens.warn,
        "red": skin_tokens.bad,
        "sweep": skin_tokens.sweep,
    }


COLORS = colors_for()

DOC_PAGES = {
    "readme": {
        "title": "Project README",
        "filename": "README.md",
        "summary": "Friendly overview, quick path chooser, previews, and links to deeper docs.",
    },
    "install": {
        "title": "Install Guide",
        "filename": "install.md",
        "summary": "Platform install steps for Windows, macOS, Raspberry Pi, source checkout, and mobile testing.",
    },
    "display-modes": {
        "title": "Display Modes",
        "filename": "display-modes.md",
        "summary": "How to choose between native desktop, LAN browser UI, Pi display modes, mobile, and Matrix.",
    },
    "privacy": {
        "title": "Privacy & Diagnostics",
        "filename": "PRIVACY.md",
        "summary": "What stays local, what reporting can send, and how diagnostics modes work.",
    },
    "changelog": {
        "title": "Release Notes",
        "filename": "CHANGELOG.md",
        "summary": "Version history and recent release changes.",
    },
    "third-party": {
        "title": "Third-Party Notices",
        "filename": "THIRD_PARTY_NOTICES.md",
        "summary": "Bundled font licenses and source attribution for local app assets.",
    },
}

NAV_GLYPHS = {
    "display": chr(9635),
    "fids": chr(9776),
    "radar": chr(9678),
    "matrix": chr(9638),
    "settings": chr(9881),
    "admin": chr(9874),
    "history": chr(9716),
    "logs": chr(8801),
    "feedback": chr(9888),
    "setup": chr(9881),
}


def native_stylesheet(
    *,
    theme: str | None = "dark",
    skin: str | None = "standard",
    operator: bool = False,
) -> str:
    normalized_theme = _normalized_theme(theme)
    is_light = normalized_theme == "light"
    colors = colors_for(normalized_theme, skin)
    control_colors = colors_for(normalized_theme, "standard")
    accent = colors["amber"] if operator else colors["blue"]
    accent_soft = _rgba(accent, 0.18)
    accent_border = _rgba(accent, 0.42)
    subtle_surface = _rgba("#000000" if is_light else "#ffffff", 0.04)
    soft_surface = _rgba("#000000" if is_light else "#ffffff", 0.07)
    strong_surface = _rgba("#000000" if is_light else "#ffffff", 0.10)
    control_subtle_surface = _rgba("#000000" if is_light else "#ffffff", 0.04)
    control_soft_surface = _rgba("#000000" if is_light else "#ffffff", 0.07)
    nav_bg = _rgba(control_colors["panel"], 0.94) if is_light else _rgba(control_colors["bg"], 0.92)
    nav_border = _rgba("#000000", 0.10) if is_light else _rgba("#ffffff", 0.07)
    button_bg = _mix_hex(colors["panel"], accent, 0.17 if is_light else 0.22)
    button_hover_bg = _mix_hex(colors["panel"], accent, 0.26 if is_light else 0.32)
    button_border = _mix_hex(colors["line"], accent, 0.48)
    button_text = _ensure_contrast(colors["text"], button_bg)
    checked_text = colors["text"]
    nav_text = control_colors["muted"] if is_light else _rgba(control_colors["text"], 0.68)
    muted_panel_text = colors["dim"] if is_light else colors["muted"]
    danger_text = "#9f1239" if is_light else "#ffc7c7"
    table_header_text = _ensure_contrast(colors["dim"], colors["panel_2"], minimum=3.0)
    return f"""
QWidget {{
  background: {colors["bg"]};
  color: {colors["text"]};
  font-family: {UI_FONT_STACK};
  font-size: 13px;
}}
QLabel {{
  background: transparent;
}}
QMainWindow {{
  background: {colors["bg"]};
}}
QFrame#TopNav {{
  background: {nav_bg};
  border-bottom: 1px solid {nav_border};
}}
QFrame#AppFooter {{
  background: {nav_bg};
  border-top: 1px solid {nav_border};
}}
QScrollArea#NavScroll {{
  background: transparent;
  border: none;
}}
QFrame#Page, QScrollArea#Page {{
  background: {colors["bg"]};
  border: none;
}}
QFrame#Card, QFrame#Panel {{
  background: {colors["panel"]};
  border: 1px solid {colors["line"]};
  border-radius: 14px;
}}
QFrame#SetupPanel {{
  background: {colors["panel"]};
  border: 1px solid {colors["line"]};
  border-radius: 18px;
}}
QFrame#SetupOptionCard {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 14px;
}}
QFrame#SetupOptionCard[selected="true"] {{
  background: {_rgba(accent, 0.16)};
  border-color: {accent};
}}
QFrame#SetupSummaryCard {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 13px;
}}
QFrame#SetupSummaryCard[tone="good"] {{
  background: {_rgba(colors["green"], 0.08)};
  border-color: {_rgba(colors["green"], 0.30)};
}}
QFrame#SetupSummaryCard[tone="warn"] {{
  background: {_rgba(colors["amber"], 0.08)};
  border-color: {_rgba(colors["amber"], 0.30)};
}}
QFrame#WeatherStrip {{
  background: {subtle_surface};
  border: 1px solid {_rgba(accent, 0.22)};
  border-radius: 10px;
}}
QFrame#WeatherChip {{
  background: {_rgba(accent, 0.08)};
  border: 1px solid {_rgba(accent, 0.24)};
  border-radius: 12px;
}}
QFrame#WeatherHero {{
  background: {_rgba(colors["green"], 0.08)};
  border: 1px solid {_rgba(colors["green"], 0.24)};
  border-radius: 14px;
}}
QFrame#WeatherStrip[tone="good"] {{
  background: {_rgba(colors["green"], 0.10)};
  border-color: {_rgba(colors["green"], 0.28)};
}}
QFrame#WeatherChip[tone="good"] {{
  background: {_rgba(colors["green"], 0.08)};
  border-color: {_rgba(colors["green"], 0.26)};
}}
QFrame#WeatherHero[tone="good"] {{
  background: {_rgba(colors["green"], 0.10)};
  border-color: {_rgba(colors["green"], 0.30)};
}}
QFrame#WeatherStrip[tone="caution"] {{
  background: {_rgba(colors["amber"], 0.11)};
  border-color: {_rgba(colors["amber"], 0.30)};
}}
QFrame#WeatherChip[tone="caution"] {{
  background: {_rgba(colors["amber"], 0.09)};
  border-color: {_rgba(colors["amber"], 0.30)};
}}
QFrame#WeatherHero[tone="caution"] {{
  background: {_rgba(colors["amber"], 0.10)};
  border-color: {_rgba(colors["amber"], 0.32)};
}}
QFrame#WeatherStrip[tone="bad"] {{
  background: {_rgba(colors["red"], 0.11)};
  border-color: {_rgba(colors["red"], 0.34)};
}}
QFrame#WeatherChip[tone="bad"] {{
  background: {_rgba(colors["red"], 0.09)};
  border-color: {_rgba(colors["red"], 0.34)};
}}
QFrame#WeatherHero[tone="bad"] {{
  background: {_rgba(colors["red"], 0.10)};
  border-color: {_rgba(colors["red"], 0.36)};
}}
QFrame#FidsHeader {{
  background: {subtle_surface};
  border: 1px solid {_rgba(accent, 0.18)};
  border-radius: 14px;
}}
QFrame#AirportHero {{
  background: {_rgba(accent, 0.10)};
  border: 1px solid {_rgba(accent, 0.28)};
  border-radius: 14px;
}}
QFrame#FidsHeaderActions {{
  background: transparent;
  border: none;
}}
QLabel#FidsAirportCode {{
  color: {colors["text"]};
  font-size: 18px;
  font-weight: 900;
}}
QLabel#FidsTitle {{
  color: {colors["muted"]};
  font-size: 11px;
  font-weight: 800;
}}
QFrame#ClockDivider {{
  background: {_rgba(colors["panel_2"], 0.86)};
  border: 1px solid {colors["line"]};
  border-radius: 12px;
}}
QFrame#InfoBanner {{
  background: {_rgba(accent, 0.10)};
  border: 1px solid {_rgba(accent, 0.28)};
  border-radius: 10px;
}}
QFrame#ErrorBanner {{
  background: {_rgba(colors["red"], 0.10)};
  border: 1px solid {_rgba(colors["red"], 0.35)};
  border-radius: 10px;
}}
QFrame#Drawer {{
  background: {colors["panel_2"]};
  border-left: 1px solid {colors["line"]};
}}
QFrame#PreviewCard {{
  background: {subtle_surface};
  border: 1px solid {_rgba(accent, 0.18)};
  border-radius: 12px;
}}
QFrame#Pill {{
  background: {accent_soft};
  border: 1px solid {accent_border};
  border-radius: 8px;
}}
QFrame#StatusPill {{
  background: {accent_soft};
  border: 1px solid {accent_border};
  border-radius: 8px;
}}
QGroupBox {{
  background: {colors["panel"]};
  border: 1px solid {colors["line"]};
  border-radius: 12px;
  margin-top: 10px;
  padding: 10px;
  font-family: {BOARD_FONT_STACK};
  font-size: 11px;
  font-weight: 800;
  color: {colors["text"]};
}}
QGroupBox::title {{
  subcontrol-origin: margin;
  subcontrol-position: top left;
  padding: 0 8px;
  left: 10px;
  color: {colors["muted"]};
}}
QFrame#BudgetBar {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 7px;
}}
QFrame#NativeSplash {{
  background: {colors["bg"]};
  border: 1px solid {colors["line"]};
  border-radius: 18px;
}}
QDialog#NativeModal {{
  background: {colors["panel"]};
  border: 1px solid {colors["line"]};
  border-radius: 16px;
}}
QLabel#Brand {{
  color: {colors["text"]};
  font-family: {BRAND_FONT_STACK};
  font-weight: 400;
  font-size: 15px;
  letter-spacing: 1px;
}}
QLabel#BrandTitle {{
  color: {colors["text"]};
  font-family: {BRAND_FONT_STACK};
  font-weight: 400;
  font-size: 26px;
  letter-spacing: 1px;
}}
QLabel#BrandMark {{
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
}}
QFrame#TopNav QLabel#Brand {{
  color: {control_colors["text"]};
}}
QFrame#TopNav QLabel#Version {{
  color: {control_colors["dim"]};
}}
QLabel#Version {{
  color: {colors["dim"]};
  font-family: {BOARD_FONT_STACK};
  font-size: 10px;
}}
QLabel#ClockChip {{
  background: {control_subtle_surface};
  border: 1px solid {control_soft_surface};
  border-radius: 8px;
  padding: 4px 8px;
  color: {control_colors["muted"]};
  font-family: {BOARD_FONT_STACK};
}}
QLabel#ClockChip[connected="true"] {{
  color: {colors["green"]};
  border-color: {colors["green"]};
  background: {_rgba(colors["green"], 0.12)};
}}
QFrame#SyncChip {{
  background: {control_subtle_surface};
  border: 1px solid {control_soft_surface};
  border-radius: 9px;
  min-width: 20px;
  max-width: 26px;
}}
QFrame#SyncChip[connected="true"] {{
  border-color: {_rgba(colors["green"], 0.42)};
  background: {_rgba(colors["green"], 0.08)};
}}
QLabel#SyncDot {{
  color: {colors["amber"]};
  font-size: 14px;
}}
QLabel#SyncDot[connected="true"] {{
  color: {colors["green"]};
}}
QLabel#SyncText {{
  color: {control_colors["muted"]};
  font-family: {BOARD_FONT_STACK};
  font-size: 11px;
}}
QLabel#SyncText[connected="true"] {{
  color: {_ensure_contrast(colors["green"], control_subtle_surface, minimum=3.0)};
}}
QLabel#Title {{
  font-size: 24px;
  font-weight: 900;
  color: {colors["text"]};
}}
QLabel#SetupTitle {{
  font-size: 24px;
  font-weight: 900;
  color: {colors["text"]};
}}
QLabel#SetupMuted {{
  color: {muted_panel_text};
  font-size: 13px;
}}
QLabel#SetupBadge {{
  color: {_ensure_contrast(colors["text"], accent_soft, minimum=3.0)};
  background: {accent_soft};
  border: 1px solid {accent_border};
  border-radius: 12px;
  padding: 5px 10px;
  font-family: {BOARD_FONT_STACK};
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.04em;
}}
QLabel#SetupCardTitle {{
  color: {colors["text"]};
  font-weight: 900;
  font-size: 15px;
}}
QLabel#SetupCardBody {{
  color: {muted_panel_text};
  font-size: 12px;
  line-height: 1.35;
}}
QLabel#SetupStatusChip {{
  color: {muted_panel_text};
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 10px;
  padding: 8px 10px;
}}
QLabel#SetupStatusChip[tone="good"] {{
  color: {_ensure_contrast(colors["green"], colors["panel"], minimum=3.0)};
  background: {_rgba(colors["green"], 0.08)};
  border-color: {_rgba(colors["green"], 0.28)};
}}
QLabel#SetupStatusChip[tone="warn"] {{
  color: {_ensure_contrast(colors["amber"], colors["panel"], minimum=3.0)};
  background: {_rgba(colors["amber"], 0.08)};
  border-color: {_rgba(colors["amber"], 0.30)};
}}
QLabel#SetupStatusChip[tone="bad"] {{
  color: {_ensure_contrast(colors["red"], colors["panel"], minimum=3.0)};
  background: {_rgba(colors["red"], 0.08)};
  border-color: {_rgba(colors["red"], 0.32)};
}}
QLabel#SetupSummaryValue {{
  color: {colors["text"]};
  font-weight: 900;
  font-size: 14px;
}}
QLabel#AirportCode {{
  font-family: {BOARD_FONT_STACK};
  font-size: 34px;
  font-weight: 900;
  letter-spacing: 0.12em;
  color: {colors["text"]};
}}
QLabel#Subtle, QLabel#Muted {{
  color: {muted_panel_text};
}}
QLabel#Dim {{
  color: {colors["dim"]};
}}
QLabel#FooterStatus {{
  color: {colors["muted"]};
  font-family: {BOARD_FONT_STACK};
  font-size: 10px;
}}
QLabel#FooterTagline {{
  color: {colors["dim"]};
  font-size: 11px;
}}
QLabel#Kicker, QLabel#Section {{
  color: {colors["dim"]};
  font-family: {BOARD_FONT_STACK};
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}}
QLabel#Metric {{
  color: {colors["text"]};
  font-size: 24px;
  font-weight: 900;
}}
QLabel#StatusGood {{
  color: {colors["green"]};
}}
QLabel#StatusWarn {{
  color: {colors["amber"]};
}}
QLabel#StatusBad {{
  color: {colors["red"]};
}}
QLabel#LiveDot {{
  color: {colors["green"]};
  font-size: 18px;
}}
QPushButton {{
  background: {button_bg};
  border: 1px solid {button_border};
  border-radius: 8px;
  padding: 8px 12px;
  color: {button_text};
  font-weight: 700;
}}
QPushButton:hover {{
  background: {button_hover_bg};
}}
QPushButton:checked, QPushButton#NavButton:checked, QPushButton#SegmentButton:checked {{
  background: {accent_soft};
  border-color: {accent};
  color: {checked_text};
}}
QPushButton#SetupStepButton {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 9px;
  padding: 7px 10px;
  color: {muted_panel_text};
  font-family: {BOARD_FONT_STACK};
  font-size: 10px;
  font-weight: 900;
}}
QPushButton#SetupStepButton:checked {{
  background: {accent_soft};
  border-color: {accent};
  color: {checked_text};
}}
QPushButton#NavButton {{
  background: {control_subtle_surface};
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 6px 10px;
  color: {nav_text};
}}
QPushButton#NavButton:checked {{
  background: {_rgba(accent, 0.12)};
  border-color: {accent};
  color: {control_colors["text"]};
}}
QPushButton#SegmentButton {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 7px;
  padding: 8px 12px;
  font-family: {BOARD_FONT_STACK};
  font-size: 11px;
}}
QPushButton#FidsActionButton {{
  background: {button_bg};
  border: 1px solid {button_border};
  border-radius: 8px;
  padding: 8px 14px;
  color: {button_text};
  font-family: {BOARD_FONT_STACK};
  font-size: 11px;
  font-weight: 900;
}}
QPushButton#Danger {{
  background: rgba(239,68,68,0.18);
  border-color: rgba(239,68,68,0.45);
  color: {danger_text};
}}
QPushButton#Quiet, QToolButton#Quiet {{
  background: transparent;
  border-color: {strong_surface};
  color: {colors["muted"]};
}}
QPushButton#FooterLink {{
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_rgba(accent, 0.12)}, stop:1 {control_subtle_surface});
  border: 1px solid {_rgba(accent, 0.28)};
  border-radius: 9px;
  color: {_ensure_contrast(colors["muted"], colors["bg"], minimum=3.0)};
  padding: 5px;
  font-size: 11px;
  font-family: {BOARD_FONT_STACK};
  font-weight: 900;
}}
QPushButton#FooterLink:hover {{
  background: {_rgba(accent, 0.18)};
  border-color: {_rgba(accent, 0.48)};
  color: {colors["text"]};
}}
QPushButton#FooterLink:focus {{
  border-color: {accent};
}}
QLineEdit, QSpinBox, QComboBox {{
  background: {control_colors["input_bg"]};
  border: 1px solid {control_colors["line"]};
  border-radius: 8px;
  color: {control_colors["text"]};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
  border-color: {accent};
}}
QPlainTextEdit, QTextEdit, QTableWidget, QTableView, QListWidget, QTabWidget::pane {{
  background: {colors["input_bg"]};
  border: 1px solid {colors["line"]};
  border-radius: 8px;
  color: {colors["text"]};
}}
QComboBox QAbstractItemView {{
  background: {control_colors["panel"]};
  color: {control_colors["text"]};
  selection-background-color: {accent_soft};
  selection-color: {control_colors["text"]};
  border: 1px solid {control_colors["line"]};
}}
QMenu {{
  background: {control_colors["panel"]};
  color: {control_colors["text"]};
  border: 1px solid {control_colors["line"]};
}}
QMenu::item {{
  background: transparent;
  padding: 7px 20px;
}}
QMenu::item:selected {{
  background: {accent_soft};
  color: {control_colors["text"]};
}}
QToolTip {{
  background: {control_colors["panel"]};
  color: {control_colors["text"]};
  border: 1px solid {control_colors["line"]};
}}
QPlainTextEdit, QTextEdit {{
  font-family: {BOARD_FONT_STACK};
}}
QHeaderView::section {{
  background: {colors["panel_2"]};
  color: {table_header_text};
  border: none;
  padding: 8px;
  font-family: {BOARD_FONT_STACK};
  font-size: 11px;
}}
QTableWidget {{
  alternate-background-color: {colors["panel_2"]};
  gridline-color: {colors["line_soft"]};
  selection-background-color: {accent_soft};
}}
QTableWidget#FidsTable {{
  background: {colors["panel_2"]};
  border: 1px solid {colors["line"]};
  border-radius: 12px;
}}
QTableView#FidsTable {{
  background: {colors["panel_2"]};
  border: 1px solid {colors["line"]};
  border-radius: 12px;
  alternate-background-color: {colors["panel"]};
  gridline-color: {colors["line_soft"]};
  selection-background-color: {accent_soft};
}}
QTableWidget::item {{
  padding: 7px;
}}
QTableView::item {{
  padding: 7px;
}}
QProgressBar {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 7px;
  min-height: 12px;
  color: transparent;
}}
QProgressBar::chunk {{
  background: {accent};
  border-radius: 6px;
}}
QSlider::groove:horizontal {{
  height: 6px;
  background: {soft_surface};
  border-radius: 3px;
}}
QSlider::handle:horizontal {{
  background: {accent};
  width: 16px;
  margin: -5px 0;
  border-radius: 8px;
}}
QTabBar::tab {{
  padding: 8px 12px;
  background: {subtle_surface};
  border-top-left-radius: 7px;
  border-top-right-radius: 7px;
  color: {colors["muted"]};
}}
QTabBar::tab:selected {{
  background: {accent_soft};
  color: {checked_text};
}}
QSplitter::handle {{
  background: {strong_surface};
}}
QScrollBar:vertical, QScrollBar:horizontal {{
  background: {colors["panel_2"]};
  border: none;
  width: 10px;
  height: 10px;
}}
QScrollBar::handle {{
  background: {colors["line"]};
  border-radius: 5px;
}}
"""


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha:.2f})"


def media_roots() -> list[Path]:
    """Return source, installed-package, and PyInstaller resource roots."""
    package_root = Path(__file__).resolve().parents[1]
    roots: list[Path] = [package_root]

    if package_root.parent.name == "src":
        repo_root = package_root.parents[1]
        roots.extend([repo_root, repo_root / "src" / "localflight"])

    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        bundle = Path(bundle_root)
        roots.extend([bundle / "localflight", bundle])

    roots.extend([package_root.parent, Path.cwd()])

    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved not in seen:
            seen.add(resolved)
            unique.append(root)
    return unique


def resolve_media_path(*parts: str) -> Path | None:
    """Find bundled SVG/docs/media in source checkout or frozen builds."""
    for root in media_roots():
        candidate = root.joinpath(*parts)
        if candidate.exists():
            return candidate
    return None


FONT_FILES = (
    ("Audiowide-Regular.ttf", BRAND_FONT_FAMILY),
    ("DMSans.ttf", UI_FONT_FAMILY),
    ("SpaceMono-Regular.ttf", BOARD_FONT_FAMILY),
    ("SpaceMono-Bold.ttf", BOARD_FONT_FAMILY),
)

_LOADED_FONT_FAMILIES: list[str] | None = None


def load_app_fonts(QtGui: Any) -> list[str]:
    """Register bundled OFL fonts with Qt before stylesheets request them."""
    global _LOADED_FONT_FAMILIES
    if _LOADED_FONT_FAMILIES is not None:
        return list(_LOADED_FONT_FAMILIES)
    loaded: list[str] = []
    font_db = getattr(QtGui, "QFontDatabase", None)
    if font_db is None:
        return loaded
    for filename, fallback_family in FONT_FILES:
        path = resolve_media_path("ui", "static", "fonts", filename)
        if path is None:
            continue
        try:
            font_id = font_db.addApplicationFont(str(path))
        except Exception:
            continue
        if font_id < 0:
            continue
        try:
            families = [str(family) for family in font_db.applicationFontFamilies(font_id)]
        except Exception:
            families = [fallback_family]
        loaded.extend(families or [fallback_family])
    if loaded:
        _LOADED_FONT_FAMILIES = sorted(set(loaded))
        return list(_LOADED_FONT_FAMILIES)
    return []


def apply_app_font_defaults(QtGui: Any, app: Any, *, point_size: int = 10) -> list[str]:
    """Load bundled fonts and make DM Sans the Qt default family.

    QSS handles normal widgets, but custom delegates and painters sometimes
    create bare ``QFont()`` instances. Setting the QApplication font keeps those
    native-only paths visually aligned with the web kiosk's DM Sans baseline.
    """
    loaded = load_app_fonts(QtGui)
    try:
        font = QtGui.QFont(UI_FONT_FAMILY)
        if point_size > 0:
            font.setPointSize(point_size)
        app.setFont(font)
    except Exception:
        pass
    return loaded


def icon_from_media(QtGui: Any, *parts: str) -> Any:
    path = resolve_media_path(*parts)
    return QtGui.QIcon(str(path)) if path else QtGui.QIcon()


def pixmap_from_media(QtCore: Any, QtGui: Any, *parts: str, width: int = 0, height: int = 0) -> Any:
    path = resolve_media_path(*parts)
    pixmap = QtGui.QPixmap(str(path)) if path else QtGui.QPixmap()
    if not pixmap.isNull() and width and height:
        pixmap = pixmap.scaled(width, height, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    return pixmap


def bundled_doc(slug: str) -> dict[str, str]:
    doc_slug = (slug or "").strip().lower()
    if doc_slug not in DOC_PAGES:
        doc_slug = "readme"
    page = DOC_PAGES[doc_slug]
    filename = page["filename"]
    path = (
        resolve_media_path("ui", "docs", filename)
        or resolve_media_path("docs", filename)
        or resolve_media_path(filename)
    )
    if path is None:
        text = f"{filename} is not bundled with this build."
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "slug": doc_slug,
        "title": page["title"],
        "filename": filename,
        "summary": page["summary"],
        "text": text,
    }


def preview_card(
    QtCore: Any,
    QtGui: Any,
    QtWidgets: Any,
    title: str,
    text: str,
    media_parts: tuple[str, ...],
) -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName("PreviewCard")
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(8)
    image = QtWidgets.QLabel()
    image.setAlignment(QtCore.Qt.AlignCenter)
    pixmap = pixmap_from_media(QtCore, QtGui, *media_parts, width=260, height=120)
    if pixmap.isNull():
        image.setText(title)
        image.setObjectName("Muted")
    else:
        image.setPixmap(pixmap)
    layout.addWidget(image)
    layout.addWidget(label(QtWidgets, title, "Kicker"))
    layout.addWidget(label(QtWidgets, text, "Muted", wrap=True))
    return box


def clear_layout(layout: Any) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            clear_layout(child_layout)


def card(QtWidgets: Any, title: str, value: Any = "", detail: str = "") -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName("Card")
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(14, 12, 14, 12)
    kicker = QtWidgets.QLabel(title)
    kicker.setObjectName("Kicker")
    metric = QtWidgets.QLabel(format_value(value) or "-")
    metric.setObjectName("Metric")
    metric.setWordWrap(True)
    layout.addWidget(kicker)
    layout.addWidget(metric)
    if detail:
        muted = QtWidgets.QLabel(detail)
        muted.setObjectName("Muted")
        muted.setWordWrap(True)
        layout.addWidget(muted)
    return box


def pill(QtWidgets: Any, text: str, *, role: str = "Muted") -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName("Pill")
    layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(8, 4, 8, 4)
    layout.setSpacing(5)
    layout.addWidget(label(QtWidgets, text, role, wrap=True))
    return box


def progress_card(QtWidgets: Any, title: str, used: Any, limit: Any, detail: str = "") -> Any:
    try:
        used_int = int(used or 0)
        limit_int = int(limit or 0)
    except (TypeError, ValueError):
        used_int = 0
        limit_int = 0
    box, layout = panel(QtWidgets, title)
    metric = QtWidgets.QLabel(f"{used_int} / {limit_int}" if limit_int else format_value(used) or "-")
    metric.setObjectName("Metric")
    bar = QtWidgets.QProgressBar()
    bar.setRange(0, max(1, limit_int))
    bar.setValue(max(0, min(used_int, max(1, limit_int))))
    layout.addWidget(metric)
    layout.addWidget(bar)
    if detail:
        layout.addWidget(label(QtWidgets, detail, "Muted", wrap=True))
    return box


def bar_summary(QtWidgets: Any, rows: list[dict[str, Any]], *, label_key: str = "label", value_key: str = "count") -> Any:
    box = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    values = []
    for row in rows:
        try:
            values.append(int(row.get(value_key) or 0))
        except (TypeError, ValueError):
            values.append(0)
    max_value = max(values or [1])
    for row in rows[:8]:
        item = QtWidgets.QWidget()
        item_layout = QtWidgets.QHBoxLayout(item)
        item_layout.setContentsMargins(0, 1, 0, 1)
        name = label(QtWidgets, format_value(row.get(label_key)) or "-", "Muted")
        name.setMinimumWidth(130)
        bar = QtWidgets.QProgressBar()
        try:
            value = int(row.get(value_key) or 0)
        except (TypeError, ValueError):
            value = 0
        bar.setRange(0, max_value)
        bar.setValue(value)
        count = label(QtWidgets, str(value), "Muted")
        item_layout.addWidget(name)
        item_layout.addWidget(bar, 1)
        item_layout.addWidget(count)
        layout.addWidget(item)
    return box


def section_label(QtWidgets: Any, text: str) -> Any:
    label = QtWidgets.QLabel(text)
    label.setObjectName("Section")
    return label


def label(QtWidgets: Any, text: str, role: str = "", *, wrap: bool = False) -> Any:
    widget = QtWidgets.QLabel(text)
    if role:
        widget.setObjectName(role)
    widget.setWordWrap(wrap)
    if wrap:
        widget.setMinimumWidth(0)
        widget.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
    return widget


def panel(QtWidgets: Any, title: str = "") -> tuple[Any, Any]:
    box = QtWidgets.QFrame()
    box.setObjectName("Panel")
    layout = QtWidgets.QVBoxLayout(box)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(10)
    if title:
        layout.addWidget(section_label(QtWidgets, title))
    return box, layout


def scroll_page(QtWidgets: Any) -> tuple[Any, Any]:
    scroll = QtWidgets.QScrollArea()
    scroll.setObjectName("Page")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
    scroll.setMinimumWidth(0)
    body = QtWidgets.QWidget()
    body.setMinimumWidth(0)
    layout = QtWidgets.QVBoxLayout(body)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    scroll.setWidget(body)
    return scroll, layout


def table(QtWidgets: Any, rows: list[dict[str, Any]], columns: list[tuple[str, str]], *, min_height: int = 180) -> Any:
    table_widget = QtWidgets.QTableWidget(len(rows), len(columns))
    table_widget.setHorizontalHeaderLabels([title for _key, title in columns])
    table_widget.verticalHeader().setVisible(False)
    table_widget.setAlternatingRowColors(True)
    table_widget.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
    table_widget.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
    table_widget.horizontalHeader().setStretchLastSection(True)
    for row_idx, row in enumerate(rows):
        for col_idx, (key, _title) in enumerate(columns):
            text = format_value(value_at(row, key))
            item = QtWidgets.QTableWidgetItem(text)
            item.setToolTip(text)
            table_widget.setItem(row_idx, col_idx, item)
    table_widget.resizeColumnsToContents()
    table_widget.setMinimumHeight(min(520, max(min_height, 48 + len(rows) * 30)))
    return table_widget


def set_table_rows(
    table_widget: Any,
    QtWidgets: Any,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    *,
    resize: bool = True,
) -> None:
    was_sorting = bool(table_widget.isSortingEnabled()) if hasattr(table_widget, "isSortingEnabled") else False
    table_widget.setUpdatesEnabled(False)
    table_widget.blockSignals(True)
    if was_sorting:
        table_widget.setSortingEnabled(False)
    try:
        table_widget.setColumnCount(len(columns))
        table_widget.setHorizontalHeaderLabels([title for _key, title in columns])
        table_widget.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            for col_idx, (key, _title) in enumerate(columns):
                text = format_value(value_at(row, key))
                item = QtWidgets.QTableWidgetItem(text)
                item.setToolTip(text)
                table_widget.setItem(row_idx, col_idx, item)
        if resize:
            table_widget.resizeColumnsToContents()
    finally:
        if was_sorting:
            table_widget.setSortingEnabled(True)
        table_widget.blockSignals(False)
        table_widget.setUpdatesEnabled(True)


def list_payload(value: Any, key: str = "rows") -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        rows = value.get(key)
        return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []
    return []


def value_at(row: dict[str, Any], dotted_key: str) -> Any:
    value: Any = row
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(part)
    return value


def format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.1f}"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
