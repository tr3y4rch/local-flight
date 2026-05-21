"""Native Settings page.

Settings is a product-facing client surface, not an operator console.  Keep the
local FastAPI backend as the source of truth and organize controls around the
things an end user changes most often.
"""
from __future__ import annotations

import webbrowser
from concurrent.futures import Future
from datetime import datetime, timezone
from typing import Any, Callable

from localflight.companion_pairing import pairing_gateway_payload, pairing_qr_png_bytes
from localflight.core.settings_options import (
    DIAGNOSTICS_OPTIONS,
    OUTPUT_OPTIONS,
    REFRESH_OPTIONS,
    SKIN_OPTIONS,
    SOURCE_OPTIONS,
    THEME_OPTIONS,
    option_label,
)
from localflight.native.api_client import LocalApiClient
from localflight.native.async_tools import API_EXECUTOR
from localflight.native.design import (
    SECTION_EMOJI,
    bundled_doc,
    colors_for,
    label,
    list_payload,
    native_stylesheet,
    paint_emoji,
    panel,
    scroll_page,
)
from localflight.native.service import NativeApiService
from localflight.native.widgets import DisclosureCard
from localflight.storage.profiles import list_profiles


DOC_CHOICES = (
    ("README", "readme"),
    ("Install guide", "install"),
    ("Display modes", "display-modes"),
    ("Privacy", "privacy"),
    ("Release notes", "changelog"),
    ("Third-party notices", "third-party"),
)


