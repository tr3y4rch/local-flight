from __future__ import annotations

import plistlib
from pathlib import Path

from scripts.make_app_bundle import _write_info_plist
from scripts.macos_icon import draw_macos_icon


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_macos_bundle_is_foreground_app() -> None:
    spec = (ROOT / "LocalFlight.spec").read_text(encoding="utf-8")

    assert '"LSUIElement"' not in spec
    assert "console=False" in spec
    assert 'bundle_identifier=_BUNDLE_IDENTIFIER' in spec
    assert '"CFBundleExecutable": "LocalFlight"' in spec
    assert '"CFBundlePackageType": "APPL"' in spec
    assert '"NSPrincipalClass": "NSApplication"' in spec
    assert '"CFBundleVersion": _VERSION' in spec
    assert '"LSApplicationCategoryType": "public.app-category.utilities"' in spec
    assert 'icon="assets/icon.icns"' in spec
    assert "localflight_version_info.txt" in spec
    assert "SetCurrentProcessExplicitAppUserModelID" in (
        ROOT / "src" / "localflight" / "native" / "identity.py"
    ).read_text(encoding="utf-8")


def test_source_macos_bundle_plist_has_dock_identity(tmp_path: Path) -> None:
    _write_info_plist(tmp_path, "0.2.5")

    plist = plistlib.loads((tmp_path / "Info.plist").read_bytes())

    assert "LSUIElement" not in plist
    assert plist["CFBundleDisplayName"] == "Local Flight"
    assert plist["CFBundleExecutable"] == "LocalFlight"
    assert plist["CFBundleIconFile"] == "AppIcon"
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["NSPrincipalClass"] == "NSApplication"
    assert plist["LSApplicationCategoryType"] == "public.app-category.utilities"


def test_source_macos_launchers_use_local_flight_process_title() -> None:
    for launcher in (
        ROOT / "scripts" / "make_app_bundle.py",
        ROOT / "installers" / "macos" / "LocalFlight.command",
        ROOT / "installers" / "macos" / "start.sh",
    ):
        assert 'exec -a "Local Flight" "$VENV/bin/python" -m localflight' in launcher.read_text(encoding="utf-8")


def test_source_macos_app_launcher_redirects_bootstrap_output() -> None:
    launcher = (ROOT / "scripts" / "make_app_bundle.py").read_text(encoding="utf-8")

    redirect = 'exec >>"$BOOTSTRAP_LOG" 2>&1'
    launch = 'exec -a "Local Flight" "$VENV/bin/python" -m localflight'
    assert 'LOG_DIR="${{HOME}}/.localflight/logs"' in launcher
    assert 'BOOTSTRAP_LOG="$LOG_DIR/source_app_bootstrap_' in launcher
    assert redirect in launcher
    assert launcher.index(redirect) < launcher.index(launch)


def test_macos_icon_source_is_rounded_square_asset() -> None:
    icon = (ROOT / "assets" / "localflight-logo.svg").read_text(encoding="utf-8")

    assert "Local Flight" in icon
    assert "app icon dark" in icon
    assert 'rx="150"' in icon
    assert "LOCAL FLIGHT" not in icon


def test_macos_icon_fallback_draws_v2_dock_tile() -> None:
    icon = draw_macos_icon(256)

    assert icon.mode == "RGBA"
    assert icon.size == (256, 256)
    assert icon.getpixel((0, 0))[3] == 255
    assert icon.getpixel((128, 128))[3] == 255
