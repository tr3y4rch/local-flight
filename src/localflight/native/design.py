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
UI_FONT_STACK = f'"{UI_FONT_FAMILY}", "Segoe UI", "Helvetica Neue", sans-serif'
BOARD_FONT_STACK = f'"{BOARD_FONT_FAMILY}", Consolas, monospace'


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
    "pax_blue": SkinTokens("#1d8cff", "#65e7ff", "#1d8cff", "#ffbd45", "#ff4d5f", "#65e7ff"),
    "solari_amber": SkinTokens("#ffad2f", "#ffd06c", "#ffad2f", "#ffe15c", "#ff5538", "#ffd06c"),
    "tower_scope": SkinTokens("#38ff75", "#4deaff", "#38ff75", "#ffd84a", "#ff4c4c", "#38ff75"),
    "vatsim_scope": SkinTokens("#74ff5f", "#6bdcff", "#74ff5f", "#ffe066", "#ff5b5b", "#74ff5f"),
    "night_ops": SkinTokens("#4bb8ff", "#49f0c8", "#4bb8ff", "#f4c95d", "#ff5d7a", "#49f0c8"),
    "sunset_terminal": SkinTokens("#ff7a3d", "#ff4fd8", "#ff7a3d", "#ffd166", "#ff3864", "#ff4fd8"),
    "ice_white": SkinTokens("#bde9ff", "#66d9ff", "#bde9ff", "#ffd35a", "#ff5252", "#66d9ff"),
    "technical": SkinTokens("#7ab0d8", "#9cd6f4", "#8ce99a", "#ffd166", "#ff6b6b", "#9cd6f4"),
    "cyan": SkinTokens("#3ddcff", "#b9f8ff", "#00d084", "#ffbd2e", "#ff5d73", "#3ddcff"),
    "crt": SkinTokens("#9aff6b", "#d5ff9b", "#7dff5b", "#ffd166", "#ff6b6b", "#9aff6b"),
    "neon": SkinTokens("#00f5ff", "#ff4dff", "#39ff14", "#ffd60a", "#ff3864", "#00f5ff"),
    "amber": SkinTokens("#ffae2e", "#ffc56b", "#ffae2e", "#ffdf55", "#ff5738", "#ffc56b"),
    "green": SkinTokens("#28f76e", "#55e7ff", "#28f76e", "#ffc94a", "#ff4d4d", "#28f76e"),
    "white": SkinTokens("#d8f1ff", "#8fdcff", "#d8f1ff", "#ffd35a", "#ff5757", "#8fdcff"),
}


def _normalized_theme(theme: str | None) -> str:
    value = (theme or "dark").strip().lower()
    return value if value in THEME_TOKENS else "dark"


def _normalized_skin(skin: str | None) -> str:
    value = (skin or "standard").strip().lower()
    return value if value in SKIN_TOKENS else "standard"


def colors_for(theme: str | None = "dark", skin: str | None = "standard") -> dict[str, str]:
    """Return a Qt-friendly color map matching the browser theme/skin model."""
    theme_tokens = THEME_TOKENS[_normalized_theme(theme)]
    skin_tokens = SKIN_TOKENS[_normalized_skin(skin)]
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
    accent = colors["amber"] if operator else colors["blue"]
    accent_soft = _rgba(accent, 0.18)
    accent_border = _rgba(accent, 0.42)
    subtle_surface = _rgba("#000000" if is_light else "#ffffff", 0.04)
    soft_surface = _rgba("#000000" if is_light else "#ffffff", 0.07)
    strong_surface = _rgba("#000000" if is_light else "#ffffff", 0.10)
    nav_bg = _rgba("#ffffff", 0.92) if is_light else _rgba("#000000", 0.25)
    nav_border = _rgba("#000000", 0.10) if is_light else _rgba("#ffffff", 0.07)
    button_bg = _rgba(accent, 0.14) if is_light else "#12324d"
    button_hover_bg = _rgba(accent, 0.22) if is_light else "#1a4d72"
    button_border = _rgba(accent, 0.40) if is_light else "#2b648d"
    button_text = colors["text"] if is_light else "#ffffff"
    checked_text = colors["text"] if is_light else "#ffffff"
    nav_text = colors["muted"] if is_light else _rgba(colors["text"], 0.68)
    muted_panel_text = colors["dim"] if is_light else colors["muted"]
    danger_text = "#9f1239" if is_light else "#ffc7c7"
    table_header_text = colors["dim"] if is_light else "#9cd6f4"
    return f"""
QWidget {{
  background: {colors["bg"]};
  color: {colors["text"]};
  font-family: {UI_FONT_STACK};
  font-size: 13px;
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
QFrame#WeatherStrip {{
  background: {subtle_surface};
  border: 1px solid {_rgba(accent, 0.22)};
  border-radius: 10px;
}}
QFrame#WeatherStrip[tone="good"] {{
  background: {_rgba(colors["green"], 0.10)};
  border-color: {_rgba(colors["green"], 0.28)};
}}
QFrame#WeatherStrip[tone="caution"] {{
  background: {_rgba(colors["amber"], 0.11)};
  border-color: {_rgba(colors["amber"], 0.30)};
}}
QFrame#WeatherStrip[tone="bad"] {{
  background: {_rgba(colors["red"], 0.11)};
  border-color: {_rgba(colors["red"], 0.34)};
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
  font-weight: 800;
  font-size: 15px;
}}
QLabel#BrandMark {{
  background: {_rgba(accent, 0.16)};
  border: 1px solid {_rgba(accent, 0.26)};
  border-radius: 9px;
  padding: 3px;
}}
QLabel#Version {{
  color: {colors["dim"]};
  font-family: {BOARD_FONT_STACK};
  font-size: 10px;
}}
QLabel#ClockChip {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 8px;
  padding: 4px 8px;
  color: {colors["muted"]};
  font-family: {BOARD_FONT_STACK};
}}
QLabel#ClockChip[connected="true"] {{
  color: {colors["green"]};
  border-color: {colors["green"]};
  background: {_rgba(colors["green"], 0.12)};
}}
QLabel#Title {{
  font-size: 24px;
  font-weight: 900;
  color: {colors["text"]};
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
QPushButton#NavButton {{
  background: {subtle_surface};
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 6px 10px;
  color: {nav_text};
}}
QPushButton#SegmentButton {{
  background: {subtle_surface};
  border: 1px solid {soft_surface};
  border-radius: 7px;
  padding: 6px 10px;
  font-family: {BOARD_FONT_STACK};
  font-size: 11px;
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
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QTableWidget, QTableView, QListWidget, QTabWidget::pane {{
  background: {colors["input_bg"]};
  border: 1px solid {colors["line"]};
  border-radius: 8px;
  color: {colors["text"]};
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
    value = hex_color.lstrip("#")
    if len(value) != 6:
        return f"rgba(74,158,218,{alpha:.2f})"
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
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
