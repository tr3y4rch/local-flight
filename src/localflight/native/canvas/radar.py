"""Qt-native radar canvas.

The browser radar remains the behavior checklist, but this module owns the
native QPainter implementation so Radar can evolve outside the legacy shell.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from localflight.native.design import colors_for, format_value


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

            def __init__(self) -> None:
                super().__init__()
                self.setMouseTracking(True)
                self.setMinimumSize(420, 420)
                self.blips: list[dict[str, Any]] = []
                self.track_history: dict[str, list[tuple[float, float]]] = {}
                self._track_absent_counts: dict[str, int] = {}
                self._max_track_points = 4
                self.surface: list[dict[str, Any]] = []
                self.procedure_paths: list[dict[str, Any]] = []
                self.terrain_features: list[dict[str, Any]] = []
                self.layers = {
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
                self._surface_version = 0
                self._surface_projection_key: tuple[Any, ...] | None = None
                self._surface_projection: list[tuple[str, str, list[Any], bool, dict[str, Any]]] = []
                self._terrain_version = 0
                self._terrain_projection_key: tuple[Any, ...] | None = None
                self._terrain_projection: list[tuple[str, str, list[Any]]] = []
                self._procedure_version = 0
                self._procedure_projection_key: tuple[Any, ...] | None = None
                self._procedure_projection: list[tuple[str, str, list[Any]]] = []
                self._static_cache_key: tuple[Any, ...] | None = None
                self._static_cache_pixmap: Any = None
                self._hover_key = ""
                self.hovered_blip: dict[str, Any] | None = None
                self._sweep_timer = QtCore.QTimer(self)
                self._sweep_interval_ms = 80
                self._sweep_timer.timeout.connect(self._tick_sweep)

            def showEvent(self, event: Any) -> None:
                super().showEvent(event)
                if not self._sweep_timer.isActive():
                    self._sweep_timer.start(self._sweep_interval_ms)

            def hideEvent(self, event: Any) -> None:
                super().hideEvent(event)
                self._sweep_timer.stop()

            def apply_theme(self, theme: str, skin: str) -> None:
                self.colors = colors_for(theme, skin)
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
                    self._invalidate_static_layer()
                    if old_key[1] not in {None, 0.0} and old_key[2] not in {None, 0.0}:
                        self.track_history.clear()
                        self._track_absent_counts.clear()
                self._update_track_history(self.blips)
                self.status = f"{len(self.blips)} visible | {payload.get('source', 'unknown')}"
                self._set_hover_blip(None)
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
                if layer in {"surface", "runways", "procedures", "terrain"}:
                    self._invalidate_static_layer()
                self.update()

            def _tick_sweep(self) -> None:
                self.sweep_angle = (self.sweep_angle + 1.92) % 360.0
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
                self._draw_sweep(painter, QtCore, QtGui, viewport)
                self._draw_track_ghosts(painter, QtCore, QtGui, viewport)
                self._draw_blips(painter, QtCore, QtGui, viewport)
                self._draw_hover(painter, QtCore, QtGui, viewport)
                painter.restore()
                self._draw_footer(painter, QtGui, rect)

            def mouseMoveEvent(self, event: Any) -> None:
                viewport = self._viewport(self.rect())
                hit = self._hit_blip(event.position().x(), event.position().y(), viewport)
                self._set_hover_blip(hit)
                self.setToolTip(self._tooltip_for_blip(hit) if hit else "")
                self.setCursor(QtCore.Qt.PointingHandCursor if hit else QtCore.Qt.ArrowCursor)

            def leaveEvent(self, event: Any) -> None:
                super().leaveEvent(event)
                self._set_hover_blip(None)
                self.setToolTip("")
                self.unsetCursor()

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
                    self._surface_version,
                    self._terrain_version,
                    self._procedure_version,
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
                    self._draw_background(static_painter, QtGui, rect, viewport)
                    static_painter.save()
                    path = QtGui.QPainterPath()
                    path.addEllipse(QtCore.QPointF(viewport.cx, viewport.cy), viewport.radius, viewport.radius)
                    static_painter.setClipPath(path)
                    if self.layers.get("terrain", False):
                        self._draw_terrain(static_painter, QtCore, QtGui, viewport)
                    if self.layers.get("surface", True) or self.layers.get("runways", True):
                        self._draw_surface(static_painter, QtCore, QtGui, viewport)
                    self._draw_grid(static_painter, QtCore, QtGui, viewport)
                    if self.layers.get("procedures", False):
                        self._draw_procedures(static_painter, QtCore, QtGui, viewport)
                    static_painter.restore()
                finally:
                    static_painter.end()
                self._static_cache_key = key
                self._static_cache_pixmap = pixmap
                return pixmap

            def _draw_background(self, painter: Any, QtGui: Any, rect: Any, viewport: RadarViewport) -> None:
                painter.fillRect(rect, QtGui.QColor(self.colors["panel_2"]))
                bg = QtGui.QColor(self.colors["panel_2"])
                painter.setBrush(bg)
                painter.setPen(QtCore.Qt.NoPen)
                painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), viewport.radius, viewport.radius)

            def _draw_grid(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                grid = QtGui.QColor(self.colors["blue"])
                grid.setAlpha(110 if viewport.radius_nm >= 20 else 130)
                painter.setPen(QtGui.QPen(grid, 1))
                label_fractions = {0.2, 0.4, 0.6, 0.8, 1.0}
                if viewport.radius_nm >= 40:
                    label_fractions = {0.4, 0.8, 1.0}
                elif viewport.radius_nm >= 20:
                    label_fractions = {0.2, 0.6, 1.0}
                for frac in (0.2, 0.4, 0.6, 0.8, 1.0):
                    r = viewport.radius * frac
                    painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), r, r)
                    if frac in label_fractions:
                        label_color = QtGui.QColor(self.colors["muted"])
                        label_color.setAlpha(110 if viewport.radius_nm >= 20 else 150)
                        painter.setPen(label_color)
                        painter.drawText(int(viewport.cx + r + 5), int(viewport.cy - 4), f"{self.radius_nm * frac:.0f}nm")
                        painter.setPen(QtGui.QPen(grid, 1))
                painter.drawLine(viewport.cx - viewport.radius, viewport.cy, viewport.cx + viewport.radius, viewport.cy)
                painter.drawLine(viewport.cx, viewport.cy - viewport.radius, viewport.cx, viewport.cy + viewport.radius)
                painter.setPen(QtGui.QColor(self.colors["muted"]))
                painter.drawText(int(viewport.cx - 4), int(viewport.cy - viewport.radius + 18), "N")
                painter.drawText(int(viewport.cx + viewport.radius - 18), int(viewport.cy + 4), "E")
                painter.drawText(int(viewport.cx - 4), int(viewport.cy + viewport.radius - 8), "S")
                painter.drawText(int(viewport.cx - viewport.radius + 8), int(viewport.cy + 4), "W")
                center = QtGui.QColor(self.colors["muted"])
                center.setAlpha(150)
                painter.setPen(QtGui.QPen(center, 1))
                painter.setBrush(center)
                painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), 3.5, 3.5)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawEllipse(QtCore.QPointF(viewport.cx, viewport.cy), 8, 8)

            def _draw_blips(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                for blip in self.blips:
                    if not self._blip_in_range(blip, viewport):
                        continue
                    pos = self._blip_pos(blip, viewport)
                    alpha = self._blip_alpha(blip)
                    flash = alpha >= 245 and not blip.get("on_ground")
                    if flash:
                        bloom = QtGui.QColor(self.colors["cyan"])
                        bloom.setAlpha(38)
                        painter.setPen(QtCore.Qt.NoPen)
                        painter.setBrush(bloom)
                        painter.drawEllipse(QtCore.QPointF(pos[0], pos[1]), 12, 12)
                    color = QtGui.QColor(self.colors["cyan"])
                    color.setAlpha(alpha)
                    painter.setPen(QtGui.QPen(color, 2))
                    painter.setBrush(color)
                    painter.drawEllipse(QtCore.QPointF(pos[0], pos[1]), 5.0 if flash else 4.0, 5.0 if flash else 4.0)
                    callsign = str(blip.get("callsign") or "").strip()
                    if callsign and self._should_draw_callsign(blip, viewport):
                        painter.setPen(QtGui.QColor(self.colors["text"]))
                        painter.drawText(int(pos[0] + 8), int(pos[1] - 6), callsign[:10])
                    status_label = self._blip_status_label(blip)
                    if self.layers.get("traffic_status", True) and status_label and viewport.radius_nm <= 20:
                        status_color = self._status_color(QtGui, status_label)
                        painter.setPen(status_color)
                        painter.drawText(int(pos[0] + 8), int(pos[1] + 12), status_label[:12])
                    self._draw_direction_indicator(painter, QtCore, QtGui, blip, pos, viewport)
                    painter.setBrush(QtCore.Qt.NoBrush)

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
                        color = QtGui.QColor(self.colors["cyan"])
                        color.setAlpha(alpha)
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
                            line = QtGui.QColor(self.colors["cyan"])
                            line.setAlpha(45)
                            painter.setPen(QtGui.QPen(line, 1))
                            for idx in range(1, len(projected)):
                                painter.drawLine(projected[idx - 1], projected[idx])
                painter.restore()

            def _draw_direction_indicator(self, painter: Any, QtCore: Any, QtGui: Any, blip: dict[str, Any], pos: tuple[float, float], viewport: RadarViewport) -> None:
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
                color = QtGui.QColor(self.colors["cyan"])
                color.setAlpha(175)
                painter.setPen(QtGui.QPen(color, 1.4))
                painter.drawLine(tail, tip)
                wing = 4.5
                left = QtCore.QPointF(tip.x() - math.cos(hr - 0.75) * wing, tip.y() - math.sin(hr - 0.75) * wing)
                right = QtCore.QPointF(tip.x() - math.cos(hr + 0.75) * wing, tip.y() - math.sin(hr + 0.75) * wing)
                painter.drawLine(tip, left)
                painter.drawLine(tip, right)

            def _draw_hover(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if self.hovered_blip:
                    hx, hy = self._blip_pos(self.hovered_blip, viewport)
                    halo = QtGui.QColor(self.colors["amber"])
                    halo.setAlpha(180)
                    painter.setPen(QtGui.QPen(halo, 2))
                    painter.setBrush(QtCore.Qt.NoBrush)
                    painter.drawEllipse(QtCore.QPointF(hx, hy), 11, 11)

            def _draw_footer(self, painter: Any, QtGui: Any, rect: Any) -> None:
                painter.setPen(QtGui.QColor(self.colors["muted"]))
                painter.drawText(14, rect.height() - 14, self.status)
                if self.attribution:
                    painter.drawText(rect.width() - 320, rect.height() - 14, self.attribution[:48])

            def _hit_blip(self, x_pos: float, y_pos: float, viewport: RadarViewport) -> dict[str, Any] | None:
                hit_radius = 11.0
                for blip in self.blips:
                    if not self._blip_in_range(blip, viewport):
                        continue
                    x, y = self._blip_pos(blip, viewport)
                    if math.hypot(x_pos - x, y_pos - y) <= hit_radius:
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
                phase = str(blip.get("radar_phase") or blip.get("radar_status") or "").strip().lower()
                if phase:
                    return phase.replace("_", " ").title()
                return ""

            def _status_color(self, QtGui: Any, status_label: str) -> Any:
                clean = status_label.lower()
                if "final" in clean or "approach" in clean:
                    return QtGui.QColor(self.colors["amber"])
                if "descend" in clean or "descent" in clean:
                    return QtGui.QColor(self.colors["blue"])
                if "depart" in clean or "climb" in clean:
                    return QtGui.QColor(self.colors["cyan"])
                return QtGui.QColor(self.colors["muted"])

            def _should_draw_callsign(self, blip: dict[str, Any], viewport: RadarViewport) -> bool:
                if self._blip_identity(blip) == self._hover_key:
                    return True
                if viewport.radius_nm <= 10:
                    return True
                phase = str(blip.get("radar_phase") or blip.get("radar_status") or "").strip().lower()
                if viewport.radius_nm <= 20:
                    return len(self.blips) <= 35 or phase in {"approach", "final", "departing"}
                return len(self.blips) <= 8 and phase in {"approach", "final", "departing"} and not bool(blip.get("on_ground"))

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
                    return (math.degrees(math.atan2(x_nm, y_nm)) + 360.0) % 360.0
                return float(blip.get("bearing_deg") or 0.0) % 360.0

            def _blip_alpha(self, blip: dict[str, Any]) -> int:
                if blip.get("on_ground"):
                    return 150
                age = (self.sweep_angle - self._blip_angle(blip) + 360.0) % 360.0
                if age > 350 or age < 30:
                    return 255
                return max(45, int(255 - ((age - 30.0) / 310.0) * 210))

            def _draw_sweep(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                painter.save()
                painter.translate(viewport.cx, viewport.cy)
                painter.rotate(self.sweep_angle)
                for idx in range(18):
                    color = QtGui.QColor(self.colors["sweep"])
                    color.setAlpha(max(0, int((1 - idx / 18) * 28)))
                    painter.setBrush(color)
                    painter.setPen(QtCore.Qt.NoPen)
                    path = QtGui.QPainterPath()
                    path.moveTo(0, 0)
                    path.arcTo(-viewport.radius, -viewport.radius, viewport.radius * 2, viewport.radius * 2, -idx * 4, -4)
                    path.closeSubpath()
                    painter.drawPath(path)
                line = QtGui.QColor(self.colors["sweep"])
                line.setAlpha(180)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setPen(QtGui.QPen(line, 1.5))
                painter.drawLine(0, 0, 0, -viewport.radius)
                painter.restore()

            def _draw_terrain(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if not self.terrain_features:
                    return
                painter.save()
                terrain = QtGui.QColor(self.colors["amber"])
                terrain.setAlpha(40 if viewport.radius_nm <= 20 else 24)
                painter.setPen(QtGui.QPen(terrain, 1))
                painter.setBrush(QtCore.Qt.NoBrush)
                for _kind, _label, poly in self._projected_terrain(QtCore, viewport):
                    if len(poly) >= 3:
                        painter.drawPolygon(poly)
                    elif len(poly) >= 2:
                        for idx in range(1, len(poly)):
                            painter.drawLine(poly[idx - 1], poly[idx])
                painter.restore()

            def _draw_procedures(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if not self.procedure_paths:
                    return
                colors = {
                    "approach": _qcolor_alpha(QtGui, self.colors["amber"], 145),
                    "departure": _qcolor_alpha(QtGui, self.colors["cyan"], 145),
                    "transition": _qcolor_alpha(QtGui, self.colors["blue"], 120),
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
                        painter.setPen(QtGui.QColor(self.colors["muted"]))
                        painter.drawText(poly[-1], label_text[:18])
                painter.restore()

            def _draw_surface(self, painter: Any, QtCore: Any, QtGui: Any, viewport: RadarViewport) -> None:
                if not self.surface:
                    return
                colors = {
                    "boundary": _qcolor_alpha(QtGui, self.colors["blue"], 110),
                    "runway": _qcolor_alpha(QtGui, self.colors["cyan"], 180),
                    "taxiway": _qcolor_alpha(QtGui, self.colors["blue"], 120),
                    "apron": _qcolor_alpha(QtGui, self.colors["blue"], 45),
                    "terminal": _qcolor_alpha(QtGui, self.colors["amber"], 55),
                    "building": _qcolor_alpha(QtGui, self.colors["amber"], 65),
                }
                painter.save()
                painter.setOpacity(self._surface_alpha())
                for kind, runway_label, poly, closed, feature in self._projected_surface(QtCore, viewport):
                    if len(poly) < 2:
                        continue
                    if kind == "runway" and not self.layers.get("runways", True):
                        continue
                    if kind != "runway" and not self.layers.get("surface", True):
                        continue
                    pen_width = self._runway_pen_width(feature, viewport) if kind == "runway" else 1
                    pen = QtGui.QPen(colors.get(kind, colors["taxiway"]), pen_width)
                    if kind == "runway" and str(feature.get("confidence") or "").lower() == "estimated":
                        pen.setStyle(QtCore.Qt.DashLine)
                    if kind == "runway" and feature.get("closed"):
                        closed_color = QtGui.QColor(self.colors["red"])
                        closed_color.setAlpha(150)
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
                        fill = QtGui.QColor(self.colors["cyan"])
                        fill.setAlpha(26)
                        painter.setBrush(fill)
                        painter.drawPolygon(poly)
                        painter.setBrush(QtCore.Qt.NoBrush)
                    if kind == "runway" and runway_label and len(poly) >= 2 and viewport.radius_nm <= 10:
                        self._draw_runway_label(painter, QtGui, runway_label, poly)
                    if kind == "runway" and len(poly) >= 2 and viewport.radius_nm <= 20:
                        self._draw_runway_thresholds(painter, QtCore, QtGui, feature, poly, viewport)
                painter.restore()

            def _runway_pen_width(self, feature: dict[str, Any], viewport: RadarViewport) -> float:
                width_ft = _safe_float(feature.get("width_ft"))
                if width_ft is None:
                    return 3.2 if viewport.radius_nm <= 10 else 2.4
                width_nm = max(0.01, width_ft / 6076.12)
                pixels = width_nm * (viewport.radius / max(0.1, viewport.radius_nm))
                return max(2.2, min(8.0, pixels))

            def _draw_runway_label(self, painter: Any, QtGui: Any, label_text: str, poly: list[Any]) -> None:
                p1 = poly[0]
                p2 = poly[-1]
                x = (p1.x() + p2.x()) / 2
                y = (p1.y() + p2.y()) / 2
                painter.save()
                painter.translate(x, y)
                painter.rotate(math.degrees(math.atan2(p2.y() - p1.y(), p2.x() - p1.x())))
                painter.setPen(QtGui.QColor(self.colors["text"]))
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
                threshold_pen = QtGui.QPen(QtGui.QColor(self.colors["text"]), 1)
                painter.setPen(threshold_pen)
                for point, text, sign in ((p1, end_labels[0], -1), (p2, end_labels[1], 1)):
                    painter.drawLine(
                        QtCore.QPointF(point.x() - nx * tick, point.y() - ny * tick),
                        QtCore.QPointF(point.x() + nx * tick, point.y() + ny * tick),
                    )
                    if text and viewport.radius_nm <= 10:
                        painter.drawText(QtCore.QPointF(point.x() + nx * tick * sign, point.y() + ny * tick * sign), text[:4])
                if str(feature.get("confidence") or "").lower() in {"ourairports", "ourairports+osm"} and viewport.radius_nm <= 10:
                    painter.setPen(QtGui.QColor(self.colors["muted"]))
                    painter.drawText(QtCore.QPointF((p1.x() + p2.x()) / 2 + 8, (p1.y() + p2.y()) / 2 + 14), str(feature.get("confidence"))[:16])
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

            def _projected_terrain(self, QtCore: Any, viewport: RadarViewport) -> list[tuple[str, str, list[Any]]]:
                key = (self._terrain_version, self._projection_key(viewport))
                if key == self._terrain_projection_key:
                    return self._terrain_projection
                projected = [(kind, label_text, poly) for kind, label_text, poly, _closed, _feature in self._project_features(QtCore, self.terrain_features, viewport, include_closed=True)]
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
                        if not isinstance(point, list | tuple) or len(point) < 2:
                            continue
                        try:
                            x_nm, y_nm = viewport.latlon_to_nm(float(point[0]), float(point[1]))
                        except (TypeError, ValueError):
                            continue
                        x, y = viewport.nm_to_canvas(x_nm, y_nm)
                        poly.append(QtCore.QPointF(x, y))
                    if len(poly) >= 2:
                        projected.append((kind, str(feature.get("label") or feature.get("name") or ""), poly, bool(feature.get("closed")) if include_closed else False, feature))
                return projected

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
