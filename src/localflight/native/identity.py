"""Native app identity helpers for Qt shells and packaged builds."""
from __future__ import annotations

import ctypes
import sys
from typing import Any

from localflight.native.design import icon_from_media

APP_NAME = "Local Flight"
APP_ORGANIZATION = "Beacon Tools"
APP_DOMAIN = "beacontools.cc"
APP_BUNDLE_ID = "com.localflight.app"
DESKTOP_FILE_NAME = "localflight"


def set_process_app_id(app_id: str = APP_BUNDLE_ID) -> None:
    """Set the OS-level app id where supported.

    On Windows this controls taskbar grouping and the icon/title surfaces used
    before Qt has painted a window. Other platforms rely on bundle metadata and
    Qt application names, so this is intentionally a no-op there.
    """
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        # App identity should never prevent the GUI from starting.
        pass


def configure_qt_app_identity(
    QtCore: Any,
    QtGui: Any,
    app: Any,
    *,
    display_name: str = APP_NAME,
    app_id: str = APP_BUNDLE_ID,
    desktop_file_name: str = DESKTOP_FILE_NAME,
) -> None:
    """Apply Local Flight identity to QApplication and the host OS."""
    set_process_app_id(app_id)
    for owner in (getattr(QtCore, "QCoreApplication", None), app):
        if owner is None:
            continue
        for method_name, value in (
            ("setApplicationName", display_name),
            ("setApplicationDisplayName", display_name),
            ("setOrganizationName", APP_ORGANIZATION),
            ("setOrganizationDomain", APP_DOMAIN),
        ):
            method = getattr(owner, method_name, None)
            if method is None:
                continue
            try:
                method(value)
            except Exception:
                pass
    qgui = getattr(QtGui, "QGuiApplication", None)
    set_desktop_file_name = getattr(qgui, "setDesktopFileName", None)
    if set_desktop_file_name is not None:
        try:
            set_desktop_file_name(desktop_file_name)
        except Exception:
            pass


def localflight_app_icon(QtGui: Any) -> Any:
    """Return the best native window/app icon available for the host platform."""
    candidates = (
        ("assets", "icon.icns"),
        ("assets", "icon.ico"),
        ("assets", "icon.png"),
        ("assets", "localflight-logo.svg"),
    )
    if sys.platform == "win32":
        candidates = (
            ("assets", "icon.ico"),
            ("assets", "icon.png"),
            ("assets", "localflight-logo.svg"),
        )
    elif sys.platform != "darwin":
        candidates = (
            ("assets", "icon.png"),
            ("assets", "localflight-logo.svg"),
            ("assets", "icon.ico"),
        )

    for parts in candidates:
        icon = icon_from_media(QtGui, *parts)
        if not icon.isNull():
            return icon
    return QtGui.QIcon()
