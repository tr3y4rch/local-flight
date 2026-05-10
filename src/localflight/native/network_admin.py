"""Operator-only native relay/network admin dashboard.

This app is intentionally separate from the public Local Flight client. It uses
admin-gated relay JSON endpoints and Basic Auth. Normal release clients should
not link to it.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable
from urllib.parse import urlencode

from localflight.native.api_client import NativeApiError, RelayAdminClient
from localflight.native.design import apply_app_font_defaults, icon_from_media, native_stylesheet
from localflight.native.geometry import fitted_window_size
from localflight.native.qt_compat import import_qt
from localflight.native.routes import NETWORK_ADMIN_ROUTES

ADMIN_ENDPOINTS = {
    route.action_id.split(".", 1)[1]: route.path
    for route in NETWORK_ADMIN_ROUTES
    if route.method == "GET" and route.action_id.startswith("network.")
}
ROUTES_BY_ACTION = {route.action_id: route for route in NETWORK_ADMIN_ROUTES}


def _raw_debug_enabled() -> bool:
    return os.environ.get("LOCALFLIGHT_NETWORK_ADMIN_RAW", "").strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    try:
        QtCore, QtGui, QtWidgets = import_qt()
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        app.setApplicationName("Local Flight Network Admin")
        if hasattr(app, "setApplicationDisplayName"):
            app.setApplicationDisplayName("Local Flight Network Admin")
        app.setOrganizationName("Local Flight")
        app.setOrganizationDomain("localflight.app")
        apply_app_font_defaults(QtGui, app)
        app_icon = icon_from_media(QtGui, "assets", "icon.ico")
        if app_icon.isNull():
            app_icon = icon_from_media(QtGui, "assets", "icon_square.svg")
        if not app_icon.isNull():
            app.setWindowIcon(app_icon)
        window = NetworkAdminWindow(QtCore, QtWidgets)
        if not app_icon.isNull():
            window.setWindowIcon(app_icon)
        geometry = app.primaryScreen().availableGeometry() if app.primaryScreen() is not None else None
        if geometry is None:
            window.resize(1280, 820)
        else:
            window.resize(*fitted_window_size(geometry.width(), geometry.height(), max_width=1440, max_height=900))
            frame = window.frameGeometry()
            frame.moveCenter(geometry.center())
            window.move(frame.topLeft())
        window.show()
        raise SystemExit(int(app.exec()))
    except Exception as exc:
        print(f"Local Flight Network Admin unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)


class NetworkAdminWindow:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtWidgets: Any):
        class _Window(QtWidgets.QMainWindow):
            def __init__(self) -> None:
                super().__init__()
                self.QtCore = QtCore
                self.QtWidgets = QtWidgets
                self.setWindowTitle("Local Flight Network Admin")
                self.setStyleSheet(native_stylesheet(operator=True) + _NETWORK_ADMIN_STYLE)
                self.client: RelayAdminClient | None = None
                self.payloads: dict[str, dict[str, Any]] = {}
                self._refreshing = False
                self._has_loaded_all = False
                self._last_refresh = ""
                self._next_refresh_seconds = 0
                self.show_raw = _raw_debug_enabled()
                self.page_filters: dict[str, dict[str, Any]] = {}
                self.page_cursors: dict[str, str] = {}
                self.page_cursor_stack: dict[str, list[str]] = {}
                self.page_sorts: dict[str, tuple[str, str]] = {
                    "fleet": ("last_seen", "desc"),
                    "traffic": ("last_seen", "desc"),
                    "schedules": ("updated_at", "desc"),
                    "surfaces": ("updated_at", "desc"),
                    "reports": ("ts", "desc"),
                }

                root = QtWidgets.QWidget()
                layout = QtWidgets.QVBoxLayout(root)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

                top_nav = QtWidgets.QFrame()
                top_nav.setObjectName("TopNav")
                top = QtWidgets.QHBoxLayout(top_nav)
                top.setContentsMargins(14, 10, 14, 10)
                top.setSpacing(10)
                self.brand_mark = QtWidgets.QLabel()
                self.brand_mark.setObjectName("BrandMark")
                self.brand_mark.setText("LF")
                try:
                    pixmap = QtWidgets.QApplication.windowIcon().pixmap(34, 34)
                    if not pixmap.isNull():
                        self.brand_mark.setPixmap(pixmap)
                        self.brand_mark.setText("")
                except Exception:
                    pass
                top.addWidget(self.brand_mark)
                brand_box = QtWidgets.QVBoxLayout()
                brand = QtWidgets.QLabel("Local Flight")
                brand.setObjectName("Brand")
                subtitle = QtWidgets.QLabel("Network Admin - operator relay console")
                subtitle.setObjectName("Kicker")
                brand_box.addWidget(brand)
                brand_box.addWidget(subtitle)
                top.addLayout(brand_box)
                self.auth_chip = QtWidgets.QLabel("OFFLINE")
                self.auth_chip.setObjectName("AuthChip")
                self.operator_chip = QtWidgets.QLabel("MONITOR / INVESTIGATE / OPERATE")
                self.operator_chip.setObjectName("OperatorChip")
                self.last_refresh_chip = QtWidgets.QLabel("not refreshed")
                self.last_refresh_chip.setObjectName("ClockChip")
                self.countdown_chip = QtWidgets.QLabel("auto 30s")
                self.countdown_chip.setObjectName("ClockChip")
                top.addStretch(1)
                top.addWidget(self.auth_chip)
                top.addWidget(self.operator_chip)
                top.addWidget(self.last_refresh_chip)
                top.addWidget(self.countdown_chip)
                layout.addWidget(top_nav)

                shell = QtWidgets.QWidget()
                shell_layout = QtWidgets.QVBoxLayout(shell)
                shell_layout.setContentsMargins(14, 14, 14, 14)
                shell_layout.setSpacing(10)

                hero = QtWidgets.QFrame()
                hero.setObjectName("HeroPanel")
                hero_layout = QtWidgets.QVBoxLayout(hero)
                hero_layout.setContentsMargins(16, 14, 16, 14)
                hero_layout.setSpacing(8)
                hero_layout.addWidget(self._label("Relay Operations Console", "Title"))
                hero_layout.addWidget(
                    self._label(
                        "Operator-only relay controls. This shell is intentionally separate from public Local Flight clients and public docs.",
                        "Muted",
                    )
                )

                login = QtWidgets.QHBoxLayout()
                self.url = QtWidgets.QLineEdit(
                    os.environ.get("LOCALFLIGHT_NETWORK_ADMIN_URL", "https://localflight-community-relay.fly.dev/admin")
                )
                self.user = QtWidgets.QLineEdit(os.environ.get("LOCALFLIGHT_NETWORK_ADMIN_USER", "admin"))
                self.password = QtWidgets.QLineEdit()
                self.password.setEchoMode(QtWidgets.QLineEdit.Password)
                self.connect_btn = QtWidgets.QPushButton("Connect to admin")
                self.refresh_btn = QtWidgets.QPushButton("Refresh snapshot")
                self.auto_refresh = QtWidgets.QCheckBox("Auto-refresh")
                self.auto_refresh.setChecked(True)
                self.refresh_interval = QtWidgets.QSpinBox()
                self.refresh_interval.setRange(10, 600)
                self.refresh_interval.setValue(30)
                self.refresh_interval.setSuffix("s")
                self.search = QtWidgets.QLineEdit()
                self.search.setPlaceholderText("Search fleet, OS, GUI, airport, reports")
                self.search.setClearButtonEnabled(True)
                self.status = QtWidgets.QLabel("Operator-only console. Mutating actions require admin auth.")
                self.status.setObjectName("Muted")
                login.addWidget(QtWidgets.QLabel("Relay admin URL"))
                login.addWidget(self.url, 3)
                login.addWidget(QtWidgets.QLabel("User"))
                login.addWidget(self.user)
                login.addWidget(QtWidgets.QLabel("Password"))
                login.addWidget(self.password)
                login.addWidget(self.connect_btn)
                login.addWidget(self.refresh_btn)
                login.addWidget(self.auto_refresh)
                login.addWidget(self.refresh_interval)
                login.addWidget(self.search, 2)
                hero_layout.addLayout(login)
                hero_layout.addWidget(self.status)
                shell_layout.addWidget(hero)

                nav_row = QtWidgets.QHBoxLayout()
                self.nav_buttons: dict[str, Any] = {}
                self.page_defs: list[tuple[str, str]] = [
                    ("overview", "Overview"),
                    ("fleet", "Fleet"),
                    ("traffic", "Traffic"),
                    ("schedules", "Schedules"),
                    ("surfaces", "Surfaces"),
                    ("activations", "Activations"),
                    ("reports", "Reports"),
                    ("providers", "Providers"),
                    ("maintenance", "Maintenance"),
                ]
                if self.show_raw:
                    self.page_defs.append(("raw", "Raw"))
                for key, text in self.page_defs:
                    button = QtWidgets.QPushButton(text)
                    button.setObjectName("NavButton")
                    button.setCheckable(True)
                    button.clicked.connect(lambda _checked=False, k=key: self._show_page(k))
                    self.nav_buttons[key] = button
                    nav_row.addWidget(button)
                nav_row.addStretch(1)
                shell_layout.addLayout(nav_row)

                self.tabs = QtWidgets.QTabWidget()
                self.pages: dict[str, Any] = {}
                self.key_to_index: dict[str, int] = {}
                for key, label in self.page_defs:
                    page = self._scroll_page()
                    self.pages[key] = page
                    self.key_to_index[key] = self.tabs.count()
                    self.tabs.addTab(page, label)
                self.tabs.tabBar().hide()
                shell_layout.addWidget(self.tabs, 1)
                layout.addWidget(shell, 1)
                self.setCentralWidget(root)

                self.connect_btn.clicked.connect(self.connect_relay)
                self.refresh_btn.clicked.connect(lambda: self.refresh_all())
                self.refresh_interval.valueChanged.connect(self._set_refresh_interval)
                self.search.textChanged.connect(lambda _text="": self._render_page(self._current_page_key()))
                self.timer = QtCore.QTimer(self)
                self.timer.timeout.connect(self._auto_refresh_tick)
                self._set_refresh_interval(self.refresh_interval.value())
                self.timer.start()
                self.countdown_timer = QtCore.QTimer(self)
                self.countdown_timer.setInterval(1000)
                self.countdown_timer.timeout.connect(self._countdown_tick)
                self.countdown_timer.start()
                self._show_page("overview")

            def _scroll_page(self) -> Any:
                scroll = self.QtWidgets.QScrollArea()
                scroll.setWidgetResizable(True)
                body = self.QtWidgets.QWidget()
                layout = self.QtWidgets.QVBoxLayout(body)
                layout.setContentsMargins(10, 10, 10, 10)
                layout.setSpacing(10)
                scroll.setWidget(body)
                scroll.body = body
                scroll.body_layout = layout
                return scroll

            def _show_page(self, page_key: str) -> None:
                if page_key not in self.key_to_index:
                    page_key = "overview"
                self.tabs.setCurrentIndex(self.key_to_index[page_key])
                for key, button in self.nav_buttons.items():
                    button.setChecked(key == page_key)
                if self.payloads:
                    self._render_page(page_key)

            def _current_page_key(self) -> str:
                index = self.tabs.currentIndex()
                for key, tab_index in self.key_to_index.items():
                    if tab_index == index:
                        return key
                return "overview"

            def _clear(self, page_key: str) -> Any:
                layout = self.pages[page_key].body_layout
                while layout.count():
                    item = layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
                return layout

            def _label(self, text: str, role: str = "") -> Any:
                label = self.QtWidgets.QLabel(text)
                label.setWordWrap(True)
                if role:
                    label.setObjectName(role)
                return label

            def _section_panel(self, title: str, detail: str = "", *, danger: bool = False) -> tuple[Any, Any]:
                box = self.QtWidgets.QFrame()
                box.setObjectName("DangerPanel" if danger else "Panel")
                layout = self.QtWidgets.QVBoxLayout(box)
                layout.setContentsMargins(14, 12, 14, 12)
                layout.setSpacing(8)
                layout.addWidget(self._label(title, "Section"))
                if detail:
                    layout.addWidget(self._label(detail, "Muted"))
                return box, layout

            def _card(self, title: str, value: str, detail: str = "") -> Any:
                box = self.QtWidgets.QFrame()
                box.setObjectName("Card")
                layout = self.QtWidgets.QVBoxLayout(box)
                layout.addWidget(self._label(title, "Kicker"))
                layout.addWidget(self._label(value, "Metric"))
                if detail:
                    layout.addWidget(self._label(detail, "Muted"))
                return box

            def _pill(self, text: str, *, kind: str = "neutral") -> Any:
                pill = self.QtWidgets.QLabel(text)
                role = {"good": "StatusGood", "warn": "StatusWarn", "bad": "StatusBad"}.get(kind, "ClockChip")
                pill.setObjectName(role)
                return pill

            def _table(self, rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> Any:
                table = self.QtWidgets.QTableWidget(len(rows), len(columns))
                table.setHorizontalHeaderLabels([label for _key, label in columns])
                table.verticalHeader().setVisible(False)
                table.setAlternatingRowColors(True)
                table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
                table.setSelectionBehavior(self.QtWidgets.QAbstractItemView.SelectRows)
                table.horizontalHeader().setStretchLastSection(True)
                table.horizontalHeader().setDefaultSectionSize(142)
                table.setWordWrap(False)
                table.setSortingEnabled(False)
                for row_idx, row in enumerate(rows):
                    for col_idx, (key, _label) in enumerate(columns):
                        value = _value_at(row, key)
                        display = _format_cell(key, value)
                        item = self.QtWidgets.QTableWidgetItem(display)
                        item.setToolTip(display)
                        table.setItem(row_idx, col_idx, item)
                table.setMinimumHeight(min(440, max(140, 46 + len(rows) * 30)))
                table.setSortingEnabled(True)
                return table

            def _action_button(self, label: str, fn: Callable[[], None], danger: bool = False, action_id: str = "") -> Any:
                button = self.QtWidgets.QPushButton(label)
                if danger:
                    button.setObjectName("Danger")
                if action_id:
                    route = ROUTES_BY_ACTION.get(action_id)
                    if route is not None:
                        button.setProperty("lf_action_id", action_id)
                        button.setProperty("lf_action_path", route.path)
                button.clicked.connect(fn)
                return button

            def _form_line(self, placeholder: str, *, password: bool = False) -> Any:
                line = self.QtWidgets.QLineEdit()
                line.setPlaceholderText(placeholder)
                line.setProperty("lf_action_form", True)
                if password:
                    line.setEchoMode(self.QtWidgets.QLineEdit.Password)
                return line

            def _form_spin(self, *, value: int, prefix: str, minimum: int = 1, maximum: int = 1_000_000) -> Any:
                spin = self.QtWidgets.QSpinBox()
                spin.setRange(minimum, maximum)
                spin.setValue(value)
                spin.setPrefix(prefix)
                spin.setProperty("lf_action_form", True)
                return spin

            def _button_row(self, actions: list[tuple]) -> Any:
                row = self.QtWidgets.QWidget()
                layout = self.QtWidgets.QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                for action in actions:
                    label, fn, danger = action[:3]
                    action_id = str(action[3]) if len(action) > 3 else ""
                    layout.addWidget(self._action_button(label, fn, danger, action_id))
                layout.addStretch(1)
                return row

            def _filtered_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
                needle = self.search.text().strip().lower() if hasattr(self, "search") else ""
                if not needle:
                    return rows
                filtered: list[dict[str, Any]] = []
                for row in rows:
                    blob = json.dumps(row, ensure_ascii=False, default=str).lower()
                    if needle in blob:
                        filtered.append(row)
                return filtered

            def connect_relay(self) -> None:
                self.client = RelayAdminClient(
                    base_url=self.url.text().strip(),
                    username=self.user.text().strip() or "admin",
                    password=self.password.text(),
                )
                self.auth_chip.setText("CONNECTING")
                self.auth_chip.setProperty("connected", False)
                self.auth_chip.style().unpolish(self.auth_chip)
                self.auth_chip.style().polish(self.auth_chip)
                self.refresh_all()

            def refresh_all(self, *, silent: bool = False, active_only: bool = False) -> None:
                if self.client is None:
                    if not silent:
                        self.status.setText("Enter relay admin URL and credentials, then connect.")
                    return
                if self._refreshing:
                    return
                self._refreshing = True
                current_key = self._current_page_key()
                errors: list[str] = []
                try:
                    keys = self._endpoint_keys_for_refresh(current_key) if active_only and self._has_loaded_all else list(ADMIN_ENDPOINTS.keys())
                    for key in keys:
                        path = ADMIN_ENDPOINTS.get(key)
                        if not path:
                            continue
                        try:
                            self.payloads[key] = self.client.get_json(self._endpoint_path(key, path))
                        except NativeApiError as exc:
                            errors.append(f"{key}: {exc}")
                    if active_only and self._has_loaded_all:
                        self._render_page(current_key)
                    else:
                        self._render_all()
                        self._has_loaded_all = True
                    self._show_page(current_key)
                    if errors:
                        self.status.setText(" | ".join(errors[:2]))
                        self.auth_chip.setText("ERROR")
                        self.auth_chip.setProperty("connected", False)
                    else:
                        stamp = self.payloads.get("overview", {}).get("generated_at", "")
                        self._last_refresh = str(stamp or "now")
                        self.last_refresh_chip.setText(f"refreshed {self._last_refresh}")
                        self.auth_chip.setText("CONNECTED")
                        self.auth_chip.setProperty("connected", True)
                        self.status.setText(f"Connected. Snapshot refreshed {stamp}.")
                    self.auth_chip.style().unpolish(self.auth_chip)
                    self.auth_chip.style().polish(self.auth_chip)
                    self._next_refresh_seconds = int(self.refresh_interval.value())
                finally:
                    self._refreshing = False

            def _endpoint_keys_for_refresh(self, page_key: str) -> list[str]:
                if page_key in {"overview", "providers", "maintenance"}:
                    return ["overview", "fleet", "usage", "activations", "reports", "schedules", "surfaces"]
                if page_key == "traffic":
                    return ["usage"]
                if page_key in ADMIN_ENDPOINTS:
                    return [page_key]
                return ["overview"]

            def _endpoint_path(self, key: str, path: str) -> str:
                query_key = "traffic" if key == "usage" else key
                if query_key not in {"fleet", "traffic", "schedules", "surfaces", "reports"}:
                    return path
                filters = {
                    name: value
                    for name, value in self.page_filters.get(query_key, {}).items()
                    if str(value or "").strip()
                }
                sort_key, direction = self.page_sorts.get(query_key, ("last_seen", "desc"))
                params: dict[str, Any] = {
                    **filters,
                    "limit": 100,
                    "sort": sort_key,
                    "dir": direction,
                }
                cursor = self.page_cursors.get(query_key, "")
                if cursor:
                    params["cursor"] = cursor
                return f"{path}?{urlencode(params)}"

            def _refresh_page(self, page_key: str) -> None:
                self.refresh_all(active_only=True)

            def _facet_options(self, payload: dict[str, Any], name: str) -> list[str]:
                facets = payload.get("facets") if isinstance(payload.get("facets"), dict) else {}
                values = facets.get(name) if isinstance(facets.get(name), dict) else {}
                return sorted([str(key) for key in values if str(key or "").strip() and str(key) != "unknown"])

            def _filter_bar(
                self,
                page_key: str,
                fields: list[tuple[str, str, str, list[str]]],
                *,
                quick_views: list[tuple[str, dict[str, Any]]] | None = None,
            ) -> Any:
                box = self.QtWidgets.QFrame()
                box.setObjectName("FilterBar")
                layout = self.QtWidgets.QHBoxLayout(box)
                layout.setContentsMargins(10, 8, 10, 8)
                layout.setSpacing(8)
                controls: dict[str, Any] = {}
                if quick_views:
                    quick = self.QtWidgets.QComboBox()
                    quick.setObjectName("FleetQuickView" if page_key == "fleet" else "QuickView")
                    quick.addItem("Saved view", {})
                    for label, filters in quick_views:
                        quick.addItem(label, filters)
                    def apply_quick(_idx: int = 0, combo: Any = quick) -> None:
                        data = combo.currentData()
                        if isinstance(data, dict) and data:
                            self.page_filters[page_key] = dict(data)
                            self.page_cursors[page_key] = ""
                            self.page_cursor_stack[page_key] = []
                            self._refresh_page(page_key)
                    quick.currentIndexChanged.connect(apply_quick)
                    layout.addWidget(quick)
                current = self.page_filters.get(page_key, {})
                for name, label_text, kind, options in fields:
                    if kind == "select":
                        control = self.QtWidgets.QComboBox()
                        control.setObjectName(f"{page_key.title()}Filter_{name}")
                        control.addItem(label_text, "")
                        for option in options:
                            control.addItem(option, option)
                        existing = str(current.get(name) or "")
                        if existing:
                            idx = control.findData(existing)
                            if idx >= 0:
                                control.setCurrentIndex(idx)
                    else:
                        control = self.QtWidgets.QLineEdit()
                        control.setObjectName(f"{page_key.title()}Filter_{name}")
                        control.setPlaceholderText(label_text)
                        control.setText(str(current.get(name) or ""))
                        control.setClearButtonEnabled(True)
                    controls[name] = control
                    layout.addWidget(control)
                apply = self.QtWidgets.QPushButton("Apply filters")
                clear = self.QtWidgets.QPushButton("Clear")
                def apply_filters() -> None:
                    values: dict[str, Any] = {}
                    for name, control in controls.items():
                        if isinstance(control, self.QtWidgets.QComboBox):
                            value = control.currentData()
                        else:
                            value = control.text()
                        if str(value or "").strip():
                            values[name] = value
                    self.page_filters[page_key] = values
                    self.page_cursors[page_key] = ""
                    self.page_cursor_stack[page_key] = []
                    self._refresh_page(page_key)
                def clear_filters() -> None:
                    self.page_filters[page_key] = {}
                    self.page_cursors[page_key] = ""
                    self.page_cursor_stack[page_key] = []
                    self._refresh_page(page_key)
                apply.clicked.connect(apply_filters)
                clear.clicked.connect(clear_filters)
                layout.addWidget(apply)
                layout.addWidget(clear)
                layout.addStretch(1)
                return box

            def _paging_row(self, page_key: str, payload: dict[str, Any]) -> Any:
                row = self.QtWidgets.QFrame()
                row.setObjectName("PagerRow")
                layout = self.QtWidgets.QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                filtered = payload.get("filtered_estimate", len(_list(payload.get("rows"))))
                total = payload.get("total_estimate", filtered)
                cursor = self.page_cursors.get(page_key, "") or "0"
                label = self.QtWidgets.QLabel(f"{filtered} filtered / {total} total | cursor {cursor}")
                label.setObjectName("Muted")
                prev = self.QtWidgets.QPushButton("Previous")
                next_btn = self.QtWidgets.QPushButton("Next")
                prev.setEnabled(bool(self.page_cursor_stack.get(page_key)))
                next_btn.setEnabled(bool(payload.get("next_cursor")))
                def go_prev() -> None:
                    stack = self.page_cursor_stack.setdefault(page_key, [])
                    self.page_cursors[page_key] = stack.pop() if stack else ""
                    self._refresh_page(page_key)
                def go_next() -> None:
                    self.page_cursor_stack.setdefault(page_key, []).append(self.page_cursors.get(page_key, ""))
                    self.page_cursors[page_key] = str(payload.get("next_cursor") or "")
                    self._refresh_page(page_key)
                prev.clicked.connect(go_prev)
                next_btn.clicked.connect(go_next)
                layout.addWidget(label)
                layout.addStretch(1)
                layout.addWidget(prev)
                layout.addWidget(next_btn)
                return row

            def _show_row_detail(self, title: str, row: dict[str, Any]) -> None:
                dialog = self.QtWidgets.QDialog(self)
                dialog.setWindowTitle(title)
                dialog.resize(720, 560)
                layout = self.QtWidgets.QVBoxLayout(dialog)
                layout.addWidget(self._label(title, "Title"))
                text = self.QtWidgets.QPlainTextEdit()
                text.setReadOnly(True)
                text.setPlainText(json.dumps(row, indent=2, ensure_ascii=False, default=str))
                layout.addWidget(text, 1)
                buttons = self.QtWidgets.QDialogButtonBox(self.QtWidgets.QDialogButtonBox.Close)
                buttons.rejected.connect(dialog.reject)
                layout.addWidget(buttons)
                dialog.exec()

            def _set_refresh_interval(self, seconds: int) -> None:
                seconds = max(10, int(seconds))
                self.timer.setInterval(seconds * 1000)
                self._next_refresh_seconds = seconds
                self.countdown_chip.setText(f"auto {seconds}s")

            def _auto_refresh_tick(self) -> None:
                if self.client is None or not self.auto_refresh.isChecked():
                    return
                if self._action_form_has_focus():
                    self.status.setText("Auto-refresh paused while editing an operator action.")
                    return
                self.refresh_all(silent=True, active_only=True)

            def _countdown_tick(self) -> None:
                if not self.auto_refresh.isChecked() or self.client is None:
                    self.countdown_chip.setText("auto paused")
                    return
                self._next_refresh_seconds = max(0, self._next_refresh_seconds - 1)
                self.countdown_chip.setText(f"auto {self._next_refresh_seconds}s")

            def _action_form_has_focus(self) -> bool:
                widget = self.QtWidgets.QApplication.focusWidget()
                while widget is not None:
                    if bool(widget.property("lf_action_form")):
                        return True
                    widget = widget.parentWidget()
                return False

            def _post(self, path: str, payload: dict[str, Any], *, confirm: str = "") -> None:
                if self.client is None:
                    self.status.setText("Connect first.")
                    return
                payload = _clean_payload(payload)
                if confirm and not self._confirm(confirm):
                    return
                try:
                    result = self.client.post_json(path, payload)
                except NativeApiError as exc:
                    self._message("Action failed", str(exc), error=True)
                    return
                token = str(result.get("activation_token") or "")
                message = str(result.get("message") or "Action completed.")
                if token:
                    self.QtWidgets.QApplication.clipboard().setText(token)
                    message += "\n\nNew token copied to clipboard:\n" + token
                self._message("Network Admin", message)
                self.refresh_all()

            def _confirm(self, message: str) -> bool:
                return (
                    self.QtWidgets.QMessageBox.question(
                        self,
                        "Confirm operator action",
                        message,
                        self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.No,
                    )
                    == self.QtWidgets.QMessageBox.Yes
                )

            def _message(self, title: str, message: str, *, error: bool = False) -> None:
                box = self.QtWidgets.QMessageBox.critical if error else self.QtWidgets.QMessageBox.information
                box(self, title, message)

            def _render_all(self) -> None:
                for key, _label in self.page_defs:
                    self._render_page(key)

            def _render_page(self, page_key: str) -> None:
                renderers = {
                    "overview": self._render_overview,
                    "fleet": self._render_fleet,
                    "traffic": self._render_traffic,
                    "providers": self._render_providers,
                    "usage": self._render_usage,
                    "schedules": self._render_schedules,
                    "surfaces": self._render_surfaces,
                    "activations": self._render_activations,
                    "reports": self._render_reports,
                    "maintenance": self._render_maintenance,
                    "raw": self._render_raw,
                }
                render = renderers.get(page_key)
                if render is not None and page_key in self.pages:
                    render()

            def _render_overview(self) -> None:
                layout = self._clear("overview")
                overview = self.payloads.get("overview", {})
                fleet = self.payloads.get("fleet", {})
                counts = overview.get("counts") if isinstance(overview.get("counts"), dict) else {}
                fleet_metrics = fleet.get("metrics") if isinstance(fleet.get("metrics"), dict) else overview.get("fleet")
                if not isinstance(fleet_metrics, dict):
                    fleet_metrics = {}
                schedule = overview.get("shared_schedule") if isinstance(overview.get("shared_schedule"), dict) else {}
                surface = overview.get("surface_cache") if isinstance(overview.get("surface_cache"), dict) else {}
                providers = overview.get("providers") if isinstance(overview.get("providers"), dict) else {}

                layout.addWidget(self._label("Network Overview", "Title"))
                layout.addWidget(self._label("Fleet health, provider readiness, shared caches, activations, and report gateway state.", "Muted"))
                grid = self.QtWidgets.QGridLayout()
                schedule_hits = int(schedule.get("cache_hits", 0) or 0)
                upstream_pulls = int(schedule.get("upstream_pulls", 0) or 0)
                accesses = int(schedule.get("client_accesses", 0) or 0)
                savings = max(0, accesses - upstream_pulls)
                configured = sum(1 for value in providers.values() if isinstance(value, dict) and value.get("configured"))
                cards = [
                    self._card("Relay month", str(overview.get("month", "-")), f"{counts.get('usage_rows', 0)} usage rows"),
                    self._card("Known installs", str(fleet_metrics.get("known_installs", counts.get("known_installs", 0))), "Fleet rows with relay activity"),
                    self._card("Active installs", str(fleet_metrics.get("active_installs_24h", counts.get("active_installs_24h", 0))), "Seen in the last 24h"),
                    self._card("Providers ready", f"{configured} / {len(providers)}", "AviationStack / RapidAPI readiness"),
                    self._card("Shared schedule cache", str(counts.get("schedule_snapshots", 0)), f"{schedule_hits} hits"),
                    self._card("Upstream pulls", str(upstream_pulls), f"{accesses} client accesses"),
                    self._card("Estimated savings", str(savings), "Client accesses minus upstream pulls"),
                    self._card("Surface cache", str(counts.get("surface_snapshots", 0)), f"{surface.get('cache_hits', 0)} hits"),
                    self._card("Activation queue", str(counts.get("activation_requests_pending", 0)), "Pending/manual review"),
                    self._card("Reports 24h", str(counts.get("reports_24h", 0)), "Sanitized gateway events"),
                    self._card("Companion installs", str(fleet_metrics.get("companion_installs", counts.get("companion_installs", 0))), "Mobile companion presence"),
                    self._card("Matrix installs", str(fleet_metrics.get("matrix_installs", counts.get("matrix_installs", 0))), "LED/matrix presence"),
                ]
                for idx, card in enumerate(cards):
                    grid.addWidget(card, idx // 3, idx % 3)
                layout.addLayout(grid)

                provider_rows = []
                for name, value in providers.items():
                    if isinstance(value, dict):
                        provider_rows.append(
                            {
                                "provider": name,
                                "configured": value.get("configured"),
                                "source": value.get("source"),
                                "masked": value.get("masked"),
                            }
                        )
                layout.addWidget(self._label("Provider readiness", "Section"))
                layout.addWidget(self._table(provider_rows, [("provider", "Provider"), ("configured", "Ready"), ("source", "Source"), ("masked", "Masked")]))
                quick, quick_layout = self._section_panel("Operator quick actions", "Common safe paths. Destructive cleanup still asks for confirmation.")
                quick_layout.addWidget(
                    self._button_row(
                        [
                            ("Open fleet", lambda: self._show_page("fleet"), False),
                            ("Open reports", lambda: self._show_page("reports"), False),
                            ("Open activations", lambda: self._show_page("activations"), False),
                            ("Open maintenance", lambda: self._show_page("maintenance"), False),
                        ]
                    )
                )
                layout.addWidget(quick)
                layout.addStretch(1)

            def _render_fleet(self) -> None:
                layout = self._clear("fleet")
                fleet = self.payloads.get("fleet", {})
                metrics = fleet.get("metrics") if isinstance(fleet.get("metrics"), dict) else {}
                rows = self._filtered_rows(_list(fleet.get("installs")))
                layout.addWidget(self._label("Fleet", "Title"))
                layout.addWidget(self._label("Sortable install registry. Rows expose fingerprints and opaque action refs only.", "Muted"))
                layout.addWidget(
                    self._filter_bar(
                        "fleet",
                        [
                            ("q", "Search fleet", "text", []),
                            ("status", "Status", "select", self._facet_options(fleet, "status")),
                            ("plan", "Plan", "select", self._facet_options(fleet, "plan")),
                            ("os_family", "OS", "select", self._facet_options(fleet, "os_family")),
                            ("effective_gui", "GUI", "select", self._facet_options(fleet, "effective_gui")),
                            ("app_version", "Version", "select", self._facet_options(fleet, "app_version")),
                            ("airport_iata", "Airport", "text", []),
                            ("has_companion", "Companion", "select", ["true", "false"]),
                            ("has_matrix", "Matrix", "select", ["true", "false"]),
                            ("blocked", "Blocked", "select", ["true", "false"]),
                            ("managed", "Managed", "select", ["true", "false"]),
                        ],
                        quick_views=[
                            ("Active installs", {"status": "active"}),
                            ("Blocked/revoked", {"blocked": "true"}),
                            ("Companion users", {"has_companion": "true"}),
                            ("Matrix installs", {"has_matrix": "true"}),
                            ("macOS native", {"os_family": "macos", "effective_gui": "native"}),
                            ("Windows native", {"os_family": "windows", "effective_gui": "native"}),
                        ],
                    )
                )
                grid = self.QtWidgets.QGridLayout()
                cards = [
                    self._card("Known installs", str(metrics.get("known_installs", len(rows))), "All tracked relay installs"),
                    self._card("Active 24h", str(metrics.get("active_installs_24h", 0)), "Recent heartbeat or relay traffic"),
                    self._card("Managed", str(metrics.get("managed_installs", 0)), "Bound managed tokens"),
                    self._card("Blocked", str(metrics.get("blocked_installs", 0)), "Revoked install access"),
                    self._card("Companion", str(metrics.get("companion_installs", 0)), "Mobile companion present"),
                    self._card("Matrix", str(metrics.get("matrix_installs", 0)), "LED/matrix present"),
                ]
                for idx, card in enumerate(cards):
                    grid.addWidget(card, idx // 3, idx % 3)
                layout.addLayout(grid)
                table = self._table(
                    rows,
                    [
                        ("install_fingerprint", "Install"),
                        ("first_seen", "First seen"),
                        ("last_seen", "Last seen"),
                        ("os_family", "OS"),
                        ("effective_gui", "GUI"),
                        ("app_version", "Version"),
                        ("plan", "Plan"),
                        ("current_lane.airport_iata", "Airport"),
                        ("companion_count", "Companion"),
                        ("matrix_online_count", "Matrix"),
                        ("schedule_calls", "Schedule"),
                        ("radar_calls", "Radar"),
                        ("status", "Status"),
                    ],
                )
                table.setColumnCount(table.columnCount() + 1)
                table.setHorizontalHeaderItem(table.columnCount() - 1, self.QtWidgets.QTableWidgetItem("Actions"))
                for row_idx, row in enumerate(rows):
                    install_ref = str(row.get("action_ref") or "")
                    fp = str(row.get("install_fingerprint") or "")
                    blocked = bool(row.get("blocked"))
                    actions = [
                        ("Reset", lambda r=install_ref, f=fp: self._reset_counter("install", install_ref=r, install_fingerprint=f), True, "counters.reset"),
                        ("Unblock" if blocked else "Block", lambda r=install_ref, f=fp, a=("unblock" if blocked else "block"): self._install_access(a, r, f), True, "install.access"),
                    ]
                    table.setCellWidget(row_idx, table.columnCount() - 1, self._button_row(actions))
                table.itemDoubleClicked.connect(lambda item, data=rows: self._show_row_detail("Fleet install", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(table)
                layout.addWidget(self._paging_row("fleet", fleet))
                layout.addStretch(1)

            def _render_traffic(self) -> None:
                layout = self._clear("traffic")
                usage = self.payloads.get("usage", {})
                layout.addWidget(self._label(f"Traffic - {usage.get('month', '')}", "Title"))
                layout.addWidget(self._label("Relay usage and transport counters. Sort by service, plan, calls, or last seen.", "Muted"))
                layout.addWidget(
                    self._filter_bar(
                        "traffic",
                        [
                            ("q", "Search traffic", "text", []),
                            ("service", "Service", "text", []),
                            ("plan", "Plan", "text", []),
                            ("status", "Status or error", "text", []),
                        ],
                    )
                )
                layout.addWidget(self._label("Monthly service counters", "Section"))
                layout.addWidget(self._table(self._filtered_rows(_list(usage.get("summary"))), [("service", "Service"), ("plan", "Plan"), ("calls", "Calls"), ("subjects", "Subjects"), ("last_seen", "Last seen")]))
                layout.addWidget(self._label("Install/service rows", "Section"))
                traffic_rows = self._filtered_rows(_list(usage.get("rows")))
                traffic_table = self._table(traffic_rows, [("subject.kind", "Kind"), ("subject.fingerprint", "Fingerprint"), ("subject.tag", "Network"), ("service", "Service"), ("plan", "Plan"), ("calls", "Calls"), ("last_seen", "Last seen")])
                traffic_table.itemDoubleClicked.connect(lambda item, data=traffic_rows: self._show_row_detail("Traffic row", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(traffic_table)
                if isinstance(usage.get("requests"), dict):
                    layout.addWidget(self._label("Recent request health", "Section"))
                    request_rows = _list(usage["requests"].get("rows"))
                    request_table = self._table(request_rows, [("ts", "Time"), ("install_fingerprint", "Install"), ("service", "Service"), ("scope", "Scope"), ("status", "Status"), ("latency_ms", "Latency"), ("plan", "Plan")])
                    request_table.itemDoubleClicked.connect(lambda item, data=request_rows: self._show_row_detail("Request row", data[item.row()] if item.row() < len(data) else {}))
                    layout.addWidget(request_table)
                layout.addWidget(self._paging_row("traffic", usage))
                layout.addStretch(1)

            def _render_providers(self) -> None:
                layout = self._clear("providers")
                overview = self.payloads.get("overview", {})
                providers = overview.get("providers") if isinstance(overview.get("providers"), dict) else {}
                layout.addWidget(self._label("Provider Keys", "Title"))
                layout.addWidget(self._label("Stored keys stay on the relay. Blank fields keep the current value.", "Muted"))
                layout.addWidget(self._table(
                    [
                        {"provider": name, **value}
                        for name, value in providers.items()
                        if isinstance(value, dict)
                    ],
                    [("provider", "Provider"), ("configured", "Ready"), ("source", "Source"), ("masked", "Masked")],
                ))
                form_box, form_layout = self._section_panel("Provider key overrides", "Save replacements without exposing current secret values back to the operator UI.")
                self.aviationstack_key = self._form_line("Paste replacement AviationStack key", password=True)
                self.rapidapi_key = self._form_line("Paste replacement RapidAPI key", password=True)
                form_layout.addWidget(self.aviationstack_key)
                form_layout.addWidget(self.rapidapi_key)
                form_layout.addWidget(
                    self._button_row(
                        [
                            ("Save provider keys", self._save_providers, False, "provider.save"),
                            ("Clear AviationStack override", lambda: self._clear_provider("aviationstack"), True, "provider.clear"),
                            ("Clear RapidAPI override", lambda: self._clear_provider("rapidapi"), True, "provider.clear"),
                        ]
                    )
                )
                layout.addWidget(form_box)
                layout.addStretch(1)

            def _save_providers(self) -> None:
                self._post(
                    "/admin/api/providers/save",
                    {
                        "aviationstack_key": self.aviationstack_key.text().strip(),
                        "rapidapi_key": self.rapidapi_key.text().strip(),
                    },
                    confirm="Save replacement provider keys to the relay?",
                )

            def _clear_provider(self, provider: str) -> None:
                self._post(
                    "/admin/api/providers/clear",
                    {"provider": provider},
                    confirm=f"Clear the relay-stored {provider} override?",
                )

            def _render_usage(self) -> None:
                layout = self._clear("usage")
                usage = self.payloads.get("usage", {})
                layout.addWidget(self._label(f"Usage - {usage.get('month', '')}", "Title"))
                layout.addWidget(self._label("Read-only usage view. Counter corrections and cleanup live in Maintenance.", "Muted"))
                layout.addWidget(self._label("Summary", "Section"))
                layout.addWidget(self._table(_list(usage.get("summary")), [("service", "Service"), ("plan", "Plan"), ("calls", "Calls"), ("subjects", "Subjects"), ("last_seen", "Last seen")]))
                layout.addWidget(self._label("Install/service rows", "Section"))
                layout.addWidget(self._table(_list(usage.get("rows")), [("subject.kind", "Kind"), ("subject.fingerprint", "Fingerprint"), ("subject.tag", "Network"), ("service", "Service"), ("plan", "Plan"), ("calls", "Calls"), ("last_seen", "Last seen")]))
                layout.addWidget(self._button_row([("Open maintenance tools", lambda: self._show_page("maintenance"), False)]))
                layout.addStretch(1)

            def _render_maintenance(self) -> None:
                layout = self._clear("maintenance")
                layout.addWidget(self._label("Maintenance", "Title"))
                layout.addWidget(self._label("Operator write actions are grouped here so normal monitoring tabs stay readable.", "Muted"))
                counters, counters_layout = self._section_panel("Counter maintenance", "Use only after a known test run or accounting correction.", danger=True)
                counters_layout.addWidget(
                    self._button_row(
                        [
                            ("Reset all monthly counters", lambda: self._reset_counter("all"), True, "counters.reset"),
                            ("Reset schedule counters", lambda: self._reset_counter("service", service="aviationstack"), True, "counters.reset"),
                            ("Reset radar counters", lambda: self._reset_counter("service", service="radar"), True, "counters.reset"),
                            ("Clear request log", lambda: self._reset_counter("logs"), True, "counters.reset"),
                        ]
                    )
                )
                self.correct_total = self.QtWidgets.QSpinBox()
                self.correct_total.setRange(0, 100_000_000)
                self.correct_total.setPrefix("Known schedule total ")
                self.correct_total.setProperty("lf_action_form", True)
                counters_layout.addWidget(self.correct_total)
                counters_layout.addWidget(self._button_row([("Correct schedule total", self._correct_schedule_total, False, "counters.correct_schedule")]))
                layout.addWidget(counters)

                trial, trial_layout = self._section_panel(
                    "Setup trial cleanup",
                    "Clears transient trial state while preserving provider keys, managed tokens, blocked installs, and usage counters.",
                    danger=True,
                )
                trial_layout.addWidget(self._button_row([("Clean setup trial state", self._clean_trial, True, "maintenance.clean_trial")]))
                layout.addWidget(trial)
                layout.addStretch(1)

            def _reset_counter(self, scope: str, **extra: Any) -> None:
                if scope == "token":
                    token_ref = self._require_text(
                        extra.get("token_ref") or extra.get("token_prefix"),
                        "token action reference",
                    )
                    if not token_ref:
                        return
                    extra["token_ref"] = token_ref
                if scope == "install":
                    install_ref = self._require_text(
                        extra.get("install_ref") or extra.get("install_fingerprint"),
                        "install action reference",
                    )
                    if not install_ref:
                        return
                    extra["install_ref"] = install_ref
                self._post(
                    "/admin/api/counters/reset",
                    {"scope": scope, **extra},
                    confirm=f"Run counter reset: {scope}?",
                )

            def _correct_schedule_total(self) -> None:
                self._post(
                    "/admin/api/counters/correct-schedule",
                    {"total": int(self.correct_total.value())},
                    confirm="Store this known schedule total correction?",
                )

            def _clean_trial(self) -> None:
                self._post(
                    "/admin/api/maintenance/clean-trial",
                    {},
                    confirm="Clean transient setup-trial rows? Provider keys, tokens, blocks, and usage counters are kept.",
                )

            def _render_schedules(self) -> None:
                layout = self._clear("schedules")
                schedules = self.payloads.get("schedules", {})
                layout.addWidget(self._label("Shared Schedule Cache", "Title"))
                layout.addWidget(self._filter_bar("schedules", [("q", "Search schedules", "text", []), ("airport_iata", "Airport", "text", []), ("cache_state", "Cache state", "text", [])]))
                schedule_rows = _list(schedules.get("snapshots"))
                schedule_table = self._table(schedule_rows, [("airport_iata", "Airport"), ("timezone", "Timezone"), ("client_accesses", "Client accesses"), ("upstream_pulls", "Upstream pulls"), ("cache_hits", "Hits"), ("last_cache_state", "State"), ("updated_at", "Updated"), ("last_error", "Error")])
                schedule_table.itemDoubleClicked.connect(lambda item, data=schedule_rows: self._show_row_detail("Schedule cache lane", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(schedule_table)
                layout.addWidget(self._paging_row("schedules", schedules))
                layout.addWidget(self._label("Live client interests", "Section"))
                layout.addWidget(self._table(_list(schedules.get("client_interests")), [("install_fingerprint", "Install"), ("plan", "Plan"), ("airport_iata", "Airport"), ("timezone", "Timezone"), ("refresh_seconds", "Refresh"), ("last_seen", "Last seen")]))
                layout.addStretch(1)

            def _render_surfaces(self) -> None:
                layout = self._clear("surfaces")
                surfaces = self.payloads.get("surfaces", {})
                layout.addWidget(self._label("Airport Surface Cache", "Title"))
                layout.addWidget(self._label(f"Relay surface overlay enabled: {surfaces.get('enabled')}", "Muted"))
                layout.addWidget(self._filter_bar("surfaces", [("q", "Search surfaces", "text", []), ("airport_iata", "Airport", "text", []), ("cache_state", "Cache state", "text", [])]))
                surface_rows = _list(surfaces.get("snapshots"))
                surface_table = self._table(surface_rows, [("airport_iata", "IATA"), ("airport_icao", "ICAO"), ("feature_count", "Features"), ("request_count", "Requests"), ("cache_hits", "Hits"), ("refresh_count", "Refreshes"), ("last_cache_state", "State"), ("updated_at", "Updated"), ("last_error", "Error")])
                surface_table.itemDoubleClicked.connect(lambda item, data=surface_rows: self._show_row_detail("Surface cache lane", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(surface_table)
                layout.addWidget(self._paging_row("surfaces", surfaces))
                layout.addStretch(1)

            def _render_activations(self) -> None:
                layout = self._clear("activations")
                activations = self.payloads.get("activations", {})
                layout.addWidget(self._label("Activations", "Title"))
                create = self.QtWidgets.QHBoxLayout()
                self.token_label = self._form_line("Token label")
                self.schedule_limit = self._form_spin(value=10_000, prefix="Schedule ")
                self.radar_limit = self._form_spin(value=10_000, prefix="Radar ")
                create_button = self._action_button("Create managed token", self._create_token, False, "activation.create")
                create.addWidget(self.token_label, 2)
                create.addWidget(self.schedule_limit)
                create.addWidget(self.radar_limit)
                create.addWidget(create_button)
                layout.addLayout(create)

                layout.addWidget(self._label("Managed tokens", "Section"))
                token_rows = _list(activations.get("tokens"))
                table = self._table(token_rows, [("token_prefix", "Prefix"), ("label", "Label"), ("schedule_limit", "Schedule"), ("radar_limit", "Radar"), ("bound_install_fingerprint", "Bound install"), ("last_seen", "Last seen"), ("revoked", "Revoked")])
                table.setColumnCount(table.columnCount() + 1)
                table.setHorizontalHeaderItem(table.columnCount() - 1, self.QtWidgets.QTableWidgetItem("Actions"))
                for row_idx, row in enumerate(token_rows):
                    prefix = str(row.get("token_prefix") or "")
                    token_ref = str(row.get("action_ref") or row.get("token_ref") or prefix)
                    revoked = bool(row.get("revoked"))
                    actions = [
                        ("Rotate", lambda r=token_ref, p=prefix: self._token_action(r, "rotate", p), True, "activation.token_action"),
                        ("Restore" if revoked else "Revoke", lambda r=token_ref, p=prefix, a=("reactivate" if revoked else "revoke"): self._token_action(r, a, p), True, "activation.token_action"),
                        ("Unbind", lambda r=token_ref, p=prefix: self._token_action(r, "unbind", p), False, "activation.token_action"),
                        ("Reset", lambda r=token_ref, p=prefix: self._reset_counter("token", token_ref=r, token_prefix=p), True, "counters.reset"),
                        ("Delete", lambda r=token_ref, p=prefix: self._token_action(r, "delete", p), True, "activation.token_action"),
                    ]
                    table.setCellWidget(row_idx, table.columnCount() - 1, self._button_row(actions))
                table.itemDoubleClicked.connect(lambda item, data=token_rows: self._show_row_detail("Managed token", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(table)

                layout.addWidget(self._label("Activation requests", "Section"))
                request_rows = _list(activations.get("requests"))
                request_table = self._table(request_rows, [("request_id", "Request"), ("install_fingerprint", "Install"), ("network_tag", "Network"), ("airport_iata", "Airport"), ("display_name", "Display"), ("status", "Status"), ("updated_at", "Updated"), ("decision_note", "Note")])
                request_table.setColumnCount(request_table.columnCount() + 1)
                request_table.setHorizontalHeaderItem(request_table.columnCount() - 1, self.QtWidgets.QTableWidgetItem("Actions"))
                for row_idx, row in enumerate(request_rows):
                    request_id = str(row.get("action_ref") or row.get("request_id") or "")
                    display_id = str(row.get("request_id") or request_id)
                    actions = [
                        ("Issue", lambda r=request_id, d=display_id: self._request_action(r, "approve", d), False, "activation.request_action"),
                        ("Dismiss", lambda r=request_id, d=display_id: self._request_action(r, "reject", d), True, "activation.request_action"),
                        ("Delete", lambda r=request_id, d=display_id: self._request_action(r, "delete", d), True, "activation.request_action"),
                    ]
                    request_table.setCellWidget(row_idx, request_table.columnCount() - 1, self._button_row(actions))
                request_table.itemDoubleClicked.connect(lambda item, data=request_rows: self._show_row_detail("Activation request", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(request_table)

                layout.addWidget(self._label("Blocked installs", "Section"))
                blocked_rows = _list(activations.get("blocked_installs"))
                blocked = self._table(blocked_rows, [("install_fingerprint", "Install"), ("reason", "Reason"), ("created_at", "Created")])
                blocked.setColumnCount(blocked.columnCount() + 1)
                blocked.setHorizontalHeaderItem(blocked.columnCount() - 1, self.QtWidgets.QTableWidgetItem("Actions"))
                for row_idx, row in enumerate(blocked_rows):
                    fp = str(row.get("install_fingerprint") or "")
                    install_ref = str(row.get("action_ref") or row.get("install_ref") or fp)
                    blocked.setCellWidget(row_idx, blocked.columnCount() - 1, self._button_row([("Unblock", lambda r=install_ref, f=fp: self._install_access("unblock", r, f), True, "install.access")]))
                layout.addWidget(blocked)
                layout.addStretch(1)

            def _create_token(self) -> None:
                self._post(
                    "/admin/api/activation/create",
                    {
                        "label": self.token_label.text().strip(),
                        "schedule_limit": int(self.schedule_limit.value()),
                        "radar_limit": int(self.radar_limit.value()),
                    },
                    confirm="Create a managed activation token?",
                )

            def _token_action(self, token_ref: str, action: str, token_prefix: str = "") -> None:
                token_ref = self._require_text(token_ref, "token action reference")
                if not token_ref:
                    return
                label = token_prefix or token_ref
                self._post(
                    "/admin/api/activation/token-action",
                    {"token_ref": token_ref, "token_prefix": token_prefix, "action": action},
                    confirm=f"Run '{action}' for token {label}?",
                )

            def _request_action(self, request_id: str, action: str, display_id: str = "") -> None:
                request_id = self._require_text(request_id, "request id")
                if not request_id:
                    return
                note = "dismissed" if action == "reject" else ""
                label = display_id or request_id
                self._post(
                    "/admin/api/activation/request-action",
                    {"request_id": request_id, "action": action, "decision_note": note},
                    confirm=f"Run '{action}' for request {label}?",
                )

            def _install_access(self, action: str, install_ref: str, fingerprint: str = "") -> None:
                install_ref = self._require_text(install_ref, "install action reference")
                if not install_ref:
                    return
                label = fingerprint or install_ref
                self._post(
                    "/admin/api/install/access",
                    {"install_ref": install_ref, "install_fingerprint": fingerprint, "action": action},
                    confirm=f"Run '{action}' for install {label}?",
                )

            def _require_text(self, value: Any, label: str) -> str:
                text = str(value or "").strip()
                if not text:
                    self._message("Missing selection", f"This row does not expose a usable {label}. Refresh the panel and try again.", error=True)
                    return ""
                return text

            def _render_reports(self) -> None:
                layout = self._clear("reports")
                reports = self.payloads.get("reports", {})
                layout.addWidget(self._label("Report Gateway", "Title"))
                layout.addWidget(self._filter_bar("reports", [("q", "Search reports", "text", []), ("report_type", "Type", "text", []), ("origin", "Origin", "text", []), ("team", "Team", "text", []), ("status", "Status", "text", [])]))
                layout.addWidget(self._table(_list(reports.get("summary_24h")), [("report_type", "Type"), ("origin", "Origin"), ("team", "Team"), ("status", "Status"), ("reports", "Reports"), ("installs", "Installs"), ("last_seen", "Last seen")]))
                layout.addWidget(self._label("Recent sanitized events", "Section"))
                report_rows = _list(reports.get("recent_events"))
                report_table = self._table(report_rows, [("ts", "Time"), ("install_fingerprint", "Install"), ("network_tag", "Network"), ("report_type", "Type"), ("origin", "Origin"), ("team", "Team"), ("status", "Status")])
                report_table.itemDoubleClicked.connect(lambda item, data=report_rows: self._show_row_detail("Report event", data[item.row()] if item.row() < len(data) else {}))
                layout.addWidget(report_table)
                layout.addWidget(self._label("Dedupe groups", "Section"))
                layout.addWidget(self._table(_list(reports.get("dedupe")), [("team", "Team"), ("report_type", "Type"), ("origin", "Origin"), ("count", "Count"), ("issue_url", "Issue"), ("last_seen", "Last seen")]))
                layout.addWidget(self._paging_row("reports", reports))
                layout.addStretch(1)

            def _render_raw(self) -> None:
                layout = self._clear("raw")
                layout.addWidget(self._label("Raw Snapshot Debug", "Title"))
                text = self.QtWidgets.QPlainTextEdit()
                text.setReadOnly(True)
                text.setPlainText(json.dumps(self.payloads, indent=2, ensure_ascii=False))
                text.setMinimumHeight(620)
                layout.addWidget(text)

        return _Window()


def _list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _value_at(row: dict[str, Any], dotted_key: str) -> Any:
    value: Any = row
    for part in dotted_key.split("."):
        if not isinstance(value, dict):
            return ""
        value = value.get(part)
    return value


def _format_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _format_cell(key: str, value: Any) -> str:
    text = _format_value(value)
    key_l = key.lower()
    if not text:
        return ""
    if any(part in key_l for part in ("fingerprint", "install", "network_tag", "request_id")):
        return _short_ref(text)
    if key_l == "issue_url":
        return "Linear issue" if text.startswith("http") else text
    return text


def _short_ref(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= 14:
        return text
    return f"{text[:10]}..."


def _clean_payload(value: Any) -> Any:
    """Keep Qt/dynamic values JSON-friendly before they hit Pydantic."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return {str(key): _clean_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


