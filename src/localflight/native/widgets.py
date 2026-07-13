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


class NoticeBanner:
    """Accessible, reusable renderer for the shared client notice contract."""

    def __new__(cls, QtWidgets: Any):
        frame = QtWidgets.QFrame()
        frame.setObjectName("NoticeBanner")
        layout = QtWidgets.QVBoxLayout(frame)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        message = label(QtWidgets, "", "Metric", wrap=True)
        next_step = label(QtWidgets, "", "Muted", wrap=True)
        layout.addWidget(message)
        layout.addWidget(next_step)
        frame.message_label = message
        frame.next_step_label = next_step

        def set_notices(notices: Any) -> None:
            rows = notices if isinstance(notices, list) else []
            notice = next((item for item in rows if isinstance(item, dict) and item.get("message")), None)
            if notice is None:
                frame.hide()
                return
            tone = str(notice.get("tone") or "info")
            if tone not in {"info", "success", "warning", "error"}:
                tone = "info"
            message.setText(str(notice.get("message") or "Local Flight status update"))
            next_text = str(notice.get("next_step") or "")
            next_step.setText(next_text)
            next_step.setVisible(bool(next_text))
            frame.setProperty("tone", tone)
            frame.setAccessibleName("Local Flight notice")
            frame.setAccessibleDescription(" ".join(part for part in (message.text(), next_text) if part))
            try:
                frame.style().unpolish(frame)
                frame.style().polish(frame)
            except Exception:
                pass
            frame.show()

        frame.set_notices = set_notices
        frame.hide()
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


class DisclosureCard:
    """A collapsible section presented as a clickable card.

    Replaces the bland ``QGroupBox(setCheckable=True)`` pattern: the whole
    header bar acts as the toggle, shows an emoji, a bold title and a
    one-line subtitle (visible even when collapsed), and a chevron that
    flips between ``▸`` and ``▾``.

    Usage::

        card = DisclosureCard(QtCore, QtWidgets, title="Relay details",
                              subtitle="Status of the optional relay link.",
                              emoji="🔗")
        card.body_layout.addWidget(...)
        parent_layout.addWidget(card)

    The hosted content is added to ``card.body_layout`` (a ``QVBoxLayout``).
    Call ``card.set_expanded(True/False)`` to drive it programmatically, or
    let the user click the header.
    """

    def __new__(
        cls,
        QtCore: Any,
        QtWidgets: Any,
        *,
        title: str,
        subtitle: str = "",
        emoji: str = "",
        expanded: bool = False,
    ):
        frame = QtWidgets.QFrame()
        frame.setObjectName("DisclosureCard")
        frame.setProperty("expanded", False)
        outer = QtWidgets.QVBoxLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- Header (clickable bar) -----------------------------------
        header = QtWidgets.QFrame()
        header.setObjectName("DisclosureHeader")
        header.setCursor(QtCore.Qt.PointingHandCursor)
        header.setProperty("expanded", False)
        row = QtWidgets.QHBoxLayout(header)
        row.setContentsMargins(16, 12, 14, 12)
        row.setSpacing(12)

        emoji_label = QtWidgets.QLabel(emoji or "•")
        emoji_label.setObjectName("DisclosureEmoji")
        emoji_label.setFixedWidth(24)
        emoji_label.setAlignment(QtCore.Qt.AlignCenter)

        text_box = QtWidgets.QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(1)
        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("DisclosureTitle")
        subtitle_label = QtWidgets.QLabel(subtitle)
        subtitle_label.setObjectName("DisclosureSubtitle")
        subtitle_label.setWordWrap(True)
        if not subtitle:
            subtitle_label.hide()
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)

        chevron = QtWidgets.QLabel("▸")  # ▸
        chevron.setObjectName("DisclosureChevron")
        chevron.setAlignment(QtCore.Qt.AlignCenter)
        chevron.setFixedWidth(22)

        row.addWidget(emoji_label, 0, QtCore.Qt.AlignVCenter)
        row.addLayout(text_box, 1)
        row.addWidget(chevron, 0, QtCore.Qt.AlignVCenter)

        outer.addWidget(header)

        # ---- Body (revealed on expand) --------------------------------
        body = QtWidgets.QFrame()
        body.setObjectName("DisclosureBody")
        body_layout = QtWidgets.QVBoxLayout(body)
        body_layout.setContentsMargins(18, 4, 18, 16)
        body_layout.setSpacing(10)
        body.setVisible(False)
        outer.addWidget(body)

        # ---- Toggle plumbing ------------------------------------------
        expanded_state = False

        def _apply_state(expanded_now: bool) -> None:
            nonlocal expanded_state
            expanded_state = bool(expanded_now)
            body.setVisible(expanded_state)
            chevron.setText("▾" if expanded_state else "▸")  # ▾ / ▸
            for widget in (frame, header):
                widget.setProperty("expanded", expanded_state)
                style = widget.style()
                style.unpolish(widget)
                style.polish(widget)
            frame.update()

        def _toggle() -> None:
            _apply_state(not expanded_state)

        def _set_expanded(value: bool) -> None:
            _apply_state(bool(value))

        def _is_expanded() -> bool:
            return expanded_state

        def _set_subtitle(text: str) -> None:
            subtitle_label.setText(text)
            subtitle_label.setVisible(bool(text))

        def _set_title(text: str) -> None:
            title_label.setText(text)

        # Whole header bar (and any child label) is a single click target.
        def _press_handler(event: Any) -> None:
            if event.button() == QtCore.Qt.LeftButton:
                _toggle()
                event.accept()
                return
            QtWidgets.QFrame.mousePressEvent(header, event)

        header.mousePressEvent = _press_handler  # type: ignore[assignment]
        # Forward clicks from child labels too (they sit on top of the header).
        for child in (emoji_label, title_label, subtitle_label, chevron):
            child.mousePressEvent = _press_handler  # type: ignore[assignment]

        # ---- Public API attached on the frame instance ----------------
        frame.toggle = _toggle
        frame.set_expanded = _set_expanded
        frame.is_expanded = _is_expanded
        # Compatibility with the older checkable QGroupBox sections.
        frame.setChecked = _set_expanded
        frame.isChecked = _is_expanded
        frame.set_subtitle = _set_subtitle
        frame.set_title = _set_title
        frame.body_layout = body_layout
        frame.body = body
        frame.header = header
        frame.title_label = title_label
        frame.subtitle_label = subtitle_label
        frame.chevron = chevron

        _apply_state(bool(expanded))
        return frame


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
