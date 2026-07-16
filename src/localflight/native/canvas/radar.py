"""Qt-native radar canvas.

The browser radar remains the behavior checklist, but this module owns the
native QPainter implementation so Radar can evolve outside the compatibility shell.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from localflight.native.design import colors_for, format_value
from localflight.radar.presentation import (
    RADAR_FLASH_DEGREES,
    RADAR_FRAME_INTERVAL_MS,
    RADAR_TRAIL_DEGREES,
    angular_age,
    bearing_from_offset,
    blip_opacity,
    label_priority,
    radar_phase_label,
    sweep_angle_after,
    target_is_interactive,
    target_shape,
    target_tone_role,
)


STATIC_RADAR_LAYER_ORDER = ("background", "surface", "map", "terrain", "grid", "runways", "procedures")
DYNAMIC_RADAR_LAYER_ORDER = ("track_ghosts", "sweep", "blips", "hover")


@dataclass(frozen=True)
class RadarViewport:
    """Projection state shared by every radar drawing layer."""

    width: int
    height: int
    cx: float
    cy: float
    radius: float
    radius_nm: float
    center_lat: float
    center_lon: float

    def latlon_to_nm(self, lat: float, lon: float) -> tuple[float, float]:
        y_nm = (lat - self.center_lat) * 60.0
        x_nm = (lon - self.center_lon) * 60.0 * math.cos(math.radians(self.center_lat))
        return x_nm, y_nm

    def nm_to_canvas(self, x_nm: float, y_nm: float) -> tuple[float, float]:
        scale = self.radius / max(0.1, self.radius_nm)
        return self.cx + x_nm * scale, self.cy - y_nm * scale


class RadarCanvas:  # pragma: no cover - optional Qt runtime
    def __new__(cls, QtCore: Any, QtGui: Any, QtWidgets: Any):
        class _Canvas(QtWidgets.QWidget):
            hoverChanged = QtCore.Signal(object)
            blipClicked = QtCore.Signal(object)

            def __init__(self) -> None:
                super().__init__()
                self.setMouseTracking(True)
                self.setFocusPolicy(QtCore.Qt.StrongFocus)
                self.setMinimumSize(260, 260)
                self.blips: list[dict[str, Any]] = []
                self.track_history: dict[str, list[tuple[float, float]]] = {}
                self._track_absent_counts: dict[str, int] = {}
                self._max_track_points = 4
                self.map_features: list[dict[str, Any]] = []
                self.surface: list[dict[str, Any]] = []
                self.procedure_paths: list[dict[str, Any]] = []
                self.terrain_features: list[dict[str, Any]] = []
                self.layers = {
                    "map": True,
                    "surface": True,
                    "runways": True,
                    "traffic_status": False,
                    "procedures": False,
                    "terrain": False,
                }
                self.center = {"lat": 0.0, "lon": 0.0}
                self.radius_nm = 20.0
                self.status = "No radar data yet"
                self.attribution = ""
                self.sweep_angle = 0.0
                self.colors = colors_for()
                self._theme = "dark"
                self._skin = "standard"
                self._map_version = 0
                self._map_projection_key: tuple[Any, ...] | None = None
                self._map_projection: list[tuple[str, str, list[Any], bool, dict[str, Any]]] = []
                self._surface_version = 0
                self._surface_projection_key: tuple[Any, ...] | None = None
                self._surface_projection: list[tuple[str, str, list[Any], bool, dict[str, Any]]] = []
                self._terrain_version = 0
                self._terrain_projection_key: tuple[Any, ...] | None = None
                self._terrain_projection: list[tuple[str, str, list[Any], bool, dict[str, Any]]] = []
                self._procedure_version = 0
                self._procedure_projection_key: tuple[Any, ...] | None = None
                self._procedure_projection: list[tuple[str, str, list[Any]]] = []
                self._static_cache_key: tuple[Any, ...] | None = None
                self._static_cache_pixmap: Any = None
                self._hover_key = ""
                self._selected_key = ""
                self.hovered_blip: dict[str, Any] | None = None
                self._sweep_timer = QtCore.QTimer(self)
                self._sweep_interval_ms = RADAR_FRAME_INTERVAL_MS
                self._sweep_clock = QtCore.QElapsedTimer()
                self._sweep_anchor_angle = self.sweep_angle
                self._animation_requested = True
                self._sweep_timer.timeout.connect(self._tick_sweep)

            def showEvent(self, event: Any) -> None:
                super().showEvent(event)
                if self._animation_requested:
                    self._start_sweep()

            def hideEvent(self, event: Any) -> None:
                super().hideEvent(event)
                self._stop_sweep()

            def set_animation_active(self, active: bool) -> None:
                """Run the presentation clock only while this canvas is requested and visible."""
                self._animation_requested = bool(active)
                if self._animation_requested and self.isVisible():
                    self._start_sweep()
                else:
                    self._stop_sweep()

            def _start_sweep(self) -> None:
                # The shell can activate a page before Qt delivers showEvent.
                # Always repair an invalid clock even when the timer is already active.
                if not self._sweep_clock.isValid():
                    self._sweep_anchor_angle = self.sweep_angle
                    self._sweep_clock.start()
                if not self._sweep_timer.isActive():
                    self._sweep_timer.start(self._sweep_interval_ms)

            def _stop_sweep(self) -> None:
                if self._sweep_clock.isValid():
                    self._tick_sweep()
                    self._sweep_clock.invalidate()
                self._sweep_timer.stop()

            def apply_theme(self, theme: str, skin: str) -> None:
                self.colors = colors_for(theme, skin)
                self._theme = (theme or "dark").strip().lower()
                self._skin = (skin or "standard").strip().lower()
                self._invalidate_static_layer()
                self.update()

            def set_radius_nm(self, radius_nm: float) -> None:
                """Update the visible range immediately, independent of API refresh."""
                try:
                    radius = float(radius_nm)
                except (TypeError, ValueError):
                    return
                radius = max(1.0, min(200.0, radius))
                if math.isclose(radius, float(self.radius_nm), rel_tol=0.0, abs_tol=0.001):
                    return
                self.radius_nm = radius
                self._surface_projection_key = None
                self._map_projection_key = None
                self._terrain_projection_key = None
                self._procedure_projection_key = None
                self._invalidate_static_layer()
                self.update()

            def set_payload(self, payload: dict[str, Any]) -> None:
                old_key = (self.radius_nm, self.center.get("lat"), self.center.get("lon"))
                self.blips = [b for b in payload.get("blips", []) if isinstance(b, dict)]
                self.radius_nm = float(payload.get("radius_nm") or self.radius_nm)
                center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
                if center:
                    self.center = {
                        "lat": float(center.get("lat") or self.center.get("lat") or 0.0),
                        "lon": float(center.get("lon") or self.center.get("lon") or 0.0),
                    }
                new_key = (self.radius_nm, self.center.get("lat"), self.center.get("lon"))
                if new_key != old_key:
                    self._surface_projection_key = None
                    self._map_projection_key = None
                    self._invalidate_static_layer()
                    if old_key[1] not in {None, 0.0} and old_key[2] not in {None, 0.0}:
                        self.track_history.clear()
                        self._track_absent_counts.clear()
                self._update_track_history(self.blips)
                self.status = f"{len(self.blips)} visible | {payload.get('source', 'unknown')}"
                self._set_hover_blip(None)
                identities = {self._blip_identity(blip) for blip in self.blips}
                if self._selected_key and self._selected_key not in identities:
                    self._selected_key = ""
                    self.blipClicked.emit(None)
                self.update()

            def set_surface(self, payload: dict[str, Any]) -> None:
                self.surface = [f for f in payload.get("features", []) if isinstance(f, dict)]
                center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
                self.center = {
                    "lat": float(center.get("lat") or self.center.get("lat") or 0.0),
                    "lon": float(center.get("lon") or self.center.get("lon") or 0.0),
                }
                attribution = payload.get("attribution") if isinstance(payload.get("attribution"), dict) else {}
                self.attribution = str(attribution.get("text") or ("Estimated airport surface" if self.surface else ""))
                self._surface_version += 1
                self._surface_projection_key = None
                self._invalidate_static_layer()
                self.update()

            def set_map(self, payload: dict[str, Any] | list[Any] | None) -> None:
                """Install optional cartographic inlay features below radar layers."""
                if isinstance(payload, dict):
                    raw = payload.get("features") or payload.get("map_features") or payload.get("ways") or []
                else:
                    raw = payload or []
                self.map_features = [f for f in raw if isinstance(f, dict)]
                self._map_version += 1
                self._map_projection_key = None
                self._invalidate_static_layer()
                self.update()

            def set_procedures(self, payload: dict[str, Any] | list[Any] | None) -> None:
                """Install optional approach/departure paths for future radar layers."""
                if isinstance(payload, dict):
                    raw = payload.get("paths") or payload.get("procedures") or payload.get("features") or []
                else:
                    raw = payload or []
                self.procedure_paths = [f for f in raw if isinstance(f, dict)]
                self._procedure_version += 1
                self._procedure_projection_key = None
                self._invalidate_static_layer()
                self.update()

            def set_terrain(self, payload: dict[str, Any] | list[Any] | None) -> None:
                """Install optional terrain/height features without changing radar APIs."""
                if isinstance(payload, dict):
                    raw = payload.get("features") or payload.get("contours") or []
                else:
                    raw = payload or []
                self.terrain_features = [f for f in raw if isinstance(f, dict)]
                self._terrain_version += 1
                self._terrain_projection_key = None
                self._invalidate_static_layer()
                self.update()

            def set_layer_enabled(self, layer: str, enabled: bool) -> None:
                if layer not in self.layers:
                    return
                self.layers[layer] = bool(enabled)
                if layer in {"map", "surface", "runways", "procedures", "terrain"}:
                    self._invalidate_static_layer()
                self.update()

            def _tick_sweep(self) -> None:
                if self._sweep_clock.isValid():
                    self.sweep_angle = sweep_angle_after(self._sweep_anchor_angle, self._sweep_clock.elapsed())
                self.update()

            def paintEvent(self, _event: Any) -> None:
                painter = QtGui.QPainter(self)
                painter.setRenderHint(QtGui.QPainter.Antialiasing)
                rect = self.rect()
                viewport = self._viewport(rect)
                painter.drawPixmap(rect.topLeft(), self._static_layer_pixmap(QtCore, QtGui, rect, viewport))
                painter.save()
                path = QtGui.QPainterPath()
                path.addEllipse(QtCore.QPointF(viewport.cx, viewport.cy), viewport.radius, viewport.radius)
                painter.setClipPath(path)
                self._draw_dynamic_layers(painter, QtCore, QtGui, viewport)
                painter.restore()
                self._draw_footer(painter, QtGui, rect)

            def mouseMoveEvent(self, event: Any) -> None:
                viewport = self._viewport(self.rect())
                hit = self._hit_blip(event.position().x(), event.position().y(), viewport)
                self._set_hover_blip(hit)
                self.setToolTip("")
                self.setCursor(QtCore.Qt.PointingHandCursor if hit else QtCore.Qt.ArrowCursor)

            def leaveEvent(self, event: Any) -> None:
                super().leaveEvent(event)
                self._set_hover_blip(None)
                self.setToolTip("")
                self.unsetCursor()

            def mousePressEvent(self, event: Any) -> None:
                viewport = self._viewport(self.rect())
                hit = self._hit_blip(event.position().x(), event.position().y(), viewport)
                if hit:
                    hit_key = self._blip_identity(hit)
                    if hit_key and hit_key == self._selected_key:
                        self.set_selected_blip(None)
                        self.blipClicked.emit(None)
                    else:
                        self.set_selected_blip(hit)
                        self.blipClicked.emit(dict(hit))
                elif self._selected_key:
                    self.set_selected_blip(None)
                    self.blipClicked.emit(None)
                super().mousePressEvent(event)

            def keyPressEvent(self, event: Any) -> None:
                if event.key() == QtCore.Qt.Key_Escape and self._selected_key:
                    self.set_selected_blip(None)
                    self.blipClicked.emit(None)
                    event.accept()
                    return
                super().keyPressEvent(event)

            def set_selected_blip(self, blip: dict[str, Any] | None) -> None:
                key = self._blip_identity(blip)
                if key == self._selected_key:
                    return
                self._selected_key = key
                self.update()

            def _viewport(self, rect: Any) -> RadarViewport:
                size = min(rect.width(), rect.height()) - 18
                return RadarViewport(
                    width=rect.width(),
                    height=rect.height(),
                    cx=float(rect.center().x()),
                    cy=float(rect.center().y()),
                    radius=max(1.0, float(size) / 2.0),
                    radius_nm=max(0.1, float(self.radius_nm)),
                    center_lat=float(self.center.get("lat") or 0.0),
                    center_lon=float(self.center.get("lon") or 0.0),
                )

            def _invalidate_static_layer(self) -> None:
                self._static_cache_key = None
                self._static_cache_pixmap = None

            def _static_layer_key(self, viewport: RadarViewport) -> tuple[Any, ...]:
                return (
                    self._projection_key(viewport),
                    self._map_version,
                    self._surface_version,
                    self._terrain_version,
                    self._procedure_version,
                    bool(self.layers.get("map", True)),
                    bool(self.layers.get("surface", True)),
                    bool(self.layers.get("runways", True)),
                    bool(self.layers.get("terrain", False)),
                    bool(self.layers.get("procedures", False)),
                    tuple(sorted(self.colors.items())),
                )

            def _static_layer_pixmap(self, QtCore: Any, QtGui: Any, rect: Any, viewport: RadarViewport) -> Any:
                key = self._static_layer_key(viewport)
                if self._static_cache_key == key and self._static_cache_pixmap is not None:
                    return self._static_cache_pixmap
                pixmap = QtGui.QPixmap(rect.size())
                pixmap.fill(QtCore.Qt.transparent)
                static_painter = QtGui.QPainter(pixmap)
                static_painter.setRenderHint(QtGui.QPainter.Antialiasing)
                try:
                    self._draw_static_layers(static_painter, QtCore, QtGui, rect, viewport)
                finally:
                    static_painter.end()
                self._static_cache_key = key
                self._static_cache_pixmap = pixmap
                return pixmap

            def _draw_static_layers(self, painter: Any, QtCore: Any, QtGui: Any, rect: Any, viewport: RadarViewport) -> None:
                self._draw_background(painter, QtGui, rect, viewport)
                painter.save()
                path = QtGui.QPainterPath()
                path.addEllipse(QtCore.QPointF(viewport.cx, viewport.cy), viewport.radius, viewport.radius)
                painter.setClipPath(path)
                try:
                    for layer in STATIC_RADAR_LAYER_ORDER:
                        if layer == "background":
                            continue
                        self._draw_static_layer(layer, painter, QtCore, QtGui, viewport)
                finally:
                    painter.restore()

            def _draw_static_layer(self, layer: str, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if layer == "map":
                    if self.layers.get("map", True):
                        self._draw_map_inlay(painter, QtCore, QtGui, viewport)
                elif layer == "terrain":
                    if self.layers.get("terrain", False):
                        self._draw_terrain(painter, QtCore, QtGui, viewport)
                elif layer == "surface":
                    if self.layers.get("surface", True) or self.layers.get("runways", True):
                        self._draw_surface(painter, QtCore, QtGui, viewport, surface_only=True)
                elif layer == "grid":
                    self._draw_grid(painter, QtCore, QtGui, viewport)
                elif layer == "runways":
                    if self.layers.get("surface", True) or self.layers.get("runways", True):
                        self._draw_surface(painter, QtCore, QtGui, viewport, runway_only=True)
                elif layer == "procedures":
                    if self.layers.get("procedures", False):
                        self._draw_procedures(painter, QtCore, QtGui, viewport)

            def _draw_dynamic_layers(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                for layer in DYNAMIC_RADAR_LAYER_ORDER:
                    if layer == "track_ghosts":
                        self._draw_track_ghosts(painter, QtCore, QtGui, viewport)
                    elif layer == "sweep":
                        self._draw_sweep(painter, QtCore, QtGui, viewport)
                    elif layer == "blips":
                        self._draw_blips(painter, QtCore, QtGui, viewport)
                    elif layer == "hover":
                        self._draw_hover(painter, QtCore, QtGui, viewport)

            def _draw_background(self, painter: Any, QtGui: Any, rect: Any, viewport: RadarViewport) -> None:
                painter.fillRect(rect, QtGui.QColor(self.colors["panel_2"]))
                bg = QtGui.QColor(self.colors["panel_2"])
                painter.setBrush(bg)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), viewport.radius, viewport.radius)

            def _radar_color(self, QtGui: Any, role: str, alpha: int = 255) -> Any:
                palette = {
                    "grid": self.colors["blue"],
                    "grid_label": self.colors["muted"],
                    "blip": self.colors["cyan"],
                    "blip_text": self.colors["text"],
                    "departure": self.colors["blue"],
                    "approach": self.colors["green"],
                    "ground": self.colors["amber"],
                    "stale": self.colors["muted"],
                    "runway": self.colors["amber"],
                    "runway_glow": self.colors["amber"],
                    "taxiway": self.colors["blue"],
                    "surface": self.colors["dim"],
                    "terminal": self.colors["amber"],
                    "map_water": self.colors["blue"],
                    "map_park": self.colors["green"],
                    "map_land": self.colors["muted"],
                    "map_road": self.colors["text"],
                    "map_rail": self.colors["dim"],
                    "map_coast": self.colors["cyan"],
                    "terrain": self.colors["amber"],
                    "hover": self.colors["amber"],
                }
                color = QtGui.QColor(palette.get(role, self.colors.get("text", "#ffffff")))
                color.setAlpha(max(0, min(255, int(alpha))))
                return color

            def _is_light_mode(self) -> bool:
                if self._theme == "light":
                    return True
                color = self.colors.get("panel_2") or "#000000"
                try:
                    raw = color.lstrip("#")
                    if len(raw) >= 6:
                        r = int(raw[0:2], 16)
                        g = int(raw[2:4], 16)
                        b = int(raw[4:6], 16)
                        return (0.2126 * r + 0.7152 * g + 0.0722 * b) > 150
                except Exception:
                    return False
                return False

            def _draw_grid(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                painter.setBrush(QtCore.Qt.NoBrush)
                grid = self._radar_color(QtGui, "grid", 110 if viewport.radius_nm >= 20 else 145)
                painter.setPen(QtGui.QPen(grid, 1))
                ring_values = self._ring_values(viewport.radius_nm)
                label_values = set(ring_values)
                if viewport.radius_nm >= 40:
                    label_values = {20.0, 40.0}
                elif viewport.radius_nm >= 20:
                    label_values = {5.0, 10.0, 20.0}
                for ring_nm in ring_values:
                    frac = ring_nm / viewport.radius_nm
                    r = viewport.radius * frac
                    painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), r, r)
                    if ring_nm in label_values:
                        label_color = self._radar_color(QtGui, "grid_label", 150 if viewport.radius_nm >= 20 else 190)
                        painter.setPen(label_color)
                        painter.drawText(int(viewport.cx + r + 5), int(viewport.cy - 4), f"{ring_nm:g}nm")
                        painter.setPen(QtGui.QPen(grid, 1))
                painter.drawLine(viewport.cx - viewport.radius, viewport.cy, viewport.cx + viewport.radius, viewport.cy)
                painter.drawLine(viewport.cx, viewport.cy - viewport.radius, viewport.cx, viewport.cy + viewport.radius)
                painter.setPen(self._radar_color(QtGui, "grid_label", 185))
                painter.drawText(int(viewport.cx - 4), int(viewport.cy - viewport.radius + 18), "N")
                painter.drawText(int(viewport.cx + viewport.radius - 18), int(viewport.cy + 4), "E")
                painter.drawText(int(viewport.cx - 4), int(viewport.cy + viewport.radius - 8), "S")
                painter.drawText(int(viewport.cx - viewport.radius + 8), int(viewport.cy + 4), "W")
                center = self._radar_color(QtGui, "grid_label", 160)
                painter.setPen(QtGui.QPen(center, 1))
                painter.setBrush(center)
                painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), 3.5, 3.5)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), 8, 8)

            def _draw_blips(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                label_candidates: list[tuple[dict[str, Any], tuple[float, float], int, bool]] = []
                for blip in self.blips:
                    if not self._blip_in_range(blip, viewport):
                        continue
                    pos = self._blip_pos(blip, viewport)
                    alpha = self._blip_alpha(blip)
                    identity = self._blip_identity(blip)
                    is_focused = identity in {self._hover_key, self._selected_key}
                    if alpha <= 4 and not is_focused:
                        continue
                    if is_focused:
                        alpha = max(alpha, 220)
                    flash = angular_age(self.sweep_angle, self._blip_angle(blip)) <= RADAR_FLASH_DEGREES
                    role = target_tone_role(blip)
                    color_role = {
                        "departure": "departure",
                        "approach": "approach",
                        "ground": "ground",
                        "stale": "stale",
                    }.get(role, "blip")
                    if flash:
                        bloom = self._radar_color(QtGui, color_role, 58)
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(bloom)
                        painter.drawEllipse(QtCore.QPointF(pos[0], pos[1]), 13, 13)
                    color = self._radar_color(QtGui, color_role, alpha)
                    painter.setPen(QtGui.QPen(color, 2.2))
                    shape = target_shape(blip)
                    size = 5.2 if flash else 4.4
                    if shape == "diamond":
                        painter.setBrush(color)
                        painter.drawPolygon(
                            QtGui.QPolygonF(
                                [
                                    QtCore.QPointF(pos[0], pos[1] - size),
                                    QtCore.QPointF(pos[0] + size, pos[1]),
                                    QtCore.QPointF(pos[0], pos[1] + size),
                                    QtCore.QPointF(pos[0] - size, pos[1]),
                                ]
                            )
                        )
                    elif shape == "hollow":
                        painter.setBrush(QtCore.Qt.NoBrush)
                        painter.drawEllipse(QtCore.QPointF(pos[0], pos[1]), size, size)
                    else:
                        painter.setBrush(color)
                        painter.drawEllipse(QtCore.QPointF(pos[0], pos[1]), size, size)
                    callsign = str(blip.get("callsign") or "").strip()
                    if callsign and self._should_draw_callsign(blip, viewport):
                        label_candidates.append((blip, pos, alpha, is_focused))
                    self._draw_direction_indicator(painter, QtCore, QtGui, blip, pos, viewport, alpha)
                    painter.setBrush(QtCore.Qt.NoBrush)

                occupied: list[Any] = []
                label_candidates.sort(key=lambda item: label_priority(item[0], focused=item[3]), reverse=True)
                metrics = painter.fontMetrics()
                for blip, pos, alpha, is_focused in label_candidates:
                    callsign = str(blip.get("callsign") or blip.get("flight_number") or "").strip().upper()[:10]
                    if not callsign:
                        continue
                    status_label = self._blip_status_label(blip) if self.layers.get("traffic_status", True) and viewport.radius_nm <= 20 else ""
                    width = max(metrics.horizontalAdvance(callsign), metrics.horizontalAdvance(status_label) if status_label else 0) + 8
                    height = metrics.height() * (2 if status_label else 1) + 4
                    rect = QtCore.QRectF(pos[0] + 7, pos[1] - metrics.height(), width, height)
                    if not is_focused and any(rect.intersects(existing) for existing in occupied):
                        continue
                    occupied.append(rect)
                    painter.setPen(self._radar_color(QtGui, "blip_text", max(80, alpha)))
                    painter.drawText(int(pos[0] + 8), int(pos[1] - 6), callsign)
                    if status_label:
                        status_color = self._status_color(QtGui, status_label)
                        status_color.setAlpha(max(70, min(255, alpha)))
                        painter.setPen(status_color)
                        painter.drawText(int(pos[0] + 8), int(pos[1] + metrics.height() - 5), status_label[:12])

            def _draw_track_ghosts(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                painter.save()
                for blip in self.blips:
                    key = self._blip_identity(blip)
                    history = self.track_history.get(key) or []
                    if len(history) < 2:
                        continue
                    ghost_points = history[:-1][-3:]
                    for idx, (lat, lon) in enumerate(ghost_points):
                        try:
                            x_nm, y_nm = viewport.latlon_to_nm(lat, lon)
                        except (TypeError, ValueError):
                            continue
                        if math.hypot(x_nm, y_nm) > viewport.radius_nm:
                            continue
                        x, y = viewport.nm_to_canvas(x_nm, y_nm)
                        alpha = max(26, 78 - (len(ghost_points) - idx - 1) * 18)
                        color = self._radar_color(QtGui, "blip", alpha)
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(color)
                        size = 3.6 + idx * 0.6
                        painter.drawEllipse(QtCore.QPointF(x, y), size, size)
                    if len(history) >= 2:
                        projected = []
                        for lat, lon in history[-4:]:
                            x_nm, y_nm = viewport.latlon_to_nm(lat, lon)
                            if math.hypot(x_nm, y_nm) <= viewport.radius_nm:
                                x, y = viewport.nm_to_canvas(x_nm, y_nm)
                                projected.append(QtCore.QPointF(x, y))
                        if len(projected) >= 2:
                            line = self._radar_color(QtGui, "blip", 58)
                            painter.setPen(QtGui.QPen(line, 1))
                            for idx in range(1, len(projected)):
                                painter.drawLine(projected[idx - 1], projected[idx])
                painter.restore()

            def _draw_direction_indicator(self, painter: Any, QtCore: Any, QtGui: Any, blip: dict[str, Any], pos: tuple[float, float], viewport: RadarViewport, alpha: int = 175) -> None:
                heading = self._direction_heading(blip)
                speed = _safe_float(blip.get("speed_kt"))
                if speed is None:
                    speed_ms = _safe_float(blip.get("speed_ms"))
                    speed = speed_ms * 1.94384 if speed_ms is not None else None
                if heading is None or (speed is not None and speed <= 8):
                    return
                length = 17 if viewport.radius_nm <= 20 else 12
                hr = math.radians(float(heading) - 90.0)
                tip = QtCore.QPointF(pos[0] + math.cos(hr) * length, pos[1] + math.sin(hr) * length)
                tail = QtCore.QPointF(pos[0] + math.cos(hr) * 5, pos[1] + math.sin(hr) * 5)
                role = target_tone_role(blip)
                color_role = {"departure": "departure", "approach": "approach", "ground": "ground", "stale": "stale"}.get(role, "blip")
                color = self._radar_color(QtGui, color_role, max(55, min(205, alpha)))
                painter.setPen(QtGui.QPen(color, 1.4))
                painter.drawLine(tail, tip)
                wing = 4.5
                left = QtCore.QPointF(tip.x() - math.cos(hr - 0.75) * wing, tip.y() - math.sin(hr - 0.75) * wing)
                right = QtCore.QPointF(tip.x() - math.cos(hr + 0.75) * wing, tip.y() - math.sin(hr + 0.75) * wing)
                painter.drawLine(tip, left)
                painter.drawLine(tip, right)

            def _draw_hover(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if self._selected_key:
                    selected = next((blip for blip in self.blips if self._blip_identity(blip) == self._selected_key), None)
                    if selected:
                        sx, sy = self._blip_pos(selected, viewport)
                        halo = self._radar_color(QtGui, "hover", 190)
                        painter.setPen(QtGui.QPen(halo, 1.6))
                        painter.setBrush(QtCore.Qt.NoBrush)
                        painter.drawEllipse(QtCore.QPointF(sx, sy), 11, 11)
                if self.hovered_blip:
                    hx, hy = self._blip_pos(self.hovered_blip, viewport)
                    halo = self._radar_color(QtGui, "hover", 220)
                    painter.setPen(QtGui.QPen(halo, 2))
                    painter.setBrush(QtCore.Qt.NoBrush)
                    painter.drawEllipse(QtCore.QPointF(hx, hy), 11, 11)
                    self._draw_hover_popup(painter, QtCore, QtGui, viewport, hx, hy)

            def _draw_hover_popup(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport, hx: float, hy: float) -> None:
                if not self.hovered_blip:
                    return
                lines = self._hover_popup_lines(self.hovered_blip)
                if not lines:
                    return
                metrics = painter.fontMetrics()
                width = min(210, max(metrics.horizontalAdvance(line) for line in lines) + 18)
                height = len(lines) * (metrics.height() + 1) + 12
                x = hx + 14
                y = hy - height - 12
                if x + width > viewport.width - 10:
                    x = hx - width - 14
                if y < 10:
                    y = hy + 16
                rect = QtCore.QRectF(x, y, width, height)
                panel = QtGui.QColor(self.colors["panel"])
                panel.setAlpha(235)
                border = self._radar_color(QtGui, "grid", 210)
                painter.setPen(QtGui.QPen(border, 1))
                painter.setBrush(panel)
                painter.drawRoundedRect(rect, 6, 6)
                painter.setPen(self._radar_color(QtGui, "blip_text", 255))
                cursor_y = y + 8 + metrics.ascent()
                for idx, line in enumerate(lines):
                    if idx:
                        painter.setPen(self._radar_color(QtGui, "grid_label", 210))
                    painter.drawText(QtCore.QPointF(x + 9, cursor_y), line)
                    cursor_y += metrics.height() + 1

            def _draw_footer(self, painter: Any, QtGui: Any, rect: Any) -> None:
                painter.setPen(self._radar_color(QtGui, "grid_label", 190))
                painter.drawText(14, rect.height() - 14, self.status)
                if self.attribution and (self.layers.get("surface", True) or self.layers.get("runways", True)):
                    painter.drawText(rect.width() - 320, rect.height() - 14, self.attribution[:48])

            def _ring_values(self, radius_nm: float) -> tuple[float, ...]:
                radius = float(radius_nm or 1.0)
                if radius <= 1:
                    return (0.25, 0.5, 0.75, 1.0)
                if radius <= 2:
                    return (0.5, 1.0, 1.5, 2.0)
                if radius <= 3:
                    return (1.0, 2.0, 3.0)
                if radius <= 5:
                    return (1.0, 2.0, 3.0, 4.0, 5.0)
                if radius <= 10:
                    return (2.0, 5.0, 10.0)
                if radius <= 20:
                    return (5.0, 10.0, 20.0)
                return (10.0, 20.0, 40.0)

            def _hit_blip(self, x_pos: float, y_pos: float, viewport: RadarViewport) -> dict[str, Any] | None:
                hit_radius = 11.0
                for blip in self.blips:
                    if not self._blip_in_range(blip, viewport):
                        continue
                    identity = self._blip_identity(blip)
                    focused = identity in {self._hover_key, self._selected_key}
                    if not target_is_interactive(self._blip_angle(blip), self.sweep_angle, focused=focused):
                        continue
                    x, y = self._blip_pos(blip, viewport)
                    if math.hypot(x_pos - x, y_pos - y) <= hit_radius:
                        return blip
                    callsign = str(blip.get("callsign") or "").strip()
                    if callsign and self._should_draw_callsign(blip, viewport):
                        label_width = min(86.0, 7.5 * len(callsign[:10]) + 12.0)
                        if x + 6 <= x_pos <= x + 8 + label_width and y - 22 <= y_pos <= y + 4:
                            return blip
                return None

            def _set_hover_blip(self, blip: dict[str, Any] | None) -> None:
                key = self._blip_identity(blip)
                if key == self._hover_key:
                    return
                self._hover_key = key
                self.hovered_blip = dict(blip) if isinstance(blip, dict) else None
                self.hoverChanged.emit(self.hovered_blip)
                self.update()

            def _blip_identity(self, blip: dict[str, Any] | None) -> str:
                if not isinstance(blip, dict):
                    return ""
                for key in ("callsign", "icao24", "hex"):
                    value = str(blip.get(key) or "").strip().upper()
                    if value:
                        return value
                return f"{blip.get('lat')}:{blip.get('lon')}"

            def _update_track_history(self, blips: list[dict[str, Any]]) -> None:
                seen: set[str] = set()
                for blip in blips:
                    key = self._blip_identity(blip)
                    if not key:
                        continue
                    lat = _safe_float(blip.get("lat"))
                    lon = _safe_float(blip.get("lon"))
                    if lat is None or lon is None:
                        continue
                    seen.add(key)
                    history = self.track_history.setdefault(key, [])
                    if not history or abs(history[-1][0] - lat) > 0.00001 or abs(history[-1][1] - lon) > 0.00001:
                        history.append((lat, lon))
                    self.track_history[key] = history[-self._max_track_points :]
                    self._track_absent_counts[key] = 0
                for key in list(self.track_history.keys()):
                    if key in seen:
                        continue
                    self._track_absent_counts[key] = self._track_absent_counts.get(key, 0) + 1
                    if self._track_absent_counts[key] >= 3:
                        self.track_history.pop(key, None)
                        self._track_absent_counts.pop(key, None)

            def _direction_heading(self, blip: dict[str, Any]) -> float | None:
                for key in ("track_deg", "heading", "nav_heading"):
                    value = _safe_float(blip.get(key))
                    if value is not None:
                        return value % 360.0
                identity = self._blip_identity(blip)
                history = self.track_history.get(identity) or []
                if len(history) < 2:
                    return None
                lat1, lon1 = history[-2]
                lat2, lon2 = history[-1]
                y_nm = (lat2 - lat1) * 60.0
                x_nm = (lon2 - lon1) * 60.0 * math.cos(math.radians((lat1 + lat2) / 2.0))
                if abs(x_nm) < 0.000001 and abs(y_nm) < 0.000001:
                    return None
                return (math.degrees(math.atan2(x_nm, y_nm)) + 360.0) % 360.0

            def _blip_status_label(self, blip: dict[str, Any]) -> str:
                label = str(blip.get("radar_status_label") or "").strip()
                if label:
                    return label
                return radar_phase_label(blip)

            def _status_color(self, QtGui: Any, status_label: str) -> Any:
                clean = status_label.lower()
                if "final" in clean or "approach" in clean:
                    return self._radar_color(QtGui, "approach", 230)
                if "ground" in clean or "taxi" in clean:
                    return self._radar_color(QtGui, "ground", 230)
                if "descend" in clean or "descent" in clean:
                    return self._radar_color(QtGui, "blip", 230)
                if "depart" in clean or "climb" in clean:
                    return self._radar_color(QtGui, "departure", 230)
                return self._radar_color(QtGui, "grid_label", 210)

            def _should_draw_callsign(self, blip: dict[str, Any], viewport: RadarViewport) -> bool:
                if self._blip_identity(blip) in {self._hover_key, self._selected_key}:
                    return True
                phase = str(blip.get("radar_phase") or blip.get("radar_status") or "").strip().lower().replace("-", "_")
                if viewport.radius_nm <= 10:
                    return len(self.blips) <= 55 or phase in {"approach", "final", "departing", "descending"}
                if viewport.radius_nm <= 20:
                    return len(self.blips) <= 35 or phase in {"approach", "final", "departing", "descending"}
                return len(self.blips) <= 12 and phase in {"approach", "final", "departing", "descending"} and not bool(blip.get("on_ground"))

            def _tooltip_for_blip(self, blip: dict[str, Any]) -> str:
                callsign = str(blip.get("callsign") or blip.get("hex") or "aircraft").strip()
                route = " -> ".join(str(v) for v in (blip.get("departure_icao"), blip.get("arrival_icao")) if v)
                details = [callsign]
                if route:
                    details.append(route)
                aircraft = blip.get("aircraft_type") or blip.get("type")
                if aircraft:
                    details.append(str(aircraft))
                status_label = self._blip_status_label(blip)
                if status_label:
                    details.append(status_label)
                altitude = self._tooltip_altitude_ft(blip.get("altitude_ft")) if blip.get("altitude_ft") is not None else self._tooltip_altitude(blip.get("altitude_m"))
                speed = self._tooltip_speed_kt(blip.get("speed_kt")) if blip.get("speed_kt") is not None else self._tooltip_speed(blip.get("speed_ms"))
                if altitude:
                    details.append(altitude)
                if speed:
                    details.append(speed)
                if blip.get("heading") is not None:
                    try:
                        details.append(f"HDG {int(round(float(blip.get('heading')))) % 360}")
                    except (TypeError, ValueError):
                        pass
                if blip.get("distance_nm") is not None:
                    details.append(f"{format_value(blip.get('distance_nm'))}nm")
                if blip.get("matched_runway") or blip.get("nearest_runway"):
                    details.append(f"RWY {blip.get('matched_runway') or blip.get('nearest_runway')}")
                if blip.get("phase_confidence"):
                    details.append(f"{str(blip.get('phase_confidence')).title()} confidence")
                if str(blip.get("source") or "").lower() == "vatsim":
                    if blip.get("flight_rules"):
                        details.append(f"Rules {blip.get('flight_rules')}")
                    if blip.get("planned_altitude"):
                        details.append(f"Planned alt {blip.get('planned_altitude')}")
                    if blip.get("cruise_tas"):
                        details.append(f"TAS {blip.get('cruise_tas')}")
                    if blip.get("route"):
                        details.append(str(blip.get("route"))[:80])
                source = blip.get("source")
                if source:
                    details.append(str(source))
                return " | ".join(details)

            def _hover_popup_lines(self, blip: dict[str, Any]) -> list[str]:
                callsign = str(blip.get("callsign") or blip.get("flight_number") or blip.get("hex") or "Aircraft").strip().upper()
                aircraft = str(blip.get("aircraft_type") or blip.get("type") or "").strip().upper()
                route = " -> ".join(str(v).strip().upper() for v in (blip.get("departure_icao"), blip.get("arrival_icao")) if str(v or "").strip())
                altitude = self._tooltip_altitude_ft(blip.get("altitude_ft")) if blip.get("altitude_ft") is not None else self._tooltip_altitude(blip.get("altitude_m"))
                speed = self._tooltip_speed_kt(blip.get("speed_kt")) if blip.get("speed_kt") is not None else self._tooltip_speed(blip.get("speed_ms"))
                status = self._blip_status_label(blip)
                confidence = str(blip.get("phase_confidence") or "").strip().upper()
                vertical = ""
                vertical_value = _safe_float(blip.get("vertical_rate_fpm"))
                if vertical_value is not None:
                    vertical = f"{vertical_value:+.0f} fpm"
                distance = ""
                distance_value = _safe_float(blip.get("distance_nm"))
                if distance_value is not None:
                    distance = f"{distance_value:.1f} nm"
                heading = self._direction_heading(blip)
                bearing = f"HDG {heading:03.0f}" if heading is not None else ""
                return [
                    line
                    for line in (
                        " | ".join(part for part in (callsign, aircraft) if part),
                        route,
                        " | ".join(part for part in (status, confidence) if part),
                        " | ".join(part for part in (altitude, speed, vertical) if part),
                        " | ".join(part for part in (distance, bearing) if part),
                    )
                    if line
                ][:5]

            def _tooltip_altitude(self, value: Any) -> str:
                try:
                    meters = float(value)
                except (TypeError, ValueError):
                    return ""
                return f"{int(round(meters * 3.28084))} ft"

            def _tooltip_altitude_ft(self, value: Any) -> str:
                try:
                    feet = float(value)
                except (TypeError, ValueError):
                    return ""
                return f"{int(round(feet))} ft"

            def _tooltip_speed(self, value: Any) -> str:
                try:
                    meters_s = float(value)
                except (TypeError, ValueError):
                    return ""
                return f"{int(round(meters_s * 1.94384))} kt"

            def _tooltip_speed_kt(self, value: Any) -> str:
                try:
                    knots = float(value)
                except (TypeError, ValueError):
                    return ""
                return f"{int(round(knots))} kt"

            def _blip_in_range(self, blip: dict[str, Any], viewport: RadarViewport) -> bool:
                if blip.get("lat") is not None and blip.get("lon") is not None:
                    try:
                        x_nm, y_nm = viewport.latlon_to_nm(float(blip["lat"]), float(blip["lon"]))
                    except (TypeError, ValueError):
                        return False
                    return math.hypot(x_nm, y_nm) <= viewport.radius_nm
                return True

            def _blip_pos(self, blip: dict[str, Any], viewport: RadarViewport) -> tuple[float, float]:
                if blip.get("lat") is not None and blip.get("lon") is not None:
                    x_nm, y_nm = viewport.latlon_to_nm(float(blip["lat"]), float(blip["lon"]))
                    return viewport.nm_to_canvas(x_nm, y_nm)
                dist = float(blip.get("distance_nm") or 0.0)
                bearing = math.radians(float(blip.get("bearing_deg") or 0.0))
                frac = min(1.0, dist / viewport.radius_nm)
                return viewport.cx + math.sin(bearing) * viewport.radius * frac, viewport.cy - math.cos(bearing) * viewport.radius * frac

            def _blip_angle(self, blip: dict[str, Any]) -> float:
                if blip.get("lat") is not None and blip.get("lon") is not None:
                    x_nm, y_nm = self._latlon_to_nm(float(blip["lat"]), float(blip["lon"]))
                    return bearing_from_offset(x_nm, y_nm)
                return float(blip.get("bearing_deg") or 0.0) % 360.0

            def _blip_alpha(self, blip: dict[str, Any]) -> int:
                identity = self._blip_identity(blip)
                focused = identity in {self._hover_key, self._selected_key}
                return int(round(255 * blip_opacity(self._blip_angle(blip), self.sweep_angle, focused=focused)))

            def _draw_sweep(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                painter.save()
                painter.translate(viewport.cx, viewport.cy)
                painter.rotate(self.sweep_angle)

                if not self._is_light_mode():
                    painter.setCompositionMode(QtGui.QPainter.CompositionMode_Screen)
                slice_count = 18
                slice_deg = RADAR_TRAIL_DEGREES / slice_count
                for idx in range(slice_count):
                    color = self._radar_color(
                        QtGui,
                        "blip",
                        max(0, int((1 - idx / slice_count) * (26 if self._is_light_mode() else 34))),
                    )
                    painter.setBrush(color)
                    painter.setPen(QtCore.Qt.NoPen)
                    path = QtGui.QPainterPath()
                    path.moveTo(0, 0)
                    path.arcTo(
                        -viewport.radius,
                        -viewport.radius,
                        viewport.radius * 2,
                        viewport.radius * 2,
                        90 + idx * slice_deg,
                        slice_deg,
                    )
                    path.closeSubpath()
                    painter.drawPath(path)
                painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)

                line = self._radar_color(QtGui, "blip", 145 if self._is_light_mode() else 120)
                painter.setBrush(QtCore.Qt.NoBrush)
                lead_pen = QtGui.QPen(line, 1.4)
                lead_pen.setCapStyle(QtCore.Qt.RoundCap)
                painter.setPen(lead_pen)
                painter.drawLine(0, 0, 0, -viewport.radius)
                painter.restore()

            def _draw_map_inlay(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if not self.map_features:
                    return
                colors = {
                    "water": self._radar_color(QtGui, "map_water", 115),
                    "park": self._radar_color(QtGui, "map_park", 86),
                    "landuse": self._radar_color(QtGui, "map_land", 72),
                    "road": self._radar_color(QtGui, "map_road", 175),
                    "rail": self._radar_color(QtGui, "map_rail", 160),
                    "boundary": self._radar_color(QtGui, "map_water", 90),
                    "coastline": self._radar_color(QtGui, "map_coast", 190),
                }
                widths = {
                    "water": 1.2,
                    "park": 1.0,
                    "landuse": 0.9,
                    "road": 2.4 if viewport.radius_nm <= 20 else 1.6,
                    "rail": 2.0 if viewport.radius_nm <= 20 else 1.3,
                    "coastline": 2.8 if viewport.radius_nm <= 20 else 1.8,
                }
                painter.save()
                for kind, _label, poly, closed, feature in self._projected_map(QtCore, viewport):
                    if len(poly) < 2:
                        continue
                    color = colors.get(kind, colors["landuse"])
                    width = widths.get(kind, 1.0)
                    if kind == "road":
                        road_class = str(feature.get("road_class") or "").lower()
                        width = 1.45 if road_class in {"motorway", "trunk", "primary"} else 0.8
                        color.setAlpha(min(color.alpha(), 125 if road_class in {"motorway", "trunk", "primary"} else 75))
                    pen = QtGui.QPen(color, width)
                    if kind == "rail":
                        pen.setDashPattern([4, 5])
                    painter.setPen(pen)
                    if closed and len(poly) >= 3 and kind in {"water", "park", "landuse"}:
                        fill = QtGui.QColor(color)
                        fill.setAlpha(max(34, int(color.alpha() * 0.58)))
                        painter.setBrush(fill)
                        painter.drawPolygon(poly)
                        painter.setBrush(QtCore.Qt.NoBrush)
                        if kind in {"water", "park"}:
                            painter.drawPolygon(poly)
                    else:
                        for idx in range(1, len(poly)):
                            painter.drawLine(poly[idx - 1], poly[idx])
                    if self._feature_pixel_span(poly) < 5.0:
                        self._draw_map_micro_marker(painter, QtCore, QtGui, poly, color, kind, viewport)
                painter.restore()

            def _feature_pixel_span(self, poly: list[Any]) -> float:
                if not poly:
                    return 0.0
                min_x = min(point.x() for point in poly)
                max_x = max(point.x() for point in poly)
                min_y = min(point.y() for point in poly)
                max_y = max(point.y() for point in poly)
                return max(max_x - min_x, max_y - min_y)

            def _draw_map_micro_marker(self, painter: Any, QtCore: Any, QtGui: Any, poly: list[Any], color: Any, kind: str, viewport: RadarViewport) -> None:
                if viewport.radius_nm > 20 or not poly:
                    return
                cx = sum(point.x() for point in poly) / len(poly)
                cy = sum(point.y() for point in poly) / len(poly)
                marker = QtGui.QColor(color)
                marker.setAlpha(max(marker.alpha(), 150))
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(marker)
                size = 2.3 if kind in {"road", "rail", "coastline"} else 1.7
                painter.drawEllipse(QtCore.QPointF(cx, cy), size, size)
                painter.setBrush(QtCore.Qt.NoBrush)

            def _draw_terrain(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if not self.terrain_features:
                    return
                painter.save()
                base = self._radar_color(QtGui, "terrain", 255)
                for kind, _label, poly, _closed, feature in self._projected_terrain(QtCore, viewport):
                    if kind == "terrain_band" and len(poly) >= 3:
                        band_index = max(0, min(4, int(feature.get("band_index") or 0)))
                        fill = QtGui.QColor(base)
                        fill.setAlpha(12 + band_index * 9)
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(fill)
                        painter.drawPolygon(poly)
                    elif kind == "contour" and len(poly) >= 2:
                        contour = QtGui.QColor(base)
                        contour.setAlpha(110 if viewport.radius_nm <= 20 else 80)
                        painter.setPen(QtGui.QPen(contour, 1.05 if viewport.radius_nm <= 20 else 0.8))
                        painter.setBrush(QtCore.Qt.NoBrush)
                        for idx in range(1, len(poly)):
                            painter.drawLine(poly[idx - 1], poly[idx])
                painter.restore()

            def _draw_procedures(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if not self.procedure_paths:
                    return
                colors = {
                    "approach": self._radar_color(QtGui, "terrain", 185),
                    "departure": self._radar_color(QtGui, "blip", 185),
                    "transition": self._radar_color(QtGui, "grid", 165),
                }
                painter.save()
                for kind, label_text, poly in self._projected_procedures(QtCore, viewport):
                    if len(poly) < 2:
                        continue
                    pen = QtGui.QPen(colors.get(kind, colors["transition"]), 1.4)
                    pen.setStyle(QtCore.Qt.DashLine)
                    painter.setPen(pen)
                    for idx in range(1, len(poly)):
                        painter.drawLine(poly[idx - 1], poly[idx])
                    if label_text and viewport.radius_nm <= 20:
                        painter.setPen(self._radar_color(QtGui, "grid_label", 220))
                        painter.drawText(poly[-1], label_text[:18])
                painter.restore()

            def _draw_surface(
                self,
                painter: Any,
                QtCore: Any,
                QtGui: Any,
                viewport: RadarViewport,
                *,
                runway_only: bool = False,
                surface_only: bool = False,
            ) -> None:
                if not self.surface:
                    return
                colors = {
                    "boundary": self._radar_color(QtGui, "surface", 120),
                    "runway": self._radar_color(QtGui, "runway", 250),
                    "taxiway": self._radar_color(QtGui, "taxiway", 135),
                    "apron": self._radar_color(QtGui, "surface", 54),
                    "terminal": self._radar_color(QtGui, "terminal", 88),
                    "building": self._radar_color(QtGui, "terminal", 102),
                }
                painter.save()
                painter.setOpacity(self._surface_alpha())
                for kind, runway_label, poly, closed, feature in self._projected_surface(QtCore, viewport):
                    if len(poly) < 2:
                        continue
                    if runway_only and kind != "runway":
                        continue
                    if surface_only and kind == "runway":
                        continue
                    if kind == "runway" and not self.layers.get("runways", True):
                        continue
                    if kind != "runway" and not self.layers.get("surface", True):
                        continue
                    if kind == "runway":
                        self._draw_runway_backdrop(painter, QtCore, QtGui, feature, poly, viewport)
                    pen_width = self._runway_pen_width(feature, viewport) if kind == "runway" else 1
                    pen = QtGui.QPen(colors.get(kind, colors["taxiway"]), pen_width)
                    if kind == "runway" and str(feature.get("confidence") or "").lower() == "estimated":
                        pen.setStyle(QtCore.Qt.DashLine)
                    if kind == "runway" and feature.get("closed"):
                        closed_color = QtGui.QColor("#ff4d4d" if not self._is_light_mode() else "#9d1f1f")
                        closed_color.setAlpha(185)
                        pen.setColor(closed_color)
                    if kind == "boundary":
                        pen.setDashPattern([6, 8])
                    painter.setPen(pen)
                    if kind in {"apron", "terminal", "building"} and closed and len(poly) >= 3:
                        painter.setBrush(colors.get(kind, colors["apron"]))
                        painter.drawPolygon(poly)
                        painter.setBrush(QtCore.Qt.NoBrush)
                    else:
                        for idx in range(1, len(poly)):
                            painter.drawLine(poly[idx - 1], poly[idx])
                    if kind == "runway" and closed and len(poly) >= 3:
                        fill = self._radar_color(QtGui, "runway", 42)
                        painter.setBrush(fill)
                        painter.drawPolygon(poly)
                        painter.setBrush(QtCore.Qt.NoBrush)
                    if kind == "runway" and runway_label and len(poly) >= 2 and viewport.radius_nm <= 3:
                        self._draw_runway_label(painter, QtGui, runway_label, poly)
                    if kind == "runway" and len(poly) >= 2 and viewport.radius_nm <= 20:
                        self._draw_runway_thresholds(painter, QtCore, QtGui, feature, poly, viewport)
                painter.restore()

            def _runway_pen_width(self, feature: dict[str, Any], viewport: RadarViewport) -> float:
                width_ft = _safe_float(feature.get("width_ft"))
                if width_ft is None:
                    return 4.2 if viewport.radius_nm <= 5 else 3.4 if viewport.radius_nm <= 10 else 2.6
                width_nm = max(0.01, width_ft / 6076.12)
                pixels = width_nm * (viewport.radius / max(0.1, viewport.radius_nm))
                floor = 4.0 if viewport.radius_nm <= 5 else 3.0 if viewport.radius_nm <= 10 else 2.2
                return max(floor, min(9.0, pixels))

            def _draw_runway_backdrop(self, painter: Any, QtCore: Any, QtGui: Any, feature: dict[str, Any], poly: list[Any], viewport: RadarViewport) -> None:
                if len(poly) < 2:
                    return
                confidence = str(feature.get("confidence") or "").strip().lower()
                glow = self._radar_color(QtGui, "runway_glow", 92 if confidence in {"ourairports", "ourairports+osm"} else 52)
                width = self._runway_pen_width(feature, viewport) + (5.5 if viewport.radius_nm <= 5 else 3.5)
                painter.save()
                painter.setPen(QtGui.QPen(glow, width, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
                for idx in range(1, len(poly)):
                    painter.drawLine(poly[idx - 1], poly[idx])
                painter.restore()

            def _draw_runway_label(self, painter: Any, QtGui: Any, label_text: str, poly: list[Any]) -> None:
                p1 = poly[0]
                p2 = poly[-1]
                x = (p1.x() + p2.x()) / 2
                y = (p1.y() + p2.y()) / 2
                painter.save()
                painter.translate(x, y)
                painter.rotate(math.degrees(math.atan2(p2.y() - p1.y(), p2.x() - p1.x())))
                painter.setPen(self._radar_color(QtGui, "runway", 255))
                painter.drawText(-32, -8, str(label_text)[:12])
                painter.restore()

            def _draw_runway_thresholds(self, painter: Any, QtCore: Any, QtGui: Any, feature: dict[str, Any], poly: list[Any], viewport: RadarViewport) -> None:
                p1 = poly[0]
                p2 = poly[-1]
                dx = p2.x() - p1.x()
                dy = p2.y() - p1.y()
                length = math.hypot(dx, dy)
                if length < 4:
                    return
                nx = -dy / length
                ny = dx / length
                tick = 7 if viewport.radius_nm <= 10 else 5
                endpoints = feature.get("endpoints") if isinstance(feature.get("endpoints"), list) else []
                end_labels = [str(endpoint.get("ident") or "").strip() for endpoint in endpoints[:2]]
                if len(end_labels) < 2:
                    label = str(feature.get("label") or "")
                    parts = [part.strip() for part in label.replace("-", "/").split("/") if part.strip()]
                    end_labels = (parts + ["", ""])[:2]
                painter.save()
                threshold_pen = QtGui.QPen(self._radar_color(QtGui, "runway", 255), 1.2)
                painter.setPen(threshold_pen)
                for point, text, sign in ((p1, end_labels[0], -1), (p2, end_labels[1], 1)):
                    painter.drawLine(
                        QtCore.QPointF(point.x() - nx * tick, point.y() - ny * tick),
                        QtCore.QPointF(point.x() + nx * tick, point.y() + ny * tick),
                    )
                    if text and viewport.radius_nm <= 3:
                        painter.drawText(QtCore.QPointF(point.x() + nx * tick * sign, point.y() + ny * tick * sign), text[:4])
                painter.restore()

            def _surface_alpha(self) -> float:
                if self.radius_nm <= 5:
                    return 1.0
                if self.radius_nm <= 10:
                    return 0.78
                if self.radius_nm <= 20:
                    return 0.55
                if self.radius_nm <= 40:
                    return 0.28
                return 0.1

            def _projected_surface(self, QtCore: Any, viewport: RadarViewport) -> list[tuple[str, str, list[Any], bool, dict[str, Any]]]:
                key = (
                    self._surface_version,
                    self._projection_key(viewport),
                )
                if key == self._surface_projection_key:
                    return self._surface_projection
                projected = self._project_features(QtCore, self.surface, viewport, include_closed=True)
                self._surface_projection_key = key
                self._surface_projection = projected
                return projected

            def _projected_map(self, QtCore: Any, viewport: RadarViewport) -> list[tuple[str, str, list[Any], bool, dict[str, Any]]]:
                key = (self._map_version, self._projection_key(viewport))
                if key == self._map_projection_key:
                    return self._map_projection
                projected = self._project_features(QtCore, self.map_features, viewport, include_closed=True)
                self._map_projection_key = key
                self._map_projection = projected
                return projected

            def _projected_terrain(self, QtCore: Any, viewport: RadarViewport) -> list[tuple[str, str, list[Any], bool, dict[str, Any]]]:
                key = (self._terrain_version, self._projection_key(viewport))
                if key == self._terrain_projection_key:
                    return self._terrain_projection
                projected = self._project_features(QtCore, self.terrain_features, viewport, include_closed=True)
                self._terrain_projection_key = key
                self._terrain_projection = projected
                return projected

            def _projected_procedures(self, QtCore: Any, viewport: RadarViewport) -> list[tuple[str, str, list[Any]]]:
                key = (self._procedure_version, self._projection_key(viewport))
                if key == self._procedure_projection_key:
                    return self._procedure_projection
                projected = [(kind, label_text, poly) for kind, label_text, poly, _closed, _feature in self._project_features(QtCore, self.procedure_paths, viewport, include_closed=False)]
                self._procedure_projection_key = key
                self._procedure_projection = projected
                return projected

            def _projection_key(self, viewport: RadarViewport) -> tuple[Any, ...]:
                return (
                    round(viewport.cx, 1),
                    round(viewport.cy, 1),
                    round(viewport.radius, 1),
                    round(viewport.radius_nm, 3),
                    round(viewport.center_lat, 6),
                    round(viewport.center_lon, 6),
                )

            def _project_features(
                self,
                QtCore: Any,
                features: list[dict[str, Any]],
                viewport: RadarViewport,
                *,
                include_closed: bool,
            ) -> list[tuple[str, str, list[Any], bool, dict[str, Any]]]:
                projected: list[tuple[str, str, list[Any], bool, dict[str, Any]]] = []
                for feature in features:
                    points = feature.get("points") or feature.get("coordinates")
                    if not isinstance(points, list) or len(points) < 2:
                        continue
                    kind = str(feature.get("kind") or feature.get("type") or "path").strip().lower()
                    poly = []
                    for point in points:
                        lat_lon = self._feature_point_lat_lon(point, viewport)
                        if lat_lon is None:
                            continue
                        x_nm, y_nm = viewport.latlon_to_nm(lat_lon[0], lat_lon[1])
                        x, y = viewport.nm_to_canvas(x_nm, y_nm)
                        poly.append(QtCore.QPointF(x, y))
                    if len(poly) >= 2:
                        projected.append((kind, str(feature.get("label") or feature.get("name") or ""), poly, bool(feature.get("closed")) if include_closed else False, feature))
                return projected

            def _feature_point_lat_lon(self, point: Any, viewport: RadarViewport) -> tuple[float, float] | None:
                if isinstance(point, dict):
                    lat = _safe_float(point.get("lat", point.get("latitude")))
                    lon = _safe_float(point.get("lon", point.get("lng", point.get("longitude"))))
                    return (lat, lon) if lat is not None and lon is not None else None
                if isinstance(point, str):
                    cleaned = point.strip().replace(",", " ")
                    parts = [part for part in cleaned.split() if part]
                    if len(parts) < 2:
                        return None
                    first = _safe_float(parts[0])
                    second = _safe_float(parts[1])
                    if first is None or second is None:
                        return None
                    return self._choose_lat_lon_pair(first, second, viewport)
                if not isinstance(point, list | tuple) or len(point) < 2:
                    return None
                first = _safe_float(point[0])
                second = _safe_float(point[1])
                if first is None or second is None:
                    return None
                return self._choose_lat_lon_pair(first, second, viewport)

            def _choose_lat_lon_pair(self, first: float, second: float, viewport: RadarViewport) -> tuple[float, float] | None:
                candidates = []
                if abs(first) <= 90 and abs(second) <= 180:
                    candidates.append((first, second))
                if abs(second) <= 90 and abs(first) <= 180:
                    candidates.append((second, first))
                if not candidates:
                    return None
                if len(candidates) == 1:
                    return candidates[0]
                return min(
                    candidates,
                    key=lambda candidate: abs(candidate[0] - viewport.center_lat) + abs(candidate[1] - viewport.center_lon),
                )

            def _latlon_to_nm(self, lat: float, lon: float) -> tuple[float, float]:
                lat0 = float(self.center.get("lat") or 0.0)
                lon0 = float(self.center.get("lon") or 0.0)
                y_nm = (lat - lat0) * 60.0
                x_nm = (lon - lon0) * 60.0 * math.cos(math.radians(lat0))
                return x_nm, y_nm

        return _Canvas()


def _qcolor_alpha(QtGui: Any, hex_color: str, alpha: int) -> Any:
    color = QtGui.QColor(hex_color)
    color.setAlpha(alpha)
    return color


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["RadarCanvas", "RadarViewport"]