_NETWORK_ADMIN_STYLE = """
QMainWindow, QWidget {
  background-color: #061019;
}
QFrame#TopNav {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #071422, stop:0.55 #0c1b2c, stop:1 #081521);
  border-bottom: 1px solid rgba(92,168,255,0.22);
}
QLabel#BrandMark {
  min-width: 34px;
  min-height: 34px;
  border-radius: 11px;
  padding: 2px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffbf59, stop:0.45 #fff4bf, stop:1 #43d8e8);
  color: #03111a;
  font-weight: 900;
}
QLabel#Brand {
  color: #edf6ff;
  font-size: 15px;
  font-weight: 900;
  letter-spacing: 1px;
  text-transform: uppercase;
}
QLabel#Kicker {
  color: #9fb4c9;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 1px;
  text-transform: uppercase;
}
QLabel#Title {
  color: #fff4df;
  font-size: 22px;
  font-weight: 900;
}
QLabel#Metric {
  font-size: 26px;
  color: #ffffff;
  font-weight: 900;
}
QFrame#HeroPanel {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,191,89,0.18), stop:0.45 rgba(15,25,38,0.98), stop:1 rgba(67,216,232,0.08));
  border: 1px solid rgba(145,167,192,0.24);
  border-radius: 18px;
}
QFrame#Panel {
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(15,26,39,0.98), stop:1 rgba(9,18,29,0.98));
  border: 1px solid rgba(35,54,74,0.92);
  border-radius: 14px;
}
QFrame#Card {
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,191,89,0.13), stop:0.04 rgba(255,191,89,0.28), stop:0.05 rgba(15,26,39,0.98), stop:1 rgba(9,18,29,0.98));
  border: 1px solid rgba(35,54,74,0.95);
  border-radius: 14px;
}
QFrame#FilterBar, QFrame#PagerRow {
  background: rgba(9,18,29,0.82);
  border: 1px solid rgba(35,54,74,0.82);
  border-radius: 13px;
}
QLineEdit, QComboBox, QSpinBox {
  background: #07111b;
  color: #edf6ff;
  border: 1px solid rgba(92,168,255,0.26);
  border-radius: 10px;
  padding: 8px 10px;
  selection-background-color: rgba(67,216,232,0.35);
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
  border-color: rgba(67,216,232,0.75);
}
QCheckBox {
  color: #cfe0f2;
  font-weight: 700;
}
QTableWidget {
  background: #081421;
  alternate-background-color: #0c1a29;
  color: #edf6ff;
  border: 1px solid rgba(35,54,74,0.92);
  border-radius: 12px;
  gridline-color: rgba(35,54,74,0.75);
  selection-background-color: rgba(92,168,255,0.24);
  selection-color: #ffffff;
}
QHeaderView::section {
  background: #111d2b;
  color: #9fb4c9;
  border: 0;
  border-right: 1px solid rgba(35,54,74,0.8);
  border-bottom: 1px solid rgba(35,54,74,0.9);
  padding: 9px 8px;
  font-size: 11px;
  font-weight: 900;
}
QPushButton {
  background: #172638;
  border: 1px solid rgba(145,167,192,0.16);
  border-radius: 11px;
  color: #edf6ff;
  font-weight: 850;
  padding: 8px 11px;
}
QPushButton:hover {
  border-color: rgba(67,216,232,0.48);
  background: rgba(92,168,255,0.20);
}
QPushButton:disabled {
  color: rgba(237,246,255,0.36);
  background: rgba(23,38,56,0.48);
}
QPushButton#NavButton {
  min-height: 30px;
  border-radius: 12px;
}
QPushButton#NavButton:checked {
  border-color: rgba(255,191,89,0.82);
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,191,89,0.24), stop:1 rgba(92,168,255,0.15));
}
QLabel#AuthChip, QLabel#OperatorChip, QLabel#ClockChip {
  color: #d8e7f8;
  background: rgba(145,167,192,0.12);
  border: 1px solid rgba(145,167,192,0.22);
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 11px;
  font-weight: 900;
}
QLabel#AuthChip[connected="true"] {
  color: #b9ffd9;
  background: rgba(42,208,127,0.16);
  border-color: rgba(42,208,127,0.42);
}
QLabel#AuthChip[connected="false"] {
  color: #ffd0cd;
  background: rgba(255,113,109,0.14);
  border-color: rgba(255,113,109,0.34);
}
QLabel#OperatorChip {
  color: #ffe3a7;
  background: rgba(255,191,89,0.14);
  border-color: rgba(255,191,89,0.36);
}
QFrame#DangerPanel {
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.35);
  border-radius: 14px;
}
QPushButton#Danger {
  background: rgba(239,68,68,0.20);
  border-color: rgba(239,68,68,0.50);
  color: #ffd0d0;
}
"""


if __name__ == "__main__":  # pragma: no cover - manual Qt entrypoint
    main()
