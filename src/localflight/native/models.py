"""Reusable Qt models for native-first pages."""
from __future__ import annotations

import re
from typing import Any

from localflight.decode.mappings.airlines import format_flight_identifier
from localflight.display.fids import enrich_presentation_fields, tone_for_status
from localflight.native.design import format_value, value_at


class _TableModelFactory:
    columns: tuple[tuple[str, str], ...] = ()

    def __new__(cls, QtCore: Any, rows: list[dict[str, Any]] | None = None):  # noqa: N804 - QtCore follows Qt naming
        columns = cls.columns

        class _Model(QtCore.QAbstractTableModel):
            def __init__(self, initial_rows: list[dict[str, Any]] | None = None) -> None:
                super().__init__()
                self._rows = list(initial_rows or [])

            def rowCount(self, _parent: Any = None) -> int:
                return len(self._rows)

            def columnCount(self, _parent: Any = None) -> int:
                return len(columns)

            def data(self, index: Any, role: int = 0) -> Any:
                if not index.isValid() or role not in (QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole):
                    return None
                row = self._rows[index.row()]
                key, _label = columns[index.column()]
                return format_value(value_at(row, key)) or "-"

            def headerData(self, section: int, orientation: Any, role: int = 0) -> Any:
                if role != QtCore.Qt.DisplayRole:
                    return None
                if orientation == QtCore.Qt.Horizontal and 0 <= section < len(columns):
                    return columns[section][1]
                return section + 1

            def rows(self) -> list[dict[str, Any]]:
                return list(self._rows)

            def set_rows(self, next_rows: list[dict[str, Any]]) -> None:
                self.beginResetModel()
                self._rows = list(next_rows or [])
                self.endResetModel()

        return _Model(rows)


