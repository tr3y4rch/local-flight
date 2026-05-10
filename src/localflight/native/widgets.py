"""Reusable Qt widgets for the native-first redesign."""
from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable

from localflight.native.async_tools import API_EXECUTOR
from localflight.native.design import card, label


class StatusCard:
    def __new__(cls, QtWidgets: Any, title: str, value: Any = "-", detail: str = ""):
        return card(QtWidgets, title, value, detail)


class WeatherStrip:
    def __new__(cls, QtWidgets: Any, text: str = "Weather loading..."):
        frame = QtWidgets.QFrame()
        frame.setObjectName("WeatherStrip")
        layout = QtWidgets.QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        icon = label(QtWidgets, "", "Metric")
        body = label(QtWidgets, text, "Muted", wrap=True)
        frame.icon_label = icon
        frame.body_label = body
        layout.addWidget(icon)
        layout.addWidget(body, 1)

        def set_weather(next_text: str, glyph: str = "") -> None:
            icon.setText(glyph)
            body.setText(next_text)

        frame.set_weather = set_weather
        return frame


class DetailDrawer:
    def __new__(cls, QtWidgets: Any, title: str = "Detail"):
        drawer = QtWidgets.QFrame()
        drawer.setObjectName("Drawer")
        drawer.setMinimumWidth(280)
        drawer.setMaximumWidth(460)
        layout = QtWidgets.QVBoxLayout(drawer)
        layout.setContentsMargins(16, 16, 16, 16)
        head = QtWidgets.QHBoxLayout()
        title_label = label(QtWidgets, title, "Title")
        close = QtWidgets.QPushButton("Close")
        close.setObjectName("Quiet")
        close.clicked.connect(drawer.hide)
        body = QtWidgets.QTextEdit()
        body.setReadOnly(True)
        head.addWidget(title_label, 1)
        head.addWidget(close)
        layout.addLayout(head)
        layout.addWidget(body, 1)
        drawer.title_label = title_label
        drawer.body = body
        drawer.close_button = close
        return drawer


class AirportSearchBox:
    """Compact reusable airport picker with debounced local API search."""

    def __new__(
        cls,
        QtCore: Any,
        QtWidgets: Any,
        *,
        search: Callable[[str], Any],
        on_select: Callable[[dict[str, Any]], None],
        placeholder: str = "Search airport, city, IATA, or ICAO...",
    ):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        line = QtWidgets.QLineEdit()
        line.setPlaceholderText(placeholder)
        results = QtWidgets.QListWidget()
        results.setMaximumHeight(160)
        status = label(QtWidgets, "", "Muted", wrap=True)
        layout.addWidget(line)
        layout.addWidget(results)
        layout.addWidget(status)
        widget.line_edit = line
        widget.results = results
        widget.status_label = status
        widget._future: Future[Any] | None = None
        widget._last_query = ""

        timer = QtCore.QTimer(widget)
        timer.setSingleShot(True)
        poll = QtCore.QTimer(widget)
        poll.setInterval(50)
        widget.search_timer = timer
        widget.search_poll_timer = poll

        def start_search() -> None:
            query = line.text().strip()
            if len(query) < 2:
                results.clear()
                status.setText("")
                return
            key = query.casefold()
            if key == widget._last_query:
                return
            if widget._future is not None and not widget._future.done():
                return
            widget._last_query = key
            results.clear()
            results.addItem("Searching airports...")
            widget._future = API_EXECUTOR.submit(lambda: search(query))
            poll.start()

        def poll_search() -> None:
            future = widget._future
            if future is None or not future.done():
                return
            poll.stop()
            widget._future = None
            try:
                payload = future.result()
            except Exception as exc:
                results.clear()
                results.addItem(f"Search failed: {exc}")
                return
            rows = payload if isinstance(payload, list) else payload.get("results", payload.get("airports", [])) if isinstance(payload, dict) else []
            results.clear()
            if not rows:
                results.addItem("No airport matches found.")
                return
            for row in rows:
                if not isinstance(row, dict):
                    continue
                item = QtWidgets.QListWidgetItem(
                    f"{row.get('iata') or '---'} / {row.get('icao') or '----'}  {row.get('name') or ''} - {row.get('city') or ''}"
                )
                item.setData(QtCore.Qt.UserRole, row)
                results.addItem(item)

        def select_item(item: Any) -> None:
            row = item.data(QtCore.Qt.UserRole)
            if isinstance(row, dict):
                on_select(row)

        line.textChanged.connect(lambda _text: timer.start(250))
        timer.timeout.connect(start_search)
        poll.timeout.connect(poll_search)
        results.itemClicked.connect(select_item)
        return widget
