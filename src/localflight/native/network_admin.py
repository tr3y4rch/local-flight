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

from localflight.native.api_client import NativeApiError, RelayAdminClient
from localflight.native.qt_compat import import_qt

ADMIN_ENDPOINTS = {
    "overview": "/admin/api/overview",
    "usage": "/admin/api/usage",
    "schedules": "/admin/api/schedules",
    "surfaces": "/admin/api/surfaces",
    "activations": "/admin/api/activations",
    "reports": "/admin/api/reports",
}


def main() -> None:
    try:
        QtCore, _QtGui, QtWidgets = import_qt()
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
        app.setApplicationName("Local Flight Network Admin")
        window = NetworkAdminWindow(QtCore, QtWidgets)
        window.resize(1280, 820)
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
                self.setStyleSheet(_STYLE)
                self.client: RelayAdminClient | None = None
                self.payloads: dict[str, dict[str, Any]] = {}
                self._refreshing = False

                root = QtWidgets.QWidget()
                layout = QtWidgets.QVBoxLayout(root)
                layout.setContentsMargins(14, 14, 14, 14)
                layout.setSpacing(10)

                login = QtWidgets.QHBoxLayout()
                self.url = QtWidgets.QLineEdit(
                    os.environ.get("LOCALFLIGHT_NETWORK_ADMIN_URL", "https://localflight-community-relay.fly.dev/admin")
                )
                self.user = QtWidgets.QLineEdit(os.environ.get("LOCALFLIGHT_NETWORK_ADMIN_USER", "admin"))
                self.password = QtWidgets.QLineEdit()
                self.password.setEchoMode(QtWidgets.QLineEdit.Password)
                self.connect_btn = QtWidgets.QPushButton("Connect")
                self.refresh_btn = QtWidgets.QPushButton("Refresh")
                self.auto_refresh = QtWidgets.QCheckBox("Auto-refresh")
                self.auto_refresh.setChecked(True)
                self.refresh_interval = QtWidgets.QSpinBox()
                self.refresh_interval.setRange(10, 600)
                self.refresh_interval.setValue(30)
                self.refresh_interval.setSuffix("s")
                self.status = QtWidgets.QLabel("Operator-only console. Mutating actions require admin auth.")
                login.addWidget(QtWidgets.QLabel("Relay"))
                login.addWidget(self.url, 3)
                login.addWidget(QtWidgets.QLabel("User"))
                login.addWidget(self.user)
                login.addWidget(QtWidgets.QLabel("Password"))
                login.addWidget(self.password)
                login.addWidget(self.connect_btn)
                login.addWidget(self.refresh_btn)
                login.addWidget(self.auto_refresh)
                login.addWidget(self.refresh_interval)
                layout.addLayout(login)
                layout.addWidget(self.status)

                self.tabs = QtWidgets.QTabWidget()
                self.pages: dict[str, Any] = {}
                for key, label in (
                    ("overview", "Overview"),
                    ("providers", "Providers"),
                    ("usage", "Usage"),
                    ("schedules", "Schedules"),
                    ("surfaces", "Surfaces"),
                    ("activations", "Activations"),
                    ("reports", "Reports"),
                    ("raw", "Raw"),
                ):
                    page = self._scroll_page()
                    self.pages[key] = page
                    self.tabs.addTab(page, label)
                layout.addWidget(self.tabs, 1)
                self.setCentralWidget(root)

                self.connect_btn.clicked.connect(self.connect_relay)
                self.refresh_btn.clicked.connect(lambda: self.refresh_all())
                self.refresh_interval.valueChanged.connect(self._set_refresh_interval)
                self.timer = QtCore.QTimer(self)
                self.timer.timeout.connect(self._auto_refresh_tick)
                self._set_refresh_interval(self.refresh_interval.value())
                self.timer.start()

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

            def _card(self, title: str, value: str, detail: str = "") -> Any:
                box = self.QtWidgets.QFrame()
                box.setObjectName("Card")
                layout = self.QtWidgets.QVBoxLayout(box)
                layout.addWidget(self._label(title, "Kicker"))
                layout.addWidget(self._label(value, "Metric"))
                if detail:
                    layout.addWidget(self._label(detail, "Muted"))
                return box

            def _table(self, rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> Any:
                table = self.QtWidgets.QTableWidget(len(rows), len(columns))
                table.setHorizontalHeaderLabels([label for _key, label in columns])
                table.verticalHeader().setVisible(False)
                table.setAlternatingRowColors(True)
                table.setEditTriggers(self.QtWidgets.QAbstractItemView.NoEditTriggers)
                table.setSelectionBehavior(self.QtWidgets.QAbstractItemView.SelectRows)
                table.horizontalHeader().setStretchLastSection(True)
                for row_idx, row in enumerate(rows):
                    for col_idx, (key, _label) in enumerate(columns):
                        value = _value_at(row, key)
                        item = self.QtWidgets.QTableWidgetItem(_format_value(value))
                        item.setToolTip(_format_value(value))
                        table.setItem(row_idx, col_idx, item)
                table.resizeColumnsToContents()
                table.setMinimumHeight(min(440, max(140, 46 + len(rows) * 30)))
                return table

            def _action_button(self, label: str, fn: Callable[[], None], danger: bool = False) -> Any:
                button = self.QtWidgets.QPushButton(label)
                if danger:
                    button.setObjectName("Danger")
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

            def _button_row(self, actions: list[tuple[str, Callable[[], None], bool]]) -> Any:
                row = self.QtWidgets.QWidget()
                layout = self.QtWidgets.QHBoxLayout(row)
                layout.setContentsMargins(0, 0, 0, 0)
                for label, fn, danger in actions:
                    layout.addWidget(self._action_button(label, fn, danger))
                layout.addStretch(1)
                return row

            def connect_relay(self) -> None:
                self.client = RelayAdminClient(
                    base_url=self.url.text().strip(),
                    username=self.user.text().strip() or "admin",
                    password=self.password.text(),
                )
                self.refresh_all()

            def refresh_all(self, *, silent: bool = False) -> None:
                if self.client is None:
                    if not silent:
                        self.status.setText("Enter relay URL and admin credentials, then connect.")
                    return
                if self._refreshing:
                    return
                self._refreshing = True
                current_tab = self.tabs.currentIndex()
                errors: list[str] = []
                try:
                    for key, path in ADMIN_ENDPOINTS.items():
                        try:
                            self.payloads[key] = self.client.get_json(path)
                        except NativeApiError as exc:
                            errors.append(f"{key}: {exc}")
                    self._render_all()
                    self.tabs.setCurrentIndex(current_tab)
                    if errors:
                        self.status.setText(" | ".join(errors[:2]))
                    else:
                        stamp = self.payloads.get("overview", {}).get("generated_at", "")
                        self.status.setText(f"Connected. Snapshot refreshed {stamp}.")
                finally:
                    self._refreshing = False

            def _set_refresh_interval(self, seconds: int) -> None:
                self.timer.setInterval(max(10, int(seconds)) * 1000)

            def _auto_refresh_tick(self) -> None:
                if self.client is None or not self.auto_refresh.isChecked():
                    return
                if self._action_form_has_focus():
                    self.status.setText("Auto-refresh paused while editing an operator action.")
                    return
                self.refresh_all(silent=True)

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
                self._render_overview()
                self._render_providers()
                self._render_usage()
                self._render_schedules()
                self._render_surfaces()
                self._render_activations()
                self._render_reports()
                self._render_raw()

            def _render_overview(self) -> None:
                layout = self._clear("overview")
                overview = self.payloads.get("overview", {})
                counts = overview.get("counts") if isinstance(overview.get("counts"), dict) else {}
                schedule = overview.get("shared_schedule") if isinstance(overview.get("shared_schedule"), dict) else {}
                surface = overview.get("surface_cache") if isinstance(overview.get("surface_cache"), dict) else {}
                providers = overview.get("providers") if isinstance(overview.get("providers"), dict) else {}

                layout.addWidget(self._label("Network Overview", "Title"))
                grid = self.QtWidgets.QGridLayout()
                cards = [
                    self._card("Usage rows", str(counts.get("usage_rows", 0)), f"Month {overview.get('month', '')}"),
                    self._card("Schedule cache", str(counts.get("schedule_snapshots", 0)), f"{schedule.get('cache_hits', 0)} hits"),
                    self._card("Upstream pulls", str(schedule.get("upstream_pulls", 0)), f"{schedule.get('client_accesses', 0)} client accesses"),
                    self._card("Surface cache", str(counts.get("surface_snapshots", 0)), f"{surface.get('cache_hits', 0)} hits"),
                    self._card("Activation queue", str(counts.get("activation_requests_pending", 0)), "Pending/manual review"),
                    self._card("Reports 24h", str(counts.get("reports_24h", 0)), "Sanitized gateway events"),
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
                self.aviationstack_key = self._form_line("Paste replacement AviationStack key", password=True)
                self.rapidapi_key = self._form_line("Paste replacement RapidAPI key", password=True)
                layout.addWidget(self.aviationstack_key)
                layout.addWidget(self.rapidapi_key)
                layout.addWidget(
                    self._button_row(
                        [
                            ("Save provider keys", self._save_providers, False),
                            ("Clear AviationStack override", lambda: self._clear_provider("aviationstack"), True),
                            ("Clear RapidAPI override", lambda: self._clear_provider("rapidapi"), True),
                        ]
                    )
                )
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
                layout.addWidget(
                    self._button_row(
                        [
                            ("Reset all monthly counters", lambda: self._reset_counter("all"), True),
                            ("Reset schedule counters", lambda: self._reset_counter("service", service="aviationstack"), True),
                            ("Reset radar counters", lambda: self._reset_counter("service", service="radar"), True),
                            ("Clear request log", lambda: self._reset_counter("logs"), True),
                            ("Clean setup trial state", self._clean_trial, True),
                        ]
                    )
                )
                layout.addWidget(self._label("Summary", "Section"))
                layout.addWidget(self._table(_list(usage.get("summary")), [("service", "Service"), ("plan", "Plan"), ("calls", "Calls"), ("subjects", "Subjects"), ("last_seen", "Last seen")]))
                layout.addWidget(self._label("Install/service rows", "Section"))
                layout.addWidget(self._table(_list(usage.get("rows")), [("subject.kind", "Kind"), ("subject.fingerprint", "Fingerprint"), ("subject.tag", "Network"), ("service", "Service"), ("plan", "Plan"), ("calls", "Calls"), ("last_seen", "Last seen")]))
                self.correct_total = self.QtWidgets.QSpinBox()
                self.correct_total.setRange(0, 100_000_000)
                self.correct_total.setPrefix("Known schedule total ")
                self.correct_total.setProperty("lf_action_form", True)
                layout.addWidget(self.correct_total)
                layout.addWidget(self._button_row([("Correct schedule total", self._correct_schedule_total, False)]))
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
                layout.addWidget(self._table(_list(schedules.get("snapshots")), [("airport_iata", "Airport"), ("timezone", "Timezone"), ("client_accesses", "Client accesses"), ("upstream_pulls", "Upstream pulls"), ("cache_hits", "Hits"), ("last_cache_state", "State"), ("updated_at", "Updated"), ("last_error", "Error")]))
                layout.addWidget(self._label("Live client interests", "Section"))
                layout.addWidget(self._table(_list(schedules.get("client_interests")), [("install_fingerprint", "Install"), ("plan", "Plan"), ("airport_iata", "Airport"), ("timezone", "Timezone"), ("refresh_seconds", "Refresh"), ("last_seen", "Last seen")]))
                layout.addStretch(1)

            def _render_surfaces(self) -> None:
                layout = self._clear("surfaces")
                surfaces = self.payloads.get("surfaces", {})
                layout.addWidget(self._label("Airport Surface Cache", "Title"))
                layout.addWidget(self._label(f"Relay surface overlay enabled: {surfaces.get('enabled')}", "Muted"))
                layout.addWidget(self._table(_list(surfaces.get("snapshots")), [("airport_iata", "IATA"), ("airport_icao", "ICAO"), ("feature_count", "Features"), ("request_count", "Requests"), ("cache_hits", "Hits"), ("refresh_count", "Refreshes"), ("last_cache_state", "State"), ("updated_at", "Updated"), ("last_error", "Error")]))
                layout.addStretch(1)

            def _render_activations(self) -> None:
                layout = self._clear("activations")
                activations = self.payloads.get("activations", {})
                layout.addWidget(self._label("Activations", "Title"))
                create = self.QtWidgets.QHBoxLayout()
                self.token_label = self._form_line("Token label")
                self.schedule_limit = self._form_spin(value=10_000, prefix="Schedule ")
                self.radar_limit = self._form_spin(value=10_000, prefix="Radar ")
                create_button = self.QtWidgets.QPushButton("Create managed token")
                create_button.clicked.connect(self._create_token)
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
                        ("Rotate", lambda r=token_ref, p=prefix: self._token_action(r, "rotate", p), True),
                        ("Restore" if revoked else "Revoke", lambda r=token_ref, p=prefix, a=("reactivate" if revoked else "revoke"): self._token_action(r, a, p), True),
                        ("Unbind", lambda r=token_ref, p=prefix: self._token_action(r, "unbind", p), False),
                        ("Reset", lambda r=token_ref, p=prefix: self._reset_counter("token", token_ref=r, token_prefix=p), True),
                        ("Delete", lambda r=token_ref, p=prefix: self._token_action(r, "delete", p), True),
                    ]
                    table.setCellWidget(row_idx, table.columnCount() - 1, self._button_row(actions))
                table.resizeColumnsToContents()
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
                        ("Issue", lambda r=request_id, d=display_id: self._request_action(r, "approve", d), False),
                        ("Dismiss", lambda r=request_id, d=display_id: self._request_action(r, "reject", d), True),
                        ("Delete", lambda r=request_id, d=display_id: self._request_action(r, "delete", d), True),
                    ]
                    request_table.setCellWidget(row_idx, request_table.columnCount() - 1, self._button_row(actions))
                request_table.resizeColumnsToContents()
                layout.addWidget(request_table)

                layout.addWidget(self._label("Blocked installs", "Section"))
                blocked_rows = _list(activations.get("blocked_installs"))
                blocked = self._table(blocked_rows, [("install_fingerprint", "Install"), ("reason", "Reason"), ("created_at", "Created")])
                blocked.setColumnCount(blocked.columnCount() + 1)
                blocked.setHorizontalHeaderItem(blocked.columnCount() - 1, self.QtWidgets.QTableWidgetItem("Actions"))
                for row_idx, row in enumerate(blocked_rows):
                    fp = str(row.get("install_fingerprint") or "")
                    install_ref = str(row.get("action_ref") or row.get("install_ref") or fp)
                    blocked.setCellWidget(row_idx, blocked.columnCount() - 1, self._button_row([("Unblock", lambda r=install_ref, f=fp: self._install_access("unblock", r, f), True)]))
                blocked.resizeColumnsToContents()
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
                layout.addWidget(self._table(_list(reports.get("summary_24h")), [("report_type", "Type"), ("origin", "Origin"), ("team", "Team"), ("status", "Status"), ("reports", "Reports"), ("installs", "Installs"), ("last_seen", "Last seen")]))
                layout.addWidget(self._label("Recent sanitized events", "Section"))
                layout.addWidget(self._table(_list(reports.get("recent_events")), [("ts", "Time"), ("install_fingerprint", "Install"), ("network_tag", "Network"), ("report_type", "Type"), ("origin", "Origin"), ("team", "Team"), ("status", "Status")]))
                layout.addWidget(self._label("Dedupe groups", "Section"))
                layout.addWidget(self._table(_list(reports.get("dedupe")), [("team", "Team"), ("report_type", "Type"), ("origin", "Origin"), ("count", "Count"), ("issue_url", "Issue"), ("last_seen", "Last seen")]))
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