class FlightBoardModel:
    """Model for the native FIDS board.

    The rows keep the full API payload so row-click detail fetches can use the
    original callsign while the visible cells stay passenger-board friendly.
    """

    columns = (
        ("display_time", "Time"),
        ("flight_cell", "Flight"),
        ("route_display", "Route"),
        ("gate", "Gate"),
        ("status_display", "Status"),
        ("aircraft_type", "A/C"),
    )

    def __new__(
        cls,
        QtCore: Any,  # noqa: N803 - QtCore follows Qt naming
        rows: list[dict[str, Any]] | None = None,
        *,
        QtGui: Any | None = None,  # noqa: N803 - QtGui follows Qt naming
        route_label: str = "Route",
        colors: dict[str, str] | None = None,
    ):
        columns = cls.columns

        class _Model(QtCore.QAbstractTableModel):
            def __init__(self, initial_rows: list[dict[str, Any]] | None = None) -> None:
                super().__init__()
                self._rows = list(initial_rows or [])
                self._route_label = route_label
                self._colors = dict(colors or {})

            def rowCount(self, _parent: Any = None) -> int:
                return len(self._rows)

            def columnCount(self, _parent: Any = None) -> int:
                return len(columns)

            def data(self, index: Any, role: int = 0) -> Any:
                if not index.isValid():
                    return None
                row = self._rows[index.row()]
                key, _label = columns[index.column()]
                if role == QtCore.Qt.DisplayRole:
                    return self._display_value(row, key)
                if role == QtCore.Qt.ToolTipRole:
                    return self._tooltip_value(row, key)
                if role == QtCore.Qt.ForegroundRole and QtGui is not None:
                    return QtGui.QBrush(QtGui.QColor(self._foreground(row, key)))
                if role == QtCore.Qt.BackgroundRole and QtGui is not None:
                    color = self._background(row, key)
                    return QtGui.QBrush(color) if color is not None else None
                if role == QtCore.Qt.FontRole and QtGui is not None:
                    return self._font(row, key)
                if role == QtCore.Qt.TextAlignmentRole:
                    if key in {"display_time", "gate", "aircraft_type"}:
                        return QtCore.Qt.AlignCenter
                    return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
                return None

            def headerData(self, section: int, orientation: Any, role: int = 0) -> Any:
                if role != QtCore.Qt.DisplayRole:
                    return None
                if orientation == QtCore.Qt.Horizontal and 0 <= section < len(columns):
                    key, label = columns[section]
                    return self._route_label if key == "route_display" else label
                return section + 1

            def rows(self) -> list[dict[str, Any]]:
                return list(self._rows)

            def row_at(self, row: int) -> dict[str, Any] | None:
                if 0 <= row < len(self._rows):
                    return dict(self._rows[row])
                return None

            def set_route_label(self, label: str) -> None:
                self._route_label = label or "Route"
                if columns:
                    self.headerDataChanged.emit(QtCore.Qt.Horizontal, 0, len(columns) - 1)

            def set_theme(self, next_colors: dict[str, str]) -> None:
                self._colors = dict(next_colors or {})
                if self._rows and columns:
                    top_left = self.index(0, 0)
                    bottom_right = self.index(len(self._rows) - 1, len(columns) - 1)
                    self.dataChanged.emit(top_left, bottom_right)

            def set_rows(self, next_rows: list[dict[str, Any]]) -> None:
                self.beginResetModel()
                self._rows = list(next_rows or [])
                self.endResetModel()

            def _display_value(self, row: dict[str, Any], key: str) -> str:
                row = enrich_presentation_fields(row)
                if key == "flight_cell":
                    values = [
                        row.get("flight_display") or row.get("callsign"),
                        row.get("airline_display"),
                        self._codeshare_text(row),
                    ]
                    return "\n".join(str(value) for value in values if format_value(value)) or "-"
                if key == "status_display":
                    status = format_value(row.get("status_display") or row.get("status")) or "Scheduled"
                    status_cls = self._status_class(row)
                    if status_cls in {"delayed", "delayed-warn", "delayed-bad"} and "delay" not in status.lower():
                        suffix = _delay_suffix(row)
                        status = f"DELAYED {suffix}M".strip()
                    elif status_cls == "early" and "early" not in status.lower():
                        delay = _delay_minutes(row)
                        status = f"EARLY {abs(delay)}M" if isinstance(delay, int) else "EARLY"
                    return status.upper()
                if key == "route_display":
                    route = format_value(row.get("route_primary")) or format_value(row.get("route_display"))
                    code = format_value(row.get("route_caption"))
                    return f"{route}\n{code}" if route and code and code not in route else route or "-"
                if key == "gate":
                    return format_value(row.get("terminal_gate_display") or row.get("gate_display") or row.get("gate")) or "-"
                return format_value(value_at(row, key)) or "-"

            def _tooltip_value(self, row: dict[str, Any], key: str) -> str:
                if key == "flight_cell":
                    values = [
                        row.get("flight_display") or row.get("callsign"),
                        row.get("airline_display"),
                        self._codeshare_text(row),
                        row.get("callsign"),
                    ]
                    return "\n".join(str(value) for value in values if format_value(value)) or "-"
                route = row.get("route_display")
                status = row.get("status_display")
                callsign = row.get("callsign")
                return " | ".join(str(value) for value in (callsign, route, status) if format_value(value)) or "-"

            def _foreground(self, row: dict[str, Any], key: str) -> str:
                row = enrich_presentation_fields(row)
                cls = self._status_class(row)
                dim = self._color("dim", "#7b8494")
                muted = self._color("muted", "#9aa3b2")
                text = self._color("text", "#e6edf5")
                if cls in {"cancelled", "departed", "landed", "arrived"}:
                    return dim
                if cls in {"delayed", "delayed-warn", "delayed-bad", "early"} and key in {"display_time", "status_display", "flight_cell"}:
                    return self._status_color(row)
                if key == "status_display":
                    return self._status_color(row)
                if key in {"gate", "aircraft_type"}:
                    return muted
                if key == "route_display":
                    return text
                return text

            def _background(self, row: dict[str, Any], key: str) -> Any:
                if QtGui is None:
                    return None
                row = enrich_presentation_fields(row)
                cls = self._status_class(row)
                if cls in {"delayed", "delayed-warn", "delayed-bad", "early"}:
                    color = QtGui.QColor(self._status_color(row))
                    color.setAlpha(42 if key != "display_time" else 78)
                    return color
                if key == "display_time" and cls in {"boarding", "approaching", "diverted", "cancelled"}:
                    color = QtGui.QColor(self._status_color(row))
                    color.setAlpha(62)
                    return color
                if row.get("_fresh"):
                    color = QtGui.QColor(self._color("blue", "#4a9eda"))
                    color.setAlpha(22)
                    return color
                if cls in {"cancelled", "departed", "landed", "arrived"}:
                    color = QtGui.QColor(self._color("panel_2", "#151923"))
                    color.setAlpha(96)
                    return color
                return None

            def _font(self, row: dict[str, Any], key: str) -> Any:
                font = QtGui.QFont("Space Mono" if key in {"display_time", "flight_cell", "gate", "aircraft_type"} else "")
                if key == "display_time":
                    font.setPointSize(13)
                    font.setBold(True)
                elif key == "flight_cell":
                    font.setPointSize(11)
                    font.setBold(True)
                elif key == "status_display":
                    font.setPointSize(9)
                    font.setBold(True)
                else:
                    font.setPointSize(10)
                if self._status_class(row) == "cancelled":
                    font.setStrikeOut(True)
                return font

            def _status_class(self, row: dict[str, Any]) -> str:
                row = enrich_presentation_fields(row)
                raw = str(row.get("status_class") or row.get("status_display") or row.get("status") or "scheduled")
                normalized = raw.strip().lower().replace(" ", "-").replace("_", "-")
                if "board" in normalized:
                    return "boarding"
                if "approach" in normalized:
                    return "approaching"
                if "cancel" in normalized:
                    return "cancelled"
                if "divert" in normalized:
                    return "diverted"
                if normalized in {"delayed-warn", "delayed-bad", "early"}:
                    return normalized
                delay_visual = _delay_visual_class(row)
                if delay_visual == "early" or "early" in normalized:
                    return "early"
                if delay_visual in {"warn", "bad"}:
                    return f"delayed-{delay_visual}"
                if "delay" in normalized or "late" in normalized:
                    return "delayed-warn"
                if "depart" in normalized:
                    return "departed"
                if "land" in normalized or "arriv" in normalized:
                    return "landed"
                if "ground" in normalized:
                    return "on-ground"
                return normalized or "scheduled"

            def _status_color(self, row: dict[str, Any]) -> str:
                row = enrich_presentation_fields(row)
                tone = str(row.get("tone") or tone_for_status(str(row.get("status_kind") or ""), str(row.get("delay_kind") or "none")))
                if tone == "green":
                    return self._color("green", "#22c55e")
                if tone == "amber":
                    return self._color("amber", "#f59e0b")
                if tone == "red":
                    return self._color("red", "#ef4444")
                if tone == "orange":
                    return "#f97316"
                if tone == "dim":
                    return self._color("dim", "#7b8494")
                cls = self._status_class(row)
                if cls in {"boarding", "landed", "early"}:
                    return self._color("green", "#22c55e")
                if cls == "approaching":
                    return self._color("amber", "#f59e0b")
                if cls == "delayed-warn":
                    return self._color("amber", "#f59e0b")
                if cls in {"delayed", "delayed-bad", "cancelled"}:
                    return self._color("red", "#ef4444")
                if cls in {"diverted"}:
                    return "#f97316"
                if cls in {"departed", "on-ground"}:
                    return self._color("dim", "#7b8494")
                return self._color("blue", "#4a9eda")

            def _status_dot(self, row: dict[str, Any]) -> str:
                cls = self._status_class(row)
                if cls in {"boarding", "approaching"}:
                    return chr(9679)
                if cls in {"delayed", "delayed-warn", "delayed-bad", "early", "diverted", "cancelled"}:
                    return chr(9650)
                if cls in {"departed", "landed"}:
                    return chr(9675)
                return chr(8226)

            def _color(self, key: str, fallback: str) -> str:
                return str(self._colors.get(key) or fallback)

            def _codeshare_text(self, row: dict[str, Any]) -> str:
                frames = row.get("_codeshare_frames")
                if isinstance(frames, list) and frames:
                    idx = int(row.get("_codeshare_frame_index") or 0) % len(frames)
                    return str(frames[idx])
                return " / ".join(_codeshare_frames(row))

        return _Model(rows)


