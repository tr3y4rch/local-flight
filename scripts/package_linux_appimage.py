#!/usr/bin/env python3
"""Package a frozen Local Flight desktop bundle as a native AppImage."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

try:
    from scripts.release_safety import (
        require_native_architecture,
        validate_elf_architecture,
        validate_public_bundle,
        write_sha256,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from release_safety import (
        require_native_architecture,
        validate_elf_architecture,
        validate_public_bundle,
        write_sha256,
    )


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
LINUX_INSTALLERS = ROOT / "installers" / "linux"


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def output_path(version: str, architecture: str) -> Path:
    return DIST / f"LocalFlight-{version}-linux-{architecture}.AppImage"


def appimagetool_path(explicit: str) -> Path:
    value = explicit.strip() or os.getenv("APPIMAGETOOL", "").strip()
    discovered = shutil.which("appimagetool") if not value else value
    if not discovered:
        raise RuntimeError(
            "appimagetool is required. Set APPIMAGETOOL to the verified native AppImageKit tool."
        )
    path = Path(discovered).resolve()
    if not path.is_file():
        raise RuntimeError(f"appimagetool does not exist: {path}")
    return path


def stage_appdir(bundle: Path, architecture: str, version: str | None = None) -> Path:
    release_version = version or project_version()
    appdir = BUILD / f"appimage-{architecture}" / "LocalFlight.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    appdir.mkdir(parents=True)

    installed_bundle = appdir / "usr" / "lib" / "localflight"
    shutil.copytree(bundle, installed_bundle, symlinks=True)
    executable = installed_bundle / "LocalFlight"
    if not executable.is_file():
        raise RuntimeError(f"Frozen desktop executable is missing: {executable}")
    bin_dir = appdir / "usr" / "bin"
    bin_dir.mkdir(parents=True)
    os.symlink("../lib/localflight/LocalFlight", bin_dir / "LocalFlight")

    desktop_source = LINUX_INSTALLERS / "cc.beacontools.localflight.desktop"
    desktop_text = desktop_source.read_text(encoding="utf-8").replace("Exec=localflight", "Exec=LocalFlight")
    desktop_root = appdir / "cc.beacontools.localflight.desktop"
    desktop_root.write_text(desktop_text, encoding="utf-8")
    applications = appdir / "usr" / "share" / "applications"
    applications.mkdir(parents=True)
    (applications / desktop_root.name).write_text(desktop_text, encoding="utf-8")

    icon_source = ROOT / "assets" / "icon.png"
    icon_root = appdir / "cc.beacontools.localflight.png"
    shutil.copy2(icon_source, icon_root)
    icon_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
    icon_dir.mkdir(parents=True)
    shutil.copy2(icon_source, icon_dir / icon_root.name)

    metadata_dir = appdir / "usr" / "share" / "localflight"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "release-metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": release_version,
                "platform": "linux",
                "architecture": architecture,
                "flavor": "desktop",
                "kind": "appimage",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    apprun = appdir / "AppRun"
    apprun.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\n'
        'exec "$HERE/usr/lib/localflight/LocalFlight" "$@"\n',
        encoding="utf-8",
    )
    apprun.chmod(0o755)
    return appdir


def build_appimage(appdir: Path, output: Path, tool: Path, architecture: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".sha256").unlink(missing_ok=True)
    tool.chmod(tool.stat().st_mode | 0o111)
    env = os.environ.copy()
    env["ARCH"] = architecture
    command = [str(tool), str(appdir), str(output)]
    if tool.name.endswith(".AppImage"):
        command.insert(1, "--appimage-extract-and-run")
    subprocess.run(command, cwd=ROOT, env=env, check=True)
    if not output.is_file():
        raise RuntimeError(f"appimagetool did not create {output}")
    output.chmod(output.stat().st_mode | 0o111)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), required=True)
    parser.add_argument("--appimagetool", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("AppImage releases must be built on Linux.")
    args = parse_args(argv)
    bundle = args.bundle_dir.resolve()
    try:
        architecture = require_native_architecture(args.target_arch)
        validate_public_bundle(bundle)
        validate_elf_architecture(bundle / "LocalFlight", architecture)
        tool = appimagetool_path(args.appimagetool)
        version = project_version()
        appdir = stage_appdir(bundle, architecture, version)
        output = output_path(version, architecture)
        build_appimage(appdir, output, tool, architecture)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    checksum = write_sha256(output)
    print(f"AppImage: {output.relative_to(ROOT)}")
    print(f"Checksum: {checksum.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
