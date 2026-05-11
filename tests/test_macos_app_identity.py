from __future__ import annotations

import plistlib
from pathlib import Path

from scripts.make_app_bundle import _write_info_plist
from scripts.macos_icon import draw_macos_icon


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_macos_bundle_is_foreground_app() -> None:
    spec = (ROOT / "LocalFlight.spec").read_text(encoding="utf-8")

    assert '"LSUIElement"' not in spec
    assert '"CFBundleVersion": _VERSION' in spec
    assert '"LSApplicationCategoryType": "public.app-category.utilities"' in spec
    assert 'icon="assets/icon.icns"' in spec


def test_source_macos_bundle_plist_has_dock_identity(tmp_path: Path) -> None:
    _write_info_plist(tmp_path, "0.2.5")

    plist = plistlib.loads((tmp_path / "Info.plist").read_bytes())

    assert "LSUIElement" not in plist
    assert plist["CFBundleDisplayName"] == "Local Flight"
    assert plist["CFBundleIconFile"] == "AppIcon"
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["LSApplicationCategoryType"] == "public.app-category.utilities"


def test_macos_icon_source_is_rounded_square_asset() -> None:
    icon = (ROOT / "assets" / "localflight-logo.svg").read_text(encoding="utf-8")

    assert "Local Flight master logo" in icon
    assert 'rx="196"' in icon
    assert "LOCAL FLIGHT" not in icon


def test_macos_icon_fallback_draws_transparent_dock_tile() -> None:
    icon = draw_macos_icon(256)

    assert icon.mode == "RGBA"
    assert icon.size == (256, 256)
    assert icon.getpixel((0, 0))[3] == 0
    assert icon.getpixel((128, 128))[3] == 255