class SettingsScreen:  # pragma: no cover - optional Qt runtime
    """Standalone native Settings screen with browser-route parity."""

    def __init__(
        self,
        QtCore: Any,
        QtGui: Any,
        QtWidgets: Any,
        client: LocalApiClient,
        base_url: str,
        on_rerun_setup: Callable[[], None] | None = None,
    ) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.base_url = base_url.rstrip("/")
        self.on_rerun_setup = on_rerun_setup
        self.current_doc_slug = "readme"
        self._airport_search_future: Future[Any] | None = None
        self._last_airport_query = ""
        self._skin_buttons: dict[str, Any] = {}
        self._surface_check_future: Future[Any] | None = None
        self._current_theme = "dark"
        self._current_skin = "standard"
        screen = self.QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        self.available_width = available.width() if available is not None else 1400
        self.compact_geometry = available is not None and available.width() < 1320

        self.widget, self.layout = scroll_page(QtWidgets)
        self.widget.setMinimumWidth(0)
        self.layout.setContentsMargins(24, 20, 24, 20)
        self.layout.setSpacing(14)

        self.search_timer = QtCore.QTimer(self.widget)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._start_airport_search)
        self.search_poll_timer = QtCore.QTimer(self.widget)
        self.search_poll_timer.setInterval(50)
        self.search_poll_timer.timeout.connect(self._poll_airport_search)
        self.surface_check_timer = QtCore.QTimer(self.widget)
        self.surface_check_timer.setInterval(100)
        self.surface_check_timer.timeout.connect(self._poll_surface_check)

        self._build_header()
        self._build_status_band()
        self._build_main_controls()
        self._build_radar_devices()
        self._build_profiles()
        self._build_companion_pairing()
        self._build_advanced_timing()
        self._build_diagnostics_maintenance()
        self._build_relay_details()
        self._build_help_docs()

        self.status = label(QtWidgets, "Settings ready. Refresh to load the current local config.", "Muted", wrap=True)
        self.loading_indicator = QtWidgets.QProgressBar()
        self.loading_indicator.setObjectName("LoadingProgress")
        self.loading_indicator.setRange(0, 0)
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.setFixedHeight(7)
        self.loading_indicator.hide()
        self.layout.addWidget(self.loading_indicator)
        self.layout.addWidget(self.status)
        self.layout.addStretch(1)
        self.open_doc("readme")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _build_header(self) -> None:
        head = self.QtWidgets.QHBoxLayout()
        title_col = self.QtWidgets.QVBoxLayout()
        title_col.setSpacing(4)
        title_col.addWidget(label(self.QtWidgets, "⚙️  Settings", "Title"))
        title_col.addWidget(
            label(
                self.QtWidgets,
                "Client controls for the local board. Relay operator tools stay in Network Admin.",
                "Muted",
                wrap=True,
            )
        )
        head.addLayout(title_col, 1)
        refresh = self.QtWidgets.QPushButton("Refresh")
        refresh.setObjectName("Quiet")
        refresh.clicked.connect(self.refresh)
        save = self.QtWidgets.QPushButton("Apply settings")
        save.clicked.connect(self.save)
        self.save_button = save
        head.addWidget(refresh)
        head.addWidget(save)
        self.layout.addLayout(head)

    def _build_status_band(self) -> None:
        box, band = panel(self.QtWidgets, "\U0001F4CB  Client State")
        grid = self.QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.current_airport_value = self._status_card("Airport", "---", "No config loaded yet.", "airport")
        self.current_source_value = self._status_card("Data", "-", "Real schedule or VATSIM source.", "source")
        self.current_refresh_value = self._status_card("Refresh", "-", "Provider-friendly cadence.", "clock")
        self.current_relay_value = self._status_card("Relay", "-", "No tokens or secrets shown here.", "relay")
        self.current_surface_value = self._status_card("Surface", "-", "Radar ground drawing state.", "radar")
        columns = 1 if self.available_width < 900 else 2 if self.compact_geometry else 5
        for index, widget in enumerate(
            (
                self.current_airport_value,
                self.current_source_value,
                self.current_refresh_value,
                self.current_relay_value,
                self.current_surface_value,
            )
        ):
            grid.addWidget(widget, index // columns, index % columns)
        band.addLayout(grid)
        self.current_layout = band
        self.layout.addWidget(box)

    def _status_card(self, title: str, value: str, detail: str, icon: str) -> Any:
        widget = self.QtWidgets.QFrame()
        widget.setObjectName("PreviewCard")
        row = self.QtWidgets.QHBoxLayout(widget)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        row.addWidget(self._settings_icon(icon))
        text_col = self.QtWidgets.QVBoxLayout()
        text_col.setSpacing(1)
        kicker = label(self.QtWidgets, title, "Kicker")
        value_label = label(self.QtWidgets, value, "Metric")
        detail_label = label(self.QtWidgets, detail, "Dim", wrap=True)
        text_col.addWidget(kicker)
        text_col.addWidget(value_label)
        text_col.addWidget(detail_label)
        row.addLayout(text_col, 1)
        widget.value_label = value_label
        widget.detail_label = detail_label
        return widget

    def _build_main_controls(self) -> None:
        grid = self.QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        if self.compact_geometry:
            grid.addWidget(self._build_airport_data(), 0, 0)
            grid.addWidget(self._build_appearance(), 1, 0)
        else:
            grid.addWidget(self._build_airport_data(), 0, 0)
            grid.addWidget(self._build_appearance(), 0, 1)
        self.layout.addLayout(grid)

    def _settings_icon(self, kind: str) -> Any:
        QtCore = self.QtCore
        QtGui = self.QtGui
        QtWidgets = self.QtWidgets
        outer = self

        class _SettingsIcon(QtWidgets.QWidget):
            def __init__(self, icon_kind: str) -> None:
                super().__init__()
                self.icon_kind = icon_kind
                self.setFixedSize(30, 30)

            def paintEvent(self, _event: Any) -> None:
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                rect = self.rect().adjusted(3, 3, -3, -3)
                colors = colors_for(outer._current_theme, outer._current_skin)
                accent = QtGui.QColor(colors["blue"])
                bg = QtGui.QColor(colors["blue"])
                bg.setAlpha(26)
                painter.setPen(QtGui.QPen(accent, 1.4))
                painter.setBrush(bg)
                painter.drawRoundedRect(rect, 8, 8)
                emoji = SECTION_EMOJI.get(self.icon_kind, "")
                if emoji:
                    paint_emoji(QtCore, QtGui, painter, rect, emoji, point_size=14)

        return _SettingsIcon(kind)

    def _build_airport_data(self) -> Any:
        box, layout = panel(self.QtWidgets, "\U0001F6EC  Airport & Source")
        layout.addWidget(
            label(
                self.QtWidgets,
                "Search by airport name, city, IATA, or ICAO. Selecting a result fills the local identity used by FIDS, Radar, Matrix, and the LAN browser UI.",
                "Muted",
                wrap=True,
            )
        )
        self.airport_search = self.QtWidgets.QLineEdit()
        self.airport_search.setPlaceholderText("Search airport, e.g. Zurich, HKG, Heathrow...")
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMaximumHeight(170)
        self.airport_results.hide()
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.airport_selected = label(self.QtWidgets, "No airport selected from search yet.", "Muted", wrap=True)
        layout.addWidget(self.airport_search)
        layout.addWidget(self.airport_results)
        layout.addWidget(self.airport_selected)

        form = self.QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.airport_iata = self._readonly_line()
        self.airport_icao = self._readonly_line()
        self.timezone = self._readonly_line()
        self.source = self.QtWidgets.QComboBox()
        for option in SOURCE_OPTIONS:
            self.source.addItem(option.label, option.value)
        self.refresh_seconds = self.QtWidgets.QComboBox()
        self._populate_refresh_options("real")
        self.source.currentIndexChanged.connect(lambda _idx: self._populate_refresh_options(self._combo_value(self.source, "real")))
        form.addRow("IATA", self.airport_iata)
        form.addRow("ICAO", self.airport_icao)
        form.addRow("Timezone", self.timezone)
        form.addRow("Flight source", self.source)
        form.addRow("Refresh cadence", self.refresh_seconds)
        layout.addLayout(form)
        layout.addWidget(
            label(
                self.QtWidgets,
                "Community Relay shows hourly-or-slower refresh choices when it is the active schedule mode.",
                "Muted",
                wrap=True,
            )
        )
        return box

    def _build_appearance(self) -> Any:
        box, layout = panel(self.QtWidgets, "\U0001F3A8  Appearance")
        form = self.QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.display_name = self.QtWidgets.QLineEdit()
        self.display_name.setPlaceholderText("Local Flight")
        self.theme = self.QtWidgets.QComboBox()
        for option in THEME_OPTIONS:
            self.theme.addItem(option.label, option.value)
        self.skin = self.QtWidgets.QComboBox()
        for option in SKIN_OPTIONS:
            self.skin.addItem(option.label, option.value)
        form.addRow("Display name", self.display_name)
        form.addRow("Theme", self.theme)
        form.addRow("Skin", self.skin)
        layout.addLayout(form)

        swatches = self.QtWidgets.QGridLayout()
        swatches.setHorizontalSpacing(8)
        swatches.setVerticalSpacing(8)
        for index, option in enumerate(SKIN_OPTIONS):
            button = self.QtWidgets.QPushButton(option.label)
            button.setCheckable(True)
            button.setProperty("skin", option.value)
            button.setProperty("skin_fg", option.fg)
            button.setProperty("skin_bg", option.bg)
            button.setProperty("skin_accent", option.accent)
            button.setObjectName("Quiet")
            button.setToolTip(option.description)
            button.setStyleSheet(
                f"QPushButton {{ background: {option.bg}; color: {option.fg}; border: 1px solid {option.accent}; }}"
            )
            button.clicked.connect(lambda _checked=False, selected=option.value: self._select_skin(selected))
            self._skin_buttons[option.value] = button
            swatches.addWidget(button, index // 4, index % 4)
        self.theme.currentIndexChanged.connect(lambda _idx: self._preview_design())
        self.skin.currentIndexChanged.connect(lambda _idx: self._preview_design())
        layout.addWidget(label(self.QtWidgets, "Skins affect native, LAN browser, and board surfaces without changing flight data.", "Muted", wrap=True))
        layout.addLayout(swatches)
        self._sync_skin_buttons("standard")
        return box

    def _build_radar_devices(self) -> None:
        self.outputs_radar_group, self.outputs_radar_body, layout = self._collapsible_section(
            "Outputs & Radar",
            subtitle="Choose display outputs and the optional radar ground drawing layer.",
            emoji="\U0001F6F0",  # 🛰
        )
        self.surface = self.QtWidgets.QCheckBox("Runway and airport surface overlay")
        self.surface.stateChanged.connect(self._surface_changed)
        layout.addWidget(self.surface)
        layout.addWidget(
            label(
                self.QtWidgets,
                "Optional surface drawing depends on cached local or relay data. It is a visual hobbyist layer, not an operational navigation source.",
                "Muted",
                wrap=True,
            )
        )
        surface_row = self.QtWidgets.QHBoxLayout()
        self.apply_surface_button = self.QtWidgets.QPushButton("Apply radar overlay")
        self.apply_surface_button.setObjectName("Quiet")
        self.apply_surface_button.clicked.connect(self.apply_surface_overlay)
        self.surface_status = label(self.QtWidgets, "Surface overlay has not been checked yet.", "Muted", wrap=True)
        self.surface_progress = self.QtWidgets.QProgressBar()
        self.surface_progress.setObjectName("LoadingProgress")
        self.surface_progress.setRange(0, 0)
        self.surface_progress.setTextVisible(False)
        self.surface_progress.setFixedHeight(7)
        self.surface_progress.hide()
        surface_row.addWidget(self.apply_surface_button)
        surface_row.addWidget(self.surface_status, 1)
        layout.addLayout(surface_row)
        layout.addWidget(self.surface_progress)
        outputs = self.QtWidgets.QHBoxLayout()
        labels = {option.value: option.label for option in OUTPUT_OPTIONS}
        self.output_web = self.QtWidgets.QCheckBox(labels.get("web", "LAN browser UI"))
        self.output_matrix = self.QtWidgets.QCheckBox(labels.get("matrix", "Matrix panel"))
        self.output_hdmi = self.QtWidgets.QCheckBox(labels.get("hdmi", "HDMI display"))
        outputs.addWidget(self.output_web)
        outputs.addWidget(self.output_matrix)
        outputs.addWidget(self.output_hdmi)
        outputs.addStretch(1)
        layout.addWidget(label(self.QtWidgets, "Display outputs", "Kicker"))
        layout.addLayout(outputs)

    def _build_profiles(self) -> None:
        self.profiles_group, self.profiles_body, layout = self._collapsible_section(
            "Profiles",
            subtitle="Save airport, source, and board presets for quick swaps.",
            emoji="\U0001F464",  # 👤
        )
        layout.addWidget(label(self.QtWidgets, "Save airport and board presets for quick swaps.", "Muted", wrap=True))
        row = self.QtWidgets.QHBoxLayout()
        self.profile_combo = self.QtWidgets.QComboBox()
        self.profile_name = self.QtWidgets.QLineEdit()
        self.profile_name.setPlaceholderText("New profile name")
        load = self.QtWidgets.QPushButton("Load")
        save = self.QtWidgets.QPushButton("Save current")
        delete = self.QtWidgets.QPushButton("Delete")
        delete.setObjectName("Quiet")
        load.clicked.connect(self.load_profile)
        save.clicked.connect(self.save_profile)
        delete.clicked.connect(self.delete_profile)
        row.addWidget(self.profile_combo, 2)
        row.addWidget(load)
        row.addWidget(self.profile_name, 2)
        row.addWidget(save)
        row.addWidget(delete)
        layout.addLayout(row)

    def _build_help_privacy(self) -> None:
        self._build_companion_pairing()
        self._build_relay_details()
        self._build_help_docs()
        self._build_diagnostics_maintenance()

    def _collapsible_section(
        self,
        title: str,
        *,
        subtitle: str = "",
        emoji: str = "",
        expanded: bool = False,
    ) -> tuple[Any, Any, Any]:
        """Add a collapsible section as a DisclosureCard.

        Returns ``(card, body, body_layout)`` so existing call-sites that
        treated the old QGroupBox as "the group" keep working.  ``body``
        is the inner frame and ``body_layout`` is the layout content
        should be added to.
        """
        card = DisclosureCard(
            self.QtCore,
            self.QtWidgets,
            title=title,
            subtitle=subtitle,
            emoji=emoji,
            expanded=expanded,
        )
        self.layout.addWidget(card)
        return card, card.body, card.body_layout

    def _build_relay_details(self) -> None:
        self.relay_group, self.relay_body, layout = self._collapsible_section(
            "Relay details",
            subtitle="Community Relay or managed-access status — tokens stay hidden.",
            emoji="\U0001F517",  # 🔗
        )
        grid = self.QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.relay_mode_detail = label(self.QtWidgets, "Loading...", "Muted", wrap=True)
        self.relay_url_detail = label(self.QtWidgets, "Loading...", "Muted", wrap=True)
        self.relay_token_detail = label(self.QtWidgets, "Loading...", "Muted", wrap=True)
        self.relay_access_detail = label(self.QtWidgets, "Loading...", "Muted", wrap=True)
        for index, (title, value) in enumerate(
            (
                ("Access mode", self.relay_mode_detail),
                ("Relay host", self.relay_url_detail),
                ("Token state", self.relay_token_detail),
                ("What it means", self.relay_access_detail),
            )
        ):
            cell = self._detail_cell(title, value)
            grid.addWidget(cell, index // 2, index % 2)
        layout.addLayout(grid)

    def _build_companion_pairing(self) -> None:
        self.companion_group, self.companion_body, layout = self._collapsible_section(
            "Pair Mobile",
            subtitle="QR pairing for LAN Companion devices on the same network.",
            emoji="\U0001F4F1",  # 📱
        )
        layout.addWidget(
            label(
                self.QtWidgets,
                "Scan this from each iPhone/iPad you want to pair. The same QR can be reused by multiple mobile devices on the same LAN.",
                "Muted",
                wrap=True,
            )
        )

        row = self.QtWidgets.QHBoxLayout()
        row.setSpacing(14)
        self.companion_qr_label = self.QtWidgets.QLabel("QR loading...")
        self.companion_qr_label.setObjectName("PreviewCard")
        self.companion_qr_label.setAlignment(self.QtCore.Qt.AlignCenter)
        self.companion_qr_label.setFixedSize(204, 204)
        row.addWidget(self.companion_qr_label)

        details = self.QtWidgets.QVBoxLayout()
        details.setSpacing(8)
        self.companion_count_label = label(self.QtWidgets, "0 paired", "Section")
        self.companion_pairing_url_label = label(self.QtWidgets, "Pairing link loading...", "Muted", wrap=True)
        self.companion_fingerprint_label = label(self.QtWidgets, "Server fingerprint loading...", "Muted", wrap=True)
        self.companion_manual_url_label = label(self.QtWidgets, "Manual URL loading...", "Muted", wrap=True)
        self.companion_entries_label = label(self.QtWidgets, "No mobile check-ins yet.", "Muted", wrap=True)
        details.addWidget(self.companion_count_label)
        details.addWidget(self.companion_pairing_url_label)
        details.addWidget(self.companion_fingerprint_label)
        details.addWidget(self.companion_manual_url_label)
        details.addWidget(self.companion_entries_label, 1)

        controls = self.QtWidgets.QHBoxLayout()
        refresh = self.QtWidgets.QPushButton("Refresh paired devices")
        refresh.setObjectName("Quiet")
        refresh.clicked.connect(self._refresh_companion_gateway)
        copy_pair = self.QtWidgets.QPushButton("Copy pairing link")
        copy_pair.setObjectName("Quiet")
        copy_pair.clicked.connect(self._copy_pairing_link)
        copy_url = self.QtWidgets.QPushButton("Copy LAN URL")
        copy_url.setObjectName("Quiet")
        copy_url.clicked.connect(self._copy_manual_pairing_url)
        reset_companions = self.QtWidgets.QPushButton("Reset paired devices")
        reset_companions.setObjectName("Danger")
        reset_companions.clicked.connect(self._reset_companion_connections)
        controls.addWidget(refresh)
        controls.addWidget(copy_pair)
        controls.addWidget(copy_url)
        controls.addWidget(reset_companions)
        controls.addStretch(1)
        details.addLayout(controls)

        row.addLayout(details, 1)
        layout.addLayout(row)
        self._render_pairing_payload()

    def _build_help_docs(self) -> None:
        self.help_docs_group, self.help_docs_body, layout = self._collapsible_section(
            "Diagnostics & Docs",
            subtitle="Diagnostics mode and the bundled documentation pages.",
            emoji="\U0001F4DA",  # 📚
        )
        self.diagnostics = self.QtWidgets.QComboBox()
        for option in DIAGNOSTICS_OPTIONS:
            self.diagnostics.addItem(option.label, option.value)
        layout.addWidget(label(self.QtWidgets, "Diagnostics mode", "Kicker"))
        layout.addWidget(self.diagnostics)
        layout.addWidget(
            label(
                self.QtWidgets,
                "Reports stay user-triggered unless this install explicitly allows automatic crash diagnostics.",
                "Muted",
                wrap=True,
            )
        )

        docs = self.QtWidgets.QHBoxLayout()
        self.doc_buttons: dict[str, Any] = {}
        for title, slug in DOC_CHOICES:
            button = self.QtWidgets.QPushButton(title)
            button.setCheckable(True)
            button.setObjectName("Quiet")
            button.clicked.connect(lambda _checked=False, s=slug: self.open_doc(s))
            docs.addWidget(button)
            self.doc_buttons[slug] = button
        docs.addStretch(1)
        open_web = self.QtWidgets.QPushButton("Open web copy")
        open_web.setObjectName("Quiet")
        open_web.clicked.connect(lambda: webbrowser.open(f"{self.base_url}/docs/{self.current_doc_slug}"))
        docs.addWidget(open_web)
        layout.addLayout(docs)

        self.doc_title = label(self.QtWidgets, "Project README", "Section")
        self.doc_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.doc_text = self.QtWidgets.QTextEdit()
        self.doc_text.setReadOnly(True)
        self.doc_text.setMinimumHeight(240)
        layout.addWidget(self.doc_title)
        layout.addWidget(self.doc_summary)
        layout.addWidget(self.doc_text)

    def _build_diagnostics_maintenance(self) -> None:
        self.maintenance_group, self.maintenance_body, layout = self._collapsible_section(
            "Maintenance",
            subtitle="Nudge the local scheduler, file a report, or re-run first-time setup.",
            emoji="\U0001F527",  # 🔧
        )
        controls = self.QtWidgets.QHBoxLayout()
        report = self.QtWidgets.QPushButton("Open report form")
        report.setObjectName("Quiet")
        restart = self.QtWidgets.QPushButton("Restart scheduler")
        restart.setObjectName("Quiet")
        reset = self.QtWidgets.QPushButton("Re-run setup")
        reset.setObjectName("Danger")
        report.clicked.connect(lambda: webbrowser.open(f"{self.base_url}/feedback"))
        restart.clicked.connect(self.restart_scheduler)
        reset.clicked.connect(self.reset_setup)
        controls.addWidget(report)
        controls.addWidget(restart)
        controls.addWidget(reset)
        controls.addStretch(1)
        layout.addLayout(controls)

    def _detail_cell(self, title: str, value_widget: Any) -> Any:
        box = self.QtWidgets.QFrame()
        box.setObjectName("PreviewCard")
        layout = self.QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(label(self.QtWidgets, title, "Kicker"))
        layout.addWidget(value_widget)
        return box

    def _build_advanced_timing(self) -> None:
        self.advanced_display_group, self.advanced_display_body, outer = self._collapsible_section(
            "Advanced Board Timing",
            subtitle="Rotation, retention, and kiosk timing. Most users can leave these alone.",
            emoji="⚙️",  # ⚙️
        )
        form_host = self.QtWidgets.QWidget()
        form = self.QtWidgets.QFormLayout(form_host)
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.web_row_limit = self.QtWidgets.QSpinBox()
        self.web_row_limit.setRange(5, 100)
        self.web_rotation = self.QtWidgets.QSpinBox()
        self.web_rotation.setRange(3, 120)
        self.grace = self.QtWidgets.QSpinBox()
        self.grace.setRange(0, 240)
        self.horizon = self.QtWidgets.QSpinBox()
        self.horizon.setRange(1, 48)
        form.addRow("Visible board rows", self.web_row_limit)
        form.addRow("Page rotation seconds", self.web_rotation)
        form.addRow("Past grace minutes", self.grace)
        form.addRow("Future horizon hours", self.horizon)
        outer.addWidget(form_host)

    def _readonly_line(self) -> Any:
        widget = self.QtWidgets.QLineEdit()
        widget.setReadOnly(True)
        return widget

    def _combo_value(self, combo: Any, default: str = "") -> str:
        value = combo.currentData()
        return str(value if value is not None else combo.currentText() or default)

    def _set_combo_value(self, combo: Any, value: Any) -> None:
        idx = combo.findData(value)
        if idx < 0:
            idx = combo.findText(str(value))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _refresh_options_for_source(self, source: str) -> list[Any]:
        try:
            from localflight.sources.web.aviationstack_client import schedule_policy

            policy = schedule_policy(source)
            allowed = {int(value) for value in (policy.get("allowed_refresh_seconds") or [])}
            if allowed:
                return [option for option in REFRESH_OPTIONS if int(option.value) in allowed]
        except Exception:
            pass
        return list(REFRESH_OPTIONS)

    def _populate_refresh_options(self, source: str) -> None:
        current = self.refresh_seconds.currentData()
        self.refresh_seconds.blockSignals(True)
        self.refresh_seconds.clear()
        options = self._refresh_options_for_source(source)
        for option in options:
            self.refresh_seconds.addItem(option.label, option.value)
        if current is not None and self.refresh_seconds.findData(current) >= 0:
            self._set_combo_value(self.refresh_seconds, current)
        elif self.refresh_seconds.findData(3600) >= 0:
            self._set_combo_value(self.refresh_seconds, 3600)
        self.refresh_seconds.blockSignals(False)

    def _select_skin(self, skin: str) -> None:
        self._set_combo_value(self.skin, skin)

    def _sync_skin_buttons(self, skin: str | None = None) -> None:
        active = skin or self._combo_value(self.skin, "standard")
        theme = self._combo_value(self.theme, "dark")
        for key, button in self._skin_buttons.items():
            checked = key == active
            button.setChecked(checked)
            colors = colors_for(theme, key)
            fg = colors.get("text", "#e8f0fe")
            bg = colors.get("panel", "#0d1520")
            accent = colors.get("blue", "#4a9eda")
            border = 2 if checked else 1
            button.setStyleSheet(
                f"QPushButton {{ background: {bg}; color: {fg}; border: {border}px solid {accent}; }}"
            )

    def _preview_design(self) -> None:
        self._current_theme = self._combo_value(self.theme, "dark")
        self._current_skin = self._combo_value(self.skin, "standard")
        self._sync_skin_buttons(self._current_skin)
        try:
            window = self.widget.window()
            if window is not None:
                window.setStyleSheet(native_stylesheet(theme=self._current_theme, skin=self._current_skin))
        except Exception:
            pass

    def _set_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        self.status.setText(text)
        self.status.setObjectName(role)
        self.loading_indicator.setVisible(bool(busy))
        try:
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        except Exception:
            pass
        if busy:
            self.QtWidgets.QApplication.processEvents()

    def refresh(self) -> None:
        self._set_status("Loading current settings from the local server...", busy=True)
        try:
            cfg = self.service.config()
        except Exception as exc:
            self._set_status(f"Settings offline: {exc}", "StatusBad")
            return
        self._populate_config(cfg)
        self._refresh_current(cfg)
        self._refresh_install()
        self._refresh_profiles()
        self._refresh_companion_gateway()
        self._set_status("Current local settings loaded.", "StatusGood")

    def _pairing_payload(self) -> dict[str, object]:
        return pairing_gateway_payload(base_url=self.base_url)

    def _render_pairing_payload(self) -> None:
        payload = self._pairing_payload()
        self._current_pairing_link = str(payload.get("deep_link") or "")
        self._current_manual_pairing_url = str(payload.get("preferred_url") or "")
        self._current_pairing_fingerprint = str(payload.get("server_fingerprint") or "")
        self.companion_pairing_url_label.setText(
            f"QR target: {self._current_manual_pairing_url}\n"
            f"Pairing link: {self._current_pairing_link}"
        )
        self.companion_fingerprint_label.setText(
            f"Server fingerprint: {self._current_pairing_fingerprint or 'unavailable'}"
        )
        manual_urls = payload.get("manual_urls") if isinstance(payload.get("manual_urls"), list) else []
        manual_text = "\n".join(str(item) for item in manual_urls[:3]) or self._current_manual_pairing_url
        self.companion_manual_url_label.setText(
            "Manual URLs, safest first. localflight.local is a fallback when only one Local Flight server is on this LAN:\n"
            f"{manual_text}"
        )

        png = pairing_qr_png_bytes(self._current_pairing_link, size=190)
        if png:
            pixmap = self.QtGui.QPixmap()
            if pixmap.loadFromData(png, "PNG"):
                self.companion_qr_label.setPixmap(pixmap)
                self.companion_qr_label.setText("")
                return
        self.companion_qr_label.setPixmap(self.QtGui.QPixmap())
        self.companion_qr_label.setText("QR unavailable\nCopy the pairing link below.")

    def _refresh_companion_gateway(self) -> None:
        self._render_pairing_payload()
        try:
            payload = self.service.connections()
        except Exception as exc:
            self.companion_count_label.setText("Pairing status unavailable")
            self.companion_entries_label.setText(f"Could not read paired mobile devices: {exc}")
            return

        companions = payload.get("companions") if isinstance(payload.get("companions"), list) else []
        count = int(payload.get("companion_count") or len(companions) or 0)
        self.companion_count_label.setText("1 paired" if count == 1 else f"{count} paired")
        if not companions:
            self.companion_entries_label.setText("No mobile check-ins yet. Scan the QR from each iPhone/iPad to pair.")
            return

        lines = []
        for item in companions[:5]:
            device = str(item.get("device_type") or "device").title()
            os_label = str(item.get("mobile_os") or "Unknown OS")
            version = str(item.get("app_version") or "unknown")
            seen = self._relative_time(str(item.get("last_seen") or ""))
            lines.append(f"{device} - {os_label} - v{version} - {seen}")
        self.companion_entries_label.setText("\n".join(lines))

    def _copy_pairing_link(self) -> None:
        self._render_pairing_payload()
        self.QtWidgets.QApplication.clipboard().setText(getattr(self, "_current_pairing_link", ""))
        self._set_status(
            "Pairing link copied. It is bound to this server fingerprint so mobile can reject the wrong host.",
            "StatusGood",
        )

    def _copy_manual_pairing_url(self) -> None:
        self._render_pairing_payload()
        self.QtWidgets.QApplication.clipboard().setText(getattr(self, "_current_manual_pairing_url", ""))
        self._set_status("Preferred LAN IP copied for mobile setup.", "StatusGood")

    def _reset_companion_connections(self) -> None:
        answer = self.QtWidgets.QMessageBox.question(
            self.widget,
            "Reset paired devices?",
            "Clear this server's remembered mobile companion check-ins? Phones that still point here can appear again after reconnecting.",
            self.QtWidgets.QMessageBox.Yes | self.QtWidgets.QMessageBox.Cancel,
            self.QtWidgets.QMessageBox.Cancel,
        )
        if answer != self.QtWidgets.QMessageBox.Yes:
            self._set_status("Companion reset cancelled.", "Muted")
            return
        self._set_status("Resetting paired mobile devices...", busy=True)
        try:
            payload = self.service.reset_companions()
        except Exception as exc:
            self._set_status(f"Could not reset paired mobile devices: {exc}", "StatusBad")
            return
        removed = int(payload.get("removed") or 0)
        self._refresh_companion_gateway()
        self._set_status(
            f"Reset paired devices. Cleared {removed} remembered mobile check-in(s).",
            "StatusGood",
        )

    def _relative_time(self, value: str) -> str:
        if not value:
            return "not seen yet"
        try:
            seen = datetime.fromisoformat(value)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - seen
        except Exception:
            return value
        seconds = max(0, int(delta.total_seconds()))
        if seconds < 90:
            return f"{seconds}s ago"
        minutes = seconds // 60
        if minutes < 90:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 48:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"

    def _populate_config(self, cfg: dict[str, Any]) -> None:
        self.airport_iata.setText(str(cfg.get("airport_iata") or ""))
        self.airport_icao.setText(str(cfg.get("airport_icao") or ""))
        self.timezone.setText(str(cfg.get("timezone") or ""))
        self.airport_search.setText(f"{cfg.get('airport_iata') or '---'} / {cfg.get('airport_icao') or '----'}")
        self.airport_selected.setText(
            f"Selected: {cfg.get('airport_iata') or '---'} / {cfg.get('airport_icao') or '----'}"
            + (f" | {cfg.get('timezone')}" if cfg.get("timezone") else "")
        )
        self.display_name.setText(str(cfg.get("display_name") or "Local Flight"))
        self._set_combo_value(self.source, str(cfg.get("source") or "real"))
        self._populate_refresh_options(str(cfg.get("source") or "real"))
        self._set_combo_value(self.theme, str(cfg.get("theme") or "dark"))
        skin = str(cfg.get("skin") or "standard")
        if self.skin.findData(skin) < 0:
            skin = "standard"
        self._set_combo_value(self.skin, skin)
        self._set_combo_value(self.diagnostics, str(cfg.get("diagnostics_mode") or "unset"))
        self.surface.setChecked(bool(cfg.get("radar_surface_enabled")))
        self._set_surface_status(
            "Surface overlay is enabled. Apply or check it to load runway data."
            if self.surface.isChecked()
            else "Surface overlay is off. Radar will show aircraft without airport ground drawing."
        )
        self.web_row_limit.setValue(int(cfg.get("web_row_limit") or 20))
        self.web_rotation.setValue(int(cfg.get("web_rotation_seconds") or 8))
        self.grace.setValue(int(cfg.get("display_grace_minutes") or 30))
        self.horizon.setValue(int(cfg.get("display_horizon_hours") or 12))
        outputs = cfg.get("display_outputs") if isinstance(cfg.get("display_outputs"), list) else ["web"]
        self.output_web.setChecked("web" in outputs)
        self.output_matrix.setChecked("matrix" in outputs)
        self.output_hdmi.setChecked("hdmi" in outputs)
        refresh_value = int(cfg.get("refresh_seconds") or 3600)
        idx = self.refresh_seconds.findData(refresh_value)
        self.refresh_seconds.setCurrentIndex(idx if idx >= 0 else self.refresh_seconds.findData(3600))
        self._preview_design()

    def _refresh_current(self, cfg: dict[str, Any]) -> None:
        self.current_airport_value.value_label.setText(
            f"{cfg.get('airport_iata') or '---'} / {cfg.get('airport_icao') or '----'}"
        )
        source_value = str(cfg.get("source") or "-")
        self.current_source_value.value_label.setText(option_label(SOURCE_OPTIONS, source_value).upper())
        self.current_refresh_value.value_label.setText(self.refresh_seconds.currentText() or "-")
        self.current_relay_value.value_label.setText("Checking...")
        surface_enabled = bool(cfg.get("radar_surface_enabled"))
        self.current_surface_value.value_label.setText("On" if surface_enabled else "Off")
        self.current_surface_value.detail_label.setText(
            "Runways/surface will draw when map data is available."
            if surface_enabled
            else "Aircraft-only radar. Enable and apply to draw airport surface."
        )

    def _refresh_install(self) -> None:
        try:
            info = self.service.setup_client_info()
        except Exception as exc:
            self.current_relay_value.value_label.setText("Unavailable")
            self.current_relay_value.detail_label.setText(f"Relay status could not be read: {exc}")
            return
        has_token = bool(info.get("has_activation_token") or info.get("activation_token_present") or info.get("managed"))
        relay_url = str(info.get("relay_url") or "local relay")
        self.current_relay_value.value_label.setText("Managed access" if has_token else "Community/BYOK")
        self.current_relay_value.detail_label.setText(f"{relay_url} - token status only, no raw token shown.")
        if hasattr(self, "relay_mode_detail"):
            mode = "Managed access" if has_token else "Community relay / BYOK"
            token = "Linked token present" if has_token else "No linked managed token"
            self.relay_mode_detail.setText(mode)
            self.relay_url_detail.setText(relay_url.rstrip("/") or "Default hosted relay")
            self.relay_token_detail.setText(token)
            self.relay_access_detail.setText(
                "Community installs share airport snapshots through the relay; BYOK keeps provider access on this device."
            )

    def _refresh_profiles(self) -> None:
        current = self.profile_combo.currentText()
        self.profile_combo.clear()
        self.profile_combo.addItems(list_profiles())
        if current:
            idx = self.profile_combo.findText(current)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)

    def _start_airport_search(self) -> None:
        query = self.airport_search.text().strip()
        if len(query) < 2 or "/" in query:
            self.airport_results.hide()
            return
        query_key = query.casefold()
        if query_key == self._last_airport_query:
            return
        self._last_airport_query = query_key
        if self._airport_search_future is not None and not self._airport_search_future.done():
            return
        self.airport_results.clear()
        self.airport_results.addItem("Searching airports...")
        self.airport_results.show()
        self._airport_search_future = API_EXECUTOR.submit(lambda: self.service.airport_search(query, limit=10))
        self.search_poll_timer.start()

    def _poll_airport_search(self) -> None:
        future = self._airport_search_future
        if future is None or not future.done():
            return
        self.search_poll_timer.stop()
        self._airport_search_future = None
        try:
            payload = future.result()
        except Exception as exc:
            self.airport_results.clear()
            self.airport_results.addItem(f"Search failed: {exc}")
            self.airport_results.show()
            return
        rows = list_payload(payload)
        self.airport_results.clear()
        if not rows:
            self.airport_results.addItem("No matching airport found.")
            self.airport_results.show()
            return
        for row in rows:
            iata = str(row.get("iata") or "").upper()
            icao = str(row.get("icao") or "").upper()
            name = row.get("name") or row.get("airport") or "Airport"
            city = row.get("city") or row.get("municipality") or ""
            country = row.get("country") or row.get("iso_country") or ""
            item = self.QtWidgets.QListWidgetItem(f"{iata or '---'} / {icao or '----'} - {name} {city} {country}".strip())
            item.setData(self.QtCore.Qt.UserRole, row)
            self.airport_results.addItem(item)
        self.airport_results.show()

    def _select_airport_item(self, item: Any) -> None:
        row = item.data(self.QtCore.Qt.UserRole)
        if not isinstance(row, dict):
            return
        iata = str(row.get("iata") or "").upper()
        icao = str(row.get("icao") or "").upper()
        timezone = str(row.get("timezone") or row.get("tz") or "")
        name = row.get("name") or row.get("airport") or "Airport"
        city = row.get("city") or row.get("municipality") or ""
        self.airport_iata.setText(iata)
        self.airport_icao.setText(icao)
        self.timezone.setText(timezone)
        self.airport_search.setText(f"{iata or '---'} / {icao or '----'}")
        self.airport_selected.setText(f"Selected: {name}" + (f" - {city}" if city else "") + (f" | {timezone}" if timezone else ""))
        self.airport_results.hide()

    def _config_payload(self) -> dict[str, Any]:
        outputs = []
        if self.output_web.isChecked():
            outputs.append("web")
        if self.output_matrix.isChecked():
            outputs.append("matrix")
        if self.output_hdmi.isChecked():
            outputs.append("hdmi")
        return {
            "airport_iata": self.airport_iata.text().strip().upper(),
            "airport_icao": self.airport_icao.text().strip().upper(),
            "timezone": self.timezone.text().strip(),
            "display_name": self.display_name.text().strip() or "Local Flight",
            "source": self._combo_value(self.source, "real"),
            "refresh_seconds": int(self.refresh_seconds.currentData()),
            "theme": self._combo_value(self.theme, "dark"),
            "skin": self._combo_value(self.skin, "standard"),
            "diagnostics_mode": self._combo_value(self.diagnostics, "unset"),
            "web_row_limit": int(self.web_row_limit.value()),
            "web_rotation_seconds": int(self.web_rotation.value()),
            "display_grace_minutes": int(self.grace.value()),
            "display_horizon_hours": int(self.horizon.value()),
            "radar_surface_enabled": bool(self.surface.isChecked()),
            "display_outputs": outputs or ["web"],
        }

    def save(self, *_args: Any, check_surface: bool = True) -> None:
        payload = self._config_payload()
        self.save_button.setEnabled(False)
        self._set_status("Saving settings to the local server...", busy=True)
        try:
            self.service.save_config(payload)
        except Exception as exc:
            self._set_status(f"Save failed: {exc}", "StatusBad")
            self.save_button.setEnabled(True)
            return
        self.save_button.setEnabled(True)
        self._refresh_current(payload)
        self._set_status("Settings saved. Scheduler restarts automatically when needed.", "StatusGood")
        if check_surface:
            self._start_surface_check() if payload.get("radar_surface_enabled") else self._surface_off()

    def apply_surface_overlay(self, *_args: Any) -> None:
        self.save(check_surface=True)

    def _surface_changed(self, _state: int = 0) -> None:
        if self.surface.isChecked():
            self._set_surface_status("Surface overlay changed. Apply radar overlay to save and check runway data.", "StatusWarn")
        else:
            self._surface_off()

    def _surface_off(self) -> None:
        self._set_surface_busy(False)
        self._set_surface_status("Surface overlay is off. Radar will show aircraft without airport ground drawing.")

    def _start_surface_check(self) -> None:
        if not self.surface.isChecked():
            self._surface_off()
            return
        if self._surface_check_future is not None and not self._surface_check_future.done():
            self._set_surface_status("Surface data check is already running...", "StatusWarn")
            return
        self._set_surface_busy(True)
        self._set_surface_status("Surface overlay saved. Checking runway and ground drawing data...", "Muted")
        self._surface_check_future = API_EXECUTOR.submit(
            lambda: self.service.radar_map(radius_nm=5.0, terrain=False, refresh_runways=False)
        )
        self.surface_check_timer.start()

    def _poll_surface_check(self) -> None:
        future = self._surface_check_future
        if future is None or not future.done():
            return
        self.surface_check_timer.stop()
        self._surface_check_future = None
        self._set_surface_busy(False)
        try:
            payload = future.result()
        except Exception as exc:
            self._set_surface_status(self._surface_error_message(exc), "StatusBad")
            return
        self._apply_surface_check_result(payload)

    def _apply_surface_check_result(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            self._set_surface_status("Surface overlay is enabled, but the map response was not readable.", "StatusBad")
            return
        runways = payload.get("runways") if isinstance(payload.get("runways"), list) else []
        features = payload.get("surface_features") if isinstance(payload.get("surface_features"), list) else []
        sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
        cache_state = str(sources.get("surface_cache_state") or "unknown").replace("_", " ")
        provider = str(sources.get("surface") or "surface data").replace("_", " ")
        runway_count = len(runways)
        feature_count = len(features)
        if runway_count or feature_count:
            self._set_surface_status(
                f"Surface data ready: {runway_count} runway layer(s), {feature_count} ground feature(s) from {provider} ({cache_state}). Refresh Radar to redraw.",
                "StatusGood",
            )
            return
        self._set_surface_status(
            "Surface overlay is enabled, but no drawable runway data is available yet. Radar will keep the overlay on and fall back when data appears.",
            "StatusWarn",
        )

    def _set_surface_busy(self, busy: bool) -> None:
        self.surface_progress.setVisible(bool(busy))
        self.apply_surface_button.setEnabled(not busy)

    def _set_surface_status(self, text: str, role: str = "Muted") -> None:
        self.surface_status.setText(text)
        self.surface_status.setObjectName(role)
        try:
            self.surface_status.style().unpolish(self.surface_status)
            self.surface_status.style().polish(self.surface_status)
        except Exception:
            pass

    def _surface_error_message(self, exc: Exception) -> str:
        text = str(exc).strip()
        clean = text.lower()
        if "timed out" in clean or "timeout" in clean:
            return (
                "Surface overlay is enabled, but the online map check timed out. "
                "Radar will use cached or estimated runway drawing and try fresh OSM data again later."
            )
        if "connection" in clean or "unavailable" in clean:
            return (
                "Surface overlay is enabled, but Local Flight could not reach the map service. "
                "Radar will keep using cached or estimated airport drawing."
            )
        return f"Surface overlay is enabled, but the data check failed: {text or 'unknown error'}"

    def restart_scheduler(self) -> None:
        self._set_status("Asking the local scheduler to restart...", busy=True)
        try:
            result = self.service.restart_scheduler()
        except Exception as exc:
            self._set_status(f"Restart failed: {exc}", "StatusBad")
            return
        self._set_status(str(result.get("message") or "Scheduler restart requested."), "StatusGood")

    def reset_setup(self) -> None:
        if (
            self.QtWidgets.QMessageBox.question(
                self.widget,
                "Re-run setup",
                "Close the current shell and open the setup wizard now?",
            )
            != self.QtWidgets.QMessageBox.Yes
        ):
            return
        self._set_status("Preparing the setup wizard...", busy=True)
        try:
            self.service.setup_reset()
        except Exception as exc:
            self._set_status(f"Setup reset failed: {exc}", "StatusBad")
            return
        if self.on_rerun_setup is None:
            self._set_status("Setup reset. Open browser setup or relaunch Local Flight to continue.", "StatusWarn")
            return
        self._set_status("Opening the setup wizard...", "StatusWarn")
        self.QtCore.QTimer.singleShot(180, self.on_rerun_setup)

    def save_profile(self) -> None:
        name = self.profile_name.text().strip()
        if not name:
            self._set_status("Enter a profile name first.", "StatusWarn")
            return
        self._set_status(f"Saving profile {name}...", busy=True)
        try:
            self.service.save_profile(name)
        except Exception as exc:
            self._set_status(f"Profile save failed: {exc}", "StatusBad")
            return
        self._set_status(f"Profile saved: {name}", "StatusGood")
        self._refresh_profiles()

    def load_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            self._set_status("No profile selected.", "StatusWarn")
            return
        self._set_status(f"Loading profile {name}...", busy=True)
        try:
            self.service.load_profile(name)
        except Exception as exc:
            self._set_status(f"Profile load failed: {exc}", "StatusBad")
            return
        self._set_status(f"Profile loaded: {name}", "StatusGood")
        self.refresh()

    def delete_profile(self) -> None:
        name = self.profile_combo.currentText().strip()
        if not name:
            self._set_status("No profile selected.", "StatusWarn")
            return
        self._set_status(f"Deleting profile {name}...", busy=True)
        try:
            self.service.delete_profile(name)
        except Exception as exc:
            self._set_status(f"Profile delete failed: {exc}", "StatusBad")
            return
        self._set_status(f"Profile deleted: {name}", "StatusGood")
        self._refresh_profiles()

    def open_doc(self, slug: str) -> None:
        doc = bundled_doc(slug)
        self.current_doc_slug = doc["slug"] or "readme"
        for button_slug, button in self.doc_buttons.items():
            button.setChecked(button_slug == self.current_doc_slug)
        self.doc_title.setText(f"{doc['title']} - {doc['filename']}")
        self.doc_summary.setText(doc["summary"])
        if hasattr(self.doc_text, "setMarkdown"):
            self.doc_text.setMarkdown(doc["text"])
        else:
            self.doc_text.setPlainText(doc["text"])


__all__ = ["SettingsScreen"]