class HistoryModel(_TableModelFactory):
    columns = (
        ("sched_time", "Scheduled"),
        ("direction", "Dir"),
        ("flight_number", "Flight"),
        ("callsign", "Callsign"),
        ("origin_iata", "From"),
        ("dest_iata", "To"),
        ("status", "Status"),
        ("gate", "Gate"),
        ("aircraft_type", "A/C"),
        ("source", "Source"),
    )


class RequestLogModel(_TableModelFactory):
    columns = (
        ("ts", "Time"),
        ("method", "Method"),
        ("path", "Path"),
        ("status_code", "Status"),
        ("latency_ms", "Latency"),
        ("client_type", "Type"),
        ("platform", "Platform"),
        ("client_id", "Client"),
    )


def _codeshare_frames(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    raw = row.get("codeshares")
    if isinstance(raw, (list, tuple, set)):
        values.extend(str(item or "") for item in raw)
    for key in ("codeshare_display", "codeshare", "sold_as"):
        text = str(row.get(key) or "").strip()
        if text:
            values.extend(_split_codeshare_text(text))

    main = _compact_flight_token(str(row.get("flight_display") or row.get("callsign") or ""))
    frames: list[str] = []
    seen: set[str] = set()
    for value in values:
        formatted = format_flight_identifier(flight_number=str(value or "").strip().upper())
        compact = _compact_flight_token(formatted)
        if not formatted or compact == main or compact in seen:
            continue
        seen.add(compact)
        frames.append(formatted)
    return frames


def _split_codeshare_text(value: str) -> list[str]:
    text = value.strip()
    text = re.sub(r"(?i)\balso\b", " ", text)
    text = re.sub(r"(?i)\bsold\s+as\b", " ", text)
    text = re.sub(r"\+\s*\d+\b", " ", text)
    return [part.strip() for part in re.split(r"[/,;|]+", text) if part.strip()]


def _split_display_delay(value: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)\s*\(([+-]?\d+)\)\s*$", str(value or "").strip())
    if not match:
        return str(value or "").strip(), ""
    return match.group(1).strip(), match.group(2).strip()


def _delay_minutes(row: dict[str, Any]) -> int | None:
    for key in ("_delay_minutes", "delay_minutes"):
        raw = row.get(key)
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    _base, suffix = _split_display_delay(str(row.get("display_time") or ""))
    if not suffix:
        return None
    try:
        return int(suffix)
    except ValueError:
        return None


def _delay_suffix(row: dict[str, Any]) -> str:
    raw_suffix = str(row.get("_delay_suffix") or "").strip()
    if raw_suffix:
        return raw_suffix
    delay = _delay_minutes(row)
    if delay is None or abs(delay) < 5:
        return ""
    sign = "+" if delay > 0 else "-"
    return f"{sign}{abs(delay)}"


def _delay_visual_class(row: dict[str, Any]) -> str:
    kind = str(row.get("delay_kind") or "").strip().lower()
    if kind in {"early", "warn", "bad"}:
        return kind
    raw = str(row.get("delay_class") or "").strip().lower()
    if raw in {"early", "warn", "bad"}:
        return raw
    delay = _delay_minutes(row)
    if delay is None or abs(delay) < 5:
        return ""
    if delay < 0:
        return "early"
    if delay > 15:
        return "bad"
    return "warn"


def _compact_flight_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
