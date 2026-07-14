"""Qt-native taskbar, Dock, and status-menu integration."""
from __future__ import annotations

import sys
from typing import Any, Callable

from localflight.native.design import colors_for


STATUS_PAGE_ACTIONS: tuple[tuple[str, str], ...] = (
    ("Display", "display"),
    ("FIDS board", "fids"),
    ("Radar", "radar"),
    ("History", "history"),
    ("Settings", "settings"),
)


def _connect(action: Any, callback: Callable[[], None]) -> None:
    action.triggered.connect(lambda _checked=False: callback())


def _status_icon(
    QtCore: Any,
    QtGui: Any,
    *,
    theme: str,
    skin: str,
    status: str,
) -> Any:
    """Draw a legible small radar/aircraft mark without shrinking the app tile."""
    colors = colors_for(theme, skin)
    size = 64
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    if sys.platform == "darwin":
        foreground = QtGui.QColor("#000000")
        painter.setPen(QtGui.QPen(foreground, 4.0))
        painter.drawEllipse(QtCore.QRectF(8, 8, 48, 48))
        painter.setPen(QtGui.QPen(foreground, 3.0))
        painter.drawLine(QtCore.QPointF(32, 12), QtCore.QPointF(32, 52))
        painter.setBrush(foreground)
        painter.setPen(QtCore.Qt.NoPen)
    else:
        painter.setBrush(QtGui.QColor("#09131d"))
        painter.setPen(QtGui.QPen(QtGui.QColor(colors["blue"]), 3.5))
        painter.drawEllipse(QtCore.QRectF(5, 5, 54, 54))
        painter.setPen(QtGui.QPen(QtGui.QColor(colors["line"]), 2.0))
        painter.drawLine(QtCore.QPointF(32, 8), QtCore.QPointF(32, 56))
        painter.setBrush(QtGui.QColor("#f8fbff"))
        painter.setPen(QtCore.Qt.NoPen)

    aircraft = QtGui.QPolygonF(
        [
            QtCore.QPointF(32, 11),
            QtCore.QPointF(37, 28),
            QtCore.QPointF(53, 34),
            QtCore.QPointF(52, 39),
            QtCore.QPointF(36, 36),
            QtCore.QPointF(36, 49),
            QtCore.QPointF(42, 54),
            QtCore.QPointF(40, 57),
            QtCore.QPointF(32, 53),
            QtCore.QPointF(24, 57),
            QtCore.QPointF(22, 54),
            QtCore.QPointF(28, 49),
            QtCore.QPointF(28, 36),
            QtCore.QPointF(12, 39),
            QtCore.QPointF(11, 34),
            QtCore.QPointF(27, 28),
        ]
    )
    painter.drawPolygon(aircraft)

    if sys.platform != "darwin":
        status_color = {
            "ready": colors["green"],
            "reconnecting": colors["amber"],
            "offline": colors["red"],
        }.get(status, colors["dim"])
        painter.setBrush(QtGui.QColor(status_color))
        painter.setPen(QtGui.QPen(QtGui.QColor("#09131d"), 2.0))
        painter.drawEllipse(QtCore.QRectF(45, 5, 14, 14))
    painter.end()

    icon = QtGui.QIcon(pixmap)
    if sys.platform == "darwin" and hasattr(icon, "setIsMask"):
        icon.setIsMask(True)
    return icon


class NativeStatusTray:
    """Own the platform status icon and the shared Dock/context menu."""

    def __init__(
        self,
        QtCore: Any,
        QtGui: Any,
        QtWidgets: Any,
        app: Any,
        *,
        app_icon: Any,
        on_show: Callable[[], None],
        on_page: Callable[[str], None],
        on_open_browser: Callable[[], None],
        on_restart: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.app = app
        self.theme = "dark"
        self.skin = "standard"
        self.status = "ready"
        self.available = bool(QtWidgets.QSystemTrayIcon.isSystemTrayAvailable())

        self.menu = QtWidgets.QMenu()
        title = self.menu.addAction(app_icon, "Local Flight")
        title.setEnabled(False)
        self.menu.addSeparator()

        self.show_action = self.menu.addAction("Show Local Flight")
        _connect(self.show_action, on_show)
        self.menu.addSeparator()
        self.page_actions: dict[str, Any] = {}
        for action_label, page_key in STATUS_PAGE_ACTIONS:
            action = self.menu.addAction(action_label)
            _connect(action, lambda key=page_key: on_page(key))
            self.page_actions[page_key] = action

        self.menu.addSeparator()
        browser_action = self.menu.addAction("Open LAN browser")
        _connect(browser_action, on_open_browser)
        restart_action = self.menu.addAction("Restart flight updates")
        _connect(restart_action, on_restart)
        self.menu.addSeparator()
        quit_action = self.menu.addAction("Quit Local Flight")
        _connect(quit_action, on_quit)

        if sys.platform == "darwin":
            set_as_dock_menu = getattr(self.menu, "setAsDockMenu", None)
            if callable(set_as_dock_menu):
                set_as_dock_menu()

        self.tray = QtWidgets.QSystemTrayIcon(app)
        self.tray.setContextMenu(self.menu)
        self.tray.setToolTip("Local Flight")
        self.tray.activated.connect(self._activated)
        self._refresh_icon()
        if self.available:
            self.tray.show()

    def _activated(self, reason: Any) -> None:
        activation_reason = getattr(self.QtWidgets.QSystemTrayIcon, "ActivationReason", None)
        trigger = getattr(self.QtWidgets.QSystemTrayIcon, "Trigger", None)
        double_click = getattr(self.QtWidgets.QSystemTrayIcon, "DoubleClick", None)
        if activation_reason is not None:
            trigger = trigger or getattr(activation_reason, "Trigger", None)
            double_click = double_click or getattr(activation_reason, "DoubleClick", None)
        if reason in {trigger, double_click}:
            self.show_action.trigger()

    def _refresh_icon(self) -> None:
        self.tray.setIcon(
            _status_icon(
                self.QtCore,
                self.QtGui,
                theme=self.theme,
                skin=self.skin,
                status=self.status,
            )
        )
        state = {
            "ready": "Live updates ready",
            "reconnecting": "Reconnecting to local updates",
            "offline": "Using local refresh",
        }.get(self.status, "Local Flight")
        self.tray.setToolTip(f"Local Flight - {state}")

    def update_appearance(self, theme: str, skin: str) -> None:
        self.theme = theme or "dark"
        self.skin = skin or "standard"
        self._refresh_icon()

    def update_connection(self, connected: bool, text: str = "") -> None:
        normalized = str(text or "").lower()
        if connected:
            self.status = "ready"
        elif "connect" in normalized or "reconnect" in normalized:
            self.status = "reconnecting"
        else:
            self.status = "offline"
        self._refresh_icon()

    def notify(self, title: str, message: str) -> None:
        if not self.available or not self.tray.supportsMessages():
            return
        try:
            message_icon = getattr(self.QtWidgets.QSystemTrayIcon, "Information", None)
            message_icon_type = getattr(self.QtWidgets.QSystemTrayIcon, "MessageIcon", None)
            if message_icon is None and message_icon_type is not None:
                message_icon = getattr(message_icon_type, "Information", None)
            if message_icon is None:
                self.tray.showMessage(title, message)
            else:
                self.tray.showMessage(title, message, message_icon, 3500)
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.tray.hide()
        except Exception:
            pass
