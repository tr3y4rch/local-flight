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
                panel = QtGui.QColor(colors.get("panel_2", "#0b1118"))
                selected = bool(option.state & QtWidgets.QStyle.State_Selected)
                if selected:
                    selected_color = QtGui.QColor(colors.get("blue", "#4a9eda"))
                    selected_color.setAlpha(66)
                    painter.fillRect(rect, selected_color)
                else:
                    painter.fillRect(rect, panel)
                alpha = int(row.get("_fresh_alpha") or 0)
                if alpha > 0:
                    flash = QtGui.QColor(colors.get("blue", "#4a9eda"))
                    flash.setAlpha(alpha)
                    painter.fillRect(rect, flash)
                status_cls = self._status_class(row)
                if status_cls in {"boarding", "approaching", "delayed", "delayed-warn", "delayed-bad", "early", "diverted", "cancelled"}:
                    accent = QtGui.QColor(self._status_color(row, colors))
                    tint = QtGui.QColor(accent)
                    tint.setAlpha(34 if status_cls in {"delayed", "delayed-warn", "delayed-bad", "early"} else 18)
                    painter.fillRect(rect, tint)
                if key == "display_time" and status_cls in {"boarding", "approaching", "delayed", "delayed-warn", "delayed-bad", "early", "diverted", "cancelled"}:
                    accent = QtGui.QColor(self._status_color(row, colors))
                    painter.setPen(QtCore.Qt.NoPen)
                    painter.setBrush(accent)
                    painter.drawRoundedRect(rect.adjusted(0, 4, -rect.width() + 7, -4), 3, 3)
                line = QtGui.QColor(colors.get("line_soft", "#202a38"))
                painter.setPen(line)
                painter.drawLine(rect.bottomLeft(), rect.bottomRight())

            def _paint_time(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                time_text = str(row.get("time_primary") or "-")
                delay_text = str(row.get("time_delta_label") or "")
                painter.setPen(QtGui.QColor(self._text_color(row, colors)))
                font = QtGui.QFont("Space Mono")
                font.setPointSize(15)
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(rect.adjusted(14, 0, -8, -10 if delay_text else 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, time_text)
                if delay_text:
                    tag_rect = QtCore.QRect(rect.left() + 14, rect.center().y() + 8, 52, 17)
                    delay_color = QtGui.QColor(self._delay_color(row, colors))
                    bg = QtGui.QColor(delay_color)
                    bg.setAlpha(42)
                    painter.setPen(QtGui.QPen(delay_color, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(tag_rect, 4, 4)
                    tag_font = QtGui.QFont("Space Mono")
                    tag_font.setPointSize(8)
                    tag_font.setBold(True)
                    painter.setFont(tag_font)
                    painter.setPen(delay_color)
                    painter.drawText(tag_rect, QtCore.Qt.AlignCenter, delay_text)

            def _paint_flight(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                left = rect.left() + 8
                top = rect.top() + 7
                text = QtGui.QColor(self._text_color(row, colors))
                muted = QtGui.QColor(colors.get("muted", "#9aa3b2"))
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                flight_font = QtGui.QFont("Space Mono")
                flight_font.setPointSize(11)
                flight_font.setBold(True)
                painter.setFont(flight_font)
                painter.setPen(accent)
                painter.drawText(QtCore.QRect(left, top, rect.width() - 14, 18), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, str(row.get("flight_display") or row.get("callsign") or "-"))
                sub_font = QtGui.QFont()
                sub_font.setPointSize(8)
                sub_font.setBold(True)
                painter.setFont(sub_font)
                airline = str(row.get("airline_display") or "")
                codeshare = self._codeshare_frame(row)
                if airline:
                    painter.setPen(muted)
                    painter.drawText(QtCore.QRect(left, top + 19, rect.width() - 14, 14), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, airline.upper())
                if codeshare:
                    code_font = QtGui.QFont("Space Mono")
                    code_font.setPointSize(8)
                    code_font.setBold(True)
                    painter.setFont(code_font)
                    fm = painter.fontMetrics()
                    y = top + 39 if airline else top + 25
                    width = min(rect.width() - 14, max(74, fm.horizontalAdvance(codeshare) + 18))
                    pill = QtCore.QRect(left, y, width, 18)
                    bg = QtGui.QColor(accent)
                    bg.setAlpha(44)
                    painter.setPen(QtGui.QPen(accent, 1))
                    painter.setBrush(bg)
                    painter.drawRoundedRect(pill, 4, 4)
                    painter.setPen(accent)
                    painter.drawText(pill.adjusted(8, 0, -8, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, codeshare)

            def _paint_route(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                primary = str(row.get("route_primary") or row.get("route_display") or "-")
                code = str(row.get("route_caption") or "")
                source_hint = str(row.get("live_hint") or row.get("source_hint") or "")
                left = rect.left() + 10
                top = rect.top() + 8
                primary_font = QtGui.QFont()
                primary_font.setPointSize(10)
                primary_font.setBold(True)
                painter.setFont(primary_font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e6edf5")))
                painter.drawText(QtCore.QRect(left, top, rect.width() - 18, 21), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, primary)
                sub = " | ".join(part for part in (code, source_hint) if part and part not in primary)
                if sub:
                    sub_font = QtGui.QFont("Space Mono")
                    sub_font.setPointSize(8)
                    painter.setFont(sub_font)
                    painter.setPen(QtGui.QColor(colors.get("muted", "#9aa3b2")))
                    painter.drawText(QtCore.QRect(left, top + 24, rect.width() - 18, 16), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, sub.upper())

            def _paint_status(self, painter: Any, rect: Any, row: dict[str, Any], colors: dict[str, str]) -> None:
                row = enrich_presentation_fields(row)
                label_text = str(row.get("status_display") or row.get("status") or "Scheduled").upper()
                color = QtGui.QColor(self._status_color(row, colors))
                bg = QtGui.QColor(color)
                bg.setAlpha(72)
                pill = rect.adjusted(8, 11, -8, -11)
                painter.setPen(QtGui.QPen(color, 2))
                painter.setBrush(bg)
                painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(color)
                dot_size = 7
                painter.drawEllipse(QtCore.QRectF(pill.left() + 10, pill.center().y() - dot_size / 2, dot_size, dot_size))
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
                    self._paint_plain(painter, rect, value, colors, muted=True)
                    return
                pill = rect.adjusted(8, 11, -8, -11)
                accent = QtGui.QColor(colors.get("blue", "#4a9eda"))
                bg = QtGui.QColor(accent)
                bg.setAlpha(58)
                painter.setPen(QtGui.QPen(accent, 1))
                painter.setBrush(bg)
                painter.drawRoundedRect(pill, 7, 7)
                font = QtGui.QFont("Space Mono")
                font.setPointSize(10)
                font.setBold(True)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("text", "#e6edf5")))
                painter.drawText(pill, QtCore.Qt.AlignCenter, value)

            def _paint_plain(self, painter: Any, rect: Any, text: Any, colors: dict[str, str], *, muted: bool = False) -> None:
                font = QtGui.QFont()
                font.setPointSize(10)
                painter.setFont(font)
                painter.setPen(QtGui.QColor(colors.get("muted" if muted else "text", "#e6edf5")))
                painter.drawText(rect.adjusted(8, 0, -8, 0), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, str(text))

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
        airport_font.setPointSize(24 if not embedded else 14)
        airport_font.setBold(True)
        self.airport.setFont(airport_font)
        self.title = QtWidgets.QLabel("Departures")
        self.title.setObjectName("FidsTitle")
        title_font = QtGui.QFont()
        title_font.setPointSize(13)
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
        header.addWidget(self.live_dot)
        header.addWidget(self.last_updated)
        header.addWidget(self.arr_btn)
        header.addWidget(self.dep_btn)
        header.addWidget(refresh)
        if embedded:
            header.addStretch(1)

        self.weather = WeatherStrip(QtWidgets, "Weather loading...")
        self.error_banner = _banner(QtWidgets, "Data fetch error", "ErrorBanner")
        self.info_banner = _banner(
            QtWidgets,
            "Updating the board with the latest airport data...",
            "InfoBanner",
        )
        self.status = label(QtWidgets, "Waiting for first board refresh...", "Muted")

        self.model = FlightBoardModel(QtCore, [], QtGui=QtGui, route_label="To", colors=self.colors)
        self.table = QtWidgets.QTableView()
        self.table.setObjectName("FidsTable")
        self.table.setModel(self.model)
        self.table.setMouseTracking(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.clicked.connect(self._show_detail_for_index)
        self.table.setWordWrap(True)
        self.table.setShowGrid(False)
        self.table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.table.horizontalHeader().setMinimumSectionSize(64)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setStyleSheet(self._table_stylesheet())
        self.delegate = _FidsBoardDelegate(QtCore, QtGui, QtWidgets, lambda: self.colors)
        self.table.setItemDelegate(self.delegate)

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
        board_layout.addWidget(self.table, 1)

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
        self.table.setStyleSheet(self._table_stylesheet())
        self._render_rows()

    def _table_stylesheet(self) -> str:
        line = self.colors.get("line", "#263244")
        panel = self.colors.get("panel_2", "#151923")
        text = self.colors.get("text", "#e6edf5")
        muted = self.colors.get("muted", "#9aa3b2")
        blue = self.colors.get("blue", "#4a9eda")
        return f"""
QTableView#FidsTable {{
  background: {panel};
  alternate-background-color: {panel};
  border: 1px solid {line};
  border-radius: 12px;
  selection-background-color: {_css_rgba(blue, 0.24)};
  selection-color: {text};
  outline: 0;
}}
QTableView#FidsTable::item {{
  padding: 7px 10px;
  border-bottom: 1px solid {_css_rgba(line, 0.68)};
}}
QTableView#FidsTable::item:hover {{
  background: {_css_rgba(blue, 0.10)};
}}
QHeaderView::section {{
  background: {panel};
  color: {muted};
  border: none;
  border-bottom: 1px solid {line};
  padding: 8px 10px;
  font-family: "Space Mono", Consolas, monospace;
  font-size: 10px;
  font-weight: 800;
}}
"""

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
        elif len(self.rows) > self.row_limit:
            self.page_timer.start(self.rotation_seconds * 1000)
            self._sync_codeshare_animation()
        else:
            self._sync_codeshare_animation()

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
        progress = self.info_banner.findChild(self.QtWidgets.QProgressBar, "LoadingProgress")
        if progress is not None:
            progress.setVisible(bool(busy and visible))
        self.info_banner.setVisible(visible)

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
        self._fit_columns()

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
        available = max(640, self.table.viewport().width() - 18)
        compact = available < 760
        time_w = 98 if compact else 112
        gate_w = 82 if compact else 104
        status_w = 118 if compact else 146
        ac_w = 0 if compact else 74
        route_w = max(170, int(available * (0.34 if compact else 0.32)))
        flight_w = max(150, available - time_w - gate_w - status_w - ac_w - route_w)
        self.table.setColumnWidth(0, time_w)
        self.table.setColumnWidth(1, flight_w)
        self.table.setColumnWidth(2, route_w)
        self.table.setColumnWidth(3, gate_w)
        self.table.setColumnWidth(4, status_w)
        self.table.setColumnHidden(5, compact)
        if not compact:
            self.table.setColumnWidth(5, ac_w)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row_idx, row in enumerate(self.visible_rows):
            if row.get("_codeshare_frames"):
                height = 70
            elif row.get("airline_display"):
                height = 62
            else:
                height = 48
            self.table.setRowHeight(row_idx, height)
        self._sync_codeshare_animation()

    def _mark_rows_fresh(self) -> None:
        self._flash_started = time.monotonic()
        for row in self.rows:
            row["_fresh"] = True
            row["_fresh_alpha"] = 34
        self._render_rows()
        self.flash_timer.start()

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
        sections = self._virtual_detail_sections(detail) if virtual else self._real_detail_sections(detail)
        parts = [
            _detail_css(self.colors),
            f"<div class='section'><div class='label'>{self._h(title)}</div>",
        ]
        headline = detail.get("flight_display") or detail.get("flight_number") or detail.get("callsign") or ""
        status = detail.get("status_display") or detail.get("status") or ""
        if headline or status:
            parts.append(f"<div class='row'><span class='key'>Flight</span><span class='val'>{self._h(headline)}</span></div>")
            parts.append(f"<div class='row'><span class='key'>Status</span><span class='val'>{self._h(status)}</span></div>")
        parts.append("</div>")
        for heading, fields in sections:
            rows = [(name, format_value(value)) for name, value in fields if format_value(value)]
            if not rows:
                continue
            if heading.lower().startswith("source"):
                parts.append("<div class='section'><div class='label'>Data Sources</div><div class='cards'>")
                for name, value in rows:
                    parts.append(f"<div class='card'><div class='key'>{self._h(name)}</div><div class='val'>{self._h(value)}</div></div>")
                parts.append("</div></div>")
                continue
            parts.append(f"<div class='section'><div class='label'>{self._h(heading)}</div>")
            for name, value in rows:
                parts.append(f"<div class='row'><span class='key'>{self._h(name)}</span><span class='val'>{self._h(value)}</span></div>")
            parts.append("</div>")
        parts.append(self._history_html(history))
        return "".join(parts)

    def _history_html(self, history: list[dict[str, Any]]) -> str:
        if not history:
            return "<div class='section'><div class='label'>Recent History (7 days)</div><div class='muted'>No history yet.</div></div>"
        parts = ["<div class='section'><div class='label'>Recent History (7 days)</div>"]
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
            parts.append(f"<div class='history'><span>{self._h(date)} - {self._h(status)}</span><span class='{cls}'>{self._h(delay_text)}</span></div>")
        parts.append("</div>")
        return "".join(parts)

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
    divider = "rgba(0,0,0,.08)" if is_light else "rgba(255,255,255,.045)"
    card_bg = _css_rgba(colors.get("blue", "#4a9eda"), 0.10 if is_light else 0.08)
    card_border = _css_rgba(colors.get("blue", "#4a9eda"), 0.28 if is_light else 0.22)
    return (
        "<style>"
        f"body{{font-family:'DM Sans','Segoe UI','Helvetica Neue',sans-serif;color:{colors['text']};background:{colors['panel_2']};}}"
        f".section{{margin:0 0 16px 0;padding:0 0 12px 0;border-bottom:1px solid {divider};}}"
        f".label{{font:700 10px 'Space Mono','Consolas',monospace;letter-spacing:.12em;text-transform:uppercase;color:{colors['dim']};margin:0 0 9px 0;}}"
        f".row{{display:flex;justify-content:space-between;gap:14px;padding:5px 0;border-bottom:1px solid {divider};}}"
        ".row:last-child{border-bottom:0;}"
        f".key{{color:{colors['muted']};}}"
        f".val{{color:{colors['text']};font-weight:700;text-align:right;}}"
        ".cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;}"
        f".card{{border:1px solid {card_border};background:{card_bg};border-radius:10px;padding:10px;}}"
        ".card .key{font:700 10px 'Space Mono','Consolas',monospace;text-transform:uppercase;letter-spacing:.08em;}"
        ".history{display:flex;justify-content:space-between;gap:12px;padding:6px 0;}"
        f".good{{color:{colors['green']}}}.warn{{color:{colors['amber']}}}.bad{{color:{colors['red']}}}.muted{{color:{colors['muted']}}}"
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
