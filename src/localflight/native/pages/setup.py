"""Native first-run setup flow."""
from __future__ import annotations

import webbrowser
from concurrent.futures import Future
from typing import Any, Callable

from localflight.native.api_client import LocalApiClient
from localflight.native.async_tools import API_EXECUTOR, AsyncFetchMixin
from localflight.native.design import (
    apply_qt_appearance,
    colors_for,
    format_value,
    label,
    list_payload,
    native_stylesheet,
    panel,
    pixmap_from_media,
    scroll_page,
)
from localflight.native.identity import localflight_app_icon
from localflight.native.pages.setup_widgets import (
    build_celebration,
    build_hero,
    build_info_button,
    build_spinner,
    build_stepper,
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


DEFAULT_RELAY_URL = "https://relay.beacontools.cc"
RELAY_ACCESS_URL = "https://beacontools.cc/local-flight/relay-access/"
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
                try:
                    cfg = self.service.config()
                except Exception:
                    cfg = {}
                self.theme = str(cfg.get("theme") or "dark")
                self.skin = str(cfg.get("skin") or "standard")
                apply_qt_appearance(QtCore, QtGui, QtWidgets.QApplication.instance(), theme=self.theme, skin=self.skin)
                self.setStyleSheet(native_stylesheet(theme=self.theme, skin=self.skin))
                app_icon = localflight_app_icon(QtGui)
                if not app_icon.isNull():
                    self.setWindowIcon(app_icon)
                self.setup_screen = SetupScreen(
                    QtCore,
                    QtWidgets,
                    self.client,
                    base_url,
                    on_setup_complete=on_setup_complete,
                    QtGui=QtGui,
                    theme=self.theme,
                    skin=self.skin,
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


class SetupScreen(AsyncFetchMixin):  # pragma: no cover - optional Qt runtime
    def __init__(
        self,
        QtCore: Any,
        QtWidgets: Any,
        client: LocalApiClient,
        base_url: str,
        *,
        on_setup_complete: Callable[[], None] | None = None,
        QtGui: Any | None = None,
        theme: str = "dark",
        skin: str = "standard",
    ) -> None:
        self.QtCore = QtCore
        self.QtGui = QtGui
        self.QtWidgets = QtWidgets
        self.client = client
        self.service = NativeApiService(client)
        self.base_url = base_url.rstrip("/")
        self.on_setup_complete = on_setup_complete
        self.theme = theme if theme in {"dark", "light"} else "dark"
        self.skin = skin or "standard"
        self._airport_search_future: Future[Any] | None = None
        self._last_airport_query = ""
        self._stored_activation = False
        self._pending_move_token = ""
        self._catalog_available = False
        self._saved_provider_state: dict[str, bool] = {}
        self._mode_initialized = False
        self._diagnostics_initialized = False
        screen = self.QtWidgets.QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None
        available_width = available.width() if available is not None else 1200
        available_height = available.height() if available is not None else 900
        self.setup_max_width = min(1080, max(540, available_width - 32))
        self.compact_setup = available_width < 900 or available_height < 820
        self.card_columns = 1 if available_width < 900 else 2 if available_width < 1220 else 3
        self.step_names = list(STEP_NAMES)
        self.step_short_labels = list(STEP_SHORT_LABELS)
        self.source_buttons: dict[str, Any] = {}
        self.diagnostics_buttons: dict[str, Any] = {}
        self.provider_link_buttons: dict[str, Any] = {}

        self.widget = QtWidgets.QWidget()
        self._init_async(QtCore, self.widget)
        self.widget.setMinimumWidth(0)
        root_layout = QtWidgets.QVBoxLayout(self.widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.scroll_area, layout = scroll_page(QtWidgets)
        self.scroll_area.setMinimumWidth(0)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self.status = self._status_chip(
            "Setup is local-first. You can change these choices later in Settings.",
            "muted",
        )
        self.status.hide()
        self._status_hide_timer = QtCore.QTimer(self.widget)
        self._status_hide_timer.setSingleShot(True)
        self._status_hide_timer.timeout.connect(self._clear_status)

        self.tabs = QtWidgets.QStackedWidget()
        self.tabs.setMinimumWidth(0)
        self.tabs.setMaximumWidth(self.setup_max_width)
        self.tabs.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
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
        layout.addWidget(self.tabs, 0, QtCore.Qt.AlignHCenter)
        # Replace the thin marquee with a rotating-glyph spinner. The widget
        # exposes show()/hide()/setVisible() so existing callers keep working.
        colors = colors_for(self.theme, self.skin)
        if QtGui is not None:
            self.loading_indicator = build_spinner(
                QtCore,
                QtGui,
                QtWidgets,
                accent_hex=colors.get("blue", "#4a9eda"),
                text_hex=colors.get("text", "#e8f0fe"),
            )
        else:
            # Headless preview path keeps the old QProgressBar so tests can
            # introspect the widget tree without optional Qt assets.
            self.loading_indicator = QtWidgets.QProgressBar()
            self.loading_indicator.setObjectName("LoadingProgress")
            self.loading_indicator.setRange(0, 0)
            self.loading_indicator.setTextVisible(False)
            self.loading_indicator.setFixedHeight(7)
            self.loading_indicator.hide()
        self.loading_indicator.setMaximumWidth(self.setup_max_width)
        footer = QtWidgets.QFrame()
        footer.setObjectName("SetupFooter")
        footer_layout = QtWidgets.QVBoxLayout(footer)
        footer_layout.setContentsMargins(12, 8, 12, 10)
        footer_layout.setSpacing(6)
        footer_layout.addWidget(self.loading_indicator, 0, QtCore.Qt.AlignHCenter)
        footer_layout.addLayout(self._navigation())
        root_layout.addWidget(self.scroll_area, 1)
        root_layout.addWidget(footer, 0)

        self._set_step(0)
        self.refresh()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def _step_header(self) -> Any:
        wrap = self.QtWidgets.QHBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addStretch(1)
        colors = colors_for(self.theme, self.skin)
        accent = colors.get("blue", "#4a9eda")
        text_hex = colors.get("text", "#e8f0fe")
        muted_hex = colors.get("muted", "#9aa3b2")
        line_hex = colors.get("line", "#1d2733")
        if self.QtGui is None:
            # Headless / preview-only path — fall back to a static caption.
            placeholder = self.QtWidgets.QLabel(
                f"Step 1 of {len(self.step_names)} · {self.step_names[0]}"
            )
            placeholder.setObjectName("SetupStepperFallback")
            wrap.addWidget(placeholder, 1)
            wrap.addStretch(1)
            self.stepper = placeholder
            return wrap
        stepper = build_stepper(
            self.QtCore,
            self.QtGui,
            self.QtWidgets,
            step_names=self.step_names,
            step_short_labels=self.step_short_labels,
            on_step_clicked=lambda idx: self._set_step(idx),
            accent_hex=accent,
            text_hex=text_hex,
            muted_hex=muted_hex,
            line_hex=line_hex,
            compact=self.compact_setup,
        )
        stepper.setMaximumWidth(self.setup_max_width)
        stepper.setMinimumWidth(min(540, self.setup_max_width))
        stepper.setSizePolicy(
            self.QtWidgets.QSizePolicy.Expanding,
            self.QtWidgets.QSizePolicy.Fixed,
        )
        self.stepper = stepper

        # Caption above the stepper for clarity: "Step 1 of 6 · Welcome".
        self.step_caption = self.QtWidgets.QLabel("")
        self.step_caption.setObjectName("SetupStepCaption")
        self.step_caption.setAlignment(self.QtCore.Qt.AlignCenter)
        column = self.QtWidgets.QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(self.step_caption, 0, self.QtCore.Qt.AlignHCenter)
        column.addWidget(stepper, 0)
        wrap.addLayout(column, 1)
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
        self.web_fallback_btn = self.QtWidgets.QPushButton("\U0001F310  Open LAN browser setup")
        self.web_fallback_btn.setObjectName("Quiet")
        self.back_btn = self.QtWidgets.QPushButton("◀  Back")
        self.back_btn.setObjectName("Quiet")
        self.next_btn = self.QtWidgets.QPushButton("Next  ▶")
        self.next_btn.setObjectName("SetupPrimary")
        self.finish_btn = self.QtWidgets.QPushButton("✅  Finish setup")
        self.finish_btn.setObjectName("SetupPrimary")
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
        page.setSizePolicy(self.QtWidgets.QSizePolicy.Expanding, self.QtWidgets.QSizePolicy.Preferred)
        layout = self.QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(9)
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
            card.setFocusPolicy(self.QtCore.Qt.StrongFocus)
            card.setAccessibleName(title)
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
            def _activate_from_keyboard(event: Any, fn: Callable[[], None] = click) -> None:
                if event.key() in {self.QtCore.Qt.Key_Return, self.QtCore.Qt.Key_Enter, self.QtCore.Qt.Key_Space}:
                    fn()
                    event.accept()
                    return
                self.QtWidgets.QFrame.keyPressEvent(card, event)

            card.keyPressEvent = _activate_from_keyboard
        return card

    def _set_card_selected(self, card: Any, selected: bool) -> None:
        card.setProperty("selected", bool(selected))
        card.setAccessibleDescription("Selected" if selected else "Not selected")
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
        # Animated hero block (radar rings + floating logo + tagline). Falls
        # back to a static brand label when QtGui is unavailable.
        if self.QtGui is not None:
            logo_size = 104 if self.compact_setup else 132
            pixmap = pixmap_from_media(
                self.QtCore,
                self.QtGui,
                "ui",
                "static",
                "localflight-logo.svg",
                width=logo_size,
                height=logo_size,
            )
            colors = colors_for(self.theme, self.skin)
            hero = build_hero(
                self.QtCore,
                self.QtGui,
                self.QtWidgets,
                pixmap=pixmap,
                accent_hex=colors.get("blue", "#4a9eda"),
                text_hex=colors.get("text", "#e8f0fe"),
                muted_hex=colors.get("muted", "#9aa3b2"),
                tagline=(
                    "Your local airport board — pixel-perfect, private, and yours."
                ),
                compact=self.compact_setup,
            )
            self.logo_label = hero
            layout.addWidget(hero)
        else:
            logo = self.QtWidgets.QLabel("Local Flight")
            logo.setAlignment(self.QtCore.Qt.AlignCenter)
            logo.setMinimumHeight(94 if self.compact_setup else 120)
            logo.setObjectName("BrandTitle")
            self.logo_label = logo
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
        self.start_btn = self.QtWidgets.QPushButton("\U0001F680  Start setup")
        self.start_btn.setObjectName("SetupPrimary")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.clicked.connect(lambda: self._set_step(1))
        start_row = self.QtWidgets.QHBoxLayout()
        start_row.addStretch(1)
        start_row.addWidget(self.start_btn)
        layout.addLayout(start_row)
        layout.addStretch(1)

    def _mini_card(self, title: str, body: str, *, icon: str = "") -> Any:
        card = self._option_card(icon=icon, title=title, body=body)
        card.setMinimumHeight(150 if self.card_columns >= 3 else 140)
        return card

    def _build_airport_page(self) -> None:
        _page, layout = self._page(
            "Choose Your Airport",
            "Search by city, airport name, IATA, or ICAO. Pick one result and the technical codes are filled for you.",
        )
        self.airport_search = self.QtWidgets.QLineEdit()
        self.airport_search.setPlaceholderText("Search airport, city, IATA, or ICAO...")
        self.airport_search.textChanged.connect(lambda _text: self.search_timer.start(250))
        self.airport_results = self.QtWidgets.QListWidget()
        self.airport_results.setMinimumHeight(120 if self.compact_setup else 135)
        self.airport_results.setMaximumHeight(170 if self.compact_setup else 190)
        self.airport_results.setSizePolicy(
            self.QtWidgets.QSizePolicy.Expanding,
            self.QtWidgets.QSizePolicy.Fixed,
        )
        self.airport_results.itemClicked.connect(self._select_airport_item)
        self.airport_search_status = self._status_chip("Type at least two characters to search the built-in airport database.", "muted")
        self.airport_selected = self._status_chip("Selected: ZRH / LSZH | Europe/Zurich", "good")
        self.display_name = self.QtWidgets.QLineEdit("Local Flight")
        self.display_name.textChanged.connect(lambda _text: self._activation_details_changed())
        self.airport_iata = self.QtWidgets.QLineEdit("ZRH")
        self.airport_icao = self.QtWidgets.QLineEdit("LSZH")
        self.timezone = self.QtWidgets.QLineEdit("Europe/Zurich")
        for field in (self.airport_iata, self.airport_icao, self.timezone):
            field.setReadOnly(True)
        form = self.QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.addRow(
            self._field_label(
                "Display name",
                "Friendly title shown on the FIDS board, e.g. your home airport name.",
            ),
            self.display_name,
        )
        form.addRow(
            self._field_label(
                "Airport IATA",
                "3-letter airline code (e.g. ZRH). Filled automatically from the search result.",
            ),
            self.airport_iata,
        )
        form.addRow(
            self._field_label(
                "Airport ICAO",
                "4-letter ICAO code (e.g. LSZH). Used for METAR and ATC lookups. Filled automatically.",
            ),
            self.airport_icao,
        )
        form.addRow(
            self._field_label(
                "Timezone",
                "Local timezone of the airport. Used for the FIDS board clock and history grouping.",
            ),
            self.timezone,
        )
        layout.addWidget(self.airport_search)
        layout.addWidget(self.airport_search_status)
        layout.addWidget(self.airport_results)
        layout.addWidget(self.airport_selected)
        layout.addLayout(form)

    def _build_source_page(self) -> None:
        _page, layout = self._page(
            "Choose Flight Data",
            "Choose Beacon Relay, bring your own provider keys, or use VATSIM virtual traffic.",
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
        self.relay_url.setReadOnly(True)
        self.relay_url.setToolTip("Beacon Relay uses the hosted Beacon Tools endpoint.")
        self.activation_token = self.QtWidgets.QLineEdit()
        self.activation_token.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.activation_token.setPlaceholderText("LFRA key or one-time activation code")
        self.activation_token.textChanged.connect(lambda _text: self._activation_details_changed())
        self.token_toggle = self.QtWidgets.QPushButton("Show key")
        self.token_toggle.setObjectName("Quiet")
        self.token_toggle.clicked.connect(lambda: self._toggle_secret(self.activation_token, self.token_toggle, "key"))
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
        token_box_layout.addWidget(label(self.QtWidgets, "Relay Access license key or activation code", "Kicker", wrap=True))
        token_box_layout.addWidget(label(self.QtWidgets, "Local Flight exchanges this for access on this device and does not save the license key.", "SetupMuted", wrap=True))
        token_box_layout.addLayout(token_row)
        relay_layout.addWidget(self.token_box)
        relay_actions = self.QtWidgets.QHBoxLayout()
        self.buy_relay_access_btn = self.QtWidgets.QPushButton("Get Relay Access")
        self.request_activation_btn = self.QtWidgets.QPushButton("Activate this desktop")
        self.check_relay_status_btn = self.QtWidgets.QPushButton("Check access")
        self.test_token_btn = self.QtWidgets.QPushButton("Test access")
        self.buy_relay_access_btn.clicked.connect(lambda: webbrowser.open(RELAY_ACCESS_URL))
        self.request_activation_btn.clicked.connect(lambda _checked=False: self.request_activation())
        self.check_relay_status_btn.clicked.connect(self.check_activation_status)
        self.test_token_btn.clicked.connect(self.test_activation)
        for idx, button in enumerate((self.buy_relay_access_btn, self.request_activation_btn, self.check_relay_status_btn, self.test_token_btn)):
            button.setMinimumHeight(44)
            relay_actions.addWidget(button)
        relay_actions.addStretch(1)
        self.relay_status = self._status_chip("Relay Access can be active on one desktop or one phone in Standalone mode.", "muted")
        self.relay_action_status = self._status_chip("", "muted")
        self.relay_action_status.hide()
        relay_layout.addLayout(relay_actions)
        relay_layout.addWidget(self.relay_status)
        relay_layout.addWidget(self.relay_action_status)
        self.move_warning = self.QtWidgets.QFrame()
        self.move_warning.setObjectName("PreviewCard")
        move_layout = self.QtWidgets.QVBoxLayout(self.move_warning)
        move_layout.setContentsMargins(12, 10, 12, 10)
        self.move_warning_text = self._status_chip("", "warn")
        move_layout.addWidget(self.move_warning_text)
        move_actions = self.QtWidgets.QHBoxLayout()
        self.keep_relay_there_btn = self.QtWidgets.QPushButton("Keep it there")
        self.move_relay_here_btn = self.QtWidgets.QPushButton("Move to this desktop")
        self.keep_relay_there_btn.clicked.connect(self.keep_relay_there)
        self.move_relay_here_btn.clicked.connect(self.move_relay_here)
        self.keep_relay_there_btn.setMinimumHeight(44)
        self.move_relay_here_btn.setMinimumHeight(44)
        move_actions.addWidget(self.keep_relay_there_btn)
        move_actions.addWidget(self.move_relay_here_btn)
        move_actions.addStretch(1)
        move_layout.addLayout(move_actions)
        self.move_warning.hide()
        relay_layout.addWidget(self.move_warning)
        layout.addWidget(self.relay_box)
        layout.addStretch(1)

    def _build_keys_page(self) -> None:
        _page, layout = self._page(
            "Direct Provider Keys",
            "BYOK keeps schedule and radar calls on this server install. Use AeroDataBox or AviationStack for schedules, ADS-B Exchange on RapidAPI for radar, and OpenSky only as optional fallback.",
        )
        self.keys_hint = self._status_chip("Beacon Relay and VATSIM can skip this page.", "muted")
        self.provider_path_hint = self._status_chip(
            "Schedules: AeroDataBox primary, AviationStack fill/fallback. Radar: ADS-B Exchange via RapidAPI.",
            "muted",
        )
        layout.addWidget(self.keys_hint)
        layout.addWidget(self.provider_path_hint)
        self.aerodatabox_key = self.QtWidgets.QLineEdit()
        self.aerodatabox_marketplace = self.QtWidgets.QComboBox()
        self.aerodatabox_marketplace.addItem("API.Market", "apimarket")
        self.aerodatabox_marketplace.addItem("RapidAPI", "rapidapi")
        self.aerodatabox_monthly_limit = self.QtWidgets.QSpinBox()
        self.aerodatabox_monthly_limit.setRange(0, 250000)
        self.aerodatabox_monthly_limit.setValue(24000)
        self.aviationstack_key = self.QtWidgets.QLineEdit()
        self.rapidapi_key = self.QtWidgets.QLineEdit()
        self.opensky_id = self.QtWidgets.QLineEdit()
        self.opensky_secret = self.QtWidgets.QLineEdit()
        for field in (self.aerodatabox_key, self.aviationstack_key, self.rapidapi_key, self.opensky_secret):
            field.setEchoMode(self.QtWidgets.QLineEdit.Password)
        self.aerodatabox_key.setPlaceholderText("AeroDataBox API key")
        self.aviationstack_key.setPlaceholderText("AviationStack API key")
        self.rapidapi_key.setPlaceholderText("ADS-B Exchange RapidAPI key")
        self.opensky_id.setPlaceholderText("OpenSky client ID")
        self.opensky_secret.setPlaceholderText("OpenSky client secret")
        form = self.QtWidgets.QFormLayout()
        form.setFieldGrowthPolicy(self.QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        form.addRow(
            self._field_label(
                "AeroDataBox schedules",
                "Recommended BYOK schedule provider. Stored locally, primary in auto mode, and used before any schedule relay.",
            ),
            self._secret_row(self.aerodatabox_key, "AeroDataBox key"),
        )
        form.addRow("AeroDataBox marketplace", self.aerodatabox_marketplace)
        form.addRow("AeroDataBox monthly unit guard", self.aerodatabox_monthly_limit)
        form.addRow(
            self._field_label(
                "AviationStack fallback",
                "Optional if AeroDataBox is set. Used as sparse-fill/fallback or as the direct source by itself.",
            ),
            self._secret_row(self.aviationstack_key, "AviationStack key"),
        )
        form.addRow(
            self._field_label(
                "ADS-B Exchange radar",
                "Optional RapidAPI key for direct live radar positions without the radar relay.",
            ),
            self._secret_row(self.rapidapi_key, "ADS-B Exchange key"),
        )
        form.addRow(
            self._field_label(
                "OpenSky ID",
                "Optional OpenSky client ID for free anonymous radar enrichment.",
            ),
            self.opensky_id,
        )
        form.addRow(
            self._field_label(
                "OpenSky Secret",
                "Pair with the OpenSky client ID above. Stored encrypted on this machine only.",
            ),
            self._secret_row(self.opensky_secret, "OpenSky secret"),
        )
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
        self.test_adb_btn = self.QtWidgets.QPushButton("\U0001F9EA  Test AeroDataBox")
        self.test_as_btn = self.QtWidgets.QPushButton("\U0001F9EA  Test AviationStack")
        self.test_rapidapi_btn = self.QtWidgets.QPushButton("\U0001F9EA  Test RapidAPI")
        self.test_adb_btn.clicked.connect(self.test_aerodatabox)
        self.test_as_btn.clicked.connect(self.test_aviationstack)
        self.test_rapidapi_btn.clicked.connect(self.test_rapidapi)
        tests.addWidget(self.test_adb_btn)
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
            "Privacy rule: no provider keys, Relay Access credentials, raw install IDs, pilot identities, or internal secrets are shown here or sent from the client UI.",
            "muted",
        )
        layout.addWidget(self.diagnostics_help)
        layout.addStretch(1)
        self._set_diagnostics_mode("manual")

    def _build_finish_page(self) -> None:
        _page, layout = self._page(
            "Review & Launch",
            "Review your launch choices. Finish saves this setup locally and opens Local Flight.",
        )
        self.finish_grid = self.QtWidgets.QGridLayout()
        self.finish_grid.setHorizontalSpacing(10)
        self.finish_grid.setVerticalSpacing(10)
        self.finish_cards: dict[str, Any] = {
            "airport": self._summary_card("Airport", "ZRH / LSZH"),
            "timezone": self._summary_card("Timezone", "Europe/Zurich"),
            "source": self._summary_card("Flight data", "Beacon Relay", tone="good"),
            "relay": self._summary_card("Relay access", "License activation required"),
            "keys": self._summary_card("Provider keys", "No provider keys saved"),
            "diagnostics": self._summary_card("Diagnostics", "Manual reports only"),
        }
        for index, card in enumerate(self.finish_cards.values()):
            self.finish_grid.addWidget(card, index // max(1, min(2, self.card_columns)), index % max(1, min(2, self.card_columns)))
        layout.addLayout(self.finish_grid)
        self.finish_summary = label(self.QtWidgets, "", "Muted", wrap=True)
        self.finish_summary.hide()
        self.diagnostics_note = self._status_chip(
            "Diagnostics can be changed later in Settings. Provider keys and Relay Access credentials are never displayed in this summary.",
            "muted",
        )
        layout.addWidget(self.diagnostics_note)
        layout.addWidget(self._link_button("Open VATSIM status", "https://network-status.vatsim.net/"))
        layout.addStretch(1)

    def _link_button(self, text: str, url: str) -> Any:
        button = self.QtWidgets.QPushButton("\U0001F517  " + text)
        button.setObjectName("Quiet")
        button.setProperty("url", url)
        button.clicked.connect(lambda _checked=False, u=url: webbrowser.open(u))
        return button

    def _field_label(self, text: str, help_text: str) -> Any:
        """Build a form-row label with an inline info bubble."""
        container = self.QtWidgets.QWidget()
        layout = self.QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        text_label = self.QtWidgets.QLabel(text)
        text_label.setObjectName("SetupFieldLabel")
        layout.addWidget(text_label)
        if self.QtGui is not None:
            layout.addWidget(
                build_info_button(self.QtCore, self.QtGui, self.QtWidgets, text=help_text)
            )
        layout.addStretch(1)
        return container

    def _secret_row(self, field: Any, label_text: str = "secret") -> Any:
        """Wrap a password QLineEdit with an eye toggle button."""
        container = self.QtWidgets.QWidget()
        layout = self.QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(field, 1)
        eye = self.QtWidgets.QToolButton()
        eye.setObjectName("SetupEyeButton")
        eye.setText("\U0001F441")  # 👁
        eye.setToolTip("Show / hide the value")
        eye.setFixedSize(30, 28)
        eye.setCursor(self.QtCore.Qt.PointingHandCursor)

        def _toggle() -> None:
            is_password = field.echoMode() == self.QtWidgets.QLineEdit.Password
            field.setEchoMode(
                self.QtWidgets.QLineEdit.Normal if is_password else self.QtWidgets.QLineEdit.Password
            )
            eye.setText("\U0001F648" if is_password else "\U0001F441")  # 🙈 / 👁
            eye.setToolTip("Hide the value" if is_password else "Show the value")

        eye.clicked.connect(_toggle)
        layout.addWidget(eye)
        return container

    def _sync_current_page_geometry(self) -> None:
        """Let the outer setup scroll area own overflow instead of clipping the active page."""
        current_page = self.tabs.currentWidget()
        if current_page is None:
            return
        try:
            page_layout = current_page.layout()
            if page_layout is not None:
                page_layout.activate()
            current_page.adjustSize()
            hint = current_page.sizeHint()
            if hint.isValid():
                self.tabs.setMinimumHeight(max(0, hint.height() + 6))
            current_page.updateGeometry()
            self.tabs.updateGeometry()
            body = self.scroll_area.widget() if hasattr(self, "scroll_area") and hasattr(self.scroll_area, "widget") else None
            if body is not None:
                body.adjustSize()
                body.updateGeometry()
        except Exception:
            pass

    def _set_step(self, index: int) -> None:
        index = max(0, min(index, self.tabs.count() - 1))
        self.tabs.setCurrentIndex(index)
        # Drive the animated stepper if available.
        if hasattr(self, "stepper") and hasattr(self.stepper, "set_active"):
            try:
                self.stepper.set_active(index)
            except Exception:
                pass
        if hasattr(self, "step_caption"):
            name = self.step_names[index] if index < len(self.step_names) else ""
            self.step_caption.setText(
                f"Step {index + 1} of {len(self.step_names)} · {name}"
            )
        # Brief fade-in of the new page for a softer transition.
        # Avoid QGraphicsOpacityEffect on setup pages: they contain animated
        # custom-painted widgets, and Qt can otherwise try to snapshot a page
        # while it is already painting.
        current_page = self.tabs.currentWidget()
        if current_page is not None:
            current_page.update()
        self._sync_current_page_geometry()
        try:
            def _reset_scroll_position() -> None:
                try:
                    self.scroll_area.verticalScrollBar().setValue(0)
                except RuntimeError:
                    # The setup window may have closed before this deferred UI
                    # update runs.
                    pass

            self.QtCore.QTimer.singleShot(0, _reset_scroll_position)
        except Exception:
            pass
        is_first = index == 0
        is_last = index == self.tabs.count() - 1
        self.back_btn.setVisible(not is_first)
        self.back_btn.setEnabled(not is_first)
        self.next_btn.setVisible(not is_first and not is_last)
        self.finish_btn.setVisible(is_last)
        self._update_finish_summary()

    def _next_step(self) -> None:
        index = self.tabs.currentIndex()
        if index == 2 and self._current_mode() in {"relay", "vatsim"}:
            self._set_step(4)
            return
        self._set_step(index + 1)

    def _previous_step(self) -> None:
        index = self.tabs.currentIndex()
        if index == 4 and self._current_mode() in {"relay", "vatsim"}:
            self._set_step(2)
            return
        self._set_step(index - 1)

    def _current_mode(self) -> str:
        return str(self.setup_mode.currentData() or "relay")

    def _current_diagnostics_mode(self) -> str:
        return str(self.diagnostics_mode.currentData() or "manual")

    def _set_mode(self, mode: str) -> None:
        previous_mode = self._current_mode() if hasattr(self, "setup_mode") else ""
        idx = self.setup_mode.findData(mode)
        self.setup_mode.setCurrentIndex(idx if idx >= 0 else self.setup_mode.findData("relay"))
        active_mode = self._current_mode()
        if previous_mode and active_mode != previous_mode:
            self._invalidate_pending_move()
        for key, card in self.source_buttons.items():
            self._set_card_selected(card, key == active_mode)
        self._mode_initialized = True
        self._sync_mode_ui()
        self._update_finish_summary()

    def _set_diagnostics_mode(self, mode: str) -> None:
        idx = self.diagnostics_mode.findData(mode)
        self.diagnostics_mode.setCurrentIndex(idx if idx >= 0 else 0)
        active_mode = self._current_diagnostics_mode()
        for key, card in self.diagnostics_buttons.items():
            self._set_card_selected(card, key == active_mode)
        self._diagnostics_initialized = True
        self._set_chip(self.diagnostics_help, diagnostics_option(active_mode)["note"], "good" if active_mode == "manual" else "warn")
        self._update_finish_summary()

    def _sync_mode_ui(self) -> None:
        mode = self._current_mode()
        self.relay_box.setVisible(mode == "relay")
        self.mode_help.setText(source_option(mode)["note"])
        if mode == "relay":
            self._set_chip(self.keys_hint, "Beacon Relay skips provider keys. Relay Access is activated on the previous page.", "good")
        elif mode == "byok":
            self._set_chip(self.keys_hint, "Paste an AeroDataBox or AviationStack schedule key. ADS-B Exchange on RapidAPI lives on this same page as the optional radar key.", "warn")
        else:
            self._set_chip(self.keys_hint, "VATSIM needs no provider keys. Virtual traffic will be used for this route.", "good")

    def _invalidate_pending_move(self) -> None:
        self._pending_move_token = ""
        if hasattr(self, "move_warning"):
            self.move_warning.hide()

    def _activation_details_changed(self) -> None:
        if self._pending_move_token:
            self._invalidate_pending_move()
            if hasattr(self, "relay_action_status"):
                self._set_relay_action_status(
                    "Activation details changed. Check the current main device again before moving access.",
                    "StatusWarn",
                )

    def keep_relay_there(self) -> None:
        self._invalidate_pending_move()
        self._set_relay_action_status(
            "Relay Access remains on its current main device. Choose BYOK or VATSIM to finish without moving it.",
            "StatusWarn",
        )

    def move_relay_here(self) -> None:
        if not self._pending_move_token:
            self._set_relay_action_status(
                "The move confirmation expired. Activate again to check the current main device.",
                "StatusWarn",
            )
            return
        self.request_activation(confirm_move=True)

    def _mode_label(self, mode: str) -> str:
        return source_option(mode)["title"]

    def _diagnostics_label(self, mode: str) -> str:
        if mode == "unset":
            return "Not chosen"
        return diagnostics_option(mode)["title"]

    def _update_finish_summary(self) -> None:
        if not hasattr(self, "finish_summary"):
            return
        mode = self._current_mode() if hasattr(self, "setup_mode") else "relay"
        source = "virtual" if mode == "vatsim" else "real"
        relay_state = "active on this desktop" if self._stored_activation else "license activation required"
        if mode != "relay":
            relay_state = "not used"
        has_adb = mode == "byok" and bool(
            self.aerodatabox_key.text().strip() or self._saved_provider_state.get("aerodatabox_configured")
        )
        has_as = mode == "byok" and bool(
            self.aviationstack_key.text().strip() or self._saved_provider_state.get("aviationstack_configured")
        )
        has_adsb = mode == "byok" and bool(
            self.rapidapi_key.text().strip() or self._saved_provider_state.get("adsbexchange_configured")
        )
        radar_note = " + ADS-B Exchange radar" if has_adsb else ""
        if has_adb and has_as:
            key_state = f"AeroDataBox primary + AviationStack fill{radar_note}"
        elif has_adb:
            key_state = f"AeroDataBox schedules{radar_note}"
        elif has_as:
            key_state = f"AviationStack schedules{radar_note}"
        else:
            key_state = "no provider keys saved"
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
            self.finish_cards["source"].setProperty("tone", "good" if mode in {"relay", "vatsim"} else "warn")
            self.finish_cards["relay"].setProperty("tone", "good" if relay_state == "active on this desktop" else "muted")
            self.finish_cards["keys"].setProperty("tone", "warn" if mode == "byok" and key_state != "no provider keys saved" else "muted")
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
        self._set_status("Checking setup...", busy=True)
        self._run_async(
            lambda: {
                "info": self.service.setup_client_info(),
                "catalog": self.service.setup_access_catalog(relay_url=self._clean_relay_display(self.relay_url.text())),
            },
            self._apply_refresh,
            self._refresh_failed,
            label="Setup refresh",
            debounce_ms=0,
        )

    def _refresh_failed(self, _exc: Exception) -> None:
        self._set_status("Setup information is temporarily unavailable.", "StatusBad")
        if not self._mode_initialized:
            self._set_mode("relay")

    def _apply_refresh(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        info = result.get("info") if isinstance(result.get("info"), dict) else {}
        catalog = result.get("catalog") if isinstance(result.get("catalog"), dict) else {}
        provider_state = info.get("provider_keys") if isinstance(info.get("provider_keys"), dict) else {}
        self._saved_provider_state = {str(key): bool(value) for key, value in provider_state.items()}
        if self._saved_provider_state.get("aerodatabox_configured"):
            self.aerodatabox_key.setPlaceholderText("Saved key available; paste to replace")
        if self._saved_provider_state.get("aviationstack_configured"):
            self.aviationstack_key.setPlaceholderText("Saved key available; paste to replace")
        if self._saved_provider_state.get("adsbexchange_configured"):
            self.rapidapi_key.setPlaceholderText("Saved key available; paste to replace")
        if info.get("relay_url"):
            self.relay_url.setText(self._clean_relay_display(str(info.get("relay_url"))))
        cfg = info.get("config") if isinstance(info.get("config"), dict) else {}
        self.display_name.setText(str(cfg.get("display_name") or self.display_name.text() or "Local Flight"))
        self.airport_iata.setText(str(cfg.get("airport_iata") or self.airport_iata.text() or "ZRH"))
        self.airport_icao.setText(str(cfg.get("airport_icao") or self.airport_icao.text() or "LSZH"))
        self.timezone.setText(str(cfg.get("timezone") or self.timezone.text() or "Europe/Zurich"))
        if not self._diagnostics_initialized:
            self._set_diagnostics_mode(str(cfg.get("diagnostics_mode") or "manual"))
        prefix = str(info.get("activation_token_prefix") or "")
        relay_state = str(info.get("relay_state") or "none")
        access_state = str(info.get("access_state") or "")
        cached_active = prefix.startswith("lfr_") and relay_state == "active" and access_state == "active"
        self._stored_activation = False
        if cached_active:
            self.activation_token.clear()
            self.activation_token.setPlaceholderText(f"Device credential stored ({prefix or 'hidden'}...)")
            self._set_chip(self.relay_status, "Checking that Relay Access is still active on this desktop...", "warn")
            self.token_box.hide()
        elif relay_state == "release_pending":
            self.activation_token.clear()
            self.activation_token.setPlaceholderText(f"Device credential retained ({prefix or 'hidden'}...)")
            self._set_chip(
                self.relay_status,
                "Relay Access release is pending. This desktop will not use Relay until release or an explicit status check succeeds.",
                "warn",
            )
            self.token_box.hide()
        elif prefix.startswith("lfr_"):
            self.activation_token.clear()
            self.activation_token.setPlaceholderText("LFRA key or one-time activation code")
            self._set_chip(self.relay_status, "The saved credential is not active. Check access or enter a replacement key or activation code.", "warn")
            self.token_box.show()
        else:
            self.activation_token.setPlaceholderText("LFRA key or one-time activation code")
            self._set_chip(self.relay_status, "Get Relay Access or enter an existing key or one-time activation code.", "warn")
            self.token_box.show()
        self._catalog_available = bool(catalog.get("ok") and catalog.get("sales_available"))
        self.buy_relay_access_btn.setVisible(self._catalog_available)
        if not self._catalog_available:
            self._set_relay_action_status(
                str(catalog.get("error") or "New purchases are temporarily unavailable. Existing keys and activation codes can still be used."),
                "StatusWarn",
                footer_text="",
            )
        route = str(cfg.get("data_route") or ("vatsim" if cfg.get("source") == "virtual" else "relay"))
        if not self._mode_initialized:
            self._set_mode(route)
        self._set_status("Setup ready.", "StatusGood")
        self._update_finish_summary()
        if cached_active and route == "relay":
            self.check_activation_status()

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

    def _clear_status(self) -> None:
        if self.loading_indicator.isVisible():
            return
        self.status.hide()

    def _set_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        full_text = str(text or "").strip()
        display_text = " ".join(full_text.split())
        if len(display_text) > 92:
            display_text = display_text[:89].rstrip() + "..."
        self._status_hide_timer.stop()
        self.status.setText(display_text)
        self.status.setToolTip(full_text)
        self.status.setProperty("tone", self._tone_for_role(role))
        self.status.setVisible(bool(display_text))
        # Keep the spinner caption in sync with the live status when busy.
        if busy and hasattr(self.loading_indicator, "set_text"):
            try:
                self.loading_indicator.set_text(display_text or "Working...")
            except Exception:
                pass
        self.loading_indicator.setVisible(bool(busy))
        self._repolish(self.status)
        self.status.adjustSize()
        self.status.updateGeometry()
        if busy:
            self.QtWidgets.QApplication.processEvents()
            return
        timeout = 6000 if role == "StatusBad" else 3600
        if display_text:
            self._status_hide_timer.start(timeout)

    def _tone_for_role(self, role: str = "Muted") -> str:
        return {
            "StatusGood": "good",
            "StatusWarn": "warn",
            "StatusBad": "bad",
            "Muted": "muted",
        }.get(role, "muted")

    def _friendly_relay_text(self, result: Any, *, default: str = "Relay response received.") -> str:
        code = str(result.get("status") or "") if isinstance(result, dict) else ""
        messages = {
            "invalid_license_key": "That Relay Access key or activation code was not accepted. Check it and try again.",
            "credential_not_found": "This desktop's saved Relay Access credential is no longer recognized. Activate access again.",
            "license_inactive": "Relay Access is not active. Open Relay Access details for the current status.",
            "suspended": "Relay Access is suspended. Open Relay Access details for the current status.",
            "refunded": "Relay Access was refunded and cannot be used on this desktop.",
            "revoked": "Relay Access was revoked and cannot be used on this desktop.",
            "stale_move_token": "That move confirmation expired because the activation details changed. Start the move again.",
            "rate_limited": "The relay is cooling down checks. Try again shortly.",
            "relay_unavailable": "The relay could not be reached right now. Your local setup is unchanged.",
            "relay_unreachable": "The relay could not be reached right now. Your local setup is unchanged.",
            "license_key_local_only": "For safety, open native setup on this desktop or use a one-time activation code.",
        }
        if code in messages:
            return messages[code]
        if isinstance(result, dict):
            return str(result.get("error") or result.get("message") or code or default)
        return format_value(result).strip() if result is not None else default

    def _relay_role_for_result(self, result: Any, status_text: str = "") -> str:
        if isinstance(result, dict):
            if result.get("ok") is False or result.get("error"):
                return "StatusBad"
            if result.get("ok") is True:
                return "StatusGood"
            status_key = str(result.get("status") or "").casefold()
            if status_key in {"active", "approved", "connected", "ok"}:
                return "StatusGood"
            if status_key in {"pending", "requested", "queued"}:
                return "StatusWarn"
        status_key = status_text.casefold()
        if status_key in {"active", "approved", "connected", "ok"}:
            return "StatusGood"
        return "StatusWarn"

    def _relay_footer_text(self, role: str, *, busy: bool = False) -> str:
        if busy:
            return "Working with the relay..."
        if role == "StatusGood":
            return "Relay panel updated."
        if role == "StatusBad":
            return "Relay needs attention. See the Relay Access panel."
        if role == "StatusWarn":
            return "Relay status needs attention. See the Relay Access panel."
        return ""

    def _set_relay_action_status(
        self,
        text: str,
        role: str = "Muted",
        *,
        busy: bool = False,
        footer_text: str | None = None,
    ) -> None:
        self.relay_action_status.setText(text)
        self.relay_action_status.setProperty("tone", self._tone_for_role(role))
        self.relay_action_status.setVisible(bool(text))
        self._repolish(self.relay_action_status)
        footer = self._relay_footer_text(role, busy=busy) if footer_text is None else footer_text
        if footer:
            self._set_status(footer, role, busy=busy)
        else:
            self.loading_indicator.setVisible(bool(busy))

    def _set_relay_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self.buy_relay_access_btn,
            self.request_activation_btn,
            self.check_relay_status_btn,
            self.test_token_btn,
            self.keep_relay_there_btn,
            self.move_relay_here_btn,
        ):
            button.setEnabled(enabled)

    def _set_provider_action_status(self, text: str, role: str = "Muted", *, busy: bool = False) -> None:
        self.provider_action_status.setText(text)
        self.provider_action_status.setProperty("tone", self._tone_for_role(role))
        self._repolish(self.provider_action_status)
        self._set_status(text, role, busy=busy)

    def _set_provider_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.test_adb_btn, self.test_as_btn, self.test_rapidapi_btn):
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
        except Exception:
            self.airport_results.clear()
            self.airport_results.addItem("Airport search could not be completed.")
            self._set_airport_status("Airport search could not be completed. Check the connection and try again.", "StatusBad")
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
            "activation_token": "",
            "license_key": self.activation_token.text().strip(),
            "confirm_move_token": self._pending_move_token,
            "airport_iata": self.airport_iata.text().strip().upper(),
            "airport_icao": self.airport_icao.text().strip().upper(),
            "display_name": self.display_name.text().strip(),
            "requested_mode": self._current_mode(),
        }

    def request_activation(self, *, confirm_move: bool = False) -> None:
        if not self.activation_token.text().strip():
            self._set_relay_action_status("Enter a Relay Access key or one-time activation code first.", "StatusWarn")
            return
        if self._pending_move_token and not confirm_move:
            self.move_warning.show()
            self._set_relay_action_status("Confirm the named move or keep Relay Access on its current main device.", "StatusWarn")
            return
        self._set_relay_action_status(
            "Moving Relay Access to this desktop..." if confirm_move else "Activating Relay Access...",
            "Muted",
            busy=True,
        )
        self._set_relay_buttons_enabled(False)
        payload = self._activation_payload()
        if not confirm_move:
            payload["confirm_move_token"] = ""
        self._run_async(
            lambda: self.service.setup_activate(payload),
            self._apply_activation_result,
            self._relay_action_failed,
            label="Relay activation",
            debounce_ms=0,
        )

    def _relay_action_failed(self, _exc: Exception) -> None:
        self._stored_activation = False
        self._pending_move_token = ""
        self.move_warning.hide()
        self.activation_token.clear()
        self.activation_token.setPlaceholderText("LFRA key or one-time activation code")
        self.token_box.show()
        self._set_relay_buttons_enabled(True)
        self._set_setup_buttons_enabled(True)
        self._set_relay_action_status("The relay could not be reached right now. Your local setup is unchanged.", "StatusBad")
        self._update_finish_summary()

    def _apply_activation_result(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        self._set_relay_buttons_enabled(True)
        if result.get("activation_token_prefix"):
            self._stored_activation = True
            self._pending_move_token = ""
            self.move_warning.hide()
            self.activation_token.clear()
            self.activation_token.setPlaceholderText(f"Device credential stored ({result.get('activation_token_prefix')}...)")
            self._set_chip(self.relay_status, "Relay Access is active. The license key was discarded after activation.", "good")
            self.token_box.hide()
            self._set_relay_action_status("Relay Access is active on this desktop.", "StatusGood")
            # A fresh status check makes the hosted service, not a local flag,
            # authoritative before Finish becomes useful.
            self.test_activation()
        elif result.get("status") == "seat_in_use" and result.get("move_token"):
            self._pending_move_token = str(result.get("move_token"))
            receiver = result.get("current_receiver") if isinstance(result.get("current_receiver"), dict) else {}
            receiver_name = str(result.get("current_main_device_description") or receiver.get("device_name") or receiver.get("device_kind") or "another main device")
            self.move_warning_text.setText(
                f"Relay Access is currently used by {receiver_name}. Moving it here will stop direct Relay use there."
            )
            self.move_warning.show()
            self._set_relay_action_status(
                "Choose whether to keep Relay Access there or move it to this desktop.",
                "StatusWarn",
            )
        elif result.get("ok") is False:
            if result.get("status") == "stale_move_token":
                self._pending_move_token = ""
                self.move_warning.hide()
            self._set_relay_action_status(self._friendly_relay_text(result), "StatusBad")
        else:
            self._set_relay_action_status(self._friendly_relay_text(result), self._relay_role_for_result(result))
        self._update_finish_summary()

    def check_activation_status(self) -> None:
        self._set_relay_action_status("Checking relay status...", "Muted", busy=True)
        self._set_relay_buttons_enabled(False)
        payload = self._activation_payload()
        self._run_async(
            lambda: self.service.setup_client_status(payload),
            self._apply_status_result,
            self._relay_action_failed,
            label="Relay status",
            debounce_ms=0,
        )

    def _apply_status_result(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        self._set_relay_buttons_enabled(True)
        status_text = self._friendly_relay_text(result, default="Relay status received.")
        role = self._relay_role_for_result(result, status_text)
        self._stored_activation = bool(result.get("ok") and str(result.get("status") or "") == "active")
        if self._stored_activation:
            self.token_box.hide()
        else:
            self._pending_move_token = ""
            self.move_warning.hide()
            self.activation_token.clear()
            self.activation_token.setPlaceholderText("LFRA key or one-time activation code")
            self.token_box.show()
        self._set_relay_action_status(status_text, role)
        self._update_finish_summary()

    def test_activation(self) -> None:
        self._set_relay_action_status("Testing Relay Access...", "Muted", busy=True)
        self._set_relay_buttons_enabled(False)
        payload = self._activation_payload()
        self._run_async(
            lambda: self.service.setup_test_activation(payload),
            self._apply_test_result,
            self._relay_action_failed,
            label="Relay verification",
            debounce_ms=0,
        )

    def _apply_test_result(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        self._set_relay_buttons_enabled(True)
        if result.get("ok"):
            self._stored_activation = True
            self.token_box.hide()
            self._set_relay_action_status("Relay Access works. You can finish setup.", "StatusGood")
            self._update_finish_summary()
            return
        self._stored_activation = False
        self._pending_move_token = ""
        self.move_warning.hide()
        self.activation_token.clear()
        self.activation_token.setPlaceholderText("LFRA key or one-time activation code")
        self.token_box.show()
        self._set_relay_action_status(self._friendly_relay_text(result), "StatusBad")
        self._update_finish_summary()

    def test_aviationstack(self) -> None:
        key = self.aviationstack_key.text().strip()
        if not key:
            self._set_provider_action_status("Paste an AviationStack key first.", "StatusWarn")
            return
        self._test_key("/api/setup/test-aviationstack", key, "AviationStack")

    def test_aerodatabox(self) -> None:
        key = self.aerodatabox_key.text().strip()
        if not key:
            self._set_provider_action_status("Paste an AeroDataBox key first.", "StatusWarn")
            return
        self._set_provider_action_status("Checking AeroDataBox key. This may consume a small provider request...", busy=True)
        self._set_provider_buttons_enabled(False)
        try:
            result = self.service.setup_test_provider_key(
                "/api/setup/test-aerodatabox",
                key,
                extra={
                    "marketplace": self.aerodatabox_marketplace.currentData() or "apimarket",
                    "airport_iata": self.airport_iata.text().strip().upper() or "ZRH",
                    "monthly_units_limit": int(self.aerodatabox_monthly_limit.value()),
                },
            )
        except Exception:
            self._set_provider_action_status("That AeroDataBox key could not be checked. Try again shortly.", "StatusBad")
            self._set_provider_buttons_enabled(True)
            return
        self._set_provider_buttons_enabled(True)
        if result.get("ok"):
            self._set_provider_action_status("AeroDataBox key works.", "StatusGood")
        else:
            self._set_provider_action_status(str(result.get("error") or "Could not check that AeroDataBox key."), "StatusBad")

    def test_rapidapi(self) -> None:
        key = self.rapidapi_key.text().strip()
        if not key:
            self._set_provider_action_status("Paste an ADS-B Exchange RapidAPI key first.", "StatusWarn")
            return
        self._test_key("/api/setup/test-rapidapi", key, "ADS-B Exchange")

    def _test_key(self, path: str, key: str, label_text: str) -> None:
        self._set_provider_action_status(f"Checking {label_text} key...", busy=True)
        self._set_provider_buttons_enabled(False)
        try:
            result = self.service.setup_test_provider_key(path, key)
        except Exception:
            self._set_provider_action_status(f"That {label_text} key could not be checked. Try again shortly.", "StatusBad")
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
            "source": "virtual" if mode == "vatsim" else "real",
            "data_route": mode,
            "setup_mode": mode,
            "display_name": self.display_name.text().strip() or "Local Flight",
            "diagnostics_mode": self._current_diagnostics_mode(),
            "relay_url": self._clean_relay_display(self.relay_url.text()) if mode == "relay" else "",
            "activation_token": "",
            "aerodatabox_key": self.aerodatabox_key.text().strip() if mode == "byok" else "",
            "aerodatabox_marketplace": self.aerodatabox_marketplace.currentData() if mode == "byok" else "apimarket",
            "aerodatabox_monthly_units_limit": int(self.aerodatabox_monthly_limit.value()) if mode == "byok" else 24000,
            "aviationstack_key": self.aviationstack_key.text().strip() if mode == "byok" else "",
            "rapidapi_key": self.rapidapi_key.text().strip() if mode == "byok" else "",
            "opensky_id": self.opensky_id.text().strip() if mode == "byok" else "",
            "opensky_secret": self.opensky_secret.text().strip() if mode == "byok" else "",
        }
        self._set_setup_buttons_enabled(False)
        self._set_status("Saving setup...", busy=True)
        self._run_async(
            lambda: self.service.setup_complete(payload),
            self._apply_finish_result,
            self._finish_failed,
            label="Setup completion",
            debounce_ms=0,
        )

    def _finish_failed(self, _exc: Exception) -> None:
        self._set_status("Setup could not be completed. Review the selected route and try again.", "StatusBad")
        self._set_setup_buttons_enabled(True)

    def _apply_finish_result(self, result: Any) -> None:
        result = result if isinstance(result, dict) else {}
        setup_ok = bool(result.get("ok"))
        if setup_ok:
            self._set_status(str(result.get("message") or "Setup saved. Preparing your first board..."), "StatusGood")
        else:
            self._set_status(
                self._friendly_relay_text(result, default="Setup could not finish. Retry the relay connection, choose VATSIM, or use your own provider keys."),
                "StatusWarn" if result.get("status") in {"rate_limited", "manual_review"} else "StatusBad",
            )
        if setup_ok:
            try:
                self.service.clear_cache()
            except Exception:
                pass
            # Play the celebration overlay before handing off to the main app.
            if self.QtGui is not None:
                try:
                    colors = colors_for(self.theme, self.skin)
                    fire = build_celebration(
                        self.QtCore,
                        self.QtGui,
                        self.QtWidgets,
                        self.widget,
                        accent_hex=colors.get("blue", "#4a9eda"),
                        text_hex=colors.get("text", "#e8f0fe"),
                        bg_hex=colors.get("bg", "#0b0f15"),
                    )
                    fire()
                except Exception:
                    pass
            if self.on_setup_complete:
                # Give the celebration a moment to be seen before launching.
                if self.QtGui is not None and hasattr(self.QtCore, "QTimer"):
                    self.QtCore.QTimer.singleShot(650, self.on_setup_complete)
                else:
                    self.on_setup_complete()
        else:
            self._set_setup_buttons_enabled(True)

    def _set_setup_buttons_enabled(self, enabled: bool) -> None:
        for button in (self.web_fallback_btn, self.back_btn, self.next_btn, self.finish_btn):
            button.setEnabled(enabled)


__all__ = ["NativeSetupWindow", "SetupScreen", "PROVIDER_LINKS"]
