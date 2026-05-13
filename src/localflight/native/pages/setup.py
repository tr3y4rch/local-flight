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
from localflight.ui.setup_guidance import (
    DIAGNOSTICS_OPTIONS,
    PROVIDER_LINKS as SETUP_PROVIDER_LINKS,
    SOURCE_OPTIONS,
    STEP_NAMES,
    STEP_SHORT_LABELS,
    WELCOME_CARDS,
    diagnostics_option,
    source_option,
)


DEFAULT_RELAY_URL = "https://localflight-community-relay.fly.dev"
PROVIDER_LINKS: tuple[tuple[str, str], ...] = tuple((item["label"], item["url"]) for item in SETUP_PROVIDER_LINKS)


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
        self.setup_max_width = min(1080, max(540, available_width - 32))
        self.compact_setup = available_width < 900
        self.card_columns = 1 if available_width < 900 else 2 if available_width < 1220 else 3
        self.step_names = list(STEP_NAMES)
        self.step_short_labels = list(STEP_SHORT_LABELS)
        self.step_buttons: list[Any] = []
        self.source_buttons: dict[str, Any] = {}
        self.diagnostics_buttons: dict[str, Any] = {}
        self.provider_link_buttons: dict[str, Any] = {}

        self.widget, layout = scroll_page(QtWidgets)
        self.widget.setMinimumWidth(0)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.status = self._status_chip(
            "Setup is local-first. You can change these choices later in Settings.",
            "muted",
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
        columns = 3 if self.compact_setup else 6
        steps = self.QtWidgets.QGridLayout(steps_wrap)
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setHorizontalSpacing(8)
        steps.setVerticalSpacing(8)
        for idx, name in enumerate(self.step_names):
            short = self.step_short_labels[idx] if idx < len(self.step_short_labels) else name
            button = self.QtWidgets.QPushButton(f"{idx + 1}  {short}")
            button.setObjectName("SetupStepButton")
            button.setCheckable(True)
            button.setMinimumHeight(34)
            button.setToolTip(name)
            button.clicked.connect(lambda _checked=False, i=idx: self._set_step(i))
            self.step_buttons.append(button)
            steps.addWidget(button, idx // columns, idx % columns)
        wrap.addWidget(steps_wrap, 1)
        wrap.addStretch(1)
        return wrap

    def _navigation(self) -> Any:
        wrap = self.QtWidgets.QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.setSpacing(8)
        self.status.setAlignment(self.QtCore.Qt.AlignCenter)
        self.status.setMaximumWidth(self.setup_max_width)
        wrap.addWidget(self.status, 0, self.QtCore.Qt.AlignHCenter)
        nav_wrap = self.QtWidgets.QWidget()
        nav_wrap.setMinimumWidth(0)
        nav_wrap.setMaximumWidth(self.setup_max_width)
        nav = self.QtWidgets.QGridLayout(nav_wrap)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setHorizontalSpacing(8)
        nav.setVerticalSpacing(8)
        self.web_fallback_btn = self.QtWidgets.QPushButton("Open LAN browser setup")
        self.web_fallback_btn.setObjectName("Quiet")
        self.back_btn = self.QtWidgets.QPushButton("Back")
        self.back_btn.setObjectName("Quiet")
        self.next_btn = self.QtWidgets.QPushButton("Next")
        self.finish_btn = self.QtWidgets.QPushButton("Finish setup")
        for button in (self.web_fallback_btn, self.back_btn, self.next_btn, self.finish_btn):
            button.setMinimumHeight(36)
            button.setSizePolicy(self.QtWidgets.QSizePolicy.MinimumExpanding, self.QtWidgets.QSizePolicy.Fixed)
        self.back_btn.clicked.connect(self._previous_step)
        self.next_btn.clicked.connect(self._next_step)
        self.finish_btn.clicked.connect(self.finish_setup)
        self.web_fallback_btn.clicked.connect(lambda: webbrowser.open(f"{self.base_url}/setup"))
        if self.compact_setup:
            nav.addWidget(self.web_fallback_btn, 0, 0, 1, 3)
            nav.addWidget(self.back_btn, 1, 0)
            nav.addWidget(self.next_btn, 1, 1)
            nav.addWidget(self.finish_btn, 1, 2)
        else:
            nav.addWidget(self.web_fallback_btn, 0, 0)
            spacer = self.QtWidgets.QSpacerItem(20, 1, self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Minimum)
            nav.addItem(spacer, 0, 1)
            nav.addWidget(self.back_btn, 0, 2)
            nav.addWidget(self.next_btn, 0, 3)
            nav.addWidget(self.finish_btn, 0, 4)
        wrap.addWidget(nav_wrap, 0, self.QtCore.Qt.AlignHCenter)
        return wrap

    def _page(self, title: str, text: str) -> tuple[Any, Any]:
        page = self.QtWidgets.QFrame()
        page.setObjectName("SetupPanel")
        page.setMinimumWidth(0)
        page.setMaximumWidth(self.setup_max_width)
        layout = self.QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title_label = label(self.QtWidgets, title, "SetupTitle", wrap=True)
        title_label.setTextFormat(self.QtCore.Qt.RichText)
        layout.addWidget(title_label)
        layout.addWidget(label(self.QtWidgets, text, "SetupMuted", wrap=True))
        self.tabs.addWidget(page)
        return page, layout

    def _repolish(self, widget: Any) -> None:
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        except Exception:
            pass

    def _status_chip(self, text: str, tone: str = "muted") -> Any:
        chip = label(self.QtWidgets, text, "SetupStatusChip", wrap=True)
        chip.setProperty("tone", tone)
        return chip

    def _set_chip(self, chip: Any, text: str, tone: str = "muted") -> None:
        chip.setText(text)
        chip.setProperty("tone", tone)
        self._repolish(chip)

    def _option_card(
        self,
        *,
        icon: str,
        title: str,
        body: str,
        click: Callable[[], None] | None = None,
        selected: bool = False,
    ) -> Any:
        card = self.QtWidgets.QFrame()
        card.setObjectName("SetupOptionCard")
        card.setProperty("selected", bool(selected))
        card.setMinimumHeight(122)
        if click is not None:
            card.setCursor(self.QtCore.Qt.PointingHandCursor)
        card.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Preferred)
        layout = self.QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        row = self.QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        badge = label(self.QtWidgets, icon, "SetupBadge")
        badge.setAlignment(self.QtCore.Qt.AlignCenter)
        row.addWidget(badge, 0, self.QtCore.Qt.AlignLeft | self.QtCore.Qt.AlignVCenter)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(label(self.QtWidgets, title, "SetupCardTitle", wrap=True))
        layout.addWidget(label(self.QtWidgets, body, "SetupCardBody", wrap=True), 1)
        if click is not None:
            card.mousePressEvent = lambda _event, fn=click: fn()
        return card

    def _set_card_selected(self, card: Any, selected: bool) -> None:
        card.setProperty("selected", bool(selected))
        self._repolish(card)

    def _summary_card(self, title: str, value: str, *, tone: str = "muted") -> Any:
        card = self.QtWidgets.QFrame()
        card.setObjectName("SetupSummaryCard")
        card.setProperty("tone", tone)
        layout = self.QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)
        layout.addWidget(label(self.QtWidgets, title, "Kicker", wrap=True))
        value_label = label(self.QtWidgets, value, "SetupSummaryValue", wrap=True)
        layout.addWidget(value_label)
        card.value_label = value_label
        return card

    def _build_welcome_page(self) -> None:
        _page, layout = self._page(
            'Welcome to <span style="font-family: Audiowide; font-weight: 400; letter-spacing: 1px;">Local Flight</span>',
            "A guided first launch for your local airport board. Pick the airport, choose the flight data path, and decide how diagnostics should behave.",
        )
        logo = self.QtWidgets.QLabel()
        logo.setAlignment(self.QtCore.Qt.AlignCenter)
        logo.setMinimumHeight(94 if self.compact_setup else 120)
        logo.setObjectName("SetupBrandMark")
        self.logo_label = logo
        if self.QtGui is not None:
            logo_size = 104 if self.compact_setup else 132
            pixmap = pixmap_from_media(self.QtCore, self.QtGui, "ui", "static", "localflight-logo.svg", width=logo_size, height=logo_size)
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
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        for index, card in enumerate(WELCOME_CARDS):
            cards.addWidget(
                self._mini_card(card["title"], card["body"], icon=card.get("icon", "")),
                index // self.card_columns,
                index % self.card_columns,
            )
        layout.addLayout(cards)
        self.start_btn = self.QtWidgets.QPushButton("Start setup")
        self.start_btn.clicked.connect(lambda: self._set_step(1))
        start_row = self.QtWidgets.QHBoxLayout()
        start_row.addStretch(1)
        start_row.addWidget(self.start_btn)
        layout.addLayout(start_row)
        layout.addStretch(1)

    def _mini_card(self, title: str, body: str, *, icon: str = "") -> Any:
        return self._option_card(icon=icon, title=title, body=body)

    def _build_airport_page(self) -> None:
        _page, layout = self._page(
            "Choose Your Airport",
            "Search by city, airport name, IATA, or ICAO. Pick one result and the technical codes are filled for you.",
        )
        self.airport_search = self.QtWidgets.QLineEdit()
        self.airport_search.setPlaceholderText("Search airport, city, IATA, or ICAO...")
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMinimumHeight(150 if self.compact_setup else 170)
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.airport_search_status = self._status_chip("Type at least two characters to search the built-in airport database.", "muted")
        self.airport_selected = self._status_chip("Selected: ZRH / LSZH | Europe/Zurich", "good")
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
        layout.addWidget(self.airport_search_status)
        layout.addWidget(self.airport_results)
        layout.addWidget(self.airport_selected)
        layout.addLayout(form)

    def _build_source_page(self) -> None:
        _page, layout = self._page(
            "Choose Flight Data",
            "Pick the path you actually want. Community Relay stays simple, BYOK is for direct provider accounts, and VATSIM is the no-key virtual path.",
        )
        self.setup_mode = self.QtWidgets.QComboBox()
        for option in SOURCE_OPTIONS:
            self.setup_mode.addItem(option["title"], option["mode"])
        self.setup_mode.hide()

        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        for index, option in enumerate(SOURCE_OPTIONS):
            mode = option["mode"]
            card = self._option_card(
                icon=option["icon"],
                title=option["title"],
                body=option["body"],
                click=lambda m=mode: self._set_mode(m),
            )
            self.source_buttons[mode] = card
            cards.addWidget(card, index // self.card_columns, index % self.card_columns)
        layout.addLayout(cards)
        self.mode_help = self._status_chip("", "muted")
        layout.addWidget(self.mode_help)

        self.relay_box, relay_layout = panel(self.QtWidgets, "Relay Access")
        self.relay_url = self.QtWidgets.QLineEdit(DEFAULT_RELAY_URL)
        self.relay_url.setPlaceholderText(DEFAULT_RELAY_URL)
        self.activation_token = self.QtWidgets.QLineEdit()
        self.activation_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.activation_token.setPlaceholderText("Paste activation token only if one was given to you")
        self.token_toggle = self.QtWidgets.QPushButton("Show token")
        self.token_toggle.setObjectName("Quiet")
        self.token_toggle.clicked.connect(lambda: self._toggle_secret(self.activation_token, self.token_toggle, "token"))
        token_row = self.QtWidgets.QHBoxLayout()
        token_row.addWidget(self.activation_token, 1)
        token_row.addWidget(self.token_toggle)
        relay_form = self.QtWidgets.QFormLayout()
        relay_form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        relay_form.addRow("Relay host", self.relay_url)
        relay_layout.addLayout(relay_form)
        self.token_box = self.QtWidgets.QFrame()
        self.token_box.setObjectName("PreviewCard")
        token_box_layout = self.QtWidgets.QVBoxLayout(self.token_box)
        token_box_layout.setContentsMargins(12, 10, 12, 10)
        token_box_layout.setSpacing(7)
        token_box_layout.addWidget(label(self.QtWidgets, "Manual token", "Kicker", wrap=True))
        token_box_layout.addWidget(label(self.QtWidgets, "Only paste a token here if the relay operator gave you one. Stored relay links stay local and do not need to be pasted again.", "SetupMuted", wrap=True))
        token_box_layout.addLayout(token_row)
        relay_layout.addWidget(self.token_box)
        relay_actions = self.QtWidgets.QHBoxLayout()
        self.request_activation_btn = self.QtWidgets.QPushButton("Request activation")
        self.check_relay_status_btn = self.QtWidgets.QPushButton("Check relay status")
        self.test_token_btn = self.QtWidgets.QPushButton("Test token")
        self.request_activation_btn.clicked.connect(self.request_activation)
        self.check_relay_status_btn.clicked.connect(self.check_activation_status)
        self.test_token_btn.clicked.connect(self.test_activation)
        for idx, button in enumerate((self.request_activation_btn, self.check_relay_status_btn, self.test_token_btn)):
            button.setMinimumHeight(34)
            relay_actions.addWidget(button)
        relay_actions.addStretch(1)
        self.relay_status = self._status_chip("Relay is the beginner path. Token values stay hidden.", "muted")
        self.relay_action_status = self._status_chip("", "muted")
        self.relay_action_status.hide()
        relay_layout.addLayout(relay_actions)
        relay_layout.addWidget(self.relay_status)
        relay_layout.addWidget(self.relay_action_status)
        layout.addWidget(self.relay_box)
        layout.addStretch(1)

    def _build_keys_page(self) -> None:
        _page, layout = self._page(
            "Optional Provider Keys",
            "Only BYOK needs AviationStack. ADS-B Exchange and OpenSky are optional enrichment sources; Community Relay and VATSIM can skip this page.",
        )
        self.keys_hint = self._status_chip("Community Relay and VATSIM can skip this page.", "muted")
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
        self.provider_action_status = self._status_chip("Provider key checks ready.", "muted")
        layout.addWidget(self.provider_action_status)
        layout.addStretch(1)

    def _build_diagnostics_page(self) -> None:
        _page, layout = self._page(
            "Diagnostics",
            "Choose how Local Flight may help report problems. Manual reports are always available.",
        )
        self.diagnostics_mode = self.QtWidgets.QComboBox()
        for option in DIAGNOSTICS_OPTIONS:
            self.diagnostics_mode.addItem(option["title"], option["mode"])
        self.diagnostics_mode.hide()
        layout.addWidget(self.diagnostics_mode)
        cards = self.QtWidgets.QGridLayout()
        cards.setHorizontalSpacing(12)
        cards.setVerticalSpacing(12)
        for index, option in enumerate(DIAGNOSTICS_OPTIONS):
            mode = option["mode"]
            card = self._option_card(
                icon=option["icon"],
                title=option["title"],
                body=option["body"],
                click=lambda m=mode: self._set_diagnostics_mode(m),
            )
            self.diagnostics_buttons[mode] = card
            cards.addWidget(card, index // self.card_columns, index % self.card_columns)
        layout.addLayout(cards)
        self.diagnostics_help = self._status_chip(
            "Privacy rule: no provider keys, activation tokens, raw install IDs, pilot identities, or internal secrets are shown here or sent from the client UI.",
            "muted",
        )
        layout.addWidget(self.diagnostics_help)
        layout.addStretch(1)
        self._set_diagnostics_mode("manual")

    def _build_finish_page(self) -> None:
        _page, layout = self._page(
            "Review & Launch",
            "Review the simple version. Finish saves the local setup and opens Local Flight.",
        )
        self.finish_grid = self.QtWidgets.QGridLayout()
        self.finish_grid.setHorizontalSpacing(10)
        self.finish_grid.setVerticalSpacing(10)
        self.finish_cards: dict[str, Any] = {
            "airport": self._summary_card("Airport", "ZRH / LSZH"),
            "timezone": self._summary_card("Timezone", "Europe/Zurich"),
            "source": self._summary_card("Flight data", "Community Relay", tone="good"),
            "relay": self._summary_card("Relay access", "Token needed or pending"),
            "keys": self._summary_card("Provider keys", "No provider keys saved"),
            "diagnostics": self._summary_card("Diagnostics", "Manual reports only"),
        }
        for index, card in enumerate(self.finish_cards.values()):
            self.finish_grid.addWidget(card, index // max(1, min(2, self.card_columns)), index % max(1, min(2, self.card_columns)))
        layout.addLayout(self.finish_grid)
        self.finish_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.finish_summary.hide()
        self.diagnostics_note = self._status_chip(
            "Diagnostics can be changed later in Settings. Provider keys and tokens are never displayed in this summary.",
            "muted",
        )
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
        for key, card in self.source_buttons.items():
            self._set_card_selected(card, key == active_mode)
        self._sync_mode_ui()
        self._update_finish_summary()

    def _set_diagnostics_mode(self, mode: str) -> None:
        idx = self.diagnostics_mode.findData(mode)
        self.diagnostics_mode.setCurrentIndex(idx if idx >= 0 else 0)
        active_mode = self._current_diagnostics_mode()
        for key, card in self.diagnostics_buttons.items():
            self._set_card_selected(card, key == active_mode)
        self._set_chip(self.diagnostics_help, diagnostics_option(active_mode)["note"], "good" if active_mode == "manual" else "warn")
        self._update_finish_summary()

    def _sync_mode_ui(self) -> None:
        mode = self._current_mode()
        self.relay_box.setVisible(mode == "community")
        self.mode_help.setText(source_option(mode)["note"])
        if mode == "community":
            self._set_chip(self.keys_hint, "Community Relay mode skips provider keys. You can add your own keys later in Settings.", "good")
        elif mode == "byok":
            self._set_chip(self.keys_hint, "Paste an AviationStack key. ADS-B Exchange on RapidAPI and OpenSky are optional enrichment helpers.", "warn")
        else:
            self._set_chip(self.keys_hint, "VATSIM needs no provider keys. This setup saves source=virtual.", "good")

    def _mode_label(self, mode: str) -> str:
        return source_option(mode)["title"]

    def _diagnostics_label(self, mode: str) -> str:
        if mode == "unset":
            return "Not chosen"
        return diagnostics_option(mode)["title"]

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
        rows = {
            "airport": f"{self.airport_iata.text().strip().upper() or 'ZRH'} / {self.airport_icao.text().strip().upper() or 'LSZH'}",
            "timezone": self.timezone.text().strip() or "Europe/Zurich",
            "source": self._mode_label(mode),
            "relay": relay_state,
            "keys": key_state,
            "diagnostics": self._diagnostics_label(diagnostics),
        }
        if hasattr(self, "finish_cards"):
            for key, value in rows.items():
                card = self.finish_cards.get(key)
                if card is not None:
                    card.value_label.setText(value)
            self.finish_cards["source"].setProperty("tone", "good" if mode in {"community", "virtual"} else "warn")
            self.finish_cards["relay"].setProperty("tone", "good" if relay_state == "connected" else "muted")
            self.finish_cards["keys"].setProperty("tone", "warn" if mode == "byok" and "will be saved" in key_state else "muted")
            self.finish_cards["diagnostics"].setProperty("tone", "good" if diagnostics == "manual" else "warn")
            for card in self.finish_cards.values():
                self._repolish(card)
        self.finish_summary.setText(
            "\n".join(
                [
                    f"Airport: {rows['airport']}",
                    f"Timezone: {rows['timezone']}",
                    f"Display name: {self.display_name.text().strip() or 'Local Flight'}",
                    f"Data path: {rows['source']}",
                    f"Source saved as: {source}",
                    f"Relay access: {rows['relay']}",
                    f"Provider keys: {rows['keys']}",
                    f"Diagnostics: {rows['diagnostics']}",
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
            self._set_chip(self.relay_status, "Relay access is connected. You can finish Community Relay setup without pasting a token.", "good")
            self.token_box.hide()
        else:
            self.activation_token.setPlaceholderText("Paste activation token only if one was given to you")
            self._set_chip(self.relay_status, "Relay access is not linked yet. Request or test a token, or choose VATSIM to continue without one.", "warn")
            self.token_box.show()
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
        self.status.setProperty("tone", self._tone_for_role(role))
        self.loading_indicator.setVisible(bool(busy))
        self._repolish(self.status)
        if busy:
            self.QtWidgets.QApplication.processEvents()

    def _tone_for_role(self, role: str = "Muted") -> str:
        return {
            "StatusGood": "good",
            "StatusWarn": "warn",
            "StatusBad": "bad",
            "Muted": "muted",
        }.get(role, "muted")

    def _set_relay_action_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        self.relay_action_status.setText(text)
        self.relay_action_status.setProperty("tone", self._tone_for_role(role))
        self.relay_action_status.setVisible(bool(text))
        self._repolish(self.relay_action_status)
        self._set_status(text, role, busy=busy)

    def _set_relay_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.request_activation_btn, self.check_relay_status_btn, self.test_token_btn):
            button.setEnabled(enabled)

    def _set_provider_action_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        self.provider_action_status.setText(text)
        self.provider_action_status.setProperty("tone", self._tone_for_role(role))
        self._repolish(self.provider_action_status)
        self._set_status(text, role, busy=busy)

    def _set_provider_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.test_as_btn, self.test_rapidapi_btn):
            button.setEnabled(enabled)

    def _start_airport_search(self) -> None:
        query = self.airport_search.text().strip()
        if len(query) < 2:
            self._set_airport_status("Type at least two characters to search the built-in airport database.")
            return
        query_key = query.casefold()
        if query_key == self._last_airport_query:
            return
        self._last_airport_query = query_key
        if self._airport_search_future is not None and not self._airport_search_future.done():
            return
        self.airport_results.clear()
        self.airport_results.addItem("Searching airports...")
        self._set_airport_status("Searching airports...", "Muted")
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
            self._set_airport_status(f"Search failed: {exc}", "StatusBad")
            return
        self.airport_results.clear()
        rows = list_payload(payload)
        if not rows:
            self.airport_results.addItem("No airport matches found.")
            self._set_airport_status("No airport matches found. Try a city, IATA, or ICAO code.", "StatusWarn")
            return
        self._set_airport_status(f"{len(rows)} airport matches found. Pick the correct airport from the list.", "StatusGood")
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
        self._set_airport_status(f"Airport selected: {iata or '---'} / {icao or '----'} | {timezone}", "StatusGood")
        self._update_finish_summary()

    def _set_airport_status(self, text: str, role: str = "Muted") -> None:
        if not hasattr(self, "airport_search_status"):
            return
        self.airport_search_status.setText(text)
        self.airport_search_status.setProperty("tone", self._tone_for_role(role))
        self._repolish(self.airport_search_status)

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
            self._set_chip(self.relay_status, "Relay access is connected. Token stored locally.", "good")
            self.token_box.hide()
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
        self._set_status("Saving setup and preparing Local Flight...", busy=True)
        try:
            result = self.service.setup_complete(payload)
        except Exception as exc:
            self._set_status(f"Setup failed: {exc}", "StatusBad")
            self._set_setup_buttons_enabled(True)
            return
        self._set_status("Setup complete. Opening Local Flight..." if result.get("ok", True) else format_value(result), "StatusGood" if result.get("ok", True) else "StatusWarn")
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
