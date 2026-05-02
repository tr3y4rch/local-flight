"""Small PySide6 import boundary.

All Qt imports stay behind this module so the normal server/client package can
run without PySide6 installed.
"""
from __future__ import annotations

from typing import Any

from localflight.native import NativeUiUnavailable


def import_qt() -> tuple[Any, Any, Any]:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise NativeUiUnavailable(
            "PySide6 is not installed. Install Local Flight with the native extra "
            "or set LOCALFLIGHT_GUI_MODE=browser/headless."
        ) from exc
    return QtCore, QtGui, QtWidgets


def qt_available() -> bool:
    try:
        import_qt()
        return True
    except NativeUiUnavailable:
        return False
