#!/usr/bin/env python3
"""Build the signed/notarized macOS installer package.

This script expects ``dist/LocalFlight.app`` to already exist from PyInstaller.
It signs that app, stages it as ``/Applications/Local Flight.app``, builds a
signed product package, notarizes the package, staples the ticket, and writes a
SHA256 file beside the final artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from scripts.release_safety import validate_frozen_runtime_resources, validate_public_bundle
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from release_safety import validate_frozen_runtime_resources, validate_public_bundle

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


def package_output_path(dist: Path, version: str, architecture: str) -> Path:
    return dist / f"LocalFlight-{version}-macos-{architecture}.pkg"


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
    if not values["CODESIGN_IDENTITY"].startswith("Developer ID Application:"):
        raise RuntimeError("CODESIGN_IDENTITY must be a Developer ID Application identity.")
    if not values["PKG_SIGN_IDENTITY"].startswith("Developer ID Installer:"):
        raise RuntimeError("PKG_SIGN_IDENTITY must be a Developer ID Installer identity.")
    return values


def run(cmd: list[str], *, cwd: Path = ROOT) -> None:
    print("  " + " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def run_output(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, cwd=ROOT, text=True, stderr=subprocess.STDOUT)


def native_architecture() -> str:
    machine = platform.machine().strip().lower()
    aliases = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}
    try:
        return aliases[machine]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported macOS build architecture: {machine}") from exc


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


def _deployment_targets(build_info: str) -> list[str]:
    """Read modern and legacy macOS deployment targets from ``vtool`` output."""
    targets: list[str] = []
    load_command: str | None = None
    version_pattern = re.compile(r"[0-9]+(?:\.[0-9]+){1,2}")

    for raw_line in build_info.splitlines():
        line = raw_line.strip()
        if re.fullmatch(r"Load command\s+\d+", line):
            load_command = None
            continue
        if line.startswith("cmd "):
            load_command = line.removeprefix("cmd ").strip()
            continue

        field, _, value = line.partition(" ")
        value = value.strip()
        if not version_pattern.fullmatch(value):
            continue
        if load_command == "LC_BUILD_VERSION" and field == "minos":
            targets.append(value)
        elif load_command == "LC_VERSION_MIN_MACOSX" and field == "version":
            # Older Intel Mach-O slices encode the deployment floor here rather
            # than in LC_BUILD_VERSION's ``minos`` field.
            targets.append(value)

    return targets


def validate_macos_bundle(
    app: Path,
    architecture: str,
    *,
    maximum_deployment_target: str = "12.0",
) -> list[Path]:
    """Require every bundled Mach-O to be single-architecture and macOS 12 compatible."""
    executable = app / "Contents" / "MacOS" / "LocalFlight"
    if not executable.is_file():
        raise RuntimeError(f"Missing app executable: {executable}")

    mach_o_files: list[Path] = []
    for candidate in sorted(path for path in app.rglob("*") if path.is_file() and not path.is_symlink()):
        description = run_output(["file", "-b", str(candidate)])
        if "Mach-O" in description:
            mach_o_files.append(candidate)
    if executable not in mach_o_files:
        raise RuntimeError("The app executable is not a Mach-O binary.")

    max_target = _version_tuple(maximum_deployment_target)
    for binary in mach_o_files:
        architectures = set(run_output(["lipo", "-archs", str(binary)]).split())
        if architectures != {architecture}:
            relative = binary.relative_to(app)
            raise RuntimeError(
                f"Unexpected Mach-O slices in {relative}: {sorted(architectures)}; "
                f"expected only {architecture}."
            )
        build_info = run_output(["xcrun", "vtool", "-show-build", str(binary)])
        targets = _deployment_targets(build_info)
        if not targets:
            relative = binary.relative_to(app)
            raise RuntimeError(f"Could not read a deployment target from {relative}.")
        too_new = [target for target in targets if _version_tuple(target) > max_target]
        if too_new:
            relative = binary.relative_to(app)
            raise RuntimeError(
                f"{relative} requires macOS {max(too_new, key=_version_tuple)}, "
                f"which exceeds the {maximum_deployment_target} release promise."
            )
    return mach_o_files


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=PYINSTALLER_APP)
    parser.add_argument("--target-arch", choices=("arm64", "x86_64"), required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    app = args.app.resolve()
    if sys.platform != "darwin":
        raise SystemExit("The macOS installer can only be built on macOS.")
    if not app.exists():
        raise SystemExit(f"Missing PyInstaller app bundle: {app}")
    try:
        actual_arch = native_architecture()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    if actual_arch != args.target_arch:
        raise SystemExit(
            f"Refusing cross-architecture package: requested {args.target_arch}, running on {actual_arch}."
        )

    try:
        env = require_release_credentials()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        validate_public_bundle(app)
        validate_frozen_runtime_resources(app)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

    version = project_version()
    pkg_root = BUILD / f"macos-pkg-root-{args.target_arch}"
    scripts_dir = BUILD / f"macos-pkg-scripts-{args.target_arch}"
    output_pkg = package_output_path(DIST, version, args.target_arch)

    print(f"Building signed macOS {args.target_arch} installer package v{version}")
    try:
        validated = validate_macos_bundle(app, args.target_arch)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"  Validated {len(validated)} Mach-O files for {args.target_arch} / macOS 12")
    sign_app(app, env["CODESIGN_IDENTITY"])
    staged_app = stage_app(app, pkg_root)
    validate_macos_bundle(staged_app, args.target_arch)
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
