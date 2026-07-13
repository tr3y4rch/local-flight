"""Native radar page.

This page is the standalone PySide6 boundary for the browser ``radar.html``
experience: range controls, METAR strip, live refresh, surface overlay, and
safe user-facing loading/error states.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from localflight.native.api_client import LocalApiClient
from localflight.native.async_tools import AsyncFetchMixin
from localflight.native.canvas.radar import RadarCanvas
from localflight.native.design import WEATHER_EMOJI, install_combo_popup_sizing, label
from localflight.native.service import NativeApiService
from localflight.native.widgets import NoticeBanner, WeatherStrip


class RadarScreen(AsyncFetchMixin):  # pragma: no cover - optional Qt runtime
    def __init__(self, QtCore: Any, QtGui: Any, QtWidgets: Any, client: LocalApiClient, *, embedded: bool = False) -> None:
        self.QtCore = QtCore
        self.QtWidgets = QtWidgets
        self.embedded = embedded
        self.client = client
        self.service = NativeApiService(client)
        self.widget = QtWidgets.QFrame()
        self._init_async(QtCore, self.widget)
        self.widget.setObjectName("Page")
        self.widget.setMinimumWidth(0)
        self.widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        layout = QtWidgets.QVBoxLayout(self.widget)
        layout.setContentsMargins(8 if embedded else 18, 8 if embedded else 18, 8 if embedded else 18, 8 if embedded else 18)
        layout.setSpacing(6 if embedded else 10)
        top_widget = QtWidgets.QWidget()
        top_widget.setMinimumWidth(0)
        top = QtWidgets.QHBoxLayout(top_widget)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        self.title = label(QtWidgets, "Radar range" if embedded else "Radar", "Kicker" if embedded else "Title")
        top.addWidget(self.title)
        top.addStretch(1)
        self._syncing_range = False
        self.range_buttons: dict[int, Any] = {}
        self.range_combo = None
        if embedded:
            self.range_combo = QtWidgets.QComboBox()
            self.range_combo.setObjectName("Input")
            self.range_combo.setToolTip("Radar range")
            for radius in (1, 2, 3, 5, 10, 20, 40):
                self.range_combo.addItem(f"{radius}nm", radius)
            install_combo_popup_sizing(self.range_combo, minimum_width=118)
            self.range_combo.currentIndexChanged.connect(self._range_combo_changed)
            top.addWidget(self.range_combo)
        else:
            for radius in (1, 2, 3, 5, 10, 20, 40):
                button = QtWidgets.QPushButton(f"{radius}nm")
                button.setObjectName("SegmentButton")
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, r=radius: self.set_radius(r))
                self.range_buttons[radius] = button
                top.addWidget(button)
        refresh = QtWidgets.QPushButton("Refresh" if embedded else "Refresh radar")
        refresh.setObjectName("Quiet" if embedded else "")
        refresh.clicked.connect(self.refresh)
        top.addWidget(refresh)
        self.view_options_button = QtWidgets.QToolButton()
        self.view_options_button.setObjectName("Quiet")
        self.view_options_button.setText("View")
        self.view_options_button.setToolTip("Radar view options")
        self.view_options_button.setCheckable(True)
        self.view_options_button.clicked.connect(self._toggle_options_panel)
        top.addWidget(self.view_options_button)
        self.advanced_panel = QtWidgets.QFrame()
        self.advanced_panel.setObjectName("PreviewCard")
        self.advanced_panel.setMinimumWidth(0)
        advanced_layout = QtWidgets.QHBoxLayout(self.advanced_panel)
        advanced_layout.setContentsMargins(10, 7, 10, 7)
        advanced_layout.setSpacing(8)
        self.layer_toggles: dict[str, Any] = {}
        for layer, text, checked in (
            ("map", "Map", True),
            ("runways", "Runways", True),
            ("surface", "Surface", True),
            ("terrain", "Terrain", False),
            ("traffic_status", "Status", False),
            ("procedures", "Routes", False),
        ):
            toggle = QtWidgets.QCheckBox(text)
            toggle.setChecked(checked)
            toggle.stateChanged.connect(lambda _state=0, key=layer: self._toggle_layer(key))
            self.layer_toggles[layer] = toggle
            advanced_layout.addWidget(toggle)
        self.traffic_filter = QtWidgets.QComboBox()
        self.traffic_filter.setObjectName("Input")
        for key, text in (
            ("all", "All"),
            ("arrivals", "Arr"),
            ("departures", "Dep"),
            ("final", "Final"),
            ("ground", "Ground"),
            ("airborne", "Air"),
        ):
            self.traffic_filter.addItem(text, key)
        install_combo_popup_sizing(self.traffic_filter, minimum_width=104)
        self.traffic_filter.currentIndexChanged.connect(lambda _idx=0: self.refresh())
        advanced_layout.addWidget(self.traffic_filter)
        self.altitude_filter = QtWidgets.QComboBox()
        self.altitude_filter.setObjectName("Input")
        for key, text in (
            ("all", "All alt"),
            ("surface", "0-3k"),
            ("terminal", "0-10k"),
            ("enroute", "10k+"),
        ):
            self.altitude_filter.addItem(text, key)
        install_combo_popup_sizing(self.altitude_filter, minimum_width=104)
        self.altitude_filter.currentIndexChanged.connect(lambda _idx=0: self.refresh())
        advanced_layout.addWidget(self.altitude_filter)
        advanced_layout.addStretch(1)
        self.advanced_scroll = QtWidgets.QScrollArea()
        self.advanced_scroll.setObjectName("NavScroll")
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.advanced_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.advanced_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.advanced_scroll.setMaximumHeight(54)
        self.advanced_scroll.setMinimumWidth(0)
        self.advanced_scroll.setWidget(self.advanced_panel)
        self.advanced_panel.hide()
        self.advanced_scroll.hide()
        self.weather = WeatherStrip(QtWidgets, "Weather loading...")
        self.notice_banner = NoticeBanner(QtWidgets)
        self.canvas = RadarCanvas(QtCore, QtGui, QtWidgets)
        if embedded:
            self.canvas.setMinimumSize(240, 240)
            self.canvas.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.canvas.hoverChanged.connect(self._show_blip_info)
        if hasattr(self.canvas, "blipClicked"):
            self.canvas.blipClicked.connect(self._show_selected_blip_info)
        source_row = QtWidgets.QHBoxLayout()
        source_row.setSpacing(8)
        self.source_info = label(QtWidgets, "Radar source preparing...", "Muted", wrap=True)
        source_row.addWidget(self.source_info, 1)
        self.filter_summary = label(QtWidgets, "", "Dim")
        source_row.addWidget(self.filter_summary)
        self.blip_info = QtWidgets.QFrame()
        self.blip_info.setObjectName("PreviewCard")
        info_layout = QtWidgets.QVBoxLayout(self.blip_info)
        info_layout.setContentsMargins(12, 9, 12, 9)
        info_layout.setSpacing(3)
        self.blip_title = label(QtWidgets, "Hover an aircraft", "Metric")
        self.blip_route = label(QtWidgets, "Move the mouse over a radar target to see basic flight information.", "Muted", wrap=True)
        self.blip_detail = label(QtWidgets, "", "Muted", wrap=True)
        info_layout.addWidget(self.blip_title)
        info_layout.addWidget(self.blip_route)
        info_layout.addWidget(self.blip_detail)
        self.blip_info.hide()
        self.status = label(QtWidgets, "Preparing radar...", "Muted")
        self._last_status_text = "Preparing radar..."
        self.loading_indicator = QtWidgets.QProgressBar()
        self.loading_indicator.setObjectName("LoadingProgress")
        self.loading_indicator.setRange(0, 0)
        self.loading_indicator.setTextVisible(False)
        self.loading_indicator.setFixedHeight(7)
        self.loading_indicator.hide()
        top_scroll = QtWidgets.QScrollArea()
        top_scroll.setObjectName("NavScroll")
        top_scroll.setWidgetResizable(True)
        top_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        top_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        top_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        top_scroll.setMaximumHeight(52)
        top_scroll.setMinimumWidth(0)
        top_scroll.setWidget(top_widget)
        layout.addWidget(top_scroll)
        layout.addWidget(self.weather)
        layout.addWidget(self.notice_banner)
        layout.addLayout(source_row)
        layout.addWidget(self.advanced_scroll)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.blip_info)
        layout.addWidget(self.loading_indicator)
        layout.addWidget(self.status)
        self.radius_nm = 20
        self.config: dict[str, Any] = {}
        self._last_payload: dict[str, Any] = {}
        self._last_surface: dict[str, Any] = {}
        if hasattr(self.canvas, "set_radius_nm"):
            self.canvas.set_radius_nm(self.radius_nm)
        self._sync_range_buttons()
        self._sync_ground_filter_for_radius()
        self._apply_layer_toggles()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.widget, name)

    def apply_theme(self, theme: str, skin: str) -> None:
        if hasattr(self.canvas, "apply_theme"):
            self.canvas.apply_theme(theme, skin)

    def set_radius(self, radius: int) -> None:
        self.radius_nm = radius
        if hasattr(self.canvas, "set_radius_nm"):
            self.canvas.set_radius_nm(radius)
        self._sync_range_buttons()
        self._sync_ground_filter_for_radius()
        self.refresh()

    def _sync_range_buttons(self) -> None:
        self._syncing_range = True
        for radius, button in self.range_buttons.items():
            button.setChecked(radius == self.radius_nm)
        if self.range_combo is not None:
            idx = self.range_combo.findData(self.radius_nm)
            if idx >= 0:
                self.range_combo.setCurrentIndex(idx)
        self._syncing_range = False

    def _sync_ground_filter_for_radius(self) -> None:
        ground_idx = self.traffic_filter.findData("ground")
        if ground_idx < 0:
            return
        enabled = self.radius_nm <= 5
        item = self.traffic_filter.model().item(ground_idx)
        if item is not None:
            item.setEnabled(enabled)
        if not enabled and str(self.traffic_filter.currentData() or "") == "ground":
            all_idx = self.traffic_filter.findData("all")
            if all_idx >= 0:
                self.traffic_filter.setCurrentIndex(all_idx)

    def _range_combo_changed(self, _idx: int = 0) -> None:
        if self._syncing_range or self.range_combo is None:
            return
        try:
            radius = int(self.range_combo.currentData())
        except (TypeError, ValueError):
            radius = self.radius_nm
        self.set_radius(radius)

    def _toggle_layer(self, _layer: str) -> None:
        self._apply_layer_toggles()
        if _layer == "terrain":
            self.refresh()

    def _toggle_options_panel(self, checked: bool = False) -> None:
        self.advanced_panel.setVisible(bool(checked))
        self.advanced_scroll.setVisible(bool(checked))
        self.view_options_button.setChecked(bool(checked))

    def _apply_layer_toggles(self) -> None:
        for layer, toggle in self.layer_toggles.items():
            if hasattr(self.canvas, "set_layer_enabled"):
                self.canvas.set_layer_enabled(layer, toggle.isChecked())
        self._update_filter_summary()
        self._refresh_optional_layers()

    def refresh(self) -> None:
        radius = self.radius_nm
        started = self._run_async(
            lambda: self._fetch_radar(radius),
            self._apply_radar,
            lambda exc: self._radar_error(exc),
            label=f"radar.{radius}nm",
        )
        if started:
            mode = "surface view" if radius <= 5 else "aircraft view"
            self._set_status(f"Updating {radius}nm radar {mode}...", busy=True)

    def handle_live_event(self, payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "")
        if event_type == "config_updated":
            self._set_status("Settings changed. Refreshing radar...")
            self.refresh()
        elif event_type in {"snapshot_updated", "scheduler_restarted"}:
            self.refresh()

    def set_active(self, active: bool) -> None:
        timer = getattr(self.canvas, "_sweep_timer", None)
        if timer is None:
            return
        if active:
            if not timer.isActive():
                timer.start(getattr(self.canvas, "_sweep_interval_ms", 100))
        else:
            timer.stop()

    def _fetch_radar(self, radius: int) -> dict[str, Any]:
        min_alt, max_alt = self._altitude_bounds()
        radar = self.service.radar(
            radius_nm=float(radius),
            include_surface=True,
            traffic=str(self.traffic_filter.currentData() or "all"),
            min_alt_ft=min_alt,
            max_alt_ft=max_alt,
            terrain=self.layer_toggles["terrain"].isChecked(),
        )
        return {
            "payload": radar.payload,
            "cfg": radar.config,
            "surface": radar.surface,
            "radar_map": radar.radar_map,
            "surface_error": radar.surface_error,
            "weather": radar.weather,
            "weather_error": radar.weather_error,
        }

    def _apply_radar(self, result: dict[str, Any]) -> None:
        self._set_busy(False)
        payload = result["payload"]
        if isinstance(result.get("radar_map"), dict):
            payload = dict(payload)
            payload["radar_map"] = result["radar_map"]
        cfg = result.get("cfg") if isinstance(result.get("cfg"), dict) else {}
        self.config = dict(cfg)
        self._apply_config(cfg)
        self._last_payload = dict(payload)
        self.notice_banner.set_notices(payload.get("notices") or [])
        if isinstance(result.get("radar_map"), dict):
            self._last_surface = _surface_from_map(result["radar_map"], payload)
            self.canvas.set_map({"features": result["radar_map"].get("map_features") or []})
            self.canvas.set_surface(self._last_surface)
        elif isinstance(result.get("surface"), dict):
            self.canvas.set_map([])
            self._last_surface = dict(result["surface"])
            self.canvas.set_surface(self._last_surface)
        elif not cfg.get("radar_surface_enabled"):
            self.canvas.set_map([])
            self._last_surface = {"features": [], "center": payload.get("center") or {}}
            self.canvas.set_surface(self._last_surface)
        if isinstance(result.get("weather"), dict):
            self.weather.set_weather(_weather_line(result["weather"], raw=True), _weather_icon_glyph(result["weather"].get("weather_icon")))
            self.weather.setProperty("tone", str(result["weather"].get("weather_tone") or "neutral"))
            self.weather.style().unpolish(self.weather)
            self.weather.style().polish(self.weather)
        else:
            self.weather.set_weather("Weather is temporarily unavailable.", "")
            self.weather.setProperty("tone", "caution")
            self.weather.style().unpolish(self.weather)
            self.weather.style().polish(self.weather)
        self.canvas.set_payload(payload)
        self._refresh_optional_layers()
        self._show_blip_info(None)
        self.source_info.setText(self._source_line(payload, self._last_surface, surface_error=str(result.get("surface_error") or "")))
        self._set_status(self._status_line(payload, surface_error=str(result.get("surface_error") or "")))

    def _apply_config(self, cfg: dict[str, Any]) -> None:
        airport = str(cfg.get("airport_iata") or cfg.get("airport_icao") or "").upper()
        source = str(cfg.get("source") or "").upper()
        if not self.embedded:
            suffix = " | ".join(part for part in (airport, source) if part)
            self.title.setText(f"Radar {suffix}" if suffix else "Radar")

    def _status_line(self, payload: dict[str, Any], *, surface_error: str = "") -> str:
        count = int(payload.get("count") or 0)
        mode = str(payload.get("radar_mode") or ("surface" if self.radius_nm <= 5 else "airborne"))
        visible_label = "targets" if mode == "surface" else "aircraft"
        if count == 0:
            base = "No aircraft visible in this range right now."
        else:
            base = f"{count} {visible_label} visible."
        hidden_airborne = int(payload.get("airborne_filtered") or payload.get("hidden_airborne_count") or 0)
        hidden_ground = int(payload.get("ground_filtered") or payload.get("hidden_ground_count") or 0)
        details: list[str] = []
        if hidden_airborne:
            details.append(f"{hidden_airborne} airborne hidden in surface view")
        if hidden_ground:
            details.append(f"{hidden_ground} ground targets hidden")
        if surface_error:
            details.append("airport map unavailable")
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        return " ".join(part for part in (base, " | ".join(details), f"Updated {timestamp} UTC") if part)

    def _source_line(self, payload: dict[str, Any], surface: dict[str, Any], *, surface_error: str = "") -> str:
        mode = str(payload.get("radar_mode") or ("surface" if self.radius_nm <= 5 else "airborne"))
        layers = []
        if self.layer_toggles["map"].isChecked():
            layers.append("map")
        if self.layer_toggles["runways"].isChecked():
            layers.append("runways")
        if self.layer_toggles["surface"].isChecked():
            layers.append("surface")
        if self.layer_toggles["traffic_status"].isChecked():
            layers.append("status labels")
        if self.layer_toggles["procedures"].isChecked():
            layers.append("route hints")
        if self.layer_toggles["terrain"].isChecked():
            layers.append("terrain")
        layer_text = ", ".join(layers) if layers else "simple view"
        parts = [f"{mode.title()} view"]
        radar_map = payload.get("radar_map") if isinstance(payload.get("radar_map"), dict) else {}
        if self.layer_toggles["map"].isChecked() and isinstance(radar_map, dict):
            map_count = len(radar_map.get("map_features") or [])
            map_state = str((radar_map.get("sources") or {}).get("map_cache_state") or "").strip()
            parts.append("airport map ready" if map_count else "airport map unavailable")
        if self.layer_toggles["terrain"].isChecked() and isinstance(radar_map, dict):
            terrain = radar_map.get("terrain") if isinstance(radar_map.get("terrain"), dict) else {}
            terrain_count = len(terrain.get("features") or [])
            terrain_state = str((radar_map.get("sources") or {}).get("terrain_cache_state") or "").strip()
            parts.append("terrain ready" if terrain_count else "terrain unavailable")
        if self.layer_toggles["runways"].isChecked() or self.layer_toggles["surface"].isChecked():
            parts.append(_surface_source_label(surface, surface_error=surface_error))
        parts.append(f"overlays: {layer_text}")
        return " | ".join(part for part in parts if part)

    def _radar_error(self, exc: Exception) -> None:
        self.notice_banner.set_notices([{
            "code": "radar.temporarily_unavailable",
            "tone": "error",
            "message": "Radar is temporarily unavailable.",
            "next_step": "The app will keep trying; you can also refresh in a moment.",
        }])
        self._set_status(
            "Radar is temporarily unavailable. Keeping the screen ready and trying again soon.",
            role="StatusBad",
            busy=False,
        )

    def _set_status(self, text: str, *, role: str = "Muted", busy: bool = False) -> None:
        self._last_status_text = text
        self.status.setText(text)
        self.status.setObjectName(role)
        try:
            self.status.style().unpolish(self.status)
            self.status.style().polish(self.status)
        except Exception:
            pass
        self._set_busy(busy)

    def _set_busy(self, busy: bool) -> None:
        self.loading_indicator.setVisible(bool(busy))

    def _show_blip_info(self, blip: Any) -> None:
        if not isinstance(blip, dict) or not blip:
            self.status.setText(self._last_status_text)
            return
        summary = _blip_summary(blip)
        self.status.setText(f"{summary['title']} under pointer. Click for flight details.")

    def _show_selected_blip_info(self, blip: Any) -> None:
        if not isinstance(blip, dict) or not blip:
            return
        summary = _blip_summary(blip)
        self._apply_selected_summary(summary)
        callsign = str(blip.get("callsign") or blip.get("flight_number") or "").strip().upper()
        if not callsign:
            return
        self._run_async(
            lambda: self.service.fids_detail(callsign),
            lambda payload: self._apply_selected_detail(summary, payload),
            lambda exc: self._apply_selected_detail_error(summary, exc),
            label=f"radar.detail.{callsign}",
            debounce_ms=0,
        )

    def _apply_selected_summary(self, summary: dict[str, str]) -> None:
        self.blip_title.setText(summary["title"])
        self.blip_route.setText(summary["route"])
        self.blip_detail.setText(summary["detail"])
        self.blip_info.show()
        self.status.setText(f"Selected {summary['title']}. Fetching linked FIDS detail...")

    def _apply_selected_detail(self, summary: dict[str, str], payload: Any) -> None:
        detail = _extract_detail_payload(payload)
        if not detail:
            self.status.setText(f"Selected {summary['title']}. No matching FIDS detail is available yet.")
            return
        intel = _extract_intel_payload(payload, detail)
        route = _intel_route(intel) or _detail_route(detail) or summary["route"]
        chips = [part for part in (
            _intel_status(intel),
            _intel_motion(intel),
            _intel_aircraft(intel),
            _intel_ops(intel),
            _intel_source(intel),
            _detail_status(detail),
            _detail_gate(detail),
            _detail_aircraft(detail),
            _detail_source(detail),
        ) if part]
        deduped: list[str] = []
        for chip in chips:
            if chip not in deduped:
                deduped.append(chip)
        self.blip_route.setText(route)
        self.blip_detail.setText(" | ".join(deduped + ([summary["detail"]] if summary["detail"] else [])))
        self.status.setText(f"Selected {summary['title']}. Flight details are ready.")

    def _apply_selected_detail_error(self, summary: dict[str, str], _exc: Exception) -> None:
        self.status.setText(f"Selected {summary['title']}. Flight details are temporarily unavailable.")

    def _refresh_optional_layers(self) -> None:
        payload = self._last_payload if isinstance(self._last_payload, dict) else {}
        surface = self._last_surface if isinstance(self._last_surface, dict) else {}
        center = payload.get("center") if isinstance(payload.get("center"), dict) else surface.get("center")
        if self.layer_toggles["procedures"].isChecked():
            self.canvas.set_procedures({"paths": _route_hint_paths(payload, self.config)})
        else:
            self.canvas.set_procedures([])
        if self.layer_toggles["terrain"].isChecked():
            radar_map = payload.get("radar_map") if isinstance(payload.get("radar_map"), dict) else {}
            terrain = radar_map.get("terrain") if isinstance(radar_map.get("terrain"), dict) else {}
            features = terrain.get("features") if isinstance(terrain.get("features"), list) else []
            self.canvas.set_terrain({"features": features or _estimated_relief_features(center, self.radius_nm)})
        else:
            self.canvas.set_terrain([])
        self.source_info.setText(self._source_line(payload, surface))
        self._update_filter_summary()

    def _altitude_bounds(self) -> tuple[float | None, float | None]:
        key = str(self.altitude_filter.currentData() or "all")
        if key == "surface":
            return 0.0, 3000.0
        if key == "terminal":
            return 0.0, 10000.0
        if key == "enroute":
            return 10000.0, None
        return None, None

    def _update_filter_summary(self) -> None:
        if not hasattr(self, "filter_summary"):
            return
        traffic = str(self.traffic_filter.currentData() or "all")
        altitude = str(self.altitude_filter.currentData() or "all")
        active_optional = [
            text
            for key, text in (
                ("traffic_status", "labels"),
                ("procedures", "routes"),
                ("terrain", "terrain"),
            )
            if self.layer_toggles.get(key) is not None and self.layer_toggles[key].isChecked()
        ]
        parts: list[str] = []
        if traffic != "all":
            parts.append(str(self.traffic_filter.currentText()))
        if altitude != "all":
            parts.append(str(self.altitude_filter.currentText()))
        parts.extend(active_optional)
        self.filter_summary.setText(" | ".join(parts))


def _source_label(source: Any) -> str:
    raw = str(source or "local").strip().lower()
    if raw.startswith("adsbexchange"):
        return "ADS-B"
    if raw.startswith("opensky"):
        return "OpenSky"
    if raw.startswith("snapshot"):
        return "local snapshot"
    if raw == "vatsim":
        return "VATSIM"
    return raw or "local"


def _blip_summary(blip: dict[str, Any]) -> dict[str, str]:
    callsign = str(blip.get("callsign") or blip.get("flight_number") or blip.get("icao24") or "Aircraft").strip().upper()
    route = " -> ".join(str(value).strip().upper() for value in (blip.get("departure_icao"), blip.get("arrival_icao")) if str(value or "").strip())
    aircraft = str(blip.get("aircraft_type") or blip.get("type") or "").strip().upper()
    altitude = _altitude_ft_text(blip.get("altitude_ft")) if blip.get("altitude_ft") is not None else _altitude_text(blip.get("altitude_m"))
    speed = _speed_kt_text(blip.get("speed_kt")) if blip.get("speed_kt") is not None else _speed_text(blip.get("speed_ms"))
    heading = _heading_text(blip.get("track_deg") if blip.get("track_deg") is not None else blip.get("heading"))
    distance = _distance_text(blip.get("distance_nm"))
    source = _source_label(blip.get("source"))
    status = str(blip.get("radar_status_label") or "").strip()
    vertical = _vertical_rate_fpm_text(blip.get("vertical_rate_fpm")) if blip.get("vertical_rate_fpm") is not None else _vertical_rate_text(blip.get("vertical_rate"))
    chips = [part for part in (status, aircraft, altitude, vertical, speed, heading, distance, source) if part]
    if blip.get("matched_runway") or blip.get("nearest_runway"):
        chips.append(f"RWY {blip.get('matched_runway') or blip.get('nearest_runway')}")
    if blip.get("phase_confidence"):
        chips.append(f"{str(blip.get('phase_confidence')).title()} confidence")
    if str(blip.get("source") or "").lower() == "vatsim":
        rules = str(blip.get("flight_rules") or "").strip()
        planned = str(blip.get("planned_altitude") or "").strip()
        if rules:
            chips.append(f"Rules {rules}")
        if planned:
            chips.append(f"Planned {planned}")
    return {
        "title": callsign,
        "route": route or "Route not available",
        "detail": " | ".join(chips + ([str(blip.get("phase_reason"))] if blip.get("phase_reason") else [])) or "Basic position only",
    }


def _extract_detail_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    detail = payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def _extract_intel_payload(payload: Any, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("intel"), dict):
        return payload["intel"]
    if isinstance(detail, dict) and isinstance(detail.get("intel"), dict):
        return detail["intel"]
    return {}


def _nested(mapping: dict[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _intel_route(intel: dict[str, Any]) -> str:
    route = str(_nested(intel, "route", "route_display") or "").strip()
    return route.replace("→", "->")


def _intel_status(intel: dict[str, Any]) -> str:
    status = str(_nested(intel, "timing", "status") or "").strip().replace("_", " ").upper()
    delay = _nested(intel, "timing", "delay_minutes")
    try:
        delay_value = int(delay)
    except (TypeError, ValueError):
        delay_value = 0
    if status and delay_value:
        return f"{status} {delay_value:+d}m"
    return status


def _intel_motion(intel: dict[str, Any]) -> str:
    motion = intel.get("motion") if isinstance(intel.get("motion"), dict) else {}
    parts: list[str] = []
    if motion.get("on_ground") is True:
        parts.append("On ground")
    elif motion.get("altitude_ft") is not None:
        try:
            parts.append(f"{int(float(motion['altitude_ft'])):,} ft")
        except (TypeError, ValueError):
            pass
    if motion.get("speed_kt") is not None:
        try:
            parts.append(f"{int(float(motion['speed_kt']))} kt")
        except (TypeError, ValueError):
            pass
    if motion.get("vertical_rate_fpm") is not None:
        try:
            parts.append(f"{int(float(motion['vertical_rate_fpm'])):+d} fpm")
        except (TypeError, ValueError):
            pass
    radar_status = str(motion.get("radar_status") or "").strip()
    if radar_status:
        parts.insert(0, radar_status)
    return " ".join(parts)


def _intel_aircraft(intel: dict[str, Any]) -> str:
    aircraft = intel.get("aircraft") if isinstance(intel.get("aircraft"), dict) else {}
    return " ".join(
        str(part).strip().upper()
        for part in (aircraft.get("type"), aircraft.get("registration"))
        if str(part or "").strip()
    )


def _intel_ops(intel: dict[str, Any]) -> str:
    ops = intel.get("operations") if isinstance(intel.get("operations"), dict) else {}
    terminal = str(ops.get("terminal") or "").strip()
    gate = str(ops.get("gate") or "").strip()
    if terminal and gate:
        return f"Terminal {terminal} Gate {gate}"
    if gate:
        return f"Gate {gate}"
    if terminal:
        return f"Terminal {terminal}"
    return ""


def _intel_source(intel: dict[str, Any]) -> str:
    evidence = intel.get("source_evidence") if isinstance(intel.get("source_evidence"), dict) else {}
    confidence = str(evidence.get("confidence") or "").strip().replace("_", " ")
    source = str(evidence.get("position_source") or evidence.get("schedule_source") or "").strip()
    return " | ".join(part for part in (source, confidence) if part)


def _detail_route(detail: dict[str, Any]) -> str:
    origin = str(detail.get("origin_iata") or detail.get("origin_icao") or "").strip().upper()
    dest = str(detail.get("dest_iata") or detail.get("dest_icao") or "").strip().upper()
    if origin and dest:
        return f"{origin} -> {dest}"
    return ""


def _detail_status(detail: dict[str, Any]) -> str:
    status = str(detail.get("status") or "").strip().replace("_", " ").upper()
    delay = detail.get("delay_minutes")
    try:
        delay_value = int(delay)
    except (TypeError, ValueError):
        delay_value = 0
    if delay_value:
        suffix = f"{delay_value:+d}m"
        return f"{status} {suffix}".strip()
    return status


def _detail_gate(detail: dict[str, Any]) -> str:
    terminal = str(detail.get("terminal") or "").strip()
    gate = str(detail.get("gate") or "").strip()
    if terminal and gate:
        return f"Terminal {terminal} Gate {gate}"
    if gate:
        return f"Gate {gate}"
    if terminal:
        return f"Terminal {terminal}"
    return ""


def _detail_aircraft(detail: dict[str, Any]) -> str:
    aircraft = str(detail.get("aircraft_type") or "").strip().upper()
    registration = str(detail.get("aircraft_registration") or "").strip().upper()
    return " ".join(part for part in (aircraft, registration) if part)


def _detail_source(detail: dict[str, Any]) -> str:
    sources = detail.get("data_sources") if isinstance(detail.get("data_sources"), dict) else {}
    confidence = str(sources.get("confidence") or "").strip().replace("_", " ")
    mode = str(detail.get("detail_mode") or detail.get("source") or "").strip()
    return " | ".join(part for part in (mode, confidence) if part)


def _surface_from_map(radar_map: dict[str, Any], radar_payload: dict[str, Any]) -> dict[str, Any]:
    center = radar_map.get("center") if isinstance(radar_map.get("center"), dict) else radar_payload.get("center")
    runways = radar_map.get("runways") if isinstance(radar_map.get("runways"), list) else []
    surface = radar_map.get("surface_features") if isinstance(radar_map.get("surface_features"), list) else []
    sources = radar_map.get("sources") if isinstance(radar_map.get("sources"), dict) else {}
    attribution_list = radar_map.get("attribution") if isinstance(radar_map.get("attribution"), list) else []
    attribution = attribution_list[0] if attribution_list and isinstance(attribution_list[0], dict) else {}
    return {
        "provider": sources.get("surface") or "radar-map",
        "cache_state": sources.get("surface_cache_state") or "map",
        "center": center or {},
        "features": [*surface, *runways],
        "attribution": attribution,
        "meta": {"validation": {"runway_count": len(runways), "building_count": len([f for f in surface if str(f.get("kind")) in {"building", "terminal"}])}},
    }


def _surface_source_label(surface: dict[str, Any], *, surface_error: str = "") -> str:
    if surface_error:
        return "surface unavailable"
    provider = str(surface.get("provider") or "").strip().lower()
    cache_state = str(surface.get("cache_state") or "").strip().lower()
    features = surface.get("features") if isinstance(surface.get("features"), list) else []
    meta = surface.get("meta") if isinstance(surface.get("meta"), dict) else {}
    validation = meta.get("validation") if isinstance(meta.get("validation"), dict) else {}
    runway_count = validation.get("runway_count")
    if cache_state == "disabled":
        return "surface overlay off in Settings"
    if not features:
        return "surface enabled, waiting for runway data"
    runway_confidences = {
        str(feature.get("confidence") or "").strip().lower()
        for feature in features
        if isinstance(feature, dict) and str(feature.get("kind") or "").strip().lower() == "runway"
    }
    if provider == "localflight-estimated" and any(conf in {"ourairports", "ourairports+osm"} for conf in runway_confidences):
        return "OurAirports runways with estimated surface"
    if provider == "openstreetmap":
        suffix = f", {runway_count} runway features" if runway_count else ""
        return f"OSM surface checked against airport center{suffix}"
    if provider == "localflight-estimated" or cache_state == "estimated":
        return "estimated airport surface"
    if cache_state == "stale":
        return "stored airport surface"
    return "airport surface loaded"


def _route_hint_paths(payload: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
    center_lat = _safe_float(center.get("lat"))
    center_lon = _safe_float(center.get("lon"))
    airport_icao = str(cfg.get("airport_icao") or "").strip().upper()
    if center_lat is None or center_lon is None:
        return []
    paths: list[dict[str, Any]] = []
    for blip in payload.get("blips") or []:
        if not isinstance(blip, dict):
            continue
        lat = _safe_float(blip.get("lat"))
        lon = _safe_float(blip.get("lon"))
        if lat is None or lon is None:
            continue
        dep = str(blip.get("departure_icao") or "").strip().upper()
        arr = str(blip.get("arrival_icao") or "").strip().upper()
        phase = str(blip.get("radar_phase") or blip.get("radar_status") or "").strip().lower()
        if arr and airport_icao and arr == airport_icao:
            kind = "approach"
        elif dep and airport_icao and dep == airport_icao:
            kind = "departure"
        elif phase in {"approach", "final", "descending"}:
            kind = "approach"
        elif phase in {"departure", "climbing"}:
            kind = "departure"
        else:
            continue
        callsign = str(blip.get("callsign") or "").strip().upper()
        if kind == "approach":
            points = [[lat, lon], [center_lat, center_lon]]
        else:
            points = [[center_lat, center_lon], [lat, lon]]
        paths.append({"kind": kind, "label": callsign or kind.title(), "points": points})
    return paths[:30]


def _estimated_relief_features(center: Any, radius_nm: int | float) -> list[dict[str, Any]]:
    if not isinstance(center, dict):
        return []
    lat = _safe_float(center.get("lat"))
    lon = _safe_float(center.get("lon"))
    if lat is None or lon is None:
        return []
    radius = max(1.0, min(40.0, float(radius_nm or 5)))
    features: list[dict[str, Any]] = []
    for idx, scale in enumerate((0.32, 0.52, 0.72), start=1):
        north = radius * scale
        east = radius * (0.18 + idx * 0.04)
        points = [
            _offset_point(lat, lon, north_nm=north * 0.45, east_nm=-east),
            _offset_point(lat, lon, north_nm=north * 0.10, east_nm=-east * 0.45),
            _offset_point(lat, lon, north_nm=-north * 0.20, east_nm=east * 0.10),
            _offset_point(lat, lon, north_nm=-north * 0.45, east_nm=east),
        ]
        features.append({"kind": "relief", "label": f"estimated relief {idx}", "points": points})
    return features


def _offset_point(lat: float, lon: float, *, north_nm: float = 0.0, east_nm: float = 0.0) -> list[float]:
    cos_lat = max(0.15, abs(math.cos(math.radians(lat))))
    return [
        round(lat + (north_nm / 60.0), 7),
        round(lon + (east_nm / (60.0 * cos_lat)), 7),
    ]


def _altitude_text(value: Any) -> str:
    try:
        meters = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{int(round(meters * 3.28084))} ft"


def _altitude_ft_text(value: Any) -> str:
    try:
        feet = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{int(round(feet))} ft"


def _vertical_rate_text(value: Any) -> str:
    try:
        meters_s = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(meters_s) < 0.2:
        return "Level"
    feet_min = int(round(meters_s * 196.8504))
    return f"{feet_min:+d} fpm"


def _vertical_rate_fpm_text(value: Any) -> str:
    try:
        feet_min = float(value)
    except (TypeError, ValueError):
        return ""
    if abs(feet_min) < 50:
        return "Level"
    return f"{int(round(feet_min)):+d} fpm"


def _speed_text(value: Any) -> str:
    try:
        meters_s = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{int(round(meters_s * 1.94384))} kt"


def _speed_kt_text(value: Any) -> str:
    try:
        knots = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{int(round(knots))} kt"


def _heading_text(value: Any) -> str:
    try:
        return f"HDG {int(round(float(value))) % 360}"
    except (TypeError, ValueError):
        return ""


def _distance_text(value: Any) -> str:
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{distance:g}nm"


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _weather_line(payload: dict[str, Any], *, raw: bool) -> str:
    cat = payload.get("flight_cat") or "?"
    temp = payload.get("temperature_c", payload.get("temp_c"))
    temp_text = f"{temp} C" if temp is not None else "-- C"
    summary = payload.get("decoded_summary") or payload.get("weather_summary") or payload.get("weather_label") or ""
    raw_text = payload.get("raw_text") or payload.get("raw") or ""
    return f"{cat} | {temp_text} | {summary}" + (f" | {raw_text}" if raw and raw_text else "")


def _weather_icon_glyph(icon_name: Any) -> str:
    icon = str(icon_name or "unknown").strip().lower()
    return WEATHER_EMOJI.get(icon, WEATHER_EMOJI["unknown"])


__all__ = ["RadarScreen"]
