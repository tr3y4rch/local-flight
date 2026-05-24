#!/usr/bin/env python3
"""Build the signed/notarized macOS installer package.

This script expects ``dist/LocalFlight.app`` to already exist from PyInstaller.
It signs that app, stages it as ``/Applications/Local Flight.app``, builds a
signed product package, notarizes the package, staples the ticket, and writes a
SHA256 file beside the final artifact.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
BUILD = ROOT / "build"

PYINSTALLER_APP = DIST / "LocalFlight.app"
APP_BUNDLE_NAME = "Local Flight.app"
LEGACY_APP_BUNDLE_NAME = "LocalFlight.app"
BUNDLE_IDENTIFIER = "com.localflight.app"
PACKAGE_IDENTIFIER = "com.localflight.app.pkg"
REQUIRED_ENV_VARS = ("CODESIGN_IDENTITY", "PKG_SIGN_IDENTITY", "NOTARIZE_PROFILE")


def project_version() -> str:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python <3.11 fallback
        import tomli as tomllib  # type: ignore

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def package_output_path(dist: Path, version: str) -> Path:
    return dist / f"LocalFlight-{version}-macos.pkg"


def staged_app_path(pkg_root: Path) -> Path:
    return pkg_root / "Applications" / APP_BUNDLE_NAME


def require_release_credentials(env: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if env is None else env
    values = {name: source.get(name, "").strip() for name in REQUIRED_ENV_VARS}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing macOS signing/notarization env vars: "
            + ", ".join(missing)
            + ". Set Developer ID Application, Developer ID Installer, and notarytool profile values before building a public .pkg."
        )
    return values


def run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print("  " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def write_preinstall_script(scripts_dir: Path) -> Path:
    scripts_dir.mkdir(parents=True, exist_ok=True)
    preinstall = scripts_dir / "preinstall"
    preinstall.write_text(
        f"""#!/bin/sh
set -eu

LEGACY_APP="/Applications/{LEGACY_APP_BUNDLE_NAME}"
EXPECTED_ID="{BUNDLE_IDENTIFIER}"

if [ -d "$LEGACY_APP" ]; then
    FOUND_ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$LEGACY_APP/Contents/Info.plist" 2>/dev/null || true)"
    if [ "$FOUND_ID" = "$EXPECTED_ID" ]; then
        rm -rf "$LEGACY_APP"
    fi
fi

exit 0
""",
        encoding="utf-8",
    )
    preinstall.chmod(0o755)
    return preinstall


def sign_app(app: Path, identity: str) -> None:
    entitlements = ROOT / "assets" / "entitlements.plist"
    cmd = [
        "codesign",
        "--deep",
        "--force",
        "--timestamp",
        "--options",
        "runtime",
        "--sign",
        identity,
    ]
    if entitlements.exists():
        cmd.extend(["--entitlements", str(entitlements)])
    cmd.append(str(app))
    run(cmd)
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=1", str(app)])


def stage_app(app: Path, pkg_root: Path) -> Path:
    target = staged_app_path(pkg_root)
    shutil.rmtree(pkg_root, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    run(["ditto", str(app), str(target)])
    return target


def build_component_pkg(pkg_root: Path, scripts_dir: Path, version: str) -> Path:
    component_pkg = BUILD / "LocalFlight-macos-component.pkg"
    component_pkg.unlink(missing_ok=True)
    run(
        [
            "pkgbuild",
            "--root",
            str(pkg_root),
            "--identifier",
            PACKAGE_IDENTIFIER,
            "--version",
            version,
            "--install-location",
            "/",
            "--scripts",
            str(scripts_dir),
            str(component_pkg),
        ]
    )
    return component_pkg


def build_signed_product_pkg(component_pkg: Path, output_pkg: Path, identity: str) -> None:
    output_pkg.unlink(missing_ok=True)
    run(["productbuild", "--package", str(component_pkg), "--sign", identity, str(output_pkg)])
    run(["pkgutil", "--check-signature", str(output_pkg)])


def notarize_and_staple(pkg: Path, profile: str) -> None:
    run(["xcrun", "notarytool", "submit", str(pkg), "--keychain-profile", profile, "--wait"])
    run(["xcrun", "stapler", "staple", str(pkg)])
    run(["xcrun", "stapler", "validate", str(pkg)])
    run(["spctl", "-a", "-vv", "-t", "install", str(pkg)])


def write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum_path


def main() -> None:
    if sys.platform != "darwin":
        raise SystemExit("The macOS installer can only be built on macOS.")
    if not PYINSTALLER_APP.exists():
        raise SystemExit(f"Missing PyInstaller app bundle: {PYINSTALLER_APP}")

    try:
        env = require_release_credentials()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    version = project_version()
    pkg_root = BUILD / "macos-pkg-root"
    scripts_dir = BUILD / "macos-pkg-scripts"
    output_pkg = package_output_path(DIST, version)

    print(f"Building signed macOS installer package v{version}")
    sign_app(PYINSTALLER_APP, env["CODESIGN_IDENTITY"])
    stage_app(PYINSTALLER_APP, pkg_root)
    write_preinstall_script(scripts_dir)
    component_pkg = build_component_pkg(pkg_root, scripts_dir, version)
    build_signed_product_pkg(component_pkg, output_pkg, env["PKG_SIGN_IDENTITY"])
    notarize_and_staple(output_pkg, env["NOTARIZE_PROFILE"])
    checksum = write_sha256(output_pkg)

    print(f"\nDone: {output_pkg.relative_to(ROOT)}")
    print(f"Checksum: {checksum.relative_to(ROOT)}")
    print("Distribute: upload the .pkg and .pkg.sha256; users double-click the installer.")


if __name__ == "__main__":
    main()
