"""Render the shared setup icon set for the native Qt wizard.

The icons are the same SVG line drawings the browser wizard inlines
(:mod:`localflight.ui.setup_guidance`). Rasterizing them through QtSvg keeps
every platform and skin identical, which emoji never were: Windows, macOS,
and Linux each shipped their own emoji glyphs, and some looked like broken
letters in the setup window.
"""
from __future__ import annotations

from typing import Any

from localflight.ui.setup_guidance import ICONS, icon_svg

_PIXMAP_CACHE: dict[tuple[str, str, int, float], Any] = {}


def has_icon(name: str) -> bool:
    return name in ICONS


def icon_pixmap(QtCore: Any, QtGui: Any, name: str, *, color_hex: str, size: int = 20, device_pixel_ratio: float = 1.0) -> Any:
    """Return a transparent ``QPixmap`` of one shared icon, or a null pixmap."""
    ratio = max(1.0, float(device_pixel_ratio or 1.0))
    key = (name, color_hex, int(size), round(ratio, 2))
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    pixmap = QtGui.QPixmap()
    try:
        from PySide6 import QtSvg  # type: ignore
    except Exception:  # pragma: no cover - QtSvg is bundled with the desktop app
        return pixmap
    try:
        renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(icon_svg(name, color=color_hex).encode("utf-8")))
        if not renderer.isValid():
            return pixmap
        pixel_size = int(round(size * ratio))
        pixmap = QtGui.QPixmap(pixel_size, pixel_size)
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        try:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
            renderer.render(painter, QtCore.QRectF(0, 0, pixel_size, pixel_size))
        finally:
            painter.end()
        pixmap.setDevicePixelRatio(ratio)
    except Exception:
        return QtGui.QPixmap()
    _PIXMAP_CACHE[key] = pixmap
    return pixmap


def icon(QtCore: Any, QtGui: Any, name: str, *, color_hex: str, size: int = 18, device_pixel_ratio: float = 1.0) -> Any:
    """Return a ``QIcon`` for buttons and tool buttons."""
    result = QtGui.QIcon()
    pixmap = icon_pixmap(QtCore, QtGui, name, color_hex=color_hex, size=size, device_pixel_ratio=device_pixel_ratio)
    if not pixmap.isNull():
        result.addPixmap(pixmap)
    return result


def screen_ratio(QtWidgets: Any) -> float:
    try:
        app = QtWidgets.QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        return float(screen.devicePixelRatio()) if screen is not None else 1.0
    except Exception:
        return 1.0


def set_button_icon(QtCore: Any, QtGui: Any, QtWidgets: Any, button: Any, name: str, *, color_hex: str, size: int = 16) -> None:
    """Attach a shared icon to a push or tool button, safely."""
    try:
        button.setIcon(icon(QtCore, QtGui, name, color_hex=color_hex, size=size, device_pixel_ratio=screen_ratio(QtWidgets)))
        button.setIconSize(QtCore.QSize(size, size))
    except Exception:
        pass


__all__ = ["has_icon", "icon", "icon_pixmap", "screen_ratio", "set_button_icon"]