_STYLE = """
QWidget {
  background: #081018;
  color: #e6f3fb;
  font-family: "Segoe UI", "Helvetica Neue", sans-serif;
  font-size: 13px;
}
QLabel#Title {
  font-size: 24px;
  font-weight: 800;
  color: #ffffff;
}
QLabel#Section {
  margin-top: 10px;
  font-size: 16px;
  font-weight: 800;
  color: #b7e7ff;
}
QLabel#Kicker {
  color: #72a6be;
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
QLabel#Metric {
  color: #ffffff;
  font-size: 28px;
  font-weight: 800;
}
QLabel#Muted {
  color: #8eb3c5;
}
QFrame#Card {
  background: #0d1824;
  border: 1px solid #224059;
  border-radius: 14px;
}
QLineEdit, QPlainTextEdit, QSpinBox, QTableWidget, QTabWidget::pane {
  background: #0d1824;
  border: 1px solid #224059;
  border-radius: 8px;
  color: #e6f3fb;
}
QHeaderView::section {
  background: #102335;
  color: #b7e7ff;
  border: none;
  padding: 7px;
}
QTableWidget {
  alternate-background-color: #0a1420;
  gridline-color: #20384c;
}
QPlainTextEdit {
  font-family: Consolas, "SF Mono", monospace;
}
QPushButton {
  background: #174866;
  border: 1px solid #347ca6;
  border-radius: 8px;
  padding: 7px 12px;
  color: #ffffff;
}
QPushButton:hover {
  background: #1f5f85;
}
QPushButton#Danger {
  background: #61301f;
  border-color: #a95d3c;
}
QTabBar::tab {
  padding: 8px 12px;
  background: #102335;
  border-top-left-radius: 7px;
  border-top-right-radius: 7px;
}
QTabBar::tab:selected {
  background: #195073;
}
"""


if __name__ == "__main__":  # pragma: no cover - manual Qt entrypoint
    main()
