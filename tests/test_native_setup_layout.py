"""Setup-window sizing, typography, and card re-flow for the native shell."""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

FONT_DIR = Path(__file__).resolve().parents[1] / "src" / "localflight" / "ui" / "static" / "fonts"


def test_setup_layout_profile_follows_the_window_not_the_screen() -> None:
    from localflight.native.geometry import (
        SETUP_WINDOW_MAX_HEIGHT,
        SETUP_WINDOW_MAX_WIDTH,
        setup_layout_profile,
    )

    cases = [
        # (screen, window, columns, compact)
        ((800, 480), (768, 422), 2, True),
        ((1024, 768), (921, 675), 2, True),
        ((1280, 720), (980, 633), 3, True),  # 1920x1080 at 150% Windows scaling
        ((1366, 768), (980, 675), 3, True),
        ((1512, 982), (980, 760), 3, False),
        ((1920, 1080), (980, 760), 3, False),
        ((3440, 1440), (980, 760), 3, False),  # ultrawide stays a normal window
        ((5120, 2160), (980, 760), 3, False),
    ]
    for (screen_w, screen_h), window, columns, compact in cases:
        profile = setup_layout_profile(screen_w, screen_h)
        assert (profile["window_width"], profile["window_height"]) == window
        assert profile["window_width"] <= SETUP_WINDOW_MAX_WIDTH
        assert profile["window_height"] <= SETUP_WINDOW_MAX_HEIGHT
        assert profile["content_width"] <= profile["window_width"]
        assert profile["columns"] == columns
        assert profile["compact"] is compact


def test_setup_card_columns_buckets() -> None:
    from localflight.native.geometry import setup_card_columns

    assert setup_card_columns(None) == 2
    assert setup_card_columns(400) == 1
    assert setup_card_columns(639) == 1
    assert setup_card_columns(640) == 2
    assert setup_card_columns(899) == 2
    assert setup_card_columns(900) == 3
    assert setup_card_columns(3000) == 3


def _name_records(path: Path) -> dict[int, str]:
    data = path.read_bytes()
    table_count = struct.unpack(">H", data[4:6])[0]
    tables = {}
    for index in range(table_count):
        tag, _checksum, offset, length = struct.unpack(">4sIII", data[12 + 16 * index : 28 + 16 * index])
        tables[tag.decode("latin1")] = (offset, length)
    assert "fvar" not in tables, f"{path.name} must be a static instance"
    offset, _length = tables["name"]
    _fmt, count, string_offset = struct.unpack(">HHH", data[offset : offset + 6])
    records: dict[int, str] = {}
    for index in range(count):
        base = offset + 6 + 12 * index
        platform, encoding, _lang, name_id, length, str_offset = struct.unpack(">HHHHHH", data[base : base + 12])
        if platform == 3 and encoding == 1:
            start = offset + string_offset + str_offset
            records[name_id] = data[start : start + length].decode("utf-16-be")
    weight = struct.unpack(">H", data[tables["OS/2"][0] + 4 : tables["OS/2"][0] + 6])[0]
    records[-1] = str(weight)
    return records


def test_static_dm_sans_weights_register_as_one_family() -> None:
    from localflight.native.design import FONT_FILES, UI_FONT_FAMILY

    expected = {
        "DMSans-Regular.ttf": ("Regular", 400),
        "DMSans-Bold.ttf": ("Bold", 700),
        "DMSans-ExtraBold.ttf": ("ExtraBold", 800),
        "DMSans-Black.ttf": ("Black", 900),
    }
    bundled = {filename for filename, family in FONT_FILES if family == UI_FONT_FAMILY}
    assert bundled == set(expected), "Qt must load the static weights, not the variable DMSans.ttf"
    for filename, (style, weight) in expected.items():
        records = _name_records(FONT_DIR / filename)
        assert records[16] == "DM Sans", filename
        assert records[17] == style, filename
        assert records[-1] == str(weight), filename
        assert records[6] == f"DMSans-{style}", filename
    # The variable font stays for the browser pages and mobile brand sync.
    assert (FONT_DIR / "DMSans.ttf").is_file()


def test_setup_cards_reflow_with_the_window_width(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets
    from localflight.native.app import SetupScreen
    from localflight.native.qt_compat import import_qt

    class _Client:
        def get_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, object]:
            if path == "/api/setup/client-info":
                return {"relay_url": "https://relay.beacontools.cc", "has_activation_token": False}
            return {}

    QtCore, _QtGui, QtWidgets2 = import_qt()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app is not None
    setup = SetupScreen(QtCore, QtWidgets2, _Client(), base_url="http://127.0.0.1:9")
    assert len(setup._card_grids) == 4

    def columns_used(grid: object) -> int:
        return max(grid.getItemPosition(i)[1] for i in range(grid.count())) + 1

    source_grid = setup._card_grids[1][0]
    finish_grid = setup._card_grids[3][0]

    setup._on_root_resized(1400)
    setup._regrid_cards()
    assert setup.card_columns == 3
    assert columns_used(source_grid) == 3
    assert columns_used(finish_grid) == 2, "the review grid never exceeds two columns"

    setup._on_root_resized(700)
    setup._regrid_cards()
    assert setup.card_columns == 2
    assert columns_used(source_grid) == 2
    assert all(grid.count() == len(cards) for grid, cards, _max in setup._card_grids)

    setup._on_root_resized(560)
    setup._regrid_cards()
    assert setup.card_columns == 1
    assert columns_used(source_grid) == 1
    assert all(grid.count() == len(cards) for grid, cards, _max in setup._card_grids)
