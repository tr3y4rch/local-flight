from __future__ import annotations

import json
import os
import plistlib
import stat
from pathlib import Path

import pytest

from scripts import package_macos_installer as macos_pkg
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


def test_v2_brand_manifest_tracks_package_qt_lan_mobile_and_site() -> None:
    manifest = json.loads((ROOT / "assets" / "brand-manifest.json").read_text(encoding="utf-8"))

    assert manifest["phase"] == "package-qt-lan-mobile-site"
    assert set(manifest["masters"]) == {
        "beacon_lockup",
        "beacon_mark",
        "local_flight_dark",
        "local_flight_light",
    }
    output_paths = {entry["path"] for entry in manifest["active_outputs"]}
    assert {
        "assets/localflight-logo.svg",
        "assets/icon.png",
        "assets/icon.ico",
        "assets/icon.icns",
    }.issubset(output_paths)
    assert {
        "src/localflight/ui/static/localflight-logo.svg",
        "src/localflight/ui/static/localflight-icon.png",
        "src/localflight/ui/static/localflight-app-icon.png",
        "mobile/assets/localflight-icon.png",
        "mobile/assets/localflight-icon-dark.png",
        "mobile/assets/localflight-icon-light.png",
        "mobile/assets/localflight-logo.png",
        "mobile/assets/localflight-logo-dark.png",
        "mobile/assets/localflight-logo-light.png",
    }.issubset(output_paths)
    assert {
        "site/assets/apple-touch-icon.png",
        "site/assets/beacon-tools-icon-512.png",
        "site/assets/beacon-tools-logo.png",
        "site/assets/beacon-tools-mark-96.png",
        "site/assets/favicon.ico",
        "site/assets/favicon-32.png",
        "site/assets/localflight-lockup.png",
    }.issubset(output_paths)


def test_v2_brand_module_outputs_are_sanitized() -> None:
    assets_dir = ROOT / "assets"
    static_dir = ROOT / "src" / "localflight" / "ui" / "static"
    mobile_dir = ROOT / "mobile" / "assets"

    assert sorted(path.name for path in assets_dir.glob("icon*")) == [
        "icon.icns",
        "icon.ico",
        "icon.iconset",
        "icon.png",
    ]
    assert sorted(path.name for path in assets_dir.glob("localflight-logo*")) == ["localflight-logo.svg"]

    assert sorted(path.name for path in static_dir.glob("localflight-logo*.svg")) == ["localflight-logo.svg"]
    assert sorted(path.name for path in static_dir.glob("localflight-logo*.png")) == []
    assert sorted(path.name for path in static_dir.glob("localflight-icon*.png")) == ["localflight-icon.png"]
    assert sorted(path.name for path in static_dir.glob("localflight-app-icon*.png")) == ["localflight-app-icon.png"]
    assert not (static_dir / "brand").exists()

    assert sorted(path.name for path in mobile_dir.glob("localflight-logo*")) == [
        "localflight-logo-dark.png",
        "localflight-logo-light.png",
        "localflight-logo.png",
    ]
    assert sorted(path.name for path in mobile_dir.glob("localflight-icon*")) == [
        "localflight-icon-dark.png",
        "localflight-icon-light.png",
        "localflight-icon.png",
    ]

    active_svgs = [
        ROOT / "assets" / "localflight-logo.svg",
        static_dir / "localflight-logo.svg",
    ]
    for path in active_svgs:
        text = path.read_text(encoding="utf-8")
        assert "Local Flight master logo" not in text
        assert "Rounded airport display tile" not in text
        assert "version-B mark" not in text
        assert "app icon dark" in text


def test_mobile_brand_config_has_light_and_dark_master_variants() -> None:
    app_config = json.loads((ROOT / "mobile" / "app.json").read_text(encoding="utf-8"))
    plugins = app_config["expo"]["plugins"]
    splash_plugin = next(plugin for plugin in plugins if isinstance(plugin, list) and plugin[0] == "expo-splash-screen")
    splash_config = splash_plugin[1]

    assert app_config["expo"]["icon"] == "./assets/localflight-icon.png"
    assert splash_config["backgroundColor"] == "#f5f9fc"
    assert splash_config["image"] == "./assets/localflight-logo-light.png"
    assert splash_config["dark"]["backgroundColor"] == "#080c12"
    assert splash_config["dark"]["image"] == "./assets/localflight-logo-dark.png"
    assert (ROOT / "mobile" / "assets" / "localflight-icon-dark.png").read_bytes() != (
        ROOT / "mobile" / "assets" / "localflight-icon-light.png"
    ).read_bytes()


def test_macos_pkg_requires_all_release_credentials() -> None:
    with pytest.raises(RuntimeError) as exc_info:
        macos_pkg.require_release_credentials({})

    message = str(exc_info.value)
    assert "CODESIGN_IDENTITY" in message
    assert "PKG_SIGN_IDENTITY" in message
    assert "NOTARIZE_PROFILE" in message

    values = macos_pkg.require_release_credentials(
        {
            "CODESIGN_IDENTITY": "Developer ID Application: Example",
            "PKG_SIGN_IDENTITY": "Developer ID Installer: Example",
            "NOTARIZE_PROFILE": "localflight-notary",
        }
    )
    assert values["CODESIGN_IDENTITY"].startswith("Developer ID Application:")
    assert values["PKG_SIGN_IDENTITY"].startswith("Developer ID Installer:")
    assert values["NOTARIZE_PROFILE"] == "localflight-notary"


def test_macos_pkg_paths_are_dau_installer_paths(tmp_path: Path) -> None:
    assert macos_pkg.package_output_path(tmp_path, "0.2.7").name == "LocalFlight-0.2.7-macos.pkg"
    assert macos_pkg.staged_app_path(tmp_path).as_posix().endswith("/Applications/Local Flight.app")
    assert macos_pkg.APP_BUNDLE_NAME == "Local Flight.app"
    assert macos_pkg.LEGACY_APP_BUNDLE_NAME == "LocalFlight.app"
    assert macos_pkg.BUNDLE_IDENTIFIER == "com.localflight.app"


def test_macos_pkg_preinstall_only_cleans_matching_legacy_bundle(tmp_path: Path) -> None:
    preinstall = macos_pkg.write_preinstall_script(tmp_path)
    script = preinstall.read_text(encoding="utf-8")

    if os.name != "nt":
        assert preinstall.stat().st_mode & stat.S_IXUSR
    assert 'LEGACY_APP="/Applications/LocalFlight.app"' in script
    assert 'EXPECTED_ID="com.localflight.app"' in script
    assert "PlistBuddy -c 'Print :CFBundleIdentifier'" in script
    assert 'if [ "$FOUND_ID" = "$EXPECTED_ID" ]; then' in script
    assert 'rm -rf "$LEGACY_APP"' in script
    assert "~/.localflight" not in script


def test_build_script_routes_platform_installers() -> None:
    build_script = (ROOT / "build.py").read_text(encoding="utf-8")

    assert "package_windows_installer.py" in build_script
    assert "package_macos_installer.py" in build_script
    assert "For public macOS releases" in build_script
    assert "LocalFlight-macos.zip" in build_script
    assert "LocalFlight-{version}-macos.pkg" in (
        ROOT / "scripts" / "package_macos_installer.py"
    ).read_text(encoding="utf-8")
