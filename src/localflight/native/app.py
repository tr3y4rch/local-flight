"""Prototype native Local Flight user UI.

This is intentionally a Qt Widgets shell, not a webview. It consumes the same
local FastAPI contracts as the browser/mobile clients while the full native UI
is built out screen by screen.
"""
from __future__ import annotations

import json
import math
import sys
import webbrowser
from typing import Any

from localflight.native.api_client import LocalApiClient, NativeApiError
from localflight.native.qt_compat import import_qt


def main() -> None:
    try:
        code = launch_native_app(base_url="http://127.0.0.1:8000", first_launch=False)
    except Exception as exc:
        print(f"Local Flight native UI unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(code)


def is_native_available() -> bool:
    try:
        import_qt()
        return True
    except Exception:
        return False


class _BaseScreen:
    def refresh(self) -> None:  # pragma: no cover - Qt runtime method
        return


def launch_native_app(
    *,
    base_url: str,
    first_launch: bool,
    fullscreen: bool = False,
) -> int:
    QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("Local Flight")
    window = NativeMainWindow(QtCore, QtGui, QtWidgets, base_url=base_url, first_launch=first_launch)
    if fullscreen:
        window.showFullScreen()
    else:
        window.resize(1280, 820)
        window.show()
    return int(app.exec())


class NativeMainWindow:  # pragma: no cover - exercised manually with optional Qt
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any, *, base_url: str, first_launch: bool):
        class _Window(QtWidgets.QMainWindow):
            def __init__(self) -> None:
                super().__init__()
                self.QtCore = QtCore
                self.QtGui = QtGui
                self.QtWidgets = QtWidgets
                self.client = LocalApiClient(base_url=base_url)
                self.setWindowTitle("Local Flight Native")
                self.setStyleSheet(_STYLE)

                root = QtWidgets.QWidget()
                layout = QtWidgets.QHBoxLayout(root)
                layout.setContentsMargins(12, 12, 12, 12)
                layout.setSpacing(12)

                self.nav = QtWidgets.QListWidget()
                self.nav.setFixedWidth(170)
                self.stack = QtWidgets.QStackedWidget()
                layout.addWidget(self.nav)
                layout.addWidget(self.stack, 1)
                self.setCentralWidget(root)

                self.screens: list[Any] = []
                self._add_screen("Setup" if first_launch else "FIDS", SetupScreen(QtWidgets, self.client, base_url) if first_launch else FidsScreen(QtCore, QtWidgets, self.client))
                self._add_screen("Radar", RadarScreen(QtCore, QtGui, QtWidgets, self.client))
                self._add_screen("Display", DisplayScreen(QtWidgets, self.client))
                self._add_screen("History", JsonScreen(QtWidgets, self.client, "History", "/api/history"))
                self._add_screen("Settings", JsonScreen(QtWidgets, self.client, "Settings", "/api/config"))
                self._add_screen("Admin", AdminSummaryScreen(QtWidgets, self.client))
                self._add_screen("Feedback", FeedbackScreen(QtWidgets, self.client))

                self.nav.currentRowChanged.connect(self._switch)
                self.nav.setCurrentRow(0)
                self.timer = QtCore.QTimer(self)
                self.timer.timeout.connect(self._refresh_active)
                self.timer.start(15_000)

            def _add_screen(self, label: str, screen: Any) -> None:
                self.nav.addItem(label)
                self.stack.addWidget(getattr(screen, "widget", screen))
                self.screens.append(screen)

            def _switch(self, index: int) -> None:
                if index < 0:
                    return
                self.stack.setCurrentIndex(index)
                self._refresh_active()

            def _refresh_active(self) -> None:
                index = self.stack.currentIndex()
                screen = self.screens[index] if 0 <= index < len(self.screens) else self.stack.currentWidget()
                if hasattr(screen, "refresh"):
                    screen.refresh()

        return _Window()


class SetupScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient, base_url: str) -> None:
        self.widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.widget)
        title = QtWidgets.QLabel("First-run setup")
        title.setObjectName("Title")
        body = QtWidgets.QLabel(
            "Native setup is staged for the Chrome-free UI migration. "
            "For this beta step, finish setup through the local web fallback, "
            "then return here for native FIDS/Radar testing."
        )
        body.setWordWrap(True)
        button = QtWidgets.QPushButton("Open setup fallback")
        button.clicked.connect(lambda: webbrowser.open(f"{base_url.rstrip('/')}/setup"))
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addWidget(button)
        layout.addStretch(1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)


class FidsScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtWidgets: Any, client: LocalApiClient) -> None:
        self.QtWidgets = QtWidgets
        self.client = client
        self.widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.widget)
        top = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("Departures")
        self.title.setObjectName("Title")
        self.toggle = QtWidgets.QComboBox()
        self.toggle.addItems(["departures", "arrivals"])
        self.toggle.currentTextChanged.connect(lambda _text: self.refresh())
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.toggle)
        self.weather = QtWidgets.QLabel("Weather loading...")
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Time", "Flight", "Airline", "Route", "Status", "A/C", "Codeshares"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        layout.addLayout(top)
        layout.addWidget(self.weather)
        layout.addWidget(self.table, 1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        view = self.toggle.currentText()
        try:
            weather = self.client.get_json("/api/metar")
            payload = self.client.get_json("/api/fids", params={"view": view, "limit": 40})
        except NativeApiError as exc:
            self.weather.setText(f"Offline: {exc}")
            return
        self.title.setText(view.title())
        self.weather.setText(_weather_line(weather))
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        self.table.setRowCount(len(rows))
        for row_idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            values = [
                row.get("time") or row.get("display_time") or "",
                row.get("flight_display") or row.get("callsign") or "",
                row.get("airline_display") or row.get("airline") or "",
                row.get("route") or row.get("destination") or row.get("origin") or "",
                row.get("status") or "",
                row.get("aircraft") or row.get("aircraft_type") or "",
                row.get("codeshare_display") or "",
            ]
            for col_idx, value in enumerate(values):
                self.table.setItem(row_idx, col_idx, self.table_item(str(value)))
        self.table.resizeColumnsToContents()

    def table_item(self, text: str) -> Any:
        item = self.QtWidgets.QTableWidgetItem(text)
        item.setToolTip(text)
        return item


class RadarCanvas:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any):
        class _Canvas(QtWidgets.QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.setMinimumSize(320, 320)
                self.blips: list[dict[str, Any]] = []
                self.radius_nm = 5.0
                self.status = "No radar data yet"

            def set_payload(self, payload: dict[str, Any]) -> None:
                self.blips = [b for b in payload.get("blips", []) if isinstance(b, dict)]
                self.radius_nm = float(payload.get("radius_nm") or self.radius_nm)
                self.status = f"{len(self.blips)} blips | {payload.get('source', 'unknown')}"
                self.update()

            def paintEvent(self, _event: Any) -> None:
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                rect = self.rect()
                size = min(rect.width(), rect.height()) - 12
                cx = rect.center().x()
                cy = rect.center().y()
                radius = size / 2
                painter.fillRect(rect, QtGui.QColor("#071018"))
                pen = QtGui.QPen(QtGui.QColor("#2b6c92"), 1)
                painter.setPen(pen)
                for frac in (0.25, 0.5, 0.75, 1.0):
                    r = radius * frac
                    painter.drawEllipse(QtCore.QPointF(cx, cy), r, r)
                painter.drawLine(cx - radius, cy, cx + radius, cy)
                painter.drawLine(cx, cy - radius, cx, cy + radius)
                painter.setPen(QtGui.QPen(QtGui.QColor("#7ce7ff"), 2))
                for blip in self.blips:
                    dist = float(blip.get("distance_nm") or 0.0)
                    bearing = math.radians(float(blip.get("bearing_deg") or 0.0))
                    frac = min(1.0, dist / max(0.1, self.radius_nm))
                    x = cx + math.sin(bearing) * radius * frac
                    y = cy - math.cos(bearing) * radius * frac
                    painter.drawEllipse(QtCore.QPointF(x, y), 4, 4)
                painter.setPen(QtGui.QColor("#8fb7c8"))
                painter.drawText(14, rect.height() - 14, self.status)

        return _Canvas()


class RadarScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient) -> None:
        self.client = client
        self.widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.widget)
        top = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLabel("Radar")
        self.title.setObjectName("Title")
        self.radius = QtWidgets.QComboBox()
        self.radius.addItems(["1", "2", "3", "5", "10", "20", "40"])
        self.radius.setCurrentText("5")
        self.radius.currentTextChanged.connect(lambda _text: self.refresh())
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(QtWidgets.QLabel("Range NM"))
        top.addWidget(self.radius)
        self.canvas = RadarCanvas(QtCore, QtGui, QtWidgets)
        self.status = QtWidgets.QLabel("Radar loading...")
        layout.addLayout(top)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.status)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        try:
            payload = self.client.get_json("/api/radar", params={"radius_nm": float(self.radius.currentText())})
        except NativeApiError as exc:
            self.status.setText(f"Offline: {exc}")
            return
        self.canvas.set_payload(payload)
        self.status.setText(
            f"{payload.get('count', 0)} visible | mode {payload.get('radar_mode', 'airborne')} | source {payload.get('source', 'unknown')}"
        )


class JsonScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient, title: str, path: str) -> None:
        self.client = client
        self.path = path
        self.widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.widget)
        label = QtWidgets.QLabel(title)
        label.setObjectName("Title")
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(label)
        layout.addWidget(self.text, 1)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        try:
            payload = self.client.get_json(self.path)
        except NativeApiError as exc:
            self.text.setPlainText(f"Offline: {exc}")
            return
        self.text.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))


class AdminSummaryScreen(JsonScreen):  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        super().__init__(QtWidgets, client, "User Admin Summary", "/api/admin/system")

    def refresh(self) -> None:
        try:
            payload = {
                "system": self.client.get_json("/api/admin/system"),
                "budget": self.client.get_json("/api/admin/budget"),
                "connections": self.client.get_json("/api/admin/connections"),
                "scheduler": self.client.get_json("/api/admin/scheduler"),
            }
        except NativeApiError as exc:
            self.text.setPlainText(f"Offline: {exc}")
            return
        self.text.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))


class DisplayScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.widget = QtWidgets.QSplitter()
        self.fids = JsonScreen(QtWidgets, client, "Display FIDS", "/api/fids")
        self.radar = JsonScreen(QtWidgets, client, "Display Radar", "/api/radar")
        self.widget.addWidget(self.fids)
        self.widget.addWidget(self.radar)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def refresh(self) -> None:
        self.fids.refresh()
        self.radar.refresh()


class FeedbackScreen:  # pragma: no cover - optional Qt runtime
    def __init__(self, QtWidgets: Any, client: LocalApiClient) -> None:
        self.client = client
        self.widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(self.widget)
        title = QtWidgets.QLabel("Feedback")
        title.setObjectName("Title")
        self.summary = QtWidgets.QLineEdit()
        self.summary.setPlaceholderText("Short title")
        self.body = QtWidgets.QPlainTextEdit()
        self.body.setPlaceholderText("What happened?")
        self.status = QtWidgets.QLabel("Manual reports are sanitized by the local server before forwarding.")
        send = QtWidgets.QPushButton("Send report")
        send.clicked.connect(self.send)
        layout.addWidget(title)
        layout.addWidget(self.summary)
        layout.addWidget(self.body, 1)
        layout.addWidget(send)
        layout.addWidget(self.status)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def send(self) -> None:
        try:
            self.client.post_json(
                "/api/feedback",
                {
                    "title": self.summary.text().strip() or "Native UI feedback",
                    "description": self.body.toPlainText().strip(),
                    "client_context": "native/gui; screen=feedback",
                },
            )
        except NativeApiError as exc:
            self.status.setText(f"Report failed: {exc}")
            return
        self.status.setText("Report sent.")


def _weather_line(payload: dict[str, Any]) -> str:
    icon = payload.get("weather_icon") or ""
    temp = payload.get("temperature_c")
    summary = payload.get("weather_summary") or payload.get("raw") or "Weather unavailable"
    temp_text = f"{temp} C" if temp is not None else "-- C"
    return f"{icon} {temp_text} | {summary}".strip()


_STYLE = """
QWidget {
  background: #071018;
  color: #dcebf5;
  font-family: "Segoe UI", "Helvetica Neue", sans-serif;
  font-size: 13px;
}
QLabel#Title {
  font-size: 24px;
  font-weight: 800;
  color: #f5fbff;
}
QListWidget, QTableWidget, QPlainTextEdit, QLineEdit, QComboBox {
  background: #0b1722;
  border: 1px solid #1e3a54;
  border-radius: 8px;
  color: #dcebf5;
}
QListWidget::item {
  padding: 10px;
}
QListWidget::item:selected {
  background: #16405f;
}
QHeaderView::section {
  background: #102638;
  color: #9cc9df;
  border: none;
  padding: 6px;
}
QPushButton {
  background: #16405f;
  border: 1px solid #2f6e9a;
  border-radius: 8px;
  padding: 8px 12px;
  color: #f5fbff;
}
"""


if __name__ == "__main__":  # pragma: no cover - manual Qt entrypoint
    main()
