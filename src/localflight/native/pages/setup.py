"""Native first-run setup flow."""
from __future__ import annotations

import webbrowser
from concurrent.futures import Future
from typing import Any, Callable

from localflight.native.api_client import LocalApiClient
from localflight.native.async_tools import API_EXECUTOR
from localflight.native.design import (
    format_value,
    icon_from_media,
    label,
    list_payload,
    native_stylesheet,
    panel,
    pixmap_from_media,
    scroll_page,
)
from localflight.native.service import NativeApiService


DEFAULT_RELAY_URL = "https://localflight-community-relay.fly.dev"
PROVIDER_LINKS: tuple[tuple[str, str], ...] = (
    ("Get AviationStack key", "https://aviationstack.com/signup"),
    ("ADS-B Exchange on RapidAPI", "https://rapidapi.com/adsbx/api/adsbexchange-com1"),
    ("OpenSky account", "https://opensky-network.org/login?view=registration"),
    ("VATSIM status", "https://network-status.vatsim.net/"),
)


class NativeSetupWindow:  # pragma: no cover - exercised with optional Qt
    def __new__(
        cls,
        QtCore: Any,
        QtGui: Any,
        QtWidgets: Any,
        *,
        base_url: str,
        on_setup_complete: Callable[[], None],
    ):
        class _Window(QtWidgets.QMainWindow):
            def __init__(self) -> None:
                super().__init__()
                self.client = LocalApiClient(base_url=base_url)
                self.service = NativeApiService(self.client)
                self._allow_close_without_backend_shutdown = False
                self._shutdown_started = False
                self.setWindowTitle("Local Flight Setup")
                self.setStyleSheet(native_stylesheet())
                app_icon = icon_from_media(QtGui, "assets", "icon.ico")
                if app_icon.isNull():
                    app_icon = icon_from_media(QtGui, "assets", "localflight-logo.svg")
                if not app_icon.isNull():
                    self.setWindowIcon(app_icon)
                self.setup_screen = SetupScreen(
                    QtCore,
                    QtWidgets,
                    self.client,
                    base_url,
                    on_setup_complete=on_setup_complete,
                    QtGui=QtGui,
                )
                self.setCentralWidget(self.setup_screen.widget)

            def allow_close_without_shutdown(self) -> None:
                self._allow_close_without_backend_shutdown = True

            def closeEvent(self, event: Any) -> None:
                if self._allow_close_without_backend_shutdown:
                    event.accept()
                    return
                if not self._shutdown_started:
                    self._shutdown_started = True
                    try:
                        self.service.quit_app()
                    except Exception:
                        pass
                event.accept()

        return _Window()


