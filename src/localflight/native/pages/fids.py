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

from localflight.native.api_client import LocalApiClient, NativeApiError
from localflight.native.async_tools import AsyncFetchMixin
from localflight.native.design import colors_for, format_value, label, list_payload, value_at
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
                icon_color = QtGui.QColor(color)
                icon_color.setAlpha(max(90, icon_color.alpha()))
                painter.setPen(QtGui.QPen(icon_color, 1.4))
                painter.setBrush(QtCore.Qt.NoBrush)
                cx = rect.center().x()
                cy = rect.center().y()
                w = rect.width()
                h = rect.height()
                if kind in {"arrival", "departure"}:
                    painter.drawLine(QtCore.QPointF(rect.left() + w * 0.10, cy), QtCore.QPointF(rect.right() - w * 0.10, cy))
                    painter.drawLine(QtCore.QPointF(cx, rect.top() + h * 0.12), QtCore.QPointF(cx, rect.bottom() - h * 0.12))
                    if kind == "arrival":
                        painter.drawLine(QtCore.QPointF(rect.left() + w * 0.20, rect.bottom() - h * 0.18), QtCore.QPointF(rect.right() - w * 0.16, rect.top() + h * 0.20))
                    else:
                        painter.drawLine(QtCore.QPointF(rect.left() + w * 0.20, rect.top() + h * 0.18), QtCore.QPointF(rect.right() - w * 0.16, rect.bottom() - h * 0.20))
                elif kind == "clock":
                    painter.drawEllipse(rect.adjusted(1.5, 1.5, -1.5, -1.5))
                    painter.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(cx, rect.top() + h * 0.26))
                    painter.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(rect.right() - w * 0.26, cy))
                elif kind == "route":
                    painter.drawEllipse(QtCore.QRectF(rect.left() + 1, cy - 3, 6, 6))
                    painter.drawEllipse(QtCore.QRectF(rect.right() - 7, cy - 3, 6, 6))
                    painter.drawLine(QtCore.QPointF(rect.left() + 7, cy), QtCore.QPointF(rect.right() - 7, cy))
                elif kind == "gate":
                    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 2, 2)
                    painter.drawLine(QtCore.QPointF(cx, rect.top() + 3), QtCore.QPointF(cx, rect.bottom() - 3))
                elif kind == "codeshare":
                    painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
                    painter.drawLine(QtCore.QPointF(rect.left() + 3, cy), QtCore.QPointF(rect.right() - 3, cy))
                elif kind == "aircraft":
                    path = QtGui.QPainterPath(QtCore.QPointF(cx, rect.top() + 1))
                    path.lineTo(QtCore.QPointF(cx + w * 0.18, cy + h * 0.10))
                    path.lineTo(QtCore.QPointF(rect.right() - 1, cy + h * 0.05))
                    path.lineTo(QtCore.QPointF(cx + w * 0.16, cy + h * 0.22))
                    path.lineTo(QtCore.QPointF(cx + w * 0.08, rect.bottom() - 1))
                    path.lineTo(QtCore.QPointF(cx, cy + h * 0.30))
                    path.lineTo(QtCore.QPointF(cx - w * 0.08, rect.bottom() - 1))
                    path.lineTo(QtCore.QPointF(cx - w * 0.16, cy + h * 0.22))
                    path.lineTo(QtCore.QPointF(rect.left() + 1, cy + h * 0.05))
                    path.lineTo(QtCore.QPointF(cx - w * 0.18, cy + h * 0.10))
                    path.closeSubpath()
                    fill = QtGui.QColor(icon_color)
                    fill.setAlpha(80)
                    painter.setBrush(fill)
                    painter.drawPath(path)
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
    """Custom passenger-board surface for native FIDS rows."""

    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any, colors_provider: Any):
        class _Board(QtWidgets.QAbstractScrollArea):
            rowActivated = QtCore.Signal(int)
            column_keys = ("display_time", "flight_cell", "route_display", "status_display", "gate", "aircraft_type")

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
                self.header_h = 38
                self.row_gap = 8
                self.row_h = 76
                self.padding = 10

            def minimumSizeHint(self) -> Any:
                return QtCore.QSize(640, 320)

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
                colors = colors_provider() or self.colors or {}
                self.colors = colors
                painter.fillRect(rect, QtGui.QColor(colors.get("panel_2", "#08111b")))
                self._draw_board_background(painter, QtCore, QtGui, rect, colors)
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
                width = max(1, rect.width() - self.padding * 2)
                compact = width < 760
                ac_w = 0 if compact else 92
                time_w = 130 if compact else 160
                status_w = 136 if compact else 176
                gate_w = 86 if compact else 118
                route_w = max(190, int(width * (0.31 if compact else 0.34)))
                flight_w = max(170, width - time_w - status_w - gate_w - ac_w - route_w)
                x = self.padding
                columns: dict[str, Any] = {}
                for key, col_w in (
                    ("display_time", time_w),
                    ("flight_cell", flight_w),
                    ("route_display", route_w),
                    ("status_display", status_w),
                    ("gate", gate_w),
                    ("aircraft_type", ac_w),
                ):
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

            def _draw_header(self, painter: Any, QtCore: Any, QtGui: Any, columns: dict[str, Any], colors: dict[str, str]) -> None:
                top = self.padding
                label_color = QtGui.QColor(colors.get("muted", "#79a7c8"))
                label_color.setAlpha(170)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(label_color)
                labels = {
                    "display_time": "TIME",
                    "flight_cell": "FLIGHT",
                    "route_display": self.route_label.upper(),
                    "status_display": "STATUS",
                    "gate": "GATE",
                    "aircraft_type": "A/C",
                }
                for key, label_text in labels.items():
                    col = columns.get(key)
                    if col is None or col.width() <= 0:
                        continue
                    painter.drawText(QtCore.QRectF(col.left() + 12, top + 4, col.width() - 16, 20), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label_text)
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                accent.setAlpha(45)
                painter.setPen(QtGui.QPen(accent, 1))
                painter.drawLine(self.padding, top + self.header_h - 5, self.viewport().width() - self.padding, top + self.header_h - 5)

            def _draw_row(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, columns: dict[str, Any], row: dict[str, Any], idx: int, colors: dict[str, str]) -> None:
                shaped = enrich_presentation_fields(row)
                status_cls = _row_status_class(shaped)
                status_color = QtGui.QColor(self._status_color(shaped, colors))
                base = QtGui.QColor(colors.get("panel", "#0d1520"))
                if idx % 2:
                    base = _blend_qcolor(QtGui, base, QtGui.QColor(colors.get("panel_2", "#0a121c")), 0.35)
                if idx == self.hover_row:
                    base = _blend_qcolor(QtGui, base, QtGui.QColor(colors.get("blue", "#4a9eda")), 0.10)
                border = QtGui.QColor(colors.get("line_soft", "#17324d"))
                border.setAlpha(155 if idx == self.hover_row else 95)
                painter.setPen(QtGui.QPen(border, 1))
                painter.setBrush(base)
                painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
                rail = QtCore.QRectF(rect.left(), rect.top() + 8, 5, rect.height() - 16)
                status_color.setAlpha(210 if status_cls not in {"scheduled", "departed", "landed"} else 120)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(status_color)
                painter.drawRoundedRect(rail, 2, 2)
                fresh = int(shaped.get("_fresh_alpha") or 0)
                if fresh:
                    shimmer = QtGui.QColor(colors.get("cyan", "#7ce7ff"))
                    shimmer.setAlpha(min(60, fresh + 12))
                    x = rect.left() + rect.width() * self.animation_phase
                    painter.setBrush(shimmer)
                    painter.drawRoundedRect(QtCore.QRectF(max(rect.left(), x - 80), rect.top(), 110, 2.5), 2, 2)
                if status_cls in {"boarding", "approaching", "delayed-warn", "delayed-bad", "cancelled", "diverted"}:
                    pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                    halo = QtGui.QColor(status_color)
                    halo.setAlpha(int(26 + pulse * 32))
                    painter.setBrush(halo)
                    painter.drawRoundedRect(QtCore.QRectF(rect.left() + 5, rect.top() + 8, 5, rect.height() - 16), 2, 2)
                self._draw_time(painter, QtCore, QtGui, self._cell_rect(rect, columns, "display_time"), shaped, colors)
                self._draw_flight(painter, QtCore, QtGui, self._cell_rect(rect, columns, "flight_cell"), shaped, colors)
                self._draw_route(painter, QtCore, QtGui, self._cell_rect(rect, columns, "route_display"), shaped, colors)
                self._draw_status(painter, QtCore, QtGui, self._cell_rect(rect, columns, "status_display"), shaped, colors)
                self._draw_gate(painter, QtCore, QtGui, self._cell_rect(rect, columns, "gate"), shaped, colors)
                ac_rect = self._cell_rect(rect, columns, "aircraft_type")
                if ac_rect.width() > 0:
                    self._draw_aircraft(painter, QtCore, QtGui, ac_rect, shaped, colors)

            def _cell_rect(self, row_rect: Any, columns: dict[str, Any], key: str) -> Any:
                col = columns[key]
                return row_rect.__class__(col.left(), row_rect.top(), col.width(), row_rect.height())

            def _draw_time(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                time_text = str(row.get("time_primary") or _split_display_delay(str(row.get("display_time") or ""))[0] or "-")
                delta = str(row.get("time_delta_label") or row.get("_delay_suffix") or "")
                muted = QtGui.QColor(colors.get("muted", "#79a7c8"))
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 16, rect.center().y() - 8, 16, 16), "clock", muted)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(20)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(self._text_color(row, colors)))
                painter.drawText(QtCore.QRectF(rect.left() + 42, rect.top() + 10, rect.width() - 46, 32), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, time_text)
                if delta:
                    color = QtGui.QColor(self._delay_color(row, colors))
                    bg = QtGui.QColor(color)
                    bg.setAlpha(34)
                    chip = QtCore.QRectF(rect.left() + 43, rect.top() + 46, 62, 20)
                    painter.setPen(QtGui.QPen(color, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(chip, 10, 10)
                    small = QtGui.QFont("Space Mono")
                    small.setPointSize(8)
                    small.setBold(True)
                    painter.setFont(small)
                    painter.setPen(color)
                    painter.drawText(chip, QtCore.Qt.AlignCenter, delta)

            def _draw_flight(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                direction = "arrival" if str(row.get("direction") or "").upper().startswith("ARR") else "departure"
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 12, rect.top() + 16, 20, 20), direction, accent)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(13)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(self._text_color(row, colors)))
                painter.drawText(QtCore.QRectF(rect.left() + 42, rect.top() + 9, rect.width() - 50, 26), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, str(row.get("flight_display") or row.get("callsign") or "-"))
                airline_font = QtGui.QFont()
                airline_font.setPointSize(8)
                airline_font.setBold(True)
                painter.setFont(airline_font)
                painter.setPen(QtGui.QColor(colors.get("muted", "#79a7c8")))
                painter.drawText(QtCore.QRectF(rect.left() + 42, rect.top() + 34, rect.width() - 50, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, str(row.get("airline_display") or "").upper())
                codeshare = self._codeshare_frame(row)
                if codeshare:
                    chip = QtCore.QRectF(rect.left() + 42, rect.top() + 52, min(rect.width() - 50, 116), 18)
                    bg = QtGui.QColor(accent)
                    bg.setAlpha(26)
                    painter.setPen(QtGui.QPen(accent, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(chip, 9, 9)
                    self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(chip.left() + 7, chip.top() + 4, 10, 10), "codeshare", accent)
                    small = QtGui.QFont("Space Mono")
                    small.setPointSize(8)
                    small.setBold(True)
                    painter.setFont(small)
                    painter.setPen(accent)
                    painter.drawText(chip.adjusted(22, 0, -6, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, codeshare)

            def _draw_route(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                muted = QtGui.QColor(colors.get("muted", "#79a7c8"))
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 12, rect.top() + 18, 18, 18), "route", muted)
                pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                dot = QtGui.QColor(colors.get("cyan", "#7ce7ff"))
                dot.setAlpha(int(100 + pulse * 110))
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(dot)
                painter.drawEllipse(QtCore.QPointF(rect.left() + 21 + pulse * 24, rect.top() + 58), 2.5, 2.5)
                primary = str(row.get("route_primary") or row.get("route_display") or "-")
                code = str(row.get("route_caption") or "")
                font = QtGui.QFont()
                font.setPointSize(11)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e8f0fe")))
                painter.drawText(QtCore.QRectF(rect.left() + 42, rect.top() + 12, rect.width() - 48, 25), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, primary)
                source = str(row.get("source_hint") or row.get("live_hint") or "")
                sub = " | ".join(part for part in (code, source) if part and part not in primary)
                small = QtGui.QFont("Space Mono")
                small.setPointSize(8)
                painter.setFont(small)
                painter.setPen(muted)
                painter.drawText(QtCore.QRectF(rect.left() + 42, rect.top() + 40, rect.width() - 48, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub.upper())

            def _draw_status(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                label_text = str(row.get("status_display") or row.get("status") or "Scheduled").upper()
                color = QtGui.QColor(self._status_color(row, colors))
                bg = QtGui.QColor(color)
                status_cls = _row_status_class(row)
                pulse = (math.sin(self.animation_phase * math.tau) + 1.0) / 2.0
                bg.setAlpha(28 if status_cls in {"scheduled", "departed", "landed"} else int(42 + pulse * 38))
                pill = QtCore.QRectF(rect.left() + 9, rect.center().y() - 19, max(20, rect.width() - 18), 38)
                painter.setPen(QtGui.QPen(color, 1.5))
                painter.setBrush(bg)
                painter.drawRoundedRect(pill, 19, 19)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(color)
                painter.drawEllipse(QtCore.QPointF(pill.left() + 14, pill.center().y()), 3.3 + pulse * 1.5, 3.3 + pulse * 1.5)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(8)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(color)
                painter.drawText(pill.adjusted(28, 0, -8, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label_text)

            def _draw_gate(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                gate = str(row.get("terminal_gate_display") or row.get("gate_display") or row.get("gate") or "").strip()
                if not gate:
                    self._draw_center_text(painter, QtCore, QtGui, rect, "-", colors, muted=True)
                    return
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                bg = QtGui.QColor(accent)
                bg.setAlpha(26)
                badge = QtCore.QRectF(rect.left() + 8, rect.center().y() - 21, max(20, rect.width() - 16), 42)
                painter.setPen(QtGui.QPen(accent, 1.3))
                painter.setBrush(bg)
                painter.drawRoundedRect(badge, 9, 9)
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(badge.left() + 9, badge.center().y() - 7, 14, 14), "gate", accent)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(10)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e8f0fe")))
                painter.drawText(badge.adjusted(30, 0, -6, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, gate)

            def _draw_aircraft(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                value = str(row.get("aircraft_type") or "").strip().upper()
                if not value:
                    self._draw_center_text(painter, QtCore, QtGui, rect, "-", colors, muted=True)
                    return
                muted = QtGui.QColor(colors.get("muted", "#79a7c8"))
                self._draw_icon(painter, QtCore, QtGui, QtCore.QRectF(rect.left() + 11, rect.center().y() - 8, 16, 16), "aircraft", muted)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(9)
                font.setBold(True)
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
                icon_color = QtGui.QColor(color)
                icon_color.setAlpha(max(100, icon_color.alpha()))
                painter.setPen(QtGui.QPen(icon_color, 1.5))
                painter.setBrush(QtCore.Qt.NoBrush)
                cx = rect.center().x()
                cy = rect.center().y()
                w = rect.width()
                h = rect.height()
                if kind in {"arrival", "departure"}:
                    painter.drawLine(QtCore.QPointF(rect.left() + w * 0.10, cy), QtCore.QPointF(rect.right() - w * 0.10, cy))
                    painter.drawLine(QtCore.QPointF(cx, rect.top() + h * 0.12), QtCore.QPointF(cx, rect.bottom() - h * 0.12))
                    if kind == "arrival":
                        painter.drawLine(QtCore.QPointF(rect.left() + w * 0.18, rect.bottom() - h * 0.16), QtCore.QPointF(rect.right() - w * 0.12, rect.top() + h * 0.18))
                    else:
                        painter.drawLine(QtCore.QPointF(rect.left() + w * 0.18, rect.top() + h * 0.16), QtCore.QPointF(rect.right() - w * 0.12, rect.bottom() - h * 0.18))
                elif kind == "clock":
                    painter.drawEllipse(rect.adjusted(1.5, 1.5, -1.5, -1.5))
                    painter.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(cx, rect.top() + h * 0.26))
                    painter.drawLine(QtCore.QPointF(cx, cy), QtCore.QPointF(rect.right() - w * 0.26, cy))
                elif kind == "route":
                    painter.drawEllipse(QtCore.QRectF(rect.left() + 1, cy - 3, 6, 6))
                    painter.drawEllipse(QtCore.QRectF(rect.right() - 7, cy - 3, 6, 6))
                    painter.drawLine(QtCore.QPointF(rect.left() + 7, cy), QtCore.QPointF(rect.right() - 7, cy))
                elif kind == "gate":
                    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 2, 2)
                    painter.drawLine(QtCore.QPointF(cx, rect.top() + 3), QtCore.QPointF(cx, rect.bottom() - 3))
                elif kind == "codeshare":
                    painter.drawEllipse(rect.adjusted(1, 1, -1, -1))
                    painter.drawLine(QtCore.QPointF(rect.left() + 3, cy), QtCore.QPointF(rect.right() - 3, cy))
                elif kind == "aircraft":
                    path = QtGui.QPainterPath(QtCore.QPointF(cx, rect.top() + 1))
                    path.lineTo(QtCore.QPointF(rect.right() - 1, cy + h * 0.05))
                    path.lineTo(QtCore.QPointF(cx + w * 0.14, cy + h * 0.22))
                    path.lineTo(QtCore.QPointF(cx + w * 0.07, rect.bottom() - 1))
                    path.lineTo(QtCore.QPointF(cx, cy + h * 0.30))
                    path.lineTo(QtCore.QPointF(cx - w * 0.07, rect.bottom() - 1))
                    path.lineTo(QtCore.QPointF(cx - w * 0.14, cy + h * 0.22))
                    path.lineTo(QtCore.QPointF(rect.left() + 1, cy + h * 0.05))
                    path.closeSubpath()
                    fill = QtGui.QColor(icon_color)
                    fill.setAlpha(86)
                    painter.setBrush(fill)
                    painter.drawPath(path)
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
        self.escape_shortcut = QtGui.QShortcut(QtGui.QKeySequence("Escape"), self.widget)
        self.escape_shortcut.activated.connect(lambda: self.drawer.hide())
        self.page_timer = QtCore.QTimer(self.widget)
        self.page_timer.timeout.connect(self._advance_page)
        self.widget.setChildrenCollapsible(False)

        board = QtWidgets.QFrame()
        board.setObjectName("Page")
        board_layout = QtWidgets.QVBoxLayout(board)
        board_layout.setContentsMargins(18, 18, 18, 18)
        board_layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)
        title_box = QtWidgets.QVBoxLayout()
        title_box.setSpacing(1)
        self.airport = QtWidgets.QLabel("LOCAL")
        self.airport.setObjectName("FidsAirportCode")
        airport_font = QtGui.QFont("Space Mono")
        airport_font.setPointSize(20 if not embedded else 14)
        airport_font.setBold(True)
        self.airport.setFont(airport_font)
        self.title = QtWidgets.QLabel("Departures")
        self.title.setObjectName("FidsTitle")
        title_font = QtGui.QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        self.title.setFont(title_font)
        if embedded:
            self.airport.hide()
            self.title.hide()
        title_box.addWidget(self.airport)
        title_box.addWidget(self.title)
        header.addLayout(title_box)
        if not embedded:
            header.addStretch(1)
        self.arr_btn = self._segment_button("ARR", "arrivals")
        self.dep_btn = self._segment_button("DEP", "departures")
        self.dep_btn.setChecked(True)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        self.live_dot = label(QtWidgets, chr(9679), "LiveDot")
        self.last_updated = label(QtWidgets, "Airport LT --:--:--", "Muted")
        self.scan_indicator = label(QtWidgets, "", "Dim")
        header.addWidget(self.live_dot)
        header.addWidget(self.last_updated)
        header.addWidget(self.scan_indicator)
        header.addWidget(self.arr_btn)
        header.addWidget(self.dep_btn)
        header.addWidget(refresh)
        if embedded:
            header.addStretch(1)

        self.weather = WeatherStrip(QtWidgets, "Weather loading...")
        self.weather.setMaximumHeight(48 if not embedded else 42)
        self.error_banner = _banner(QtWidgets, "Data fetch error", "ErrorBanner")
        self.info_banner = _banner(
            QtWidgets,
            "Updating the board with the latest airport data...",
            "InfoBanner",
        )
        self.status = label(QtWidgets, "Waiting for first board refresh...", "Muted")

        self.model = FlightBoardModel(QtCore, [], QtGui=QtGui, route_label="To", colors=self.colors)
        self.delegate = _FidsBoardDelegate(QtCore, QtGui, QtWidgets, lambda: self.colors)
        self.board = FidsBoardView(QtCore, QtGui, QtWidgets, lambda: self.colors)
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

        board_layout.addLayout(header)
        board_layout.addWidget(self.weather)
        board_layout.addWidget(self.error_banner)
        board_layout.addWidget(self.info_banner)
        board_layout.addWidget(self.status)
        board_layout.addWidget(self.board, 1)

        self.drawer = self._build_detail_drawer()
        self.drawer.hide()
        self.widget.addWidget(board)
        self.widget.addWidget(self.drawer)
        self.widget.setSizes([940, 340])

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

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
        self.airport.setText(airport)
        if not self.embedded:
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
        self.last_updated.setText(f"{airport} LT " + datetime.now(self.airport_tz).strftime("%H:%M:%S"))
        page_count = max(1, math.ceil(len(self.rows) / max(1, self.row_limit)))
        self.status.setText(f"{len(self.rows)} {view} loaded | {source} source | page 1/{page_count} | airport-local time")
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
        origin = detail.get("origin_iata") or detail.get("origin_icao") or "-"
        dest = detail.get("dest_iata") or detail.get("dest_icao") or "-"
        airline = detail.get("airline_display") or detail.get("airline_name") or ""
        self.detail_route.setText(f"{origin} -> {dest}" + (f" | {airline}" if airline else ""))
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
            "</div>",
        ]
        if virtual:
            parts.append(self._detail_card_html("Virtual Flight", "&#9992;", [
                ("Callsign", detail.get("callsign")),
                ("Flight", detail.get("flight_display") or detail.get("flight_number")),
                ("Aircraft", detail.get("aircraft_type")),
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
                ("Aircraft", detail.get("aircraft_type")),
                ("Registration", detail.get("aircraft_registration")),
                ("Callsign", detail.get("callsign")),
                ("Airline", airline),
                ("Codeshares", ", ".join(detail.get("codeshares") or [])),
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
            ("On ground", value_at(detail, "position.on_ground")),
            ("Squawk", value_at(detail, "position.squawk")),
            ("Last contact", value_at(detail, "position.last_contact")),
        ]
        if not any(format_value(value) for _name, value in rows):
            return ""
        return self._detail_card_html(title, "&#8982;", rows)

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
                ("Aircraft", detail.get("aircraft_type")),
                ("Registration", detail.get("aircraft_registration")),
                ("Callsign", detail.get("callsign")),
                ("Airline", detail.get("airline_display") or detail.get("airline_name") or detail.get("airline_iata")),
                ("Codeshares", ", ".join(detail.get("codeshares") or [])),
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
                ("Aircraft", detail.get("aircraft_type")),
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
    cat = payload.get("flight_cat") or "?"
    temp = payload.get("temperature_c")
    temp_text = f"{temp} C" if temp is not None else "-- C"
    summary = payload.get("decoded_summary") or payload.get("weather_summary") or payload.get("weather_label") or ""
    raw_text = payload.get("raw_text") or payload.get("raw") or ""
    return f"{cat} | {temp_text} | {summary}" + (f" | {raw_text}" if raw and raw_text else "")


def _weather_icon_glyph(icon_name: Any) -> str:
    icon = str(icon_name or "unknown").strip().lower()
    return {
        "sun": chr(0x2600),
        "partly": chr(0x26C5),
        "cloud": chr(0x2601),
        "rain": chr(0x2614),
        "snow": chr(0x2744),
        "fog": chr(0x224B),
        "storm": chr(0x26A1),
        "wind": chr(0x21C1),
        "ice": chr(0x25C7),
        "unknown": chr(0x2022),
    }.get(icon, chr(0x2022))


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
    return [part.strip() for part in re.split(r"[/,;|]+", text) if part.strip()]


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
        f".status.good,.delay-chip.good{{border-color:{_css_rgba(green, 0.55)};background:{_css_rgba(green, 0.14)};color:{green};}}"
        f".status.warn,.delay-chip.warn{{border-color:{_css_rgba(amber, 0.60)};background:{_css_rgba(amber, 0.15)};color:{amber};}}"
        f".status.bad,.delay-chip.bad{{border-color:{_css_rgba(red, 0.60)};background:{_css_rgba(red, 0.15)};color:{red};}}"
        f".status.orange{{border-color:{_css_rgba(orange, 0.60)};background:{_css_rgba(orange, 0.15)};color:{orange};}}"
        f".status.dim,.delay-chip.muted{{border-color:{_css_rgba(dim, 0.45)};background:{_css_rgba(dim, 0.10)};color:{dim};}}"
        f".status.neutral{{border-color:{card_border};background:{chip_bg};color:{blue};}}"
        f".time-strip{{border:1px solid {divider};background:{panel};border-radius:10px;padding:10px 10px 6px 10px;margin:0 0 12px 0;}}"
        f".time-key,.detail-row td:first-child,.route-line span{{color:{muted};font:700 9px 'Space Mono','Consolas',monospace;text-transform:uppercase;letter-spacing:.08em;}}"
        f".time-val,.detail-row b,.route-line b{{color:{text};font-weight:800;}}"
        f".detail-card{{border:1px solid {divider};background:{panel};border-radius:10px;padding:11px;margin:0 0 12px 0;}}"
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
