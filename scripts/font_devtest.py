"""Small Qt font smoke/viewer for Local Flight native typography.

This does not start the backend. It only checks that the bundled OFL fonts can
be resolved and registered with Qt, then optionally opens a tiny preview window.
"""
from __future__ import annotations

import sys

from localflight.native.design import apply_app_font_defaults, icon_from_media, native_stylesheet, resolve_media_path
from localflight.native.qt_compat import import_qt


EXPECTED_FAMILIES = ("DM Sans", "Space Mono")
FONT_FILES = (
    "DMSans.ttf",
    "SpaceMono-Regular.ttf",
    "SpaceMono-Bold.ttf",
    "OFL-DMSans.txt",
    "OFL-SpaceMono.txt",
)


def _check_files() -> list[str]:
    missing: list[str] = []
    for filename in FONT_FILES:
        if resolve_media_path("ui", "static", "fonts", filename) is None:
            missing.append(filename)
    return missing


def _font_label(QtGui, family: str, point_size: int, *, bold: bool = False):
    font = QtGui.QFont(family, point_size)
    font.setBold(bold)
    return font


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    smoke_only = "--smoke" in argv
    missing_files = _check_files()
    if missing_files:
        print("Missing bundled font files: " + ", ".join(missing_files), file=sys.stderr)
        return 1

    QtCore, QtGui, QtWidgets = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("Local Flight Font Devtest")
    loaded = sorted(set(apply_app_font_defaults(QtGui, app)))
    missing_families = [family for family in EXPECTED_FAMILIES if family not in loaded]
    print("Loaded Qt font families: " + ", ".join(loaded or ["<none>"]))
    if missing_families:
        print("Missing Qt font families: " + ", ".join(missing_families), file=sys.stderr)
        return 2
    if smoke_only:
        return 0

    icon = icon_from_media(QtGui, "assets", "icon_circle.svg")
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = QtWidgets.QWidget()
    window.setWindowTitle("Local Flight Font Devtest")
    if not icon.isNull():
        window.setWindowIcon(icon)
    window.setStyleSheet(native_stylesheet())

    layout = QtWidgets.QVBoxLayout(window)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(12)

    title = QtWidgets.QLabel("Local Flight Typography")
    title.setObjectName("Title")
    title.setFont(_font_label(QtGui, "DM Sans", 22, bold=True))
    layout.addWidget(title)

    body = QtWidgets.QLabel("DM Sans drives readable setup, settings, admin, and document views.")
    body.setWordWrap(True)
    body.setFont(_font_label(QtGui, "DM Sans", 12))
    layout.addWidget(body)

    board = QtWidgets.QLabel("ZRH 09:41  LX 1952  SWISS  BCN  SCHEDULED  A220")
    board.setObjectName("ClockChip")
    board.setFont(_font_label(QtGui, "Space Mono", 15, bold=True))
    board.setMinimumHeight(46)
    layout.addWidget(board)

    mono = QtWidgets.QLabel("UTC 08:41:22 | LT 09:41:22 | METAR LSZH 020350Z CAVOK")
    mono.setObjectName("Muted")
    mono.setFont(_font_label(QtGui, "Space Mono", 10))
    layout.addWidget(mono)

    loaded_label = QtWidgets.QLabel("Loaded: " + ", ".join(loaded))
    loaded_label.setObjectName("Muted")
    loaded_label.setWordWrap(True)
    layout.addWidget(loaded_label)

    close = QtWidgets.QPushButton("Close")
    close.clicked.connect(window.close)
    layout.addWidget(close)

    window.resize(720, 320)
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