class SetupScreen:  # pragma: no cover - optional Qt runtime
    def __init__(
        self,
        QtCore: Any,
        QtWidgets: Any,
        client: LocalApiClient,
        base_url: str,
        *,
        on_setup_complete: Callable[[], None] | None = None,
        QtGui: Any | None = None,
    ) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.base_url = base_url.rstrip("/")
        self.on_setup_complete = on_setup_complete
        self._airport_search_future: Future[Any] | None = None
        self._last_airport_query = ""
        self._stored_activation = False
        self._mode_initialized = False
        screen = self.QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 1200
        self.setup_max_width = 900 if available_width >= 900 else max(560, available_width - 48)
        self.card_columns = 1 if available_width < 760 else 3
        self.step_names = ["Welcome", "Airport", "Data Access", "Provider Keys", "Diagnostics", "Finish"]
        self.step_buttons: list[Any] = []
        self.source_buttons: dict[str, Any] = {}
        self.diagnostics_buttons: dict[str, Any] = {}
        self.provider_link_buttons: dict[str, Any] = {}

        self.widget, layout = scroll_page(QtWidgets)
        self.widget.setMinimumWidth(0)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)
        self.status = label(
            QtWidgets,
            "Setup is local-first. You can change these choices later in Settings.",
            "Muted",
            wrap=True,
        )

        self.tabs = QtWidgets.QStackedWidget()
        self.tabs.setMinimumWidth(0)
        self.tabs.setMaximumWidth(self.setup_max_width)
        self.tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.search_timer = QtCore.QTimer(self.widget)
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._start_airport_search)
        self.search_poll_timer = QtCore.QTimer(self.widget)
        self.search_poll_timer.setInterval(50)
        self.search_poll_timer.timeout.connect(self._poll_airport_search)

        self._build_welcome_page()
        self._build_airport_page()
        self._build_source_page()
        self._build_keys_page()
        self._build_diagnostics_page()
        self._build_finish_page()

        layout.addLayout(self._step_header())
        layout.addWidget(self.tabs, 1, QtCore.Qt.AlignHCenter)
        self.loading_indicator = QtWidgets.QProgressBar()
        self.loading_indicator.setObjectName("LoadingProgress")
        self.loading_indicator.setRange(0, 0)
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.setFixedHeight(7)
        self.loading_indicator.setMaximumWidth(self.setup_max_width)
        self.loading_indicator.hide()
        layout.addWidget(self.loading_indicator, 0, QtCore.Qt.AlignHCenter)
        layout.addWidget(self.status, 0, QtCore.Qt.AlignHCenter)
        layout.addLayout(self._navigation())
        layout.addStretch(1)

        self._set_step(0)
        self.refresh()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _step_header(self) -> Any:
        wrap = self.QtWidgets.QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        steps_wrap = self.QtWidgets.QWidget()
        steps_wrap.setMinimumWidth(0)
        steps_wrap.setMaximumWidth(self.setup_max_width)
        steps = self.QtWidgets.QHBoxLayout(steps_wrap)
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(6)
        for idx, name in enumerate(self.step_names):
            button = self.QtWidgets.QPushButton(f"{idx + 1}. {name}")
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, i=idx: self._set_step(i))
            self.step_buttons.append(button)
            steps.addWidget(button)
        steps_scroll = self.QtWidgets.QScrollArea()
        steps_scroll.setObjectName("NavScroll")
        steps_scroll.setWidgetResizable(True)
        steps_scroll.setFrameShape(self.QtWidgets.QFrame.NoFrame)
        steps_scroll.setHorizontalScrollBarPolicy(self.QtCore.Qt.ScrollBarAsNeeded)
        steps_scroll.setVerticalScrollBarPolicy(self.QtCore.Qt.ScrollBarAlwaysOff)
        steps_scroll.setMinimumWidth(0)
        steps_scroll.setMaximumWidth(self.setup_max_width)
        steps_scroll.setMaximumHeight(52)
        steps_scroll.setWidget(steps_wrap)
        wrap.addWidget(steps_scroll, 1)
        wrap.addStretch(1)
        return wrap

    def _navigation(self) -> Any:
        wrap = self.QtWidgets.QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        nav_wrap = self.QtWidgets.QWidget()
        nav_wrap.setMinimumWidth(0)
        nav_wrap.setMaximumWidth(self.setup_max_width)
        nav = self.QtWidgets.QHBoxLayout(nav_wrap)
        nav.setContentsMargins(0, 0, 0, 0)
        self.web_fallback_btn = self.QtWidgets.QPushButton("Open browser setup")
        self.web_fallback_btn.setObjectName("Quiet")
        self.back_btn = self.QtWidgets.QPushButton("Back")
        self.back_btn.setObjectName("Quiet")
        self.next_btn = self.QtWidgets.QPushButton("Next")
        self.finish_btn = self.QtWidgets.QPushButton("Finish setup")
        self.back_btn.clicked.connect(self._previous_step)
        self.next_btn.clicked.connect(self._next_step)
        self.finish_btn.clicked.connect(self.finish_setup)
        self.web_fallback_btn.clicked.connect(lambda: webbrowser.open(f"{self.base_url}/setup"))
        nav.addWidget(self.web_fallback_btn)
        nav.addStretch(1)
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.finish_btn)
        nav_scroll = self.QtWidgets.QScrollArea()
        nav_scroll.setObjectName("NavScroll")
        nav_scroll.setWidgetResizable(True)
        nav_scroll.setFrameShape(self.QtWidgets.QFrame.NoFrame)
        nav_scroll.setHorizontalScrollBarPolicy(self.QtCore.Qt.ScrollBarAsNeeded)
        nav_scroll.setVerticalScrollBarPolicy(self.QtCore.Qt.ScrollBarAlwaysOff)
        nav_scroll.setMinimumWidth(0)
        nav_scroll.setMaximumWidth(self.setup_max_width)
        nav_scroll.setMaximumHeight(52)
        nav_scroll.setWidget(nav_wrap)
        wrap.addStretch(1)
        wrap.addWidget(nav_scroll, 1)
        wrap.addStretch(1)
        return wrap

    def _page(self, title: str, text: str) -> tuple[Any, Any]:
        page = self.QtWidgets.QFrame()
        page.setObjectName("Panel")
        page.setMinimumWidth(0)
        page.setMaximumWidth(self.setup_max_width)
        layout = self.QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(label(self.QtWidgets, title, "Title"))
        layout.addWidget(label(self.QtWidgets, text, "Muted", wrap=True))
        self.tabs.addWidget(page)
        return page, layout

    def _build_welcome_page(self) -> None:
        _page, layout = self._page(
            'Welcome to <span style="font-family: Audiowide; font-weight: 400; letter-spacing: 1px;">Local Flight</span>',
            "This setup gets the local display running without making you understand every backend detail first.",
        )
        logo = self.QtWidgets.QLabel()
        logo.setAlignment(self.QtCore.Qt.AlignCenter)
        logo.setMinimumHeight(120)
        logo.setObjectName("SetupBrandMark")
        self.logo_label = logo
        if self.QtGui is not None:
            pixmap = pixmap_from_media(self.QtCore, self.QtGui, "ui", "static", "localflight-logo.svg", width=132, height=132)
            if not pixmap.isNull():
                logo.setPixmap(pixmap)
            else:
                logo.setText("Local Flight")
                logo.setObjectName("BrandTitle")
        else:
            logo.setText("Local Flight")
            logo.setObjectName("BrandTitle")
        layout.addWidget(logo)
        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        for index, (title, body) in enumerate(
            (
            ("Local first", "Native GUI, local backend, LAN browser fallback."),
            ("Community default", "Start with the hosted relay; add your own keys only if you want them."),
            ("Private by design", "Secrets stay masked and diagnostics are an explicit setup choice."),
            )
        ):
            cards.addWidget(self._mini_card(title, body), index // self.card_columns, index % self.card_columns)
        layout.addLayout(cards)
        self.start_btn = self.QtWidgets.QPushButton("Start setup")
        self.start_btn.clicked.connect(lambda: self._set_step(1))
        start_row = self.QtWidgets.QHBoxLayout()
        start_row.addStretch(1)
        start_row.addWidget(self.start_btn)
        layout.addLayout(start_row)
        layout.addStretch(1)

    def _mini_card(self, title: str, body: str) -> Any:
        box = self.QtWidgets.QFrame()
        box.setObjectName("PreviewCard")
        layout = self.QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.addWidget(label(self.QtWidgets, title, "Kicker", wrap=True))
        layout.addWidget(label(self.QtWidgets, body, "Muted", wrap=True))
        return box

    def _build_airport_page(self) -> None:
        _page, layout = self._page(
            "Choose Your Airport",
            "Search by city, airport name, IATA, or ICAO. Pick one result and the technical codes are filled for you.",
        )
        self.airport_search = self.QtWidgets.QLineEdit()
        self.airport_search.setPlaceholderText("Search airport, city, IATA, or ICAO...")
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMinimumHeight(170)
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.airport_selected = label(self.QtWidgets, "Selected: ZRH / LSZH | Europe/Zurich", "Muted", wrap=True)
        self.display_name = self.QtWidgets.QLineEdit("Local Flight")
        self.airport_iata = self.QtWidgets.QLineEdit("ZRH")
        self.airport_icao = self.QtWidgets.QLineEdit("LSZH")
        self.timezone = self.QtWidgets.QLineEdit("Europe/Zurich")
        for field in (self.airport_iata, self.airport_icao, self.timezone):
            field.setReadOnly(True)
        form = self.QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("Display name", self.display_name)
        form.addRow("Airport IATA", self.airport_iata)
        form.addRow("Airport ICAO", self.airport_icao)
        form.addRow("Timezone", self.timezone)
        layout.addWidget(self.airport_search)
        layout.addWidget(self.airport_results)
        layout.addWidget(self.airport_selected)
        layout.addLayout(form)

    def _build_source_page(self) -> None:
        _page, layout = self._page(
            "Choose Data Access",
            "Community Relay is the guided default. BYOK is for direct provider accounts. VATSIM is the no-key virtual path.",
        )
        self.setup_mode = self.QtWidgets.QComboBox()
        for label_text, mode in (
            ("Community relay", "community"),
            ("Bring your own AviationStack key", "byok"),
            ("Virtual / VATSIM", "virtual"),
        ):
            self.setup_mode.addItem(label_text, mode)
        self.setup_mode.hide()

        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        for index, (mode, title, body) in enumerate(
            (
                ("community", "Community Relay", "Recommended. Shared real-flight snapshots through the hosted relay."),
                ("byok", "Use My Own Keys", "For AviationStack users who want direct quota ownership."),
                ("virtual", "VATSIM", "No schedule key. Virtual traffic with privacy-safe details."),
            )
        ):
            button = self.QtWidgets.QPushButton(f"{title}\n{body}")
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(112)
            button.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Preferred)
            button.clicked.connect(lambda _checked=False, m=mode: self._set_mode(m))
            self.source_buttons[mode] = button
            cards.addWidget(button, index // self.card_columns, index % self.card_columns)
        layout.addLayout(cards)
        self.mode_help = label(self.QtWidgets, "", "Muted", wrap=True)
        layout.addWidget(self.mode_help)

        self.relay_box, relay_layout = panel(self.QtWidgets, "Relay Access")
        self.relay_url = self.QtWidgets.QLineEdit(DEFAULT_RELAY_URL)
        self.relay_url.setPlaceholderText(DEFAULT_RELAY_URL)
        self.activation_token = self.QtWidgets.QLineEdit()
        self.activation_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.activation_token.setPlaceholderText("Paste activation token only if one was given to you")
        token_toggle = self.QtWidgets.QPushButton("Show token")
        token_toggle.setObjectName("Quiet")
        token_toggle.clicked.connect(lambda: self._toggle_secret(self.activation_token, token_toggle, "token"))
        token_row = self.QtWidgets.QHBoxLayout()
        token_row.addWidget(self.activation_token, 1)
        token_row.addWidget(token_toggle)
        relay_form = self.QtWidgets.QFormLayout()
        relay_form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        relay_form.addRow("Relay host", self.relay_url)
        relay_form.addRow("Activation token", token_row)
        relay_layout.addLayout(relay_form)
        relay_actions = self.QtWidgets.QHBoxLayout()
        self.request_activation_btn = self.QtWidgets.QPushButton("Request activation")
        self.check_relay_status_btn = self.QtWidgets.QPushButton("Check relay status")
        self.test_token_btn = self.QtWidgets.QPushButton("Test token")
        self.request_activation_btn.clicked.connect(self.request_activation)
        self.check_relay_status_btn.clicked.connect(self.check_activation_status)
        self.test_token_btn.clicked.connect(self.test_activation)
        relay_actions.addWidget(self.request_activation_btn)
        relay_actions.addWidget(self.check_relay_status_btn)
        relay_actions.addWidget(self.test_token_btn)
        relay_actions.addStretch(1)
        self.relay_status = label(self.QtWidgets, "Relay is the beginner path. Token values stay hidden.", "Muted", wrap=True)
        self.relay_action_status = label(self.QtWidgets, "Relay check ready.", "Muted", wrap=True)
        relay_layout.addLayout(relay_actions)
        relay_layout.addWidget(self.relay_status)
        relay_layout.addWidget(self.relay_action_status)
        layout.addWidget(self.relay_box)
        layout.addStretch(1)

    def _build_keys_page(self) -> None:
        _page, layout = self._page(
            "Optional Provider Keys",
            "Only BYOK needs AviationStack. ADS-B Exchange and OpenSky are optional enrichment sources.",
        )
        self.keys_hint = label(self.QtWidgets, "Community Relay and VATSIM can skip this page.", "Muted", wrap=True)
        layout.addWidget(self.keys_hint)
        self.aviationstack_key = self.QtWidgets.QLineEdit()
        self.rapidapi_key = self.QtWidgets.QLineEdit()
        self.opensky_id = self.QtWidgets.QLineEdit()
        self.opensky_secret = self.QtWidgets.QLineEdit()
        for field in (self.aviationstack_key, self.rapidapi_key, self.opensky_secret):
            field.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.aviationstack_key.setPlaceholderText("AviationStack API key")
        self.rapidapi_key.setPlaceholderText("RapidAPI key for ADS-B Exchange")
        self.opensky_id.setPlaceholderText("OpenSky client ID")
        self.opensky_secret.setPlaceholderText("OpenSky client secret")
        form = self.QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("AviationStack", self.aviationstack_key)
        form.addRow("RapidAPI", self.rapidapi_key)
        form.addRow("OpenSky ID", self.opensky_id)
        form.addRow("OpenSky Secret", self.opensky_secret)
        layout.addLayout(form)

        link_grid = self.QtWidgets.QGridLayout()
        link_grid.setHorizontalSpacing(8)
        link_grid.setVerticalSpacing(8)
        for idx, (text, url) in enumerate(PROVIDER_LINKS):
            button = self._link_button(text, url)
            self.provider_link_buttons[text] = button
            link_grid.addWidget(button, idx // 2, idx % 2)
        layout.addLayout(link_grid)
        tests = self.QtWidgets.QHBoxLayout()
        self.test_as_btn = self.QtWidgets.QPushButton("Test AviationStack")
        self.test_rapidapi_btn = self.QtWidgets.QPushButton("Test RapidAPI")
        self.test_as_btn.clicked.connect(self.test_aviationstack)
        self.test_rapidapi_btn.clicked.connect(self.test_rapidapi)
        tests.addWidget(self.test_as_btn)
        tests.addWidget(self.test_rapidapi_btn)
        tests.addStretch(1)
        layout.addLayout(tests)
        self.provider_action_status = label(self.QtWidgets, "Provider key checks ready.", "Muted", wrap=True)
        layout.addWidget(self.provider_action_status)
        layout.addStretch(1)

    def _build_diagnostics_page(self) -> None:
        _page, layout = self._page(
            "Diagnostics",
            "Choose how Local Flight may help report problems. Manual reports are always available.",
        )
        self.diagnostics_mode = self.QtWidgets.QComboBox()
        for label_text, mode in (
            ("Manual reports only", "manual"),
            ("Auto crash reports", "auto"),
            ("Auto crash reports + local logs", "auto_logs"),
        ):
            self.diagnostics_mode.addItem(label_text, mode)
        self.diagnostics_mode.hide()
        layout.addWidget(self.diagnostics_mode)
        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(10)
        cards.setVerticalSpacing(10)
        for index, (mode, title, body) in enumerate(
            (
                ("manual", "Manual", "Nothing is sent unless you submit a report."),
                ("auto", "Auto crashes", "Send sanitized exception details for native crashes."),
                ("auto_logs", "Auto + logs", "Also attach a short local log tail for hard-to-track issues."),
            )
        ):
            button = self.QtWidgets.QPushButton(f"{title}\n{body}")
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setMinimumHeight(106)
            button.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Preferred)
            button.clicked.connect(lambda _checked=False, m=mode: self._set_diagnostics_mode(m))
            self.diagnostics_buttons[mode] = button
            cards.addWidget(button, index // self.card_columns, index % self.card_columns)
        layout.addLayout(cards)
        self.diagnostics_help = label(
            self.QtWidgets,
            "Privacy rule: no provider keys, activation tokens, raw install IDs, pilot identities, or internal secrets are shown here or sent from the client UI.",
            "Muted",
            wrap=True,
        )
        layout.addWidget(self.diagnostics_help)
        layout.addStretch(1)
        self._set_diagnostics_mode("manual")

    def _build_finish_page(self) -> None:
        _page, layout = self._page(
            "Ready to Launch",
            "Review the simple version. Finish saves the local setup and opens the native display.",
        )
        self.finish_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.diagnostics_note = label(
            self.QtWidgets,
            "Diagnostics can be changed later in Settings. Provider keys and tokens are never displayed in this summary.",
            "Muted",
            wrap=True,
        )
        layout.addWidget(self.finish_summary)
        layout.addWidget(self.diagnostics_note)
        layout.addWidget(self._link_button("Open VATSIM status", "https://network-status.vatsim.net/"))
        layout.addStretch(1)

    def _link_button(self, text: str, url: str) -> Any:
        button = self.QtWidgets.QPushButton(text)
        button.setObjectName("Quiet")
        button.setProperty("url", url)
        button.clicked.connect(lambda _checked=False, u=url: webbrowser.open(u))
        return button

    def _set_step(self, index: int) -> None:
        index = max(0, min(index, self.tabs.count() - 1))
        self.tabs.setCurrentIndex(index)
        for idx, button in enumerate(self.step_buttons):
            button.setChecked(idx == index)
        self.back_btn.setEnabled(index > 0)
        self.next_btn.setVisible(index < self.tabs.count() - 1)
        self.finish_btn.setVisible(index == self.tabs.count() - 1)
        self._update_finish_summary()

    def _next_step(self) -> None:
        index = self.tabs.currentIndex()
        if index == 2 and self._current_mode() in {"community", "virtual"}:
            self._set_step(4)
            return
        self._set_step(index + 1)

    def _previous_step(self) -> None:
        index = self.tabs.currentIndex()
        if index == 4 and self._current_mode() in {"community", "virtual"}:
            self._set_step(2)
            return
        self._set_step(index - 1)

    def _current_mode(self) -> str:
        return str(self.setup_mode.currentData() or "community")

    def _current_diagnostics_mode(self) -> str:
        return str(self.diagnostics_mode.currentData() or "manual")

    def _set_mode(self, mode: str) -> None:
        idx = self.setup_mode.findData(mode)
        self.setup_mode.setCurrentIndex(idx if idx >= 0 else self.setup_mode.findData("community"))
        active_mode = self._current_mode()
        for key, button in self.source_buttons.items():
            button.setChecked(key == active_mode)
        self._sync_mode_ui()
        self._update_finish_summary()

    def _set_diagnostics_mode(self, mode: str) -> None:
        idx = self.diagnostics_mode.findData(mode)
        self.diagnostics_mode.setCurrentIndex(idx if idx >= 0 else 0)
        active_mode = self._current_diagnostics_mode()
        for key, button in self.diagnostics_buttons.items():
            button.setChecked(key == active_mode)
        if active_mode == "auto_logs":
            text = "Auto + logs is helpful during beta testing. Reports stay sanitized and include only a short local log tail."
        elif active_mode == "auto":
            text = "Auto crash reports send sanitized exception details only when diagnostics allow it."
        else:
            text = "Manual mode is privacy-first: reports are sent only when you press Submit in the Report screen."
        self.diagnostics_help.setText(text)
        self._update_finish_summary()

    def _sync_mode_ui(self) -> None:
        mode = self._current_mode()
        self.relay_box.setVisible(mode == "community")
        if mode == "community":
            self.mode_help.setText("Recommended first path. Uses hosted community snapshots when this install has access. VATSIM remains available as the no-key virtual path.")
            self.keys_hint.setText("Community Relay mode skips provider keys. You can add your own keys later in Settings.")
        elif mode == "byok":
            self.mode_help.setText("Direct provider mode. Use this when you want AviationStack calls from this device and you own the provider quota.")
            self.keys_hint.setText("Paste an AviationStack key. ADS-B Exchange on RapidAPI and OpenSky are optional enrichment helpers.")
        else:
            self.mode_help.setText("VATSIM mode uses virtual flight-network data. It needs no schedule key and never displays pilot identities.")
            self.keys_hint.setText("VATSIM needs no provider keys. This setup saves source=virtual.")

    def _mode_label(self, mode: str) -> str:
        return {
            "community": "Community Relay",
            "byok": "Bring your own keys",
            "virtual": "Virtual / VATSIM",
        }.get(mode, mode)

    def _diagnostics_label(self, mode: str) -> str:
        return {
            "manual": "Manual reports only",
            "auto": "Auto crash reports",
            "auto_logs": "Auto crash reports + local logs",
            "unset": "Not chosen",
        }.get(mode, mode)

    def _update_finish_summary(self) -> None:
        if not hasattr(self, "finish_summary"):
            return
        mode = self._current_mode() if hasattr(self, "setup_mode") else "community"
        source = "virtual" if mode == "virtual" else "real"
        relay_state = "connected" if self._stored_activation else "token needed or pending"
        if mode != "community":
            relay_state = "not used"
        key_state = "AviationStack key will be saved" if mode == "byok" and self.aviationstack_key.text().strip() else "no provider keys saved"
        diagnostics = self._current_diagnostics_mode()
        self.finish_summary.setText(
            "\n".join(
                [
                    f"Airport: {self.airport_iata.text().strip().upper() or 'ZRH'} / {self.airport_icao.text().strip().upper() or 'LSZH'}",
                    f"Timezone: {self.timezone.text().strip() or 'Europe/Zurich'}",
                    f"Display name: {self.display_name.text().strip() or 'Local Flight'}",
                    f"Data path: {self._mode_label(mode)}",
                    f"Source saved as: {source}",
                    f"Relay access: {relay_state}",
                    f"Provider keys: {key_state}",
                    f"Diagnostics: {self._diagnostics_label(diagnostics)}",
                ]
            )
        )

    def refresh(self) -> None:
        self._set_status("Checking local setup and relay state...", busy=True)
        try:
            info = self.service.setup_client_info()
        except Exception as exc:
            self._set_status(f"Setup info unavailable: {exc}", "StatusBad")
            self._set_mode("community")
            return
        if info.get("relay_url"):
            self.relay_url.setText(self._clean_relay_display(str(info.get("relay_url"))))
        prefix = str(info.get("activation_token_prefix") or "")
        self._stored_activation = bool(info.get("activation_token_present") or info.get("has_activation_token") or prefix)
        if self._stored_activation:
            self.activation_token.clear()
            self.activation_token.setPlaceholderText(f"Stored token linked ({prefix or 'hidden'}...)")
            self.relay_status.setText("Relay access is connected. You can finish Community Relay setup without pasting a token.")
        else:
            self.activation_token.setPlaceholderText("Paste activation token only if one was given to you")
            self.relay_status.setText("Relay access is not linked yet. Request or test a token, or choose VATSIM to continue without one.")
        if not self._mode_initialized:
            self._set_mode("community")
            self._mode_initialized = True
        self._set_status("Setup ready. Choose your airport and data path.", "StatusGood")
        self._update_finish_summary()

    def _clean_relay_display(self, value: str) -> str:
        clean = (value or "").strip().rstrip("/")
        for suffix in ("/v1/flights", "/v1/schedule", "/flights", "/schedule"):
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
        return clean or DEFAULT_RELAY_URL

    def _toggle_secret(self, field: Any, button: Any, label_text: str) -> None:
        is_password = field.echoMode() == self.QtWidgets.QLineEdit.Password
        field.setEchoMode(self.QtWidgets.QLineEdit.Normal if is_password else self.QtWidgets.QLineEdit.Password)
        button.setText(("Hide " if is_password else "Show ") + label_text)

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

    def _set_relay_action_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        self.relay_action_status.setText(text)
        self.relay_action_status.setObjectName(role)
        try:
            self.relay_action_status.style().unpolish(self.relay_action_status)
            self.relay_action_status.style().polish(self.relay_action_status)
        except Exception:
            pass
        self._set_status(text, role, busy=busy)

    def _set_relay_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.request_activation_btn, self.check_relay_status_btn, self.test_token_btn):
            button.setEnabled(enabled)

    def _set_provider_action_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        self.provider_action_status.setText(text)
        self.provider_action_status.setObjectName(role)
        try:
            self.provider_action_status.style().unpolish(self.provider_action_status)
            self.provider_action_status.style().polish(self.provider_action_status)
        except Exception:
            pass
        self._set_status(text, role, busy=busy)

    def _set_provider_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.test_as_btn, self.test_rapidapi_btn):
            button.setEnabled(enabled)

    def _start_airport_search(self) -> None:
        query = self.airport_search.text().strip()
        if len(query) < 2:
            return
        query_key = query.casefold()
        if query_key == self._last_airport_query:
            return
        self._last_airport_query = query_key
        if self._airport_search_future is not None and not self._airport_search_future.done():
            return
        self.airport_results.clear()
        self.airport_results.addItem("Searching airports...")
        self._airport_search_future = API_EXECUTOR.submit(lambda: self.service.airport_search(query, limit=12))
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
            return
        self.airport_results.clear()
        rows = list_payload(payload)
        if not rows:
            self.airport_results.addItem("No airport matches found.")
            return
        for row in rows:
            item = self.QtWidgets.QListWidgetItem(
                f"{row.get('iata') or '---'} / {row.get('icao') or '----'}  {row.get('name') or ''} - {row.get('city') or row.get('municipality') or ''}"
            )
            item.setData(self.QtCore.Qt.UserRole, row)
            self.airport_results.addItem(item)

    def _select_airport_item(self, item: Any) -> None:
        row = item.data(self.QtCore.Qt.UserRole)
        if not isinstance(row, dict):
            return
        iata = str(row.get("iata") or "").upper()
        icao = str(row.get("icao") or "").upper()
        timezone = str(row.get("timezone") or row.get("tz") or "UTC")
        name = str(row.get("name") or row.get("airport") or "Airport")
        city = str(row.get("city") or row.get("municipality") or "")
        self.airport_iata.setText(iata)
        self.airport_icao.setText(icao)
        self.timezone.setText(timezone)
        self.airport_search.blockSignals(True)
        self.airport_search.setText(f"{iata or '---'} / {icao or '----'}")
        self.airport_search.blockSignals(False)
        self.airport_selected.setText(f"Selected: {name}" + (f" - {city}" if city else "") + f" | {timezone}")
        self._update_finish_summary()

    def _activation_payload(self) -> dict[str, Any]:
        return {
            "relay_url": self._clean_relay_display(self.relay_url.text()),
            "activation_token": self.activation_token.text().strip(),
            "airport_iata": self.airport_iata.text().strip().upper(),
            "airport_icao": self.airport_icao.text().strip().upper(),
            "display_name": self.display_name.text().strip(),
            "requested_mode": self._current_mode(),
        }

    def request_activation(self) -> None:
        self._set_relay_action_status("Requesting relay access...", "Muted", busy=True)
        self._set_relay_buttons_enabled(False)
        try:
            result = self.service.setup_activate(self._activation_payload())
        except Exception as exc:
            self._set_status(f"Activation request failed: {exc}", "StatusBad")
            self._set_relay_action_status(f"Activation request failed: {exc}", "StatusBad")
            self._set_relay_buttons_enabled(True)
            return
        self._set_relay_buttons_enabled(True)
        if result.get("activation_token_prefix"):
            self._stored_activation = True
            self.activation_token.clear()
            self.activation_token.setPlaceholderText(f"Stored token linked ({result.get('activation_token_prefix')}...)")
            self.relay_status.setText("Relay access is connected. Token stored locally.")
            self._set_relay_action_status("Relay access is connected. Token stored locally.", "StatusGood")
        elif result.get("ok") is False:
            self._set_relay_action_status(format_value(result.get("error") or result.get("message") or result), "StatusBad")
        else:
            self._set_relay_action_status(format_value(result.get("message") or result.get("status") or result), "StatusWarn")
        self._update_finish_summary()

    def check_activation_status(self) -> None:
        self._set_relay_action_status("Checking relay status...", "Muted", busy=True)
        self._set_relay_buttons_enabled(False)
        try:
            result = self.service.setup_client_status(self._activation_payload())
        except Exception as exc:
            self._set_status(f"Status check failed: {exc}", "StatusBad")
            self._set_relay_action_status(f"Status check failed: {exc}", "StatusBad")
            self._set_relay_buttons_enabled(True)
            return
        self._set_relay_buttons_enabled(True)
        status_text = format_value(result.get("status") or result.get("message") or result)
        status_key = status_text.casefold()
        role = "StatusGood" if result.get("ok") or any(word in status_key for word in ("active", "approved", "connected", "ok")) else "StatusWarn"
        self._set_relay_action_status(status_text, role)

    def test_activation(self) -> None:
        self._set_relay_action_status("Testing activation token...", "Muted", busy=True)
        self._set_relay_buttons_enabled(False)
        try:
            result = self.service.setup_test_activation(self._activation_payload())
        except Exception as exc:
            self._set_status(f"Token test failed: {exc}", "StatusBad")
            self._set_relay_action_status(f"Token test failed: {exc}", "StatusBad")
            self._set_relay_buttons_enabled(True)
            return
        self._set_relay_buttons_enabled(True)
        if result.get("ok"):
            self._set_relay_action_status("Relay token works. You can finish Community Relay setup.", "StatusGood")
            return
        self._set_relay_action_status(format_value(result.get("error") or result.get("message") or result), "StatusBad")

    def test_aviationstack(self) -> None:
        key = self.aviationstack_key.text().strip()
        if not key:
            self._set_provider_action_status("Paste an AviationStack key first.", "StatusWarn")
            return
        self._test_key("/api/setup/test-aviationstack", key, "AviationStack")

    def test_rapidapi(self) -> None:
        key = self.rapidapi_key.text().strip()
        if not key:
            self._set_provider_action_status("Paste a RapidAPI key first.", "StatusWarn")
            return
        self._test_key("/api/setup/test-rapidapi", key, "RapidAPI")

    def _test_key(self, path: str, key: str, label_text: str) -> None:
        self._set_provider_action_status(f"Checking {label_text} key...", busy=True)
        self._set_provider_buttons_enabled(False)
        try:
            result = self.service.setup_test_provider_key(path, key)
        except Exception as exc:
            self._set_provider_action_status(f"Could not check that {label_text} key: {exc}", "StatusBad")
            self._set_provider_buttons_enabled(True)
            return
        self._set_provider_buttons_enabled(True)
        if result.get("ok"):
            self._set_provider_action_status(f"{label_text} key works.", "StatusGood")
        else:
            self._set_provider_action_status(f"Could not check that {label_text} key.", "StatusBad")

    def finish_setup(self) -> None:
        mode = self._current_mode()
        payload = {
            "airport_iata": self.airport_iata.text().strip().upper() or "ZRH",
            "airport_icao": self.airport_icao.text().strip().upper() or "LSZH",
            "timezone": self.timezone.text().strip() or "Europe/Zurich",
            "source": "virtual" if mode == "virtual" else "real",
            "setup_mode": mode,
            "display_name": self.display_name.text().strip() or "Local Flight",
            "diagnostics_mode": self._current_diagnostics_mode(),
            "relay_url": self._clean_relay_display(self.relay_url.text()) if mode == "community" else "",
            "activation_token": self.activation_token.text().strip() if mode == "community" else "",
            "aviationstack_key": self.aviationstack_key.text().strip() if mode == "byok" else "",
            "rapidapi_key": self.rapidapi_key.text().strip() if mode == "byok" else "",
            "opensky_id": self.opensky_id.text().strip() if mode == "byok" else "",
            "opensky_secret": self.opensky_secret.text().strip() if mode == "byok" else "",
        }
        self._set_setup_buttons_enabled(False)
        self._set_status("Saving setup and preparing the native display...", busy=True)
        try:
            result = self.service.setup_complete(payload)
        except Exception as exc:
            self._set_status(f"Setup failed: {exc}", "StatusBad")
            self._set_setup_buttons_enabled(True)
            return
        self._set_status("Setup complete. Opening the native display..." if result.get("ok", True) else format_value(result), "StatusGood" if result.get("ok", True) else "StatusWarn")
        if result.get("ok", True):
            try:
                self.service.clear_cache()
            except Exception:
                pass
            if self.on_setup_complete:
                self.on_setup_complete()
        else:
            self._set_setup_buttons_enabled(True)

    def _set_setup_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.web_fallback_btn, self.back_btn, self.next_btn, self.finish_btn):
            button.setEnabled(enabled)


__all__ = ["NativeSetupWindow", "SetupScreen", "PROVIDER_LINKS"]
