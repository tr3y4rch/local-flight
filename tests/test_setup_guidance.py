"""Shared setup-wizard guidance: one copy source and one icon set for Qt and the browser."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src" / "localflight" / "ui" / "templates" / "setup.html"


def test_step_copy_and_icons_are_complete_and_plain() -> None:
    from localflight.ui.setup_guidance import (
        BUTTON_LABELS,
        DIAGNOSTICS_OPTIONS,
        ICONS,
        SOURCE_OPTIONS,
        STEP_COPY,
        STEP_NAMES,
        STEP_SHORT_LABELS,
        WELCOME_CARDS,
        icon_svg,
    )

    assert len(STEP_COPY) == len(STEP_NAMES) == len(STEP_SHORT_LABELS) == 6
    for step in STEP_COPY:
        assert step["heading"] and step["lede"]
        assert len(step["lede"]) < 220, "ledes stay to one or two short sentences"
    for card in (*WELCOME_CARDS, *SOURCE_OPTIONS, *DIAGNOSTICS_OPTIONS):
        assert card["icon"] in ICONS, f"unknown icon {card['icon']!r} on {card['title']!r}"
        assert len(card["body"]) < 170, f"card body too long: {card['title']!r}"
        # No emoji: the wizards paint the shared line icons instead.
        assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", card["icon"] + card["title"] + card["body"])
    assert set(BUTTON_LABELS) == {"start", "back", "next", "finish", "skip_keys", "browser"}
    svg = icon_svg("antenna", color="#123456")
    assert svg.startswith("<svg") and 'stroke="#123456"' in svg and "currentColor" not in svg
    assert 'stroke="currentColor"' in icon_svg("antenna")


def test_browser_template_renders_from_the_shared_guidance() -> None:
    from localflight.ui.setup_guidance import BUTTON_LABELS, ICONS

    template = TEMPLATE.read_text(encoding="utf-8")
    assert "setup_guidance.step_copy" in template
    assert "setup_guidance.icons[" in template
    assert "setup_guidance.provider_key_groups" in template
    assert "setup_guidance.summary_labels" in template
    for name in ("check", "arrow_left", "arrow_right", "takeoff", "eye", "search", "info", "external", "flask"):
        assert name in ICONS and f"setup_guidance.icons.{name}" in template
    assert BUTTON_LABELS["finish"] == "Open Local Flight"
    assert "data-reduce-motion" in template
    assert "prefers-reduced-motion" in template
    assert 'role="radiogroup"' in template
    # No emoji in the served markup either.
    assert not re.search(r"[\U0001F300-\U0001FAFF]", template)


def test_guidance_context_exposes_rendered_icons() -> None:
    from localflight.ui.setup_guidance import ICONS, guidance_context

    context = guidance_context()
    assert set(context["icons"]) == set(ICONS)
    assert all(value.startswith("<svg") for value in context["icons"].values())
    assert context["buttons"]["next"] == "Continue"
    json.dumps(context["summary_labels"])


def test_reduce_motion_setting_round_trips_through_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from localflight.storage import config as config_module

    monkeypatch.setenv("LOCALFLIGHT_HOME", str(tmp_path))
    path = tmp_path / ".localflight" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"airport_icao": "LSZH", "airport_iata": "ZRH", "reduce_motion": "yes"}), encoding="utf-8")
    loaded = config_module.load_config()
    assert loaded.reduce_motion is True
    config_module.save_config(loaded)
    assert json.loads(path.read_text(encoding="utf-8"))["reduce_motion"] is True
    default = config_module.AppConfig()
    assert default.reduce_motion is False


def test_native_icons_rasterize_through_qtsvg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6 import QtCore, QtGui, QtWidgets

    from localflight.native.pages.setup_icons import icon, icon_pixmap
    from localflight.ui.setup_guidance import ICONS

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    assert app is not None
    for name in ICONS:
        pixmap = icon_pixmap(QtCore, QtGui, name, color_hex="#4a9eda", size=20, device_pixel_ratio=2.0)
        assert not pixmap.isNull(), name
        assert pixmap.width() == 40 and pixmap.devicePixelRatio() == 2.0
    assert not icon(QtCore, QtGui, "takeoff", color_hex="#ffffff").isNull()
    # Unknown names fall back to the info icon rather than failing.
    assert not icon_pixmap(QtCore, QtGui, "does-not-exist", color_hex="#ffffff").isNull()
