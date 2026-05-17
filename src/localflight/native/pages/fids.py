"""Native FIDS page.

This is the first standalone page extraction from the old monolithic native
prototype.  The browser ``fids.html`` remains the parity checklist for routes,
live refresh, weather, scheduler health, empty states, rotation, and detail
fetch behavior.
"""
from __future__ import annotations

import math
import re
import time
from datetime import datetime, timezone
from html import escape as html_escape
from typing import Any
from zoneinfo import ZoneInfo

from localflight.core.airports import city_country_label
from localflight.native.api_client import LocalApiClient, NativeApiError
from localflight.native.async_tools import AsyncFetchMixin
from localflight.native.design import (
    SECTION_EMOJI,
    WEATHER_EMOJI,
    colors_for,
    format_value,
    label,
    list_payload,
    paint_emoji,
    value_at,
)
from localflight.native.models import FlightBoardModel
from localflight.native.service import NativeApiService
from localflight.native.widgets import DetailDrawer, WeatherStrip
from localflight.decode.mappings.airlines import format_flight_identifier
from localflight.display.fids import enrich_presentation_fields, tone_for_status


class _FidsBoardDelegate:  # pragma: no cover - visual Qt delegate
    """Paint the native FIDS board with real Qt graphics instead of text-only cells."""

    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any, colors_provider: Any):
        class _Delegate(QtWidgets.QStyledItemDelegate):
            def __init__(self) -> None:
                super().__init__()
                self.animation_phase = 0.0

            def set_animation_phase(self, phase: float) -> None:
                try:
                    self.animation_phase = float(phase) % 1.0
                except (TypeError, ValueError):
                    self.animation_phase = 0.0

            def paint(self, painter: Any, option: Any, index: Any) -> None:
                model = index.model()
                row = model.row_at(index.row()) if hasattr(model, "row_at") else {}
                columns = getattr(model, "columns", ())
                key = columns[index.column()][0] if 0 <= index.column() < len(columns) else ""
                colors = colors_provider() or {}
                rect = option.rect.adjusted(0, 0, -1, -1)

                painter.save()
                painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                self._paint_background(painter, rect, option, row, colors, key)
                if key == "status_display":
                    self._paint_status(painter, rect, row, colors)
                elif key == "flight_cell":
                    self._paint_flight(painter, rect, row, colors)
                elif key == "gate":
                    self._paint_gate(painter, rect, row, colors)
                elif key == "display_time":
                    self._paint_time(painter, rect, row, colors)
                elif key == "route_display":
                    self._paint_route(painter, rect, row, colors)
                elif key == "aircraft_type":
                    self._paint_aircraft(painter, rect, row, colors)
                else:
                    self._paint_plain(painter, rect, index.data() or "-", colors)
                painter.restore()

            def sizeHint(self, option: Any, index: Any) -> Any:
                model = index.model()
                row = model.row_at(index.row()) if hasattr(model, "row_at") else {}
                if self._codeshare_frame(row):
                    height = 70
                elif row.get("airline_display"):
                    height = 62
                else:
                    height = 48
                return QtCore.QSize(option.rect.width(), height)

            def _paint_background(self, painter: Any, rect: Any, option: Any, row: dict[str, Any], colors: dict[str, str], key: str) -> None:
                row_index = int(row.get("_source_row_index") or 0)
                base_hex = colors.get("panel_2", "#0b1118")
                panel = QtGui.QColor(base_hex)
                if row_index % 2:
                    panel = _blend_qcolor(QtGui, panel, QtGui.QColor(colors.get("panel", "#111927")), 0.22)
                selected = bool(option.state & QtWidgets.QStyle.State_Selected)
                painter.fillRect(rect, panel)
                if selected:
                    selected_color = QtGui.QColor(colors.get("blue", "#4a9eda"))
                    selected_color.setAlpha(38)
                    painter.fillRect(rect, selected_color)
                alpha = int(row.get("_fresh_alpha") or 0)
                if alpha > 0:
                    shimmer = QtGui.QColor(colors.get("blue", "#4a9eda"))
                    shimmer.setAlpha(max(0, min(42, alpha)))
                    if key == "display_time":
                        painter.fillRect(rect.adjusted(0, 3, -rect.width() + 5, -3), shimmer)
                    painter.fillRect(rect.adjusted(0, 0, 0, -rect.height() + 2), shimmer)
                status_cls = self._status_class(row)
                if key == "display_time" and status_cls not in {"scheduled", ""}:
                    accent = QtGui.QColor(self._status_color(row, colors))
                    accent.setAlpha(185 if status_cls in {"delayed-bad", "cancelled", "diverted"} else 145)
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(accent)
                    painter.drawRoundedRect(rect.adjusted(0, 5, -rect.width() + 5, -5), 2, 2)
                line = QtGui.QColor(colors.get("line_soft", "#202a38"))
                line.setAlpha(125)
                painter.setPen(line)
                painter.drawLine(rect.bottomLeft(), rect.bottomRight())

            def _paint_time(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                time_text = str(row.get("time_primary") or "-")
                delay_text = str(row.get("time_delta_label") or "")
                icon_rect = QtCore.QRectF(rect.left() + 14, rect.center().y() - 8, 16, 16)
                self._draw_icon(painter, icon_rect, "clock", QtGui.QColor(colors.get("muted", "#9aa3b2")))
                painter.setPen(QtGui.QColor(self._text_color(row, colors)))
                font = QtGui.QFont("Space Mono")
                font.setPointSize(17)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(rect.adjusted(36, 0, -8, -12 if delay_text else 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, time_text)
                if delay_text:
                    tag_rect = QtCore.QRect(rect.left() + 36, rect.center().y() + 9, 58, 18)
                    delay_color = QtGui.QColor(self._delay_color(row, colors))
                    bg = QtGui.QColor(delay_color)
                    bg.setAlpha(30)
                    painter.setPen(QtGui.QPen(delay_color, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(tag_rect, 9, 9)
                    tag_font = QtGui.QFont("Space Mono")
                    tag_font.setPointSize(8)
                    tag_font.setBold(True)
                    painter.setFont(tag_font)
                    painter.setPen(delay_color)
                    painter.drawText(tag_rect, QtCore.Qt.AlignCenter, delay_text)

            def _paint_flight(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                left = rect.left() + 12
                top = rect.top() + 7
                text = QtGui.QColor(self._text_color(row, colors))
                muted = QtGui.QColor(colors.get("muted", "#9aa3b2"))
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                icon_rect = QtCore.QRectF(left, top + 1, 17, 17)
                raw_direction = str(row.get("direction") or "").upper()
                route_label = str(getattr(self, "route_label", "") or "")
                direction = "arrival" if raw_direction.startswith("ARR") or route_label.lower().startswith("from") else "departure"
                self._draw_icon(painter, icon_rect, direction, accent)
                flight_font = QtGui.QFont("Space Mono")
                flight_font.setPointSize(12)
                flight_font.setBold(True)
                painter.setFont(flight_font)
                painter.setPen(text)
                painter.drawText(QtCore.QRect(left + 24, top, rect.width() - 34, 20), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, str(row.get("flight_display") or row.get("callsign") or "-"))
                sub_font = QtGui.QFont()
                sub_font.setPointSize(8)
                sub_font.setBold(True)
                painter.setFont(sub_font)
                airline = str(row.get("airline_display") or "")
                codeshare = self._codeshare_frame(row)
                if airline:
                    painter.setPen(muted)
                    painter.drawText(QtCore.QRect(left + 24, top + 21, rect.width() - 34, 14), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, airline.upper())
                if codeshare:
                    code_font = QtGui.QFont("Space Mono")
                    code_font.setPointSize(8)
                    code_font.setBold(True)
                    painter.setFont(code_font)
                    fm = painter.fontMetrics()
                    y = top + 39 if airline else top + 25
                    width = min(rect.width() - 38, max(84, fm.horizontalAdvance(codeshare) + 28))
                    pill = QtCore.QRect(left + 24, y, width, 18)
                    bg = QtGui.QColor(accent)
                    bg.setAlpha(22)
                    painter.setPen(QtGui.QPen(accent, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(pill, 9, 9)
                    self._draw_icon(painter, QtCore.QRectF(pill.left() + 7, pill.top() + 4, 10, 10), "codeshare", accent)
                    painter.setPen(accent)
                    painter.drawText(pill.adjusted(22, 0, -8, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, codeshare)

            def _paint_route(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                primary = str(row.get("route_primary") or row.get("route_display") or "-")
                code = str(row.get("route_caption") or "")
                source_hint = str(row.get("live_hint") or row.get("source_hint") or "")
                left = rect.left() + 12
                top = rect.top() + 8
                route_color = QtGui.QColor(colors.get("muted", "#9aa3b2"))
                self._draw_icon(painter, QtCore.QRectF(left, top + 3, 15, 15), "route", route_color)
                primary_font = QtGui.QFont()
                primary_font.setPointSize(11)
                primary_font.setBold(True)
                painter.setFont(primary_font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e6edf5")))
                painter.drawText(QtCore.QRect(left + 23, top, rect.width() - 34, 23), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, primary)
                sub = " | ".join(part for part in (code, source_hint) if part and part not in primary)
                if sub:
                    sub_font = QtGui.QFont("Space Mono")
                    sub_font.setPointSize(8)
                    painter.setFont(sub_font)
                    painter.setPen(QtGui.QColor(colors.get("muted", "#9aa3b2")))
                    painter.drawText(QtCore.QRect(left + 23, top + 25, rect.width() - 34, 16), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub.upper())

            def _paint_status(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                label_text = str(row.get("status_display") or row.get("status") or "Scheduled").upper()
                color = QtGui.QColor(self._status_color(row, colors))
                bg = QtGui.QColor(color)
                bg.setAlpha(self._status_bg_alpha(row))
                pill = rect.adjusted(8, 13, -8, -13)
                painter.setPen(QtGui.QPen(color, 1.4))
                painter.setBrush(bg)
                painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(color)
                dot_size = 6
                dot_pulse = 1.8 if self._status_should_breathe(row) else 0.0
                painter.drawEllipse(QtCore.QRectF(pill.left() + 10, pill.center().y() - (dot_size + dot_pulse) / 2, dot_size + dot_pulse, dot_size + dot_pulse))
                font = QtGui.QFont("Space Mono")
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(pill.adjusted(24, 0, -8, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, label_text)

            def _paint_gate(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                value = str(row.get("terminal_gate_display") or row.get("gate_display") or "").strip()
                if not value:
                    self._paint_plain(painter, rect, "-", colors, muted=True, align_center=True)
                    return
                pill = rect.adjusted(9, 12, -9, -12)
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                bg = QtGui.QColor(accent)
                bg.setAlpha(20)
                painter.setPen(QtGui.QPen(accent, 1))
                painter.setBrush(bg)
                painter.drawRoundedRect(pill, 8, 8)
                self._draw_icon(painter, QtCore.QRectF(pill.left() + 8, pill.center().y() - 6, 12, 12), "gate", accent)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(10)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e6edf5")))
                painter.drawText(pill.adjusted(24, 0, -8, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, value)

            def _paint_aircraft(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                value = str(row.get("aircraft_type") or "").strip().upper()
                if not value:
                    self._paint_plain(painter, rect, "-", colors, muted=True, align_center=True)
                    return
                muted = QtGui.QColor(colors.get("muted", "#9aa3b2"))
                self._draw_icon(painter, QtCore.QRectF(rect.left() + 11, rect.center().y() - 7, 14, 14), "aircraft", muted)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(9)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e6edf5")))
                painter.drawText(rect.adjusted(30, 0, -8, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, value)

            def _paint_plain(self, painter: Any, rect: Any, text: Any, colors: dict[str, str], *, muted: bool = False, align_center: bool = False) -> None:
                font = QtGui.QFont()
                font.setPointSize(10)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("muted" if muted else "text", "#e6edf5")))
                alignment = QtCore.Qt.AlignCenter if align_center else QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft
                painter.drawText(rect.adjusted(8, 0, -8, 0), alignment, str(text))

            def _status_should_breathe(self, row: dict[str, Any]) -> bool:
                return self._status_class(row) in {"boarding", "approaching", "delayed-warn", "delayed-bad", "cancelled", "diverted"}

            def _status_bg_alpha(self, row: dict[str, Any]) -> int:
                base = 28
                if self._status_class(row) in {"scheduled", "departed", "landed", "on-ground"}:
                    return 18
                if not self._status_should_breathe(row):
                    return 34
                pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                return int(base + pulse * 28)

            def _draw_icon(self, painter: Any, rect: Any, kind: str, color: Any) -> None:
                painter.save()
                emoji = SECTION_EMOJI.get(kind, "")
                if emoji:
                    paint_emoji(QtCore, QtGui, painter, rect, emoji)
                painter.restore()

            def _status_class(self, row: dict[str, Any]) -> str:
                return _row_status_class(row)

            def _status_color(self, row: dict[str, Any], colors: dict[str, str]) -> str:
                row = enrich_presentation_fields(row)
                tone = str(row.get("tone") or tone_for_status(str(row.get("status_kind") or ""), str(row.get("delay_kind") or "none")))
                if tone == "green":
                    return colors.get("green", "#22c55e")
                if tone == "amber":
                    return colors.get("amber", "#f59e0b")
                if tone == "red":
                    return colors.get("red", "#ef4444")
                if tone == "orange":
                    return "#f97316"
                if tone == "dim":
                    return colors.get("dim", "#7b8494")
                status_cls = self._status_class(row)
                if status_cls in {"boarding", "landed", "early"}:
                    return colors.get("green", "#22c55e")
                if status_cls == "approaching":
                    return colors.get("amber", "#f59e0b")
                if status_cls == "delayed-warn":
                    return colors.get("amber", "#f59e0b")
                if status_cls in {"delayed", "delayed-bad", "cancelled"}:
                    return colors.get("red", "#ef4444")
                if status_cls == "diverted":
                    return "#f97316"
                if status_cls == "departed":
                    return colors.get("dim", "#7b8494")
                return colors.get("blue", "#4a9eda")

            def _delay_color(self, row: dict[str, Any], colors: dict[str, str]) -> str:
                delay_cls = _delay_visual_class(row)
                if delay_cls == "early":
                    return colors.get("green", "#22c55e")
                if delay_cls == "warn":
                    return colors.get("amber", "#f59e0b")
                if delay_cls == "bad":
                    return colors.get("red", "#ef4444")
                return self._status_color(row, colors)

            def _text_color(self, row: dict[str, Any], colors: dict[str, str]) -> str:
                if self._status_class(row) in {"cancelled", "departed", "landed"}:
                    return colors.get("dim", "#7b8494")
                return colors.get("text", "#e6edf5")

            def _codeshare_frame(self, row: dict[str, Any]) -> str:
                frames = row.get("_codeshare_frames")
                if isinstance(frames, list) and frames:
                    idx = int(row.get("_codeshare_frame_index") or 0) % len(frames)
                    return str(frames[idx])
                return ""

            def _split_time_delay(self, value: str) -> tuple[str, str]:
                match = re.match(r"^(.+?)\s*\(([+-]?\d+)\)\s*$", value.strip())
                if not match:
                    return value, ""
                return match.group(1).strip(), match.group(2).strip()

        return _Delegate()


class FidsBoardView:  # pragma: no cover - optional Qt runtime
    """Custom passenger-board surface for native FIDS rows.

    Renders the active ``FidsStyle`` skin (classic / pax / vatsim / nerd).
    The board owns its own column layout, row height, header chrome, and
    status chip — driven by ``set_style(style)``.  All sizes scale with
    the viewport via :meth:`_viewport_scale` so the same skin looks
    proportional at 800px wide or 2400px wide.
    """

    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any, colors_provider: Any):
        from localflight.native.pages.fids_styles import DEFAULT_STYLE, FidsStyle

        class _Board(QtWidgets.QAbstractScrollArea):
            rowActivated = QtCore.Signal(int)

            def __init__(self) -> None:
                super().__init__()
                self.setObjectName("FidsBoardView")
                self.setMouseTracking(True)
                self.setFrameShape(QtWidgets.QFrame.NoFrame)
                self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
                self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
                self.rows: list[dict[str, Any]] = []
                self.route_label = "Route"
                self.animation_phase = 0.0
                self.hover_row = -1
                self.colors = colors_provider() or {}
                self.style: FidsStyle = DEFAULT_STYLE
                self.header_h = self.style.header_height
                self.row_gap = self.style.row_gap
                self.row_h = self.style.row_height
                self.padding = self.style.padding

            # ------------------------------------------------------------ skin
            def set_style(self, style: FidsStyle) -> None:
                self.style = style
                self.header_h = style.header_height
                self.row_gap = style.row_gap
                self.row_h = self._scaled_row_height()
                self.padding = style.padding
                self._sync_scroll()
                self.viewport().update()

            @property
            def column_keys(self) -> tuple[str, ...]:
                """Compatibility accessor for tests and older call sites."""
                return self.style.column_keys

            def _viewport_scale(self) -> float:
                """A 1.0-centered scale factor based on viewport width.

                A 1200px-wide board gets scale 1.0; narrower viewports
                shrink and wider ones grow, but the factor is clamped
                tightly so text never looks comical.
                """
                width = max(1, self.viewport().width() or 1200)
                raw = width / 1200.0
                return max(0.78, min(1.35, raw))

            def _scaled_row_height(self) -> int:
                s = self._viewport_scale()
                base = int(self.style.row_height * s)
                return max(self.style.row_height_min, min(self.style.row_height_max, base))

            def _font_pt(self, base: float) -> int:
                pt = base * self.style.font_scale * self._viewport_scale()
                return max(7, int(round(pt)))

            def _primary_font(self, base: float, *, bold: bool = False) -> Any:
                family = self.style.font_mono if self.style.monospace_everywhere else self.style.font_primary
                font = QtGui.QFont(family)
                font.setPointSize(self._font_pt(base))
                font.setBold(bold)
                return font

            def _mono_font(self, base: float, *, bold: bool = False) -> Any:
                font = QtGui.QFont(self.style.font_mono)
                font.setPointSize(self._font_pt(base))
                font.setBold(bold)
                return font

            def _palette(self) -> dict[str, str]:
                return self.style.with_palette_over(colors_provider() or self.colors or {})

            def minimumSizeHint(self) -> Any:
                return QtCore.QSize(460, 300)

            def set_rows(self, rows: list[dict[str, Any]], *, route_label: str = "Route") -> None:
                self.rows = list(rows or [])
                self.route_label = route_label or "Route"
                self._sync_scroll()
                self.viewport().update()

            def set_colors(self, colors: dict[str, str]) -> None:
                self.colors = dict(colors or {})
                self.viewport().update()

            def set_animation_phase(self, phase: float) -> None:
                try:
                    self.animation_phase = float(phase) % 1.0
                except (TypeError, ValueError):
                    self.animation_phase = 0.0
                self.viewport().update()

            def resizeEvent(self, event: Any) -> None:
                super().resizeEvent(event)
                # Row height is viewport-dependent; recompute on resize so
                # the skin keeps its proportions.
                self.row_h = self._scaled_row_height()
                self._sync_scroll()

            def mouseMoveEvent(self, event: Any) -> None:
                row = self._row_at_y(event.position().y())
                if row != self.hover_row:
                    self.hover_row = row
                    self.viewport().update()
                self.setCursor(QtCore.Qt.PointingHandCursor if row >= 0 else QtCore.Qt.ArrowCursor)

            def leaveEvent(self, event: Any) -> None:
                super().leaveEvent(event)
                if self.hover_row != -1:
                    self.hover_row = -1
                    self.viewport().update()
                self.unsetCursor()

            def mousePressEvent(self, event: Any) -> None:
                row = self._row_at_y(event.position().y())
                if row >= 0:
                    self.rowActivated.emit(row)
                    return
                super().mousePressEvent(event)

            def paintEvent(self, _event: Any) -> None:
                painter = QtGui.QPainter(self.viewport())
                painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                rect = self.viewport().rect()
                colors = self._palette()
                self.colors = colors
                painter.fillRect(rect, QtGui.QColor(colors.get("panel_2", "#08111b")))
                if self.style.row_chrome in {"card", "card-big"}:
                    self._draw_board_background(painter, QtCore, QtGui, rect, colors)
                elif self.style.row_chrome == "scope":
                    self._draw_scope_background(painter, QtCore, QtGui, rect, colors)
                # Recompute row height under current viewport — keeps the
                # skin proportional during live resize.
                self.row_h = self._scaled_row_height()
                columns = self._column_rects(rect)
                self._draw_header(painter, QtCore, QtGui, columns, colors)
                scroll = self.verticalScrollBar().value()
                y = self.padding + self.header_h - scroll
                for idx, row in enumerate(self.rows):
                    row_rect = QtCore.QRectF(self.padding, y, max(1, rect.width() - self.padding * 2), self.row_h)
                    if row_rect.bottom() >= 0 and row_rect.top() <= rect.height():
                        self._draw_row(painter, QtCore, QtGui, row_rect, columns, row, idx, colors)
                    y += self.row_h + self.row_gap
                painter.end()

            def _sync_scroll(self) -> None:
                content = self.padding * 2 + self.header_h + len(self.rows) * self.row_h + max(0, len(self.rows) - 1) * self.row_gap
                maximum = max(0, content - self.viewport().height())
                self.verticalScrollBar().setRange(0, maximum)
                self.verticalScrollBar().setPageStep(max(1, self.viewport().height()))

            def _row_at_y(self, y_pos: float) -> int:
                y = float(y_pos) + self.verticalScrollBar().value() - self.padding - self.header_h
                step = self.row_h + self.row_gap
                if y < 0:
                    return -1
                idx = int(y // step)
                if 0 <= idx < len(self.rows) and (y % step) <= self.row_h:
                    return idx
                return -1

            def _column_rects(self, rect: Any) -> dict[str, Any]:
                """Compute per-column rects from the active style.

                Each style entry is ``(key, label, weight, min_w, hide_threshold)``.
                Columns whose ``hide_threshold`` exceeds the viewport width are
                dropped; the remaining columns split the leftover space
                proportionally to their ``weight``.
                """
                width = max(1, rect.width() - self.padding * 2)
                visible: list[tuple[str, float, int]] = []  # (key, weight, min_w)
                for key, _label, weight, min_w, hide_threshold in self.style.columns:
                    if hide_threshold and width < hide_threshold:
                        continue
                    visible.append((key, float(weight), int(min_w)))
                # If even the min widths don't fit, drop the lowest-priority
                # (last-listed) columns until they do.
                while visible and sum(m for _k, _w, m in visible) > width:
                    visible.pop()
                if not visible:
                    return {}
                total_min = sum(m for _k, _w, m in visible)
                slack = max(0, width - total_min)
                total_weight = sum(w for _k, w, _m in visible) or 1.0
                widths: dict[str, int] = {}
                used = 0
                for idx, (key, weight, min_w) in enumerate(visible):
                    extra = int(round(slack * (weight / total_weight)))
                    if idx == len(visible) - 1:
                        # Last column absorbs rounding remainder so we fill exactly.
                        col_w = max(min_w, width - used)
                    else:
                        col_w = min_w + extra
                    widths[key] = col_w
                    used += col_w
                # Build rects in style-declared order; hidden columns map to zero-width.
                x = self.padding
                columns: dict[str, Any] = {}
                for key, _label, _w, _m, _h in self.style.columns:
                    col_w = widths.get(key, 0)
                    columns[key] = QtCore.QRectF(x, 0, max(0, col_w), 1)
                    x += col_w
                return columns

            def _draw_board_background(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, colors: dict[str, str]) -> None:
                line = QtGui.QColor(colors.get("blue", "#4a9eda"))
                line.setAlpha(22)
                painter.setPen(QtGui.QPen(line, 1))
                base_y = rect.height() - 34
                painter.drawLine(24, base_y, rect.width() - 24, base_y)
                for offset in range(0, max(1, rect.width()), 120):
                    painter.drawLine(offset + 30, base_y, offset + 82, base_y - 16)
                glow = QtGui.QColor(colors.get("blue", "#4a9eda"))
                glow.setAlpha(12)
                painter.setBrush(glow)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(QtCore.QPointF(rect.width() - 90, 36), 110, 28)

            def _draw_scope_background(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, colors: dict[str, str]) -> None:
                """ATC-scope style faint grid for VATSIM skin."""
                grid = QtGui.QColor(colors.get("blue", "#3ddc84"))
                grid.setAlpha(14)
                painter.setPen(QtGui.QPen(grid, 1))
                step = 64
                for x in range(0, rect.width(), step):
                    painter.drawLine(x, 0, x, rect.height())
                for y in range(0, rect.height(), step):
                    painter.drawLine(0, y, rect.width(), y)
                # Range ring marker in the corner gives the unmistakable scope feel.
                ring = QtGui.QColor(colors.get("cyan", "#5cffae"))
                ring.setAlpha(36)
                painter.setPen(QtGui.QPen(ring, 1.2))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawEllipse(QtCore.QPointF(rect.width() - 60, rect.height() - 60), 48, 48)
                painter.drawEllipse(QtCore.QPointF(rect.width() - 60, rect.height() - 60), 24, 24)

            def _draw_header(self, painter: Any, QtCore: Any, QtGui: Any, columns: dict[str, Any], colors: dict[str, str]) -> None:
                top = self.padding
                kind = self.style.header_kind
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))

                if kind == "tape":
                    # PAX: airline-board tape — accent band with bold labels.
                    tape = QtCore.QRectF(self.padding, top, self.viewport().width() - self.padding * 2, self.header_h - 4)
                    bg = QtGui.QColor(accent)
                    bg.setAlpha(28)
                    painter.setPen(QtGui.QPen(accent, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(tape, 8, 8)
                elif kind == "scope":
                    # VATSIM: thin scope-style underscore + section markers.
                    scope = QtGui.QColor(colors.get("cyan", "#5cffae"))
                    scope.setAlpha(95)
                    painter.setPen(QtGui.QPen(scope, 1))
                    painter.drawLine(self.padding, top + self.header_h - 4, self.viewport().width() - self.padding, top + self.header_h - 4)
                elif kind == "mono":
                    # NERD: monospace tape with column separators.
                    sep = QtGui.QColor(colors.get("line_soft", "#202a38"))
                    sep.setAlpha(120)
                    painter.setPen(QtGui.QPen(sep, 1))
                    for col in columns.values():
                        if col.width() <= 0:
                            continue
                        painter.drawLine(col.left(), top + 2, col.left(), top + self.header_h - 4)
                # Header text per column from the style spec.
                label_color = QtGui.QColor(colors.get("muted", "#79a7c8"))
                if kind == "tape":
                    label_color = QtGui.QColor(colors.get("text", "#e8f0fe"))
                label_color.setAlpha(220 if kind == "tape" else 175)
                header_font = self._mono_font(8.4, bold=True)
                painter.setFont(header_font)
                painter.setPen(label_color)
                # Build live label map; route header uses dynamic ARR/DEP-aware label.
                label_map = {key: lbl for key, lbl, *_ in self.style.columns}
                if "route_display" in label_map:
                    label_map["route_display"] = self.route_label.upper()
                inset = 12 if kind != "mono" else 6
                for key, col in columns.items():
                    if col.width() <= 0:
                        continue
                    text = label_map.get(key, key.upper())
                    painter.drawText(QtCore.QRectF(col.left() + inset, top + 4, col.width() - inset - 4, self.header_h - 8), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, text)
                if kind == "pill":
                    accent_line = QtGui.QColor(accent)
                    accent_line.setAlpha(45)
                    painter.setPen(QtGui.QPen(accent_line, 1))
                    painter.drawLine(self.padding, top + self.header_h - 5, self.viewport().width() - self.padding, top + self.header_h - 5)

            def _draw_row(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, columns: dict[str, Any], row: dict[str, Any], idx: int, colors: dict[str, str]) -> None:
                shaped = enrich_presentation_fields(row)
                status_cls = _row_status_class(shaped)
                status_color = QtGui.QColor(self._status_color(shaped, colors))
                chrome = self.style.row_chrome

                # ---- Row chrome --------------------------------------------------
                if chrome in {"card", "card-big"}:
                    base = QtGui.QColor(colors.get("panel", "#0d1520"))
                    if idx % 2:
                        base = _blend_qcolor(QtGui, base, QtGui.QColor(colors.get("panel_2", "#0a121c")), 0.35)
                    if idx == self.hover_row:
                        base = _blend_qcolor(QtGui, base, QtGui.QColor(colors.get("blue", "#4a9eda")), 0.10)
                    border = QtGui.QColor(colors.get("line_soft", "#17324d"))
                    border.setAlpha(155 if idx == self.hover_row else 95)
                    painter.setPen(QtGui.QPen(border, 1))
                    painter.setBrush(base)
                    radius = 14 if chrome == "card-big" else 10
                    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
                    rail_inset = 10 if chrome == "card-big" else 8
                    rail = QtCore.QRectF(rect.left(), rect.top() + rail_inset, 5 if chrome == "card" else 7, rect.height() - rail_inset * 2)
                    status_color_rail = QtGui.QColor(status_color)
                    status_color_rail.setAlpha(210 if status_cls not in {"scheduled", "departed", "landed"} else 120)
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(status_color_rail)
                    painter.drawRoundedRect(rail, 2, 2)
                    if status_cls in {"boarding", "approaching", "delayed-warn", "delayed-bad", "cancelled", "diverted"}:
                        pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                        halo = QtGui.QColor(status_color)
                        halo.setAlpha(int(26 + pulse * 32))
                        painter.setBrush(halo)
                        painter.drawRoundedRect(QtCore.QRectF(rect.left() + (5 if chrome == "card" else 7), rect.top() + rail_inset, 5, rect.height() - rail_inset * 2), 2, 2)
                elif chrome == "scope":
                    # Flat row with a thin underline + left rail.  Square, no rounding.
                    if idx == self.hover_row:
                        hover = QtGui.QColor(colors.get("blue", "#3ddc84"))
                        hover.setAlpha(22)
                        painter.fillRect(rect, hover)
                    line = QtGui.QColor(colors.get("blue", "#3ddc84"))
                    line.setAlpha(45)
                    painter.setPen(QtGui.QPen(line, 1))
                    painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
                    rail = QtCore.QRectF(rect.left(), rect.top(), 3, rect.height())
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(status_color)
                    painter.drawRect(rail)
                elif chrome == "grid":
                    # NERD: dense grid lines between every cell.
                    if idx % 2:
                        zebra = QtGui.QColor(colors.get("panel", "#0d1520"))
                        zebra.setAlpha(80)
                        painter.fillRect(rect, zebra)
                    if idx == self.hover_row:
                        hover = QtGui.QColor(colors.get("blue", "#4a9eda"))
                        hover.setAlpha(28)
                        painter.fillRect(rect, hover)
                    grid = QtGui.QColor(colors.get("line_soft", "#202a38"))
                    grid.setAlpha(80)
                    painter.setPen(QtGui.QPen(grid, 1))
                    painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())
                    for col in columns.values():
                        if col.width() <= 0:
                            continue
                        painter.drawLine(col.left(), rect.top(), col.left(), rect.bottom())
                    # Status dot only — color the whole row's left edge.
                    dot = QtCore.QRectF(rect.left() + 2, rect.center().y() - 2.5, 5, 5)
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(status_color)
                    painter.drawEllipse(dot)

                # ---- Fresh-row shimmer (cards only) ------------------------------
                if chrome in {"card", "card-big"}:
                    fresh = int(shaped.get("_fresh_alpha") or 0)
                    if fresh:
                        shimmer = QtGui.QColor(colors.get("cyan", "#7ce7ff"))
                        shimmer.setAlpha(min(60, fresh + 12))
                        x = rect.left() + rect.width() * self.animation_phase
                        painter.setBrush(shimmer)
                        painter.drawRoundedRect(QtCore.QRectF(max(rect.left(), x - 80), rect.top(), 110, 2.5), 2, 2)

                # ---- Cells ------------------------------------------------------
                # Iterate the *active style's* columns so non-classic skins
                # (VATSIM, NERD) render their extended fields.
                for key, _label, _w, _m, _h in self.style.columns:
                    cell = self._cell_rect(rect, columns, key)
                    if cell.width() <= 0:
                        continue
                    self._draw_cell(painter, QtCore, QtGui, cell, shaped, colors, key)

            def _cell_rect(self, row_rect: Any, columns: dict[str, Any], key: str) -> Any:
                col = columns.get(key)
                if col is None:
                    return row_rect.__class__(row_rect.left(), row_rect.top(), 0, row_rect.height())
                return row_rect.__class__(col.left(), row_rect.top(), col.width(), row_rect.height())

            # ---- Cell dispatcher ------------------------------------------------
            def _draw_cell(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str], key: str) -> None:
                """Route a single (row, column) draw to its specialised painter.

                Bespoke painters exist for the rich Classic/PAX cells; the
                long tail (VATSIM extras + NERD operator fields) goes
                through the generic text/chip helpers so adding a column to
                a style does not require a new draw method.
                """
                if key == "display_time":
                    self._draw_time(painter, QtCore, QtGui, rect, row, colors)
                elif key == "flight_cell":
                    self._draw_flight(painter, QtCore, QtGui, rect, row, colors)
                elif key == "route_display":
                    self._draw_route(painter, QtCore, QtGui, rect, row, colors)
                elif key == "status_display":
                    self._draw_status(painter, QtCore, QtGui, rect, row, colors)
                elif key == "gate":
                    self._draw_gate(painter, QtCore, QtGui, rect, row, colors)
                elif key == "aircraft_type":
                    self._draw_aircraft(painter, QtCore, QtGui, rect, row, colors)
                elif key == "phase":
                    self._draw_phase_chip(painter, QtCore, QtGui, rect, row, colors)
                elif key == "callsign":
                    text = str(row.get("callsign") or row.get("flight_display") or "-")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, accent=True, bold=True, base_pt=12)
                elif key == "flight_display":
                    text = str(row.get("flight_display") or row.get("flight_number") or row.get("callsign") or "-")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, bold=True, base_pt=10)
                elif key == "registration":
                    text = str(row.get("registration") or row.get("aircraft_reg") or "-")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9)
                elif key == "altitude_ft":
                    text = self._cell_text(row, "altitude_ft")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9)
                elif key == "ground_speed_kt":
                    text = self._cell_text(row, "ground_speed_kt")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9)
                elif key == "alt_speed":
                    text = self._cell_text(row, "alt_speed")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9, bold=True)
                elif key == "squawk":
                    text = str(row.get("squawk") or row.get("transponder") or "-")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9)
                elif key == "flight_rules":
                    rules = str(row.get("flight_rules") or row.get("rules") or "").strip()
                    badge = rules[:1].upper() if rules else "-"
                    self._draw_text_cell(painter, QtCore, QtGui, rect, badge, colors, accent=True, bold=True, base_pt=11, align_center=True)
                elif key == "delay_label":
                    text = self._cell_text(row, "delay_label")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9, muted=True)
                elif key == "source":
                    text = str(row.get("source") or row.get("provider") or "-")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=8, muted=True)
                else:
                    text = str(row.get(key) or "-")
                    self._draw_text_cell(painter, QtCore, QtGui, rect, text, colors, base_pt=9, muted=True)

            def _cell_text(self, row: dict[str, Any], key: str) -> str:
                """Resolve text for non-bespoke operator columns."""
                if key == "altitude_ft":
                    alt = row.get("altitude_ft") or row.get("alt") or row.get("altitude")
                    try:
                        return f"{int(float(alt)):,}" if alt not in (None, "", "-") else "-"
                    except (TypeError, ValueError):
                        return "-"
                if key == "ground_speed_kt":
                    gs = row.get("ground_speed_kt") or row.get("speed_kt") or row.get("speed")
                    try:
                        return f"{int(float(gs))}kt" if gs not in (None, "", "-") else "-"
                    except (TypeError, ValueError):
                        return "-"
                if key == "alt_speed":
                    alt = row.get("altitude_ft") or row.get("alt")
                    gs = row.get("ground_speed_kt") or row.get("speed_kt") or row.get("speed")
                    try:
                        alt_s = f"FL{int(float(alt))//100:03d}" if alt not in (None, "", "-") else "—"
                    except (TypeError, ValueError):
                        alt_s = "—"
                    try:
                        gs_s = f"{int(float(gs))}kt" if gs not in (None, "", "-") else "—"
                    except (TypeError, ValueError):
                        gs_s = "—"
                    return f"{alt_s}/{gs_s}"
                if key == "delay_label":
                    delay = _delay_minutes(row)
                    if delay is None:
                        return "-"
                    if abs(delay) < 5:
                        return "on time"
                    return f"-{abs(delay)}m" if delay < 0 else f"+{delay}m"
                return str(row.get(key) or "-")

            def _draw_text_cell(
                self,
                painter: Any,
                QtCore: Any,
                QtGui: Any,
                rect: Any,
                text: str,
                colors: dict[str, str],
                *,
                bold: bool = False,
                muted: bool = False,
                accent: bool = False,
                base_pt: float = 10.0,
                align_center: bool = False,
            ) -> None:
                font = self._mono_font(base_pt, bold=bold) if self.style.monospace_everywhere else self._primary_font(base_pt, bold=bold)
                painter.setFont(font)
                if accent:
                    color = QtGui.QColor(colors.get("blue", "#4a9eda"))
                elif muted:
                    color = QtGui.QColor(colors.get("muted", "#79a7c8"))
                else:
                    color = QtGui.QColor(colors.get("text", "#e8f0fe"))
                if self.style.color_intensity == "low" and not accent:
                    color.setAlpha(195)
                painter.setPen(color)
                # Elide so long values don't overflow into the next cell.
                metrics = painter.fontMetrics()
                avail = max(12, int(rect.width()) - 10)
                rendered = metrics.elidedText(text, QtCore.Qt.ElideRight, avail)
                inset = 6 if self.style.row_chrome == "grid" else 10
                alignment = QtCore.Qt.AlignCenter if align_center else (QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
                painter.drawText(rect.adjusted(inset, 0, -4, 0), alignment, rendered)

            def _draw_phase_chip(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                """Square ATC phase chip (VATSIM)."""
                from localflight.native.pages.fids_styles import translate_status

                cls = _row_status_class(row)
                text = translate_status(str(row.get("status_display") or row.get("status") or ""), cls, vocabulary="phase")
                color = QtGui.QColor(self._status_color(row, colors))
                bg = QtGui.QColor(color)
                bg.setAlpha(38)
                pad_x = 8
                chip_h = max(18, int(rect.height() * 0.55))
                chip = QtCore.QRectF(rect.left() + pad_x, rect.center().y() - chip_h / 2, max(28, rect.width() - pad_x * 2), chip_h)
                painter.setPen(QtGui.QPen(color, 1))
                painter.setBrush(bg)
                painter.drawRect(chip)  # square, not rounded — scope aesthetic
                painter.setPen(color)
                painter.setFont(self._mono_font(9, bold=True))
                painter.drawText(chip, QtCore.Qt.AlignCenter, text)

            def _draw_time(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                time_text = str(row.get("time_primary") or _split_display_delay(str(row.get("display_time") or ""))[0] or "-")
                delta = str(row.get("time_delta_label") or row.get("_delay_suffix") or "")
                muted = QtGui.QColor(colors.get("muted", "#79a7c8"))
                chrome = self.style.row_chrome
                if chrome == "grid":
                    # NERD: tiny text, no icon, single row of time.
                    self._draw_text_cell(painter, QtCore, QtGui, rect, time_text, colors, bold=True, base_pt=9)
                    return
                if chrome == "scope":
                    # VATSIM: monospace, no icon, just the time.
                    self._draw_text_cell(painter, QtCore, QtGui, rect, time_text, colors, bold=True, base_pt=10, accent=True)
                    return
                icon_y_off = max(6, int(rect.height() * 0.42)) - 8
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 14, rect.top() + icon_y_off, 16, 16), "clock", muted)
                font = self._mono_font(18.0, bold=True) if chrome == "card-big" else self._mono_font(16.0, bold=True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(self._text_color(row, colors)))
                time_block = QtCore.QRectF(rect.left() + 40, rect.top() + 10, rect.width() - 46, max(22, rect.height() * 0.45))
                painter.drawText(time_block, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, time_text)
                if delta:
                    color = QtGui.QColor(self._delay_color(row, colors))
                    bg = QtGui.QColor(color)
                    bg.setAlpha(34)
                    chip = QtCore.QRectF(rect.left() + 42, rect.top() + rect.height() * 0.6, 64, max(18, int(rect.height() * 0.26)))
                    painter.setPen(QtGui.QPen(color, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(chip, chip.height() / 2, chip.height() / 2)
                    painter.setFont(self._mono_font(8.0, bold=True))
                    painter.setPen(color)
                    painter.drawText(chip, QtCore.Qt.AlignCenter, delta)

            def _draw_flight(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                chrome = self.style.row_chrome
                flight_text = str(row.get("flight_display") or row.get("callsign") or "-")
                if chrome == "grid":
                    # NERD: pure compact text, no icon.
                    self._draw_text_cell(painter, QtCore, QtGui, rect, flight_text, colors, bold=True, base_pt=9, accent=True)
                    return
                direction = "arrival" if str(row.get("direction") or "").upper().startswith("ARR") else "departure"
                icon_size = 22 if chrome == "card-big" else 20
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 12, rect.top() + 14, icon_size, icon_size), direction, accent)
                font = self._mono_font(13.0 if chrome == "card-big" else 12.0, bold=True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(self._text_color(row, colors)))
                flight_rect = QtCore.QRectF(rect.left() + 40, rect.top() + 8, max(18, rect.width() - 50), max(20, rect.height() * 0.36))
                flight_rendered = painter.fontMetrics().elidedText(flight_text, QtCore.Qt.ElideRight, max(18, int(flight_rect.width())))
                painter.drawText(flight_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, flight_rendered)
                airline_font = self._primary_font(8.0, bold=True)
                painter.setFont(airline_font)
                painter.setPen(QtGui.QColor(colors.get("muted", "#79a7c8")))
                airline_rect = QtCore.QRectF(rect.left() + 40, rect.top() + rect.height() * 0.42, max(18, rect.width() - 50), 18)
                airline = painter.fontMetrics().elidedText(str(row.get("airline_display") or "").upper(), QtCore.Qt.ElideRight, max(18, int(airline_rect.width())))
                painter.drawText(airline_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, airline)
                if not self.style.show_codeshares:
                    return
                codeshare = self._codeshare_frame(row)
                if codeshare:
                    chip = QtCore.QRectF(rect.left() + 40, rect.top() + rect.height() * 0.66, min(rect.width() - 50, 124), max(18, int(rect.height() * 0.22)))
                    bg = QtGui.QColor(accent)
                    bg.setAlpha(26)
                    painter.setPen(QtGui.QPen(accent, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(chip, chip.height() / 2, chip.height() / 2)
                    self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(chip.left() + 7, chip.top() + 4, 10, 10), "codeshare", accent)
                    painter.setFont(self._mono_font(8.0, bold=True))
                    painter.setPen(accent)
                    painter.drawText(chip.adjusted(22, 0, -6, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, codeshare)

            def _draw_route(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                muted = QtGui.QColor(colors.get("muted", "#79a7c8"))
                primary = str(row.get("route_primary") or row.get("route_display") or "-")
                chrome = self.style.row_chrome
                if chrome == "grid":
                    self._draw_text_cell(painter, QtCore, QtGui, rect, primary, colors, base_pt=9)
                    return
                if chrome == "scope":
                    # VATSIM: pure mono route, no decor.
                    self._draw_text_cell(painter, QtCore, QtGui, rect, primary, colors, base_pt=10, bold=True)
                    return
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 12, rect.top() + rect.height() * 0.24, 18, 18), "route", muted)
                pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                dot = QtGui.QColor(colors.get("cyan", "#7ce7ff"))
                dot.setAlpha(int(100 + pulse * 110))
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(dot)
                painter.drawEllipse(QtCore.QPointF(rect.left() + 21 + pulse * 24, rect.top() + rect.height() * 0.76), 2.5, 2.5)
                code = str(row.get("route_caption") or "")
                font = self._primary_font(11.0 if chrome == "card-big" else 10.0, bold=True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e8f0fe")))
                painter.drawText(QtCore.QRectF(rect.left() + 40, rect.top() + 10, rect.width() - 46, max(20, rect.height() * 0.4)), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, primary)
                source = str(row.get("source_hint") or row.get("live_hint") or "")
                sub = " | ".join(part for part in (code, source) if part and part not in primary)
                small = self._mono_font(8.0)
                painter.setFont(small)
                painter.setPen(muted)
                painter.drawText(QtCore.QRectF(rect.left() + 40, rect.top() + rect.height() * 0.5, rect.width() - 46, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub.upper())

            def _draw_status(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                from localflight.native.pages.fids_styles import translate_status

                status_cls = _row_status_class(row)
                vocab = self.style.status_vocabulary
                raw = str(row.get("status_display") or row.get("status") or "Scheduled")
                label_text = translate_status(raw, status_cls, vocabulary=vocab) if vocab != "standard" else raw.upper()
                color = QtGui.QColor(self._status_color(row, colors))
                pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                chip_kind = self.style.status_chip

                if chip_kind == "code":
                    # NERD: just the 3-letter code in colored text — no chip.
                    painter.setFont(self._mono_font(9, bold=True))
                    painter.setPen(color)
                    painter.drawText(rect.adjusted(6, 0, -4, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, label_text)
                    return
                if chip_kind == "square":
                    # VATSIM: square chip, no rounding, square dot indicator.
                    chip_h = max(18, int(rect.height() * 0.58))
                    chip = QtCore.QRectF(rect.left() + 6, rect.center().y() - chip_h / 2, max(20, rect.width() - 12), chip_h)
                    bg = QtGui.QColor(color)
                    bg.setAlpha(34 if status_cls in {"scheduled", "departed", "landed"} else int(48 + pulse * 32))
                    painter.setPen(QtGui.QPen(color, 1))
                    painter.setBrush(bg)
                    painter.drawRect(chip)
                    painter.setPen(color)
                    painter.setFont(self._mono_font(9, bold=True))
                    painter.drawText(chip, QtCore.Qt.AlignCenter, label_text)
                    return
                # pill / pill-big — Classic / PAX
                pill_h = 46 if chip_kind == "pill-big" else 38
                pill_h = min(pill_h, max(28, int(rect.height() * 0.62)))
                pill = QtCore.QRectF(rect.left() + 9, rect.center().y() - pill_h / 2, max(20, rect.width() - 18), pill_h)
                bg = QtGui.QColor(color)
                bg.setAlpha(28 if status_cls in {"scheduled", "departed", "landed"} else int(42 + pulse * 38))
                painter.setPen(QtGui.QPen(color, 1.5))
                painter.setBrush(bg)
                painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(color)
                dot_radius = (4.4 if chip_kind == "pill-big" else 3.3) + pulse * 1.5
                painter.drawEllipse(QtCore.QPointF(pill.left() + 16, pill.center().y()), dot_radius, dot_radius)
                font_base = 9.6 if chip_kind == "pill-big" else 8.0
                painter.setFont(self._mono_font(font_base, bold=True))
                painter.setPen(color)
                # Elide on small viewports.
                metrics = painter.fontMetrics()
                avail = max(20, int(pill.width()) - 36)
                rendered = metrics.elidedText(label_text, QtCore.Qt.ElideRight, avail)
                painter.drawText(pill.adjusted(32, 0, -10, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, rendered)

            def _draw_gate(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                gate = str(row.get("terminal_gate_display") or row.get("gate_display") or row.get("gate") or "").strip()
                if not gate:
                    self._draw_center_text(painter, QtCore, QtGui, rect, "-", colors, muted=True)
                    return
                chrome = self.style.row_chrome
                if chrome == "grid":
                    self._draw_text_cell(painter, QtCore, QtGui, rect, gate, colors, bold=True, base_pt=9)
                    return
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                bg = QtGui.QColor(accent)
                bg.setAlpha(26)
                badge_h = max(28, min(int(rect.height() * 0.62), 56 if chrome == "card-big" else 44))
                badge = QtCore.QRectF(rect.left() + 8, rect.center().y() - badge_h / 2, max(20, rect.width() - 16), badge_h)
                painter.setPen(QtGui.QPen(accent, 1.3))
                painter.setBrush(bg)
                radius = 12 if chrome == "card-big" else 9 if chrome == "card" else 4
                painter.drawRoundedRect(badge, radius, radius)
                icon_size = 16 if chrome == "card-big" else 14
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(badge.left() + 9, badge.center().y() - icon_size / 2, icon_size, icon_size), "gate", accent)
                font = self._mono_font(11.5 if chrome == "card-big" else 10.0, bold=True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e8f0fe")))
                painter.drawText(badge.adjusted(28 if chrome != "card-big" else 32, 0, -6, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, gate)

            def _draw_aircraft(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                value = str(row.get("aircraft_type") or "").strip().upper()
                if not value:
                    self._draw_center_text(painter, QtCore, QtGui, rect, "-", colors, muted=True)
                    return
                chrome = self.style.row_chrome
                if chrome in {"grid", "scope"}:
                    # Compact skins: just the text, no icon.
                    self._draw_text_cell(painter, QtCore, QtGui, rect, value, colors, bold=True, base_pt=9)
                    return
                muted = QtGui.QColor(colors.get("muted", "#79a7c8"))
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 11, rect.center().y() - 8, 16, 16), "aircraft", muted)
                font = self._mono_font(10.0 if chrome == "card-big" else 9.0, bold=True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e8f0fe")))
                painter.drawText(QtCore.QRectF(rect.left() + 32, rect.top(), rect.width() - 34, rect.height()), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, value)

            def _draw_center_text(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, text: str, colors: dict[str, str], *, muted: bool = False) -> None:
                font = QtGui.QFont("Space Mono")
                font.setPointSize(9)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("muted" if muted else "text", "#e8f0fe")))
                painter.drawText(rect, QtCore.Qt.AlignCenter, text)

            def _codeshare_frame(self, row: dict[str, Any]) -> str:
                frames = row.get("_codeshare_frames")
                if isinstance(frames, list) and frames:
                    idx = int(row.get("_codeshare_frame_index") or 0) % len(frames)
                    return str(frames[idx])
                return ""

            def _status_color(self, row: dict[str, Any], colors: dict[str, str]) -> str:
                tone = str(row.get("tone") or tone_for_status(str(row.get("status_kind") or ""), str(row.get("delay_kind") or "none")))
                if tone == "green":
                    return colors.get("green", "#22c55e")
                if tone == "amber":
                    return colors.get("amber", "#f59e0b")
                if tone == "red":
                    return colors.get("red", "#ef4444")
                if tone == "orange":
                    return "#f97316"
                if tone == "dim":
                    return colors.get("dim", "#7b8494")
                cls = _row_status_class(row)
                if cls in {"boarding", "landed", "early"}:
                    return colors.get("green", "#22c55e")
                if cls in {"approaching", "delayed-warn"}:
                    return colors.get("amber", "#f59e0b")
                if cls in {"delayed", "delayed-bad", "cancelled"}:
                    return colors.get("red", "#ef4444")
                if cls == "diverted":
                    return "#f97316"
                if cls in {"departed", "on-ground"}:
                    return colors.get("dim", "#7b8494")
                return colors.get("blue", "#4a9eda")

            def _delay_color(self, row: dict[str, Any], colors: dict[str, str]) -> str:
                delay_cls = _delay_visual_class(row)
                if delay_cls == "early":
                    return colors.get("green", "#22c55e")
                if delay_cls == "warn":
                    return colors.get("amber", "#f59e0b")
                if delay_cls == "bad":
                    return colors.get("red", "#ef4444")
                return self._status_color(row, colors)

            def _text_color(self, row: dict[str, Any], colors: dict[str, str]) -> str:
                if _row_status_class(row) in {"cancelled", "departed", "landed"}:
                    return colors.get("dim", "#7b8494")
                return colors.get("text", "#e8f0fe")

            def _draw_icon(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, kind: str, color: Any) -> None:
                painter.save()
                emoji = SECTION_EMOJI.get(kind, "")
                if emoji:
                    paint_emoji(QtCore, QtGui, painter, rect, emoji)
                painter.restore()

        return _Board()


class FidsScreen(AsyncFetchMixin):  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient, *, embedded: bool = False) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.embedded = embedded
        self.view = "departures"
        self.rows: list[dict[str, Any]] = []
        self.visible_rows: list[dict[str, Any]] = []
        self._airport_full_title = "LOCAL"
        self._airport_code = "LOCAL"
        self.row_limit = 20
        self.rotation_seconds = 8
        self.page_index = 0
        self._active = False
        self._loading_busy = False
        self._board_animation_phase = 0.0
        self._board_animation_tick = 0
        self.airport_tz_name = "UTC"
        self.airport_tz = timezone.utc
        self.colors = colors_for()

        self.widget = QtWidgets.QSplitter()
        self._init_async(QtCore, self.widget)
        self.widget.setMinimumWidth(0)
        self.escape_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Escape"), self.widget)
        self.escape_shortcut.activated.connect(lambda: self.drawer.hide())
        self.page_timer = QtCore.QTimer(self.widget)
        self.page_timer.timeout.connect(self._advance_page)
        self.widget.setChildrenCollapsible(False)

        board = QtWidgets.QFrame()
        board.setObjectName("Page")
        board.setMinimumWidth(0)
        board.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        board_layout = QtWidgets.QVBoxLayout(board)
        board_layout.setContentsMargins(10 if embedded else 18, 10 if embedded else 18, 10 if embedded else 18, 10 if embedded else 18)
        board_layout.setSpacing(8 if embedded else 10)

        header_widget = QtWidgets.QFrame()
        header_widget.setObjectName("FidsHeader")
        header_widget.setMinimumWidth(0)
        header = QtWidgets.QVBoxLayout(header_widget)
        header.setContentsMargins(8 if embedded else 12, 7 if embedded else 9, 8 if embedded else 12, 7 if embedded else 9)
        header.setSpacing(6 if embedded else 0)
        title_row = QtWidgets.QVBoxLayout() if embedded else QtWidgets.QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6 if embedded else 12)
        title_box = QtWidgets.QVBoxLayout()
        title_box.setContentsMargins(10, 7, 10, 7)
        title_box.setSpacing(2)
        screen_ref = self

        class _AirportHeroFrame(QtWidgets.QFrame):
            def resizeEvent(self, event: Any) -> None:
                super().resizeEvent(event)
                screen_ref._sync_airport_hero_text()

        title_container = _AirportHeroFrame()
        title_container.setObjectName("AirportHero")
        title_container.setLayout(title_box)
        title_container.setMinimumWidth(170 if not embedded else 118)
        title_container.setMaximumWidth(520 if not embedded else 420)
        title_container.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding if embedded else QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Preferred,
        )
        self.airport_hero = title_container
        self.airport = QtWidgets.QLabel("LOCAL")
        self.airport.setObjectName("FidsAirportCode")
        self.airport.setWordWrap(True)
        airport_font = QtGui.QFont()
        airport_font.setPointSize(17 if not embedded else 13)
        airport_font.setBold(True)
        self.airport.setFont(airport_font)
        self.title = QtWidgets.QLabel("Departures")
        self.title.setObjectName("FidsTitle")
        title_font = QtGui.QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        self.title.setFont(title_font)
        title_box.addWidget(self.airport)
        title_box.addWidget(self.title)
        title_row.addWidget(title_container, 0 if embedded else 2)

        self.weather = WeatherStrip(QtWidgets, "Weather loading...")
        self.weather.setObjectName("WeatherHero")
        self.weather.setMinimumHeight(48 if not embedded else 40)
        self.weather.setMaximumHeight(56 if not embedded else 44)
        self.weather.setMinimumWidth(180 if not embedded else 128)
        self.weather.setMaximumWidth(760 if not embedded else 520)
        self.weather.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        title_row.addWidget(self.weather, 0 if embedded else 3)

        self.last_updated = label(QtWidgets, "", "Muted")
        self.last_updated.hide()

        controls_frame = QtWidgets.QFrame()
        controls_frame.setObjectName("FidsHeaderActions")
        controls_frame.setMinimumWidth(0)
        controls_frame.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Preferred)
        controls_row = QtWidgets.QHBoxLayout(controls_frame)
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(5 if embedded else 8)
        self.arr_btn = self._segment_button("ARR", "arrivals")
        self.dep_btn = self._segment_button("DEP", "departures")
        self.dep_btn.setChecked(True)
        if embedded:
            self.arr_btn.setMinimumWidth(46)
            self.dep_btn.setMinimumWidth(46)
        refresh = QtWidgets.QPushButton("Refresh" if embedded else "\U0001F504  Refresh")
        refresh.setObjectName("FidsActionButton")
        refresh.setMinimumHeight(36)
        if embedded:
            refresh.setMinimumWidth(64)
        self.refresh_button = refresh
        refresh.clicked.connect(self.refresh)
        # FIDS style selector: 4 segment buttons (🛬 Classic · 🧳 PAX · 🛩 VATSIM · 🤓 Nerd)
        from localflight.native.pages.fids_styles import STYLES, style_for

        settings = QtCore.QSettings("LocalFlight", "Native")
        saved_style = str(settings.value("fids/style", "classic") or "classic")
        self._fids_style = style_for(saved_style)
        self._fids_style_buttons: dict[str, Any] = {}
        self._fids_style_combo = None
        if embedded:
            style_combo = QtWidgets.QComboBox()
            style_combo.setObjectName("FidsStyleCombo")
            style_combo.setMinimumHeight(32)
            style_combo.setToolTip("FIDS board style")
            for fs in STYLES:
                style_combo.addItem(f"{fs.emoji} {fs.label}", fs.key)
            current_idx = style_combo.findData(self._fids_style.key)
            if current_idx >= 0:
                style_combo.setCurrentIndex(current_idx)
            style_combo.currentIndexChanged.connect(lambda _idx: self.set_fids_style(str(style_combo.currentData() or "classic")))
            self._fids_style_combo = style_combo
            controls_row.addWidget(style_combo)
        else:
            for fs in STYLES:
                btn = QtWidgets.QPushButton(f"{fs.emoji} {fs.label}")
                btn.setObjectName("FidsStyleButton")
                btn.setCheckable(True)
                btn.setChecked(fs.key == self._fids_style.key)
                btn.setToolTip(fs.description)
                btn.setMinimumHeight(32)
                btn.clicked.connect(lambda _checked=False, k=fs.key: self.set_fids_style(k))
                self._fids_style_buttons[fs.key] = btn
                controls_row.addWidget(btn)
        self.scan_indicator = label(QtWidgets, "", "Dim")
        controls_row.addWidget(self.arr_btn)
        controls_row.addWidget(self.dep_btn)
        controls_row.addWidget(refresh)
        controls_row.addWidget(self.scan_indicator)
        controls_scroll = QtWidgets.QScrollArea()
        controls_scroll.setObjectName("FidsHeaderActionsScroll")
        controls_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        controls_scroll.setWidgetResizable(False)
        controls_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        controls_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        controls_scroll.setMinimumWidth(0)
        controls_scroll.setMaximumHeight(48 if embedded else 50)
        controls_scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding if embedded else QtWidgets.QSizePolicy.Maximum,
            QtWidgets.QSizePolicy.Preferred,
        )
        controls_scroll.setWidget(controls_frame)
        self.controls_scroll = controls_scroll
        title_row.addWidget(controls_scroll, 0, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        header.addLayout(title_row)

        self.error_banner = _banner(QtWidgets, "Data fetch error", "ErrorBanner")
        self.info_banner = _banner(
            QtWidgets,
            "Updating the board with the latest airport data...",
            "InfoBanner",
        )
        self.status = label(QtWidgets, "Waiting for first board refresh...", "Muted")

        self.model = FlightBoardModel(
            QtCore,
            [],
            QtGui=QtGui,
            route_label="To",
            colors=self.colors,
            columns=self._fids_style.model_columns,
            status_vocabulary=self._fids_style.status_vocabulary,
        )
        self.delegate = _FidsBoardDelegate(QtCore, QtGui, QtWidgets, lambda: self.colors)
        self.board = FidsBoardView(QtCore, QtGui, QtWidgets, lambda: self.colors)
        self.board.set_style(self._fids_style)
        self.board.setMinimumWidth(0)
        self.board.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.board.rowActivated.connect(lambda row_idx: self._show_detail_for_row(row_idx, 0))

        self.board_animation_timer = QtCore.QTimer(self.widget)
        self.board_animation_timer.setInterval(50)
        self.board_animation_timer.timeout.connect(self._advance_board_animation)
        self.flash_timer = QtCore.QTimer(self.widget)
        self.flash_timer.setInterval(33)
        self.flash_timer.timeout.connect(self._advance_row_flash)
        self._flash_started = 0.0
        self._flash_duration = 1.15
        self._codeshare_frame_index = 0
        self.codeshare_timer = QtCore.QTimer(self.widget)
        self.codeshare_timer.setInterval(1350)
        self.codeshare_timer.timeout.connect(self._advance_codeshare_frames)

        board_layout.addWidget(header_widget)
        board_layout.addWidget(self.error_banner)
        board_layout.addWidget(self.info_banner)
        board_layout.addWidget(self.status)
        board_layout.addWidget(self.board, 1)

        self.drawer = self._build_detail_drawer()
        if embedded:
            self.drawer.setMinimumWidth(0)
            self.drawer.setMaximumWidth(380)
        self.drawer.hide()
        self.widget.addWidget(board)
        self.widget.addWidget(self.drawer)
        self.widget.setSizes([940, 340])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _sync_airport_hero_text(self) -> None:
        if not hasattr(self, "airport"):
            return
        full_title = str(getattr(self, "_airport_full_title", "") or "LOCAL").strip()
        airport_code = str(getattr(self, "_airport_code", "") or "LOCAL").strip().upper()
        available = max(120, int(getattr(self, "airport_hero", self.widget).width()) - 24)
        metrics = self.QtGui.QFontMetrics(self.airport.font())
        if available < 210:
            display = airport_code
        else:
            display = metrics.elidedText(full_title, self.QtCore.Qt.ElideRight, available)
        self.airport.setText(display)
        self.airport.setToolTip(full_title if display != full_title else "")

    def apply_theme(self, theme: str, skin: str) -> None:
        self.colors = colors_for(theme, skin)
        if hasattr(self.model, "set_theme"):
            self.model.set_theme(self.colors)
        if hasattr(self, "board"):
            self.board.set_colors(self.colors)
        if hasattr(self, "detail_body"):
            self._style_detail_body()
        self._render_rows()

    def _style_detail_body(self) -> None:
        panel = self.colors.get("panel_2", "#08111b")
        text = self.colors.get("text", "#e8f0fe")
        line = self.colors.get("line", "#263244")
        selection = _css_rgba(self.colors.get("blue", "#4a9eda"), 0.28)
        self.detail_body.setStyleSheet(
            "QTextEdit {"
            f"background: {panel};"
            f"color: {text};"
            f"border: 1px solid {line};"
            "border-radius: 10px;"
            "padding: 8px;"
            "}"
            f"QTextEdit::selection {{ background: {selection}; }}"
        )

    def _segment_button(self, text: str, view: str) -> Any:
        button = self.QtWidgets.QPushButton(text)
        button.setObjectName("SegmentButton")
        button.setCheckable(True)
        button.setMinimumHeight(36)
        button.setMinimumWidth(56)
        button.clicked.connect(lambda _checked=False, v=view: self.set_view(v))
        return button

    def _build_detail_drawer(self) -> Any:
        drawer = DetailDrawer(self.QtWidgets, "Flight detail")
        self.detail_title = drawer.title_label
        self.detail_route = label(self.QtWidgets, "", "Muted", wrap=True)
        self.detail_body = drawer.body
        self._style_detail_body()
        layout = drawer.layout()
        if layout is not None:
            layout.insertWidget(1, self.detail_route)
        return drawer

    def set_view(self, view: str) -> None:
        self.view = view
        self.arr_btn.setChecked(view == "arrivals")
        self.dep_btn.setChecked(view == "departures")
        self.refresh()

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type in {"snapshot_updated", "config_updated"}:
            self.refresh()
        elif event_type == "scheduler_restarted":
            self.status.setText("Scheduler restarted. Refreshing board...")
            self.refresh()

    def set_fids_style(self, key: str) -> None:
        """Switch the FIDS board style (classic / pax / vatsim / nerd).

        Persists via QSettings("display/fids_style"), reshapes the model
        columns, updates header tooltips, and triggers a board refresh.
        """
        from localflight.native.pages.fids_styles import style_for

        style = style_for(key)
        self._fids_style = style
        for k, btn in getattr(self, "_fids_style_buttons", {}).items():
            try:
                btn.setChecked(k == style.key)
            except Exception:
                pass
        combo = getattr(self, "_fids_style_combo", None)
        if combo is not None:
            try:
                idx = combo.findData(style.key)
                if idx >= 0 and combo.currentIndex() != idx:
                    previous = combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(previous)
            except Exception:
                pass
        try:
            settings = self.QtCore.QSettings("LocalFlight", "Native")
            settings.setValue("fids/style", style.key)
        except Exception:
            pass
        try:
            self.model.set_columns(style.model_columns)
            if hasattr(self.model, "set_status_vocabulary"):
                self.model.set_status_vocabulary(style.status_vocabulary)
        except Exception:
            pass
        try:
            if hasattr(self.board, "set_style"):
                self.board.set_style(style)
            if hasattr(self.board, "viewport"):
                self.board.viewport().update()
        except Exception:
            pass
        # Re-render with the new skin's row layout.
        try:
            self._render_rows()
        except Exception:
            pass

    def set_active(self, active: bool) -> None:
        self._active = active
        if not active:
            self.page_timer.stop()
            self.codeshare_timer.stop()
            self.board_animation_timer.stop()
            self.scan_indicator.setText("")
        elif len(self.rows) > self.row_limit:
            self.page_timer.start(self.rotation_seconds * 1000)
            self._sync_codeshare_animation()
            self._sync_board_animation()
        else:
            self._sync_codeshare_animation()
            self._sync_board_animation()

    def refresh(self) -> None:
        view = self.view
        had_rows = bool(self.rows)
        started = self._run_async(
            lambda: self._fetch_board(view),
            self._apply_board,
            lambda exc: self._board_error(exc, had_rows=had_rows),
            label=f"fids.{view}",
        )
        if started:
            if not had_rows:
                self._set_info_banner(
                    f"Updating {view}. First refreshes can take a moment while airport data is prepared.",
                    True,
                    busy=True,
                )
            self.status.setText(f"Updating {view}...")
            self._sync_board_animation()

    def _fetch_board(self, view: str) -> dict[str, Any]:
        board = self.service.fids_board(view=view, limit=80)
        return {
            "view": board.view,
            "cfg": board.config,
            "payload": board.rows,
            "health": board.health,
            "health_error": board.health_error,
            "weather": board.weather,
            "weather_error": board.weather_error,
        }

    def _apply_board(self, result: dict[str, Any]) -> None:
        cfg = result["cfg"]
        view = str(result["view"])
        self.error_banner.hide()
        self._apply_scheduler_health(result.get("health"), str(result.get("health_error") or ""))
        weather = result.get("weather")
        if isinstance(weather, dict):
            self.weather.set_weather(_weather_line(weather, raw=False), _weather_icon_glyph(weather.get("weather_icon")))
            self.weather.setProperty("tone", str(weather.get("weather_tone") or "neutral"))
            self.weather.style().unpolish(self.weather)
            self.weather.style().polish(self.weather)
        else:
            self.weather.set_weather(f"Weather unavailable: {result.get('weather_error') or 'offline'}", "")
            self.weather.setProperty("tone", "bad")
            self.weather.style().unpolish(self.weather)
            self.weather.style().polish(self.weather)

        airport = str(cfg.get("airport_iata") or cfg.get("airport_icao") or "LOCAL").upper()
        source = str(cfg.get("source") or "real").upper()
        self._set_airport_timezone(str(cfg.get("timezone") or "UTC"))
        self._airport_code = airport
        self._airport_full_title = _airport_title(cfg, airport)
        self._sync_airport_hero_text()
        self.title.setText("Arrivals" if view == "arrivals" else "Departures")
        if hasattr(self.model, "set_route_label"):
            self.model.set_route_label("From" if view == "arrivals" else "To")
        self.rows = self._ordered_board_rows(list_payload(result.get("payload")))
        self.row_limit = max(5, int(cfg.get("web_row_limit") or 20))
        self.rotation_seconds = max(3, int(cfg.get("web_rotation_seconds") or 8))
        self.page_index = 0
        if self.rows:
            self._set_info_banner("", False)
        else:
            self._set_info_banner(
                "No flights match this board window yet. Local Flight will keep checking automatically.",
                True,
                busy=False,
            )
        self.last_updated.setText("")
        page_count = max(1, math.ceil(len(self.rows) / max(1, self.row_limit)))
        self.status.setText(f"{len(self.rows)} {view} loaded | {source} source | page 1/{page_count} | updated now")
        if len(self.rows) > self.row_limit and self._active:
            self.page_timer.start(self.rotation_seconds * 1000)
        else:
            self.page_timer.stop()
        self._render_rows()
        if self.rows:
            self._mark_rows_fresh()
        self._sync_codeshare_animation()

    def _apply_scheduler_health(self, health: Any, health_error: str = "") -> None:
        if not isinstance(health, dict):
            if health_error:
                self.error_banner.show()
                self._set_banner_text(self.error_banner, f"Scheduler health unavailable: {health_error}")
            return
        last_error = str(health.get("last_error") or "").strip()
        if health.get("ok") is False and last_error:
            key_error = any(part in last_error.lower() for part in ("401", "invalid_access_key", "access_key"))
            message = (
                "AviationStack API key is invalid - update it in Settings"
                if key_error
                else f"Fetch error: {last_error}"
            )
            self.error_banner.show()
            self._set_banner_text(self.error_banner, message)
        else:
            self.error_banner.hide()

    def _board_error(self, exc: Exception, *, had_rows: bool = False) -> None:
        self.error_banner.show()
        self._set_banner_text(self.error_banner, f"Data fetch error: {exc}")
        if not had_rows:
            self._set_info_banner("Connection interrupted. Keeping the board ready and trying again shortly.", True, busy=True)
        self.status.setText(f"Board offline: {exc}")

    def _set_info_banner(self, text: str, visible: bool, *, busy: bool = False) -> None:
        if text:
            self._set_banner_text(self.info_banner, text)
        self._loading_busy = bool(busy and visible)
        progress = self.info_banner.findChild(self.QtWidgets.QProgressBar, "LoadingProgress")
        if progress is not None:
            progress.setVisible(bool(busy and visible))
        self.info_banner.setVisible(visible)
        self._sync_board_animation()

    def _set_banner_text(self, banner: Any, text: str) -> None:
        label_widget = banner.findChild(self.QtWidgets.QLabel)
        if label_widget is not None:
            label_widget.setText(text)

    def _set_airport_timezone(self, timezone_name: str) -> None:
        self.airport_tz_name = timezone_name or "UTC"
        try:
            self.airport_tz = ZoneInfo(self.airport_tz_name)
        except Exception:
            self.airport_tz = timezone.utc
            self.airport_tz_name = "UTC"

    def _row_display_time(self, row: dict[str, Any]) -> str:
        enriched = enrich_presentation_fields(row)
        primary = format_value(enriched.get("time_primary")) or ""
        delta = format_value(enriched.get("time_delta_label")) or ""
        if primary and primary != "-":
            return f"{primary} ({delta})" if delta else primary
        existing = format_value(row.get("display_time")) or ""
        existing_base, existing_delay = _split_display_delay(existing)
        for key in ("sched_time", "estimated_time", "est_time", "actual_time", "time"):
            value = row.get(key)
            if not value:
                continue
            parsed = self._parse_time(value)
            if parsed is not None:
                base = parsed.astimezone(self.airport_tz).strftime("%H:%M")
                delay = _delay_suffix(row, existing_delay)
                return f"{base} ({delay})" if delay else base
        delay = _delay_suffix(row, existing_delay)
        if existing_base and existing_base != "-":
            return f"{existing_base} ({delay})" if delay and not existing_delay else existing
        return "-"

    def _parse_time(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=self.airport_tz)
        text = str(value or "").strip()
        if not text or len(text) <= 5:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _ordered_board_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep visible slots filled by moving completed flights behind active rows.

        The local API remains the chronological source.  Native FIDS keeps the
        cached rows, but departed/landed/cancelled rows no longer occupy the
        first page while there are still active rows waiting behind them.
        """
        annotated: list[tuple[int, dict[str, Any]]] = [(idx, dict(row)) for idx, row in enumerate(rows)]
        for idx, row in annotated:
            row["_cache_index"] = idx
        active = [(idx, row) for idx, row in annotated if not _is_completed_status(row)]
        completed = [(idx, row) for idx, row in annotated if _is_completed_status(row)]
        active.sort(key=self._chronological_key)
        completed.sort(key=self._chronological_key)
        return [row for _idx, row in [*active, *completed]]

    def _chronological_key(self, item: tuple[int, dict[str, Any]]) -> tuple[int, datetime | str, int]:
        idx, row = item
        for key in ("sched_time", "estimated_time", "est_time", "actual_time", "time"):
            parsed = self._parse_time(row.get(key))
            if parsed is not None:
                return (0, parsed.astimezone(timezone.utc), idx)
        display_time = str(row.get("display_time") or "")
        match = re.search(r"(\d{1,2}):(\d{2})", display_time)
        if match:
            return (1, f"{int(match.group(1)):02d}:{match.group(2)}", idx)
        return (2, "", idx)

    def _render_rows(self) -> None:
        start = self.page_index * self.row_limit
        source_rows = self.rows[start : start + self.row_limit] or self.rows[: self.row_limit]
        self.visible_rows = [self._model_row(row, start + idx) for idx, row in enumerate(source_rows)]
        self.model.set_rows(self.visible_rows)
        if hasattr(self, "board"):
            self.board.set_rows(self.visible_rows, route_label="From" if self.view == "arrivals" else "To")
        self._fit_columns()
        self._sync_board_animation()

    def _model_row(self, row: dict[str, Any], source_index: int) -> dict[str, Any]:
        shaped = enrich_presentation_fields(dict(row))
        shaped["display_time"] = self._row_display_time(row)
        shaped = enrich_presentation_fields(shaped)
        shaped["_delay_minutes"] = _delay_minutes(shaped)
        shaped["_delay_suffix"] = _delay_suffix(shaped)
        status_cls = _row_status_class(shaped)
        if status_cls in {"delayed", "delayed-warn", "delayed-bad"}:
            if "delay" not in str(shaped.get("status_display") or "").lower():
                suffix = shaped.get("_delay_suffix") or ""
                shaped["status_display"] = f"DELAYED {suffix}M".strip()
            shaped["status_class"] = status_cls
        elif status_cls == "early":
            if "early" not in str(shaped.get("status_display") or "").lower():
                delay = _delay_minutes(shaped)
                shaped["status_display"] = f"EARLY {abs(delay)}M" if isinstance(delay, int) else "EARLY"
            shaped["status_class"] = "early"
        shaped.pop("status_kind", None)
        shaped.pop("tone", None)
        shaped = enrich_presentation_fields(shaped)
        shaped["_codeshare_frames"] = _codeshare_frames(shaped)
        shaped["codeshare_display"] = " / ".join(shaped["_codeshare_frames"])
        shaped["_codeshare_frame_index"] = self._codeshare_frame_index
        shaped["_source_row_index"] = source_index
        shaped["_fresh"] = bool(row.get("_fresh"))
        shaped["_fresh_alpha"] = int(row.get("_fresh_alpha") or 0)
        return shaped

    def _fit_columns(self) -> None:
        if hasattr(self, "board"):
            self.board.set_rows(self.visible_rows, route_label="From" if self.view == "arrivals" else "To")
        self._sync_codeshare_animation()

    def _mark_rows_fresh(self) -> None:
        self._flash_started = time.monotonic()
        for row in self.rows:
            row["_fresh"] = True
            row["_fresh_alpha"] = 34
        self._render_rows()
        self.flash_timer.start()
        self._sync_board_animation()

    def _advance_row_flash(self) -> None:
        elapsed = time.monotonic() - self._flash_started
        progress = min(1.0, max(0.0, elapsed / self._flash_duration))
        alpha = int((1.0 - progress) * 34)
        changed = False
        for row in self.rows:
            if progress >= 1.0:
                if row.pop("_fresh", None) or row.pop("_fresh_alpha", None):
                    changed = True
            else:
                row["_fresh"] = True
                row["_fresh_alpha"] = alpha
                changed = True
        if changed:
            self._render_rows()
        if progress >= 1.0:
            self.flash_timer.stop()
            self._sync_board_animation()

    def _advance_board_animation(self) -> None:
        self._board_animation_tick += 1
        self._board_animation_phase = (self._board_animation_phase + 0.018) % 1.0
        if hasattr(self.delegate, "set_animation_phase"):
            self.delegate.set_animation_phase(self._board_animation_phase)
        if hasattr(self, "board"):
            self.board.set_animation_phase(self._board_animation_phase)
        if self._loading_busy:
            dots = "." * ((self._board_animation_tick % 4) + 1)
            self.scan_indicator.setText(f"SCAN {dots:<4}")
        else:
            self.scan_indicator.setText("")
        if hasattr(self, "board"):
            self.board.viewport().update()
        self._sync_board_animation()

    def _sync_board_animation(self) -> None:
        if not hasattr(self, "board_animation_timer"):
            return
        has_attention = any(_row_status_class(row) in {"boarding", "approaching", "delayed-warn", "delayed-bad", "cancelled", "diverted"} for row in self.visible_rows)
        should_run = bool(self._active and (self._loading_busy or has_attention or self.flash_timer.isActive()))
        if should_run and not self.board_animation_timer.isActive():
            self.board_animation_timer.start()
        elif not should_run and self.board_animation_timer.isActive():
            self.board_animation_timer.stop()
            self.scan_indicator.setText("")

    def _advance_page(self) -> None:
        if len(self.rows) <= self.row_limit:
            return
        page_count = max(1, math.ceil(len(self.rows) / max(1, self.row_limit)))
        self.page_index = (self.page_index + 1) % page_count
        self.status.setText(f"{len(self.rows)} {self.view} loaded | page {self.page_index + 1}/{page_count} | rotating every {self.rotation_seconds}s")
        self._render_rows()

    def _sync_codeshare_animation(self) -> None:
        has_frames = any(len(row.get("_codeshare_frames") or []) > 1 for row in self.visible_rows)
        if self._active and has_frames:
            if not self.codeshare_timer.isActive():
                self.codeshare_timer.start()
        else:
            self.codeshare_timer.stop()

    def _advance_codeshare_frames(self) -> None:
        self._codeshare_frame_index = (self._codeshare_frame_index + 1) % 12
        self._render_rows()

    def _show_detail_for_index(self, index: Any) -> None:
        if not index.isValid():
            return
        self._show_detail_for_row(index.row(), index.column())

    def _show_detail_for_row(self, row_idx: int, _col: int = 0) -> None:
        row = self.model.row_at(row_idx) if hasattr(self.model, "row_at") else None
        if not row and 0 <= row_idx < len(self.visible_rows):
            row = self.visible_rows[row_idx]
        if not row:
            return
        actual_idx = int(row.get("_source_row_index") if row.get("_source_row_index") is not None else row_idx)
        source_row = self.rows[actual_idx] if 0 <= actual_idx < len(self.rows) else row
        callsign = str(source_row.get("callsign") or "").strip()
        if not callsign:
            return
        self.drawer.show()
        self.detail_title.setText(source_row.get("flight_display") or callsign)
        self.detail_route.setText("Loading detail...")
        self.detail_body.setPlainText("")
        started = self._run_async(
            lambda: self.service.fids_detail(callsign),
            self._apply_detail,
            lambda exc: self.detail_route.setText(f"Detail unavailable: {exc}"),
            label="fids.detail",
            debounce_ms=0,
        )
        if not started:
            self.detail_route.setText("Board refresh is still running. Try the row again in a moment.")

    def _apply_detail(self, payload: dict[str, Any]) -> None:
        detail = payload.get("detail") if isinstance(payload.get("detail"), dict) else payload
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        intel = payload.get("intel") if isinstance(payload.get("intel"), dict) else detail.get("intel") if isinstance(detail.get("intel"), dict) else {}
        intel_route = value_at(intel, "route.route_display")
        origin = detail.get("origin_iata") or detail.get("origin_icao") or "-"
        dest = detail.get("dest_iata") or detail.get("dest_icao") or "-"
        airline = detail.get("airline_display") or detail.get("airline_name") or ""
        self.detail_route.setText((intel_route or f"{origin} -> {dest}") + (f" | {airline}" if airline else ""))
        mode = str(detail.get("detail_mode") or detail.get("source") or value_at(detail, "data_sources.schedule") or "real").strip().lower()
        self.detail_body.setHtml(self._detail_html(detail, history, virtual=("virtual" in mode or "vatsim" in mode)))

    def _detail_html(self, detail: dict[str, Any], history: list[dict[str, Any]], *, virtual: bool) -> str:
        title = "Virtual flight" if virtual else "Schedule"
        headline = detail.get("flight_display") or detail.get("flight_number") or detail.get("callsign") or "Flight"
        airline = detail.get("airline_display") or detail.get("airline_name") or detail.get("airline_iata") or ""
        status = detail.get("status_display") or detail.get("status") or "Scheduled"
        status_class = self._detail_tone_class(detail)
        route = self._detail_route_points(detail)
        gate = self._terminal_gate_line(detail) or "Gate pending"
        aircraft = self._aircraft_line(detail) or "Aircraft pending"
        source = value_at(detail, "data_sources.schedule") or detail.get("source") or ("vatsim" if virtual else "schedule")
        parts = [
            _detail_css(self.colors),
            "<div class='detail-shell'>",
            "<div class='detail-hero'>",
            "<div class='hero-rail'></div>",
            f"<div class='hero-kicker'>&#9992; {self._h(title)}</div>",
            f"<div class='hero-flight'>{self._h(headline)}</div>",
            f"<div class='hero-sub'>{self._h(airline or source)}</div>",
            f"<div class='hero-route'><span>{self._h(route[0])}</span><b>&#8594;</b><span>{self._h(route[1])}</span></div>",
            f"<div class='hero-chips'><span class='chip status {status_class}'>{self._h(status)}</span><span class='chip gate'>&#9635; {self._h(gate)}</span><span class='chip aircraft'>&#9992; {self._h(aircraft)}</span></div>",
            self._hero_pills_html(detail),
            "</div>",
        ]
        parts.append(self._detail_card_html("Flight Identity", "&#9673;", self._identity_fields(detail), wide=True))
        if virtual:
            parts.append(self._detail_card_html("Virtual Flight", "&#9992;", [
                ("Callsign", detail.get("callsign")),
                ("Flight", detail.get("flight_display") or detail.get("flight_number")),
                ("A/C code", detail.get("aircraft_type")),
                ("Aircraft type", detail.get("aircraft_type_full") or value_at(detail, "intel.aircraft.model") or value_at(detail, "intel.aircraft.full_type")),
                ("Status", detail.get("status") or detail.get("status_display")),
                ("Source", source),
            ]))
            parts.append(self._detail_card_html("Flight Plan", "&#8644;", [
                ("Origin", self._airport_line(detail, "origin")),
                ("Destination", self._airport_line(detail, "dest")),
                ("Rules", value_at(detail, "flight_plan.flight_rules")),
                ("Route", value_at(detail, "flight_plan.route")),
                ("Cruise altitude", value_at(detail, "flight_plan.cruise_altitude")),
                ("Cruise TAS", value_at(detail, "flight_plan.cruise_tas")),
                ("Planned departure", value_at(detail, "flight_plan.planned_departure")),
                ("Planned arrival", value_at(detail, "flight_plan.planned_arrival")),
                ("Enroute", self._minutes(value_at(detail, "flight_plan.enroute_minutes"))),
                ("Alternate", value_at(detail, "flight_plan.alternate_icao")),
                ("Squawk", value_at(detail, "flight_plan.assigned_transponder") or value_at(detail, "position.squawk")),
            ], wide=True))
            parts.append(self._track_card_html(detail, "Aircraft Track"))
            parts.append(self._detail_card_html("VATSIM Data", "&#9679;", [
                ("Snapshot generated", value_at(detail, "data_sources.snapshot_generated_at")),
                ("Snapshot age", self._seconds(value_at(detail, "data_sources.snapshot_age_seconds"))),
                ("Position age", self._seconds(value_at(detail, "data_sources.position_age_seconds"))),
            ], quiet=True))
        else:
            parts.append(self._time_strip_html(detail))
            parts.append(self._route_card_html(detail))
            parts.append(self._detail_card_html("Operations & Aircraft", "&#9635;", [
                ("Terminal", detail.get("terminal")),
                ("Gate", detail.get("gate")),
                ("Stand", detail.get("stand") or value_at(detail, "intel.operations.stand")),
                ("Direction", "Departure" if detail.get("direction") == "DEP" else "Arrival" if detail.get("direction") == "ARR" else detail.get("direction")),
                ("A/C code", detail.get("aircraft_type")),
                ("Aircraft type", detail.get("aircraft_type_full") or value_at(detail, "intel.aircraft.model") or value_at(detail, "intel.aircraft.full_type")),
                ("Aircraft category", value_at(detail, "intel.aircraft.category")),
                ("Registration", detail.get("aircraft_registration")),
                ("ICAO24", value_at(detail, "intel.aircraft.icao24") or value_at(detail, "position.icao24")),
                ("Squawk", value_at(detail, "intel.aircraft.squawk") or value_at(detail, "position.squawk")),
                ("Callsign", detail.get("callsign")),
                ("Airline", airline),
            ]))
            parts.append(self._detail_card_html("Source Confidence", "&#9679;", [
                ("Schedule", source),
                ("Live Track", detail.get("enriched_by") or value_at(detail, "data_sources.enrichment") or "schedule only"),
                ("Confidence", value_at(detail, "data_sources.confidence")),
                ("Snapshot age", self._seconds(value_at(detail, "data_sources.snapshot_age_seconds"))),
            ], quiet=True))
            parts.append(self._track_card_html(detail, "Live Track"))
        parts.append(self._history_html(history))
        parts.append("</div>")
        return "".join(parts)

    def _hero_pills_html(self, detail: dict[str, Any]) -> str:
        items = [
            ("gate", self._terminal_gate_line(detail)),
            ("aircraft", self._aircraft_line(detail) or detail.get("aircraft_type_full") or value_at(detail, "intel.aircraft.model")),
            ("track", "track available" if value_at(detail, "position.lat") or value_at(detail, "intel.motion.has_position") else "schedule only"),
            ("source", detail.get("enriched_by") or detail.get("source")),
        ]
        pills = [f"<span class='mini-pill'><em>{self._h(label)}</em>{self._h(value)}</span>" for label, value in items if format_value(value)]
        if not pills:
            return ""
        return "<div class='mini-pill-row'>" + "".join(pills) + "</div>"

    def _identity_fields(self, detail: dict[str, Any]) -> list[tuple[str, Any]]:
        sold_as = self._flight_identifier_list(detail.get("sold_as"))
        sold_compact = {str(item).replace(" ", "") for item in sold_as}
        codeshares = [
            item
            for item in self._flight_identifier_list(detail.get("codeshares"))
            if str(item).replace(" ", "") not in sold_compact
        ]
        marketed = ", ".join(sold_as) or self._flight_identifier(detail.get("marketing_flight_number"))
        if codeshares and marketed:
            marketed = f"{marketed} | also {', '.join(codeshares[:4])}"
        elif codeshares:
            marketed = ", ".join(codeshares[:4])
        return [
            ("Operating flight", detail.get("flight_display") or self._flight_identifier(detail.get("flight_number")) or detail.get("callsign")),
            ("Operating airline", detail.get("airline_display") or detail.get("airline_name") or detail.get("airline_iata") or detail.get("airline_icao")),
            ("ATC callsign", detail.get("operating_callsign") or detail.get("callsign")),
            ("Sold as / marketed", marketed),
            ("Provider evidence", str(detail.get("identity_source") or value_at(detail, "intel.identity.identity_source") or "provider").replace("_", " ").upper()),
        ]

    def _flight_identifier_list(self, values: Any) -> list[str]:
        if not values:
            return []
        raw_values = values if isinstance(values, (list, tuple, set)) else [values]
        out: list[str] = []
        for value in raw_values:
            text = self._flight_identifier(value)
            if text and text not in out:
                out.append(text)
        return out

    def _flight_identifier(self, value: Any) -> str:
        return _format_codeshare_number(value)

    def _history_html(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return "<div class='detail-card history-card'><div class='card-title'>&#9719; Recent History (7 days)</div><div class='muted empty'>No history yet.</div></div>"
        parts = ["<div class='detail-card history-card'><div class='card-title'>&#9719; Recent History (7 days)</div><table class='detail-table' width='100%' cellspacing='0' cellpadding='0'>"]
        for item in history[:8]:
            delay = item.get("delay_minutes")
            try:
                delay_i = int(delay)
            except (TypeError, ValueError):
                delay_i = 0
            cls = "bad" if delay_i > 15 else "warn" if delay_i >= 5 else "good" if delay_i <= 0 else "muted"
            delay_text = "On time" if delay_i == 0 else f"{delay_i:+d} min"
            date = item.get("date") or str(item.get("snapshot_ts") or "")[:10] or "-"
            status = item.get("status") or "-"
            parts.append(f"<tr class='history'><td>{self._h(date)} - {self._h(status)}</td><td align='right'><span class='delay-chip {cls}'>{self._h(delay_text)}</span></td></tr>")
        parts.append("</table></div>")
        return "".join(parts)

    def _time_strip_html(self, detail: dict[str, Any]) -> str:
        items = [
            ("Scheduled", detail.get("sched_time")),
            ("Estimated", detail.get("est_time")),
            ("Actual", detail.get("actual_time")),
            ("Delay", self._minutes(detail.get("delay_minutes"))),
        ]
        parts = ["<div class='time-strip'><div class='strip-label'>&#9716; Times (UTC)</div><table class='time-table' width='100%' cellspacing='0' cellpadding='0'>"]
        for name, value in items:
            parts.append(f"<tr><td class='time-key'>{self._h(name)}</td><td class='time-val' align='right'>{self._h(value)}</td></tr>")
        parts.append("</table></div>")
        return "".join(parts)

    def _route_card_html(self, detail: dict[str, Any]) -> str:
        origin, dest = self._detail_route_points(detail)
        return (
            "<div class='detail-card route-card'>"
            "<div class='card-title'>&#8644; Route</div>"
            "<table class='route-line' width='100%' cellspacing='0' cellpadding='0'>"
            f"<tr><td><span>Origin</span><b>{self._h(origin)}</b></td><td class='route-arrow' align='center'>&#8594;</td><td align='right'><span>Destination</span><b>{self._h(dest)}</b></td></tr>"
            "</table>"
            "</div>"
        )

    def _track_card_html(self, detail: dict[str, Any], title: str) -> str:
        rows = [
            ("Latitude", value_at(detail, "position.lat")),
            ("Longitude", value_at(detail, "position.lon")),
            ("Altitude", self._altitude(value_at(detail, "position.altitude_m"))),
            ("Ground speed", self._speed(value_at(detail, "position.speed_ms"))),
            ("Heading", self._heading(value_at(detail, "position.heading"))),
            ("Vertical rate", self._vertical_rate(value_at(detail, "position.vertical_rate") or value_at(detail, "intel.motion.vertical_rate_ms"))),
            ("On ground", value_at(detail, "position.on_ground")),
            ("Distance", self._nm(value_at(detail, "intel.motion.distance_nm"))),
            ("Radar status", value_at(detail, "intel.motion.radar_status")),
            ("Track quality", str(value_at(detail, "intel.motion.source_quality") or "").replace("_", " ").upper()),
            ("Squawk", value_at(detail, "position.squawk")),
            ("Last contact", value_at(detail, "position.last_contact")),
        ]
        if not any(format_value(value) for _name, value in rows):
            return ""
        return self._detail_card_html(title, "&#8982;", rows)

    def _vertical_rate(self, value: Any) -> str:
        try:
            fpm = float(value) * 196.8504
        except (TypeError, ValueError):
            return ""
        sign = "+" if fpm >= 0 else ""
        return f"{sign}{fpm:,.0f} fpm"

    def _nm(self, value: Any) -> str:
        try:
            return f"{float(value):.1f} NM"
        except (TypeError, ValueError):
            return ""

    def _detail_card_html(self, title: str, icon: str, fields: list[tuple[str, Any]], *, quiet: bool = False, wide: bool = False) -> str:
        rows = [(name, format_value(value)) for name, value in fields if format_value(value)]
        if not rows:
            return ""
        class_name = "detail-card"
        if quiet:
            class_name += " quiet"
        if wide:
            class_name += " wide"
        parts = [f"<div class='{class_name}'><div class='card-title'>{icon} {self._h(title)}</div><table class='detail-table' width='100%' cellspacing='0' cellpadding='0'>"]
        for name, value in rows:
            parts.append(f"<tr class='detail-row'><td>{self._h(name)}</td><td align='right'><b>{self._h(value)}</b></td></tr>")
        parts.append("</table></div>")
        return "".join(parts)

    def _detail_route_points(self, detail: dict[str, Any]) -> tuple[str, str]:
        origin = self._airport_line(detail, "origin") or detail.get("origin_iata") or detail.get("origin_icao") or "-"
        dest = self._airport_line(detail, "dest") or detail.get("dest_iata") or detail.get("dest_icao") or "-"
        return (format_value(origin) or "-", format_value(dest) or "-")

    def _terminal_gate_line(self, detail: dict[str, Any]) -> str:
        terminal = format_value(detail.get("terminal"))
        gate = format_value(detail.get("gate"))
        if terminal and gate:
            return f"Terminal {terminal} Gate {gate}"
        if gate:
            return f"Gate {gate}"
        if terminal:
            return f"Terminal {terminal}"
        return ""

    def _aircraft_line(self, detail: dict[str, Any]) -> str:
        aircraft = format_value(detail.get("aircraft_type"))
        registration = format_value(detail.get("aircraft_registration"))
        return " ".join(part for part in (aircraft, registration) if part)

    def _detail_tone_class(self, detail: dict[str, Any]) -> str:
        cls = _row_status_class(detail)
        if cls in {"boarding", "landed", "early"}:
            return "good"
        if cls in {"approaching", "delayed-warn"}:
            return "warn"
        if cls in {"delayed", "delayed-bad", "cancelled"}:
            return "bad"
        if cls == "diverted":
            return "orange"
        if cls in {"departed", "on-ground"}:
            return "dim"
        return "neutral"

    def _h(self, value: Any) -> str:
        return html_escape(format_value(value) or "-")

    def _real_detail_sections(self, detail: dict[str, Any]) -> list[tuple[str, list[tuple[str, Any]]]]:
        return [
            ("Flight Identity", self._identity_fields(detail)),
            ("Times (UTC)", [
                ("Scheduled", detail.get("sched_time")),
                ("Estimated", detail.get("est_time")),
                ("Actual", detail.get("actual_time")),
                ("Delay", self._minutes(detail.get("delay_minutes"))),
            ]),
            ("Operations & Aircraft", [
                ("Origin", self._airport_line(detail, "origin")),
                ("Destination", self._airport_line(detail, "dest")),
                ("Terminal", detail.get("terminal")),
                ("Gate", detail.get("gate")),
                ("A/C code", detail.get("aircraft_type")),
                ("Aircraft type", detail.get("aircraft_type_full") or value_at(detail, "intel.aircraft.model") or value_at(detail, "intel.aircraft.full_type")),
                ("Registration", detail.get("aircraft_registration")),
                ("Callsign", detail.get("callsign")),
                ("Airline", detail.get("airline_display") or detail.get("airline_name") or detail.get("airline_iata")),
            ]),
            ("Source Confidence", [
                ("Schedule", value_at(detail, "data_sources.schedule") or detail.get("source")),
                ("Live Track", detail.get("enriched_by") or value_at(detail, "data_sources.enrichment") or "schedule only"),
                ("Confidence", value_at(detail, "data_sources.confidence")),
                ("Snapshot age", self._seconds(value_at(detail, "data_sources.snapshot_age_seconds"))),
            ]),
            ("Live Track", [
                ("Latitude", value_at(detail, "position.lat")),
                ("Longitude", value_at(detail, "position.lon")),
                ("Altitude", self._altitude(value_at(detail, "position.altitude_m"))),
                ("Ground speed", self._speed(value_at(detail, "position.speed_ms"))),
                ("Heading", self._heading(value_at(detail, "position.heading"))),
                ("On ground", value_at(detail, "position.on_ground")),
                ("Squawk", value_at(detail, "position.squawk")),
            ]),
        ]

    def _virtual_detail_sections(self, detail: dict[str, Any]) -> list[tuple[str, list[tuple[str, Any]]]]:
        return [
            ("Virtual Flight", [
                ("Callsign", detail.get("callsign")),
                ("Flight", detail.get("flight_display") or detail.get("flight_number")),
                ("A/C code", detail.get("aircraft_type")),
                ("Aircraft type", detail.get("aircraft_type_full") or value_at(detail, "intel.aircraft.model") or value_at(detail, "intel.aircraft.full_type")),
                ("Status", detail.get("status") or detail.get("status_display")),
                ("Source", value_at(detail, "data_sources.schedule") or detail.get("source")),
            ]),
            ("Flight plan", [
                ("Origin", self._airport_line(detail, "origin")),
                ("Destination", self._airport_line(detail, "dest")),
                ("Rules", value_at(detail, "flight_plan.flight_rules")),
                ("Route", value_at(detail, "flight_plan.route")),
                ("Cruise altitude", value_at(detail, "flight_plan.cruise_altitude")),
                ("Cruise TAS", value_at(detail, "flight_plan.cruise_tas")),
                ("Planned departure", value_at(detail, "flight_plan.planned_departure")),
                ("Planned arrival", value_at(detail, "flight_plan.planned_arrival")),
                ("Enroute", self._minutes(value_at(detail, "flight_plan.enroute_minutes"))),
                ("Alternate", value_at(detail, "flight_plan.alternate_icao")),
                ("Squawk", value_at(detail, "flight_plan.assigned_transponder") or value_at(detail, "position.squawk")),
            ]),
            ("Aircraft Track", [
                ("Latitude", value_at(detail, "position.lat")),
                ("Longitude", value_at(detail, "position.lon")),
                ("Altitude", self._altitude(value_at(detail, "position.altitude_m"))),
                ("Ground speed", self._speed(value_at(detail, "position.speed_ms"))),
                ("Heading", self._heading(value_at(detail, "position.heading"))),
                ("On ground", value_at(detail, "position.on_ground")),
                ("Last contact", value_at(detail, "position.last_contact")),
            ]),
            ("VATSIM Data", [
                ("Snapshot generated", value_at(detail, "data_sources.snapshot_generated_at")),
                ("Snapshot age", self._seconds(value_at(detail, "data_sources.snapshot_age_seconds"))),
                ("Position age", self._seconds(value_at(detail, "data_sources.position_age_seconds"))),
            ]),
        ]

    def _airport_line(self, detail: dict[str, Any], prefix: str) -> str:
        iata = detail.get(f"{prefix}_iata")
        icao = detail.get(f"{prefix}_icao")
        name = detail.get(f"{prefix}_name")
        codes = " / ".join(str(v) for v in (iata, icao) if v)
        return (codes + (f" - {name}" if name else "")).strip()

    def _altitude(self, value: Any) -> str:
        try:
            meters = float(value)
        except (TypeError, ValueError):
            return ""
        return f"{int(round(meters * 3.28084))} ft"

    def _speed(self, value: Any) -> str:
        try:
            meters_s = float(value)
        except (TypeError, ValueError):
            return ""
        return f"{int(round(meters_s * 1.94384))} kt"

    def _heading(self, value: Any) -> str:
        try:
            return f"{int(round(float(value))) % 360} deg"
        except (TypeError, ValueError):
            return ""

    def _minutes(self, value: Any) -> str:
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return ""
        if minutes == 0:
            return "0 min"
        hours, mins = divmod(abs(minutes), 60)
        sign = "-" if minutes < 0 else ""
        if hours:
            return f"{sign}{hours}h {mins}m"
        return f"{sign}{mins} min"

    def _seconds(self, value: Any) -> str:
        try:
            seconds = int(value)
        except (TypeError, ValueError):
            return ""
        if seconds < 90:
            return f"{seconds}s"
        return self._minutes(round(seconds / 60))


def _banner(QtWidgets: Any, text: str, role: str) -> Any:
    box = QtWidgets.QFrame()
    box.setObjectName(role)
    if role == "InfoBanner":
        layout = QtWidgets.QVBoxLayout(box)
        layout.setSpacing(6)
    else:
        layout = QtWidgets.QHBoxLayout(box)
    layout.setContentsMargins(10, 7, 10, 7)
    layout.addWidget(label(QtWidgets, text, "Muted", wrap=True))
    if role == "InfoBanner":
        progress = QtWidgets.QProgressBar()
        progress.setObjectName("LoadingProgress")
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedHeight(8)
        progress.hide()
        layout.addWidget(progress)
    box.hide()
    return box


def _blend_qcolor(QtGui: Any, first: Any, second: Any, amount: float) -> Any:
    ratio = min(1.0, max(0.0, float(amount)))
    return QtGui.QColor(
        int(first.red() * (1.0 - ratio) + second.red() * ratio),
        int(first.green() * (1.0 - ratio) + second.green() * ratio),
        int(first.blue() * (1.0 - ratio) + second.blue() * ratio),
        int(first.alpha() * (1.0 - ratio) + second.alpha() * ratio),
    )


def _weather_line(payload: dict[str, Any], *, raw: bool) -> str:
    cat = str(payload.get("flight_cat") or "").strip().upper()
    temp_text = str(payload.get("temperature_short") or payload.get("temperature_display") or "").strip()
    if not temp_text:
        temp = payload.get("temperature_c", payload.get("temp_c"))
        temp_text = f"{temp}°C" if temp is not None else ""
    summary = _passenger_weather_label(
        payload.get("condition_display")
        or payload.get("weather_label")
        or payload.get("weather_display")
        or payload.get("weather_summary")
        or payload.get("decoded_summary")
        or "Weather observed"
    )
    parts = [summary]
    if temp_text:
        parts.append(_clean_temperature_text(temp_text))
    if cat:
        parts.append(_flight_category_hint(cat))
    raw_text = payload.get("raw_text") or payload.get("raw") or ""
    line = " · ".join(part for part in parts if part)
    return line + (f" · METAR {raw_text}" if raw and raw_text else "")


def _airport_title(cfg: dict[str, Any], airport_code: str) -> str:
    return city_country_label(
        iata=str(cfg.get("airport_iata") or airport_code),
        icao=str(cfg.get("airport_icao") or ""),
        city=str(cfg.get("airport_city") or ""),
        country=str(cfg.get("airport_country") or cfg.get("country") or ""),
    )


def _passenger_weather_label(value: Any) -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"[_-]+", " ", text).strip().lower()
    mapping = {
        "clear": "Clear skies",
        "sunny": "Sunny",
        "partly": "Partly cloudy",
        "partly cloudy": "Partly cloudy",
        "cloud": "Cloudy",
        "cloudy": "Cloudy",
        "rain": "Rain nearby",
        "light rain": "Light rain",
        "snow": "Snow",
        "fog": "Foggy",
        "fog / haze": "Fog or haze",
        "low visibility": "Low visibility",
        "windy": "Windy",
        "storm": "Storm nearby",
        "thunderstorm": "Thunderstorm nearby",
    }
    if normalized in mapping:
        return mapping[normalized]
    if "clear" in normalized:
        return "Clear skies"
    if "partly" in normalized:
        return "Partly cloudy"
    if "rain" in normalized:
        return "Rain nearby"
    if "fog" in normalized or "haze" in normalized:
        return "Fog or haze"
    if "snow" in normalized:
        return "Snow"
    return text or "Weather observed"


def _flight_category_hint(category: str) -> str:
    return {
        "VFR": "good visibility",
        "MVFR": "reduced visibility",
        "IFR": "low cloud or visibility",
        "LIFR": "very low visibility",
    }.get(category.upper(), "")


def _clean_temperature_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace(" C", "°C").replace("C", "°C")
    text = text.replace("°°C", "°C")
    return text


def _weather_icon_glyph(icon_name: Any) -> str:
    icon = str(icon_name or "unknown").strip().lower()
    return WEATHER_EMOJI.get(icon, WEATHER_EMOJI["unknown"])


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
        formatted = _format_codeshare_number(value)
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
    return [part.strip() for part in re.split(r"[/,;|Â·]+", text) if part.strip()]


def _split_display_delay(value: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)\s*\(([+-]?\d+)\)\s*$", str(value or "").strip())
    if not match:
        return str(value or "").strip(), ""
    return match.group(1).strip(), match.group(2).strip()


def _delay_suffix(row: dict[str, Any], fallback: str = "") -> str:
    delay = _delay_minutes(row)
    if delay is None:
        return fallback.strip()
    if abs(delay) < 5:
        return ""
    sign = "+" if delay > 0 else "-"
    return f"{sign}{abs(delay)}"


def _delay_minutes(row: dict[str, Any]) -> int | None:
    raw = row.get("delay_minutes")
    try:
        return int(raw)
    except (TypeError, ValueError):
        _base, suffix = _split_display_delay(str(row.get("display_time") or ""))
        if not suffix:
            return None
        try:
            return int(suffix)
        except ValueError:
            return None


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


def _format_codeshare_number(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    return format_flight_identifier(flight_number=text)


def _compact_flight_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _row_status_class(row: dict[str, Any]) -> str:
    row = enrich_presentation_fields(row)
    raw = str(row.get("status_class") or row.get("status_display") or row.get("status") or "scheduled")
    normalized = raw.strip().lower().replace(" ", "-").replace("_", "-")
    if normalized in {"delayed-warn", "delayed-bad", "early"}:
        return normalized
    if "board" in normalized:
        return "boarding"
    if "approach" in normalized:
        return "approaching"
    if "cancel" in normalized:
        return "cancelled"
    if "divert" in normalized:
        return "diverted"
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


def _is_completed_status(row: dict[str, Any]) -> bool:
    return _row_status_class(row) in {"departed", "landed", "arrived", "cancelled"}


def _detail_css(colors: dict[str, str]) -> str:
    is_light = str(colors.get("bg", "")).lower() == "#f4f7fb"
    divider = "rgba(0,0,0,.10)" if is_light else "rgba(255,255,255,.06)"
    blue = colors.get("blue", "#4a9eda")
    panel = colors.get("panel", "#0d1520")
    panel_2 = colors.get("panel_2", "#08111b")
    text = colors.get("text", "#e8f0fe")
    muted = colors.get("muted", "#79a7c8")
    dim = colors.get("dim", "#7b8494")
    green = colors.get("green", "#22c55e")
    amber = colors.get("amber", "#f59e0b")
    red = colors.get("red", "#ef4444")
    orange = "#f97316"
    card_bg = _css_rgba(blue, 0.08 if is_light else 0.06)
    card_border = _css_rgba(blue, 0.28 if is_light else 0.20)
    chip_bg = _css_rgba(blue, 0.13 if is_light else 0.10)
    return (
        "<style>"
        f"body{{font-family:'DM Sans','Segoe UI','Helvetica Neue',sans-serif;color:{text};background:{panel_2};margin:0;}}"
        ".detail-shell{padding:2px 0 8px 0;}"
        f".detail-hero{{position:relative;border:1px solid {card_border};background:{_css_rgba(blue, 0.09 if is_light else 0.07)};border-radius:12px;padding:13px 13px 12px 17px;margin:0 0 12px 0;}}"
        f".hero-rail{{position:absolute;left:0;top:10px;bottom:10px;width:4px;background:{blue};border-radius:3px;}}"
        f".hero-kicker,.strip-label,.card-title{{font:700 10px 'Space Mono','Consolas',monospace;letter-spacing:.10em;text-transform:uppercase;color:{dim};margin:0 0 8px 0;}}"
        ".hero-flight{font:800 24px 'Space Mono','Consolas',monospace;margin:0 0 2px 0;}"
        f".hero-sub{{font-weight:700;color:{muted};margin:0 0 10px 0;text-transform:uppercase;}}"
        f".hero-route{{color:{text};font-weight:800;margin:0 0 10px 0;}}"
        f".hero-route b{{color:{blue};font-family:'Space Mono','Consolas',monospace;}}"
        ".hero-chips{margin-top:6px;}"
        f".chip,.delay-chip{{border:1px solid {card_border};background:{chip_bg};color:{blue};border-radius:999px;padding:4px 8px;margin-right:5px;font:800 10px 'Space Mono','Consolas',monospace;text-transform:uppercase;}}"
        f".chip.gate,.chip.aircraft{{color:{text};background:{_css_rgba(blue, 0.10)};}}"
        ".mini-pill-row{margin-top:10px;display:flex;flex-wrap:wrap;gap:5px;}"
        f".mini-pill{{display:inline-block;border:1px solid {card_border};background:{_css_rgba(blue, 0.10)};color:{blue};border-radius:999px;padding:4px 8px;font:800 10px 'Space Mono','Consolas',monospace;text-transform:uppercase;}}"
        f".mini-pill em{{font:800 8px 'DM Sans','Segoe UI',sans-serif;letter-spacing:.10em;color:{muted};font-style:normal;margin-right:5px;}}"
        f".status.good,.delay-chip.good{{border-color:{_css_rgba(green, 0.55)};background:{_css_rgba(green, 0.14)};color:{green};}}"
        f".status.warn,.delay-chip.warn{{border-color:{_css_rgba(amber, 0.60)};background:{_css_rgba(amber, 0.15)};color:{amber};}}"
        f".status.bad,.delay-chip.bad{{border-color:{_css_rgba(red, 0.60)};background:{_css_rgba(red, 0.15)};color:{red};}}"
        f".status.orange{{border-color:{_css_rgba(orange, 0.60)};background:{_css_rgba(orange, 0.15)};color:{orange};}}"
        f".status.dim,.delay-chip.muted{{border-color:{_css_rgba(dim, 0.45)};background:{_css_rgba(dim, 0.10)};color:{dim};}}"
        f".status.neutral{{border-color:{card_border};background:{chip_bg};color:{blue};}}"
        f".time-strip{{border:1px solid {divider};background:{panel};border-radius:10px;padding:10px 10px 6px 10px;margin:0 0 12px 0;}}"
        f".time-key,.detail-row td:first-child,.route-line span{{color:{muted};font:700 9px 'Space Mono','Consolas',monospace;text-transform:uppercase;letter-spacing:.08em;}}"
        f".time-val,.detail-row b,.route-line b{{color:{text};font-weight:800;}}"
        f".detail-card{{border:1px solid {divider};background:linear-gradient(180deg,{_css_rgba(blue, 0.045)},transparent 70%),{panel};border-radius:11px;padding:11px;margin:0 0 12px 0;}}"
        f".detail-card.quiet{{background:{card_bg};border-color:{card_border};}}"
        ".detail-card.wide .detail-row b{font-size:11px;}"
        f".detail-row td,.time-table td{{padding:6px 0;border-bottom:1px solid {divider};}}"
        ".detail-row:last-child td,.time-table tr:last-child td{border-bottom:0;}"
        f".route-card{{background:{_css_rgba(blue, 0.07)};border-color:{card_border};}}"
        ".route-line td{vertical-align:middle;}"
        f".route-arrow{{color:{blue};font:900 18px 'Space Mono','Consolas',monospace;}}"
        ".history-card{padding-bottom:8px;}"
        f".history td{{padding:7px 0;border-bottom:1px solid {divider};}}"
        ".history:last-child td{border-bottom:0;}"
        f".muted{{color:{muted};}}.empty{{padding:4px 0 2px 0;}}"
        f".good{{color:{green};}}.warn{{color:{amber};}}.bad{{color:{red};}}.orange{{color:{orange};}}"
        "</style>"
    )


def _css_rgba(hex_color: str, alpha: float) -> str:
    value = str(hex_color or "").lstrip("#")
    if len(value) != 6:
        return f"rgba(74,158,218,{alpha:.2f})"
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
    except ValueError:
        return f"rgba(74,158,218,{alpha:.2f})"
    return f"rgba({r},{g},{b},{alpha:.2f})"


__all__ = ["FidsScreen"]
