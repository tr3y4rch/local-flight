#!/usr/bin/env python3
"""Package a frozen Local Flight desktop or server bundle as a Debian package."""
from __future__ import annotations

import argparse
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
        validate_frozen_runtime_resources,
        validate_public_bundle,
        write_sha256,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from release_safety import (
        require_native_architecture,
        validate_elf_architecture,
        validate_frozen_runtime_resources,
        validate_public_bundle,
        write_sha256,
    )


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
LINUX_INSTALLERS = ROOT / "installers" / "linux"
DEBIAN_ARCH_TO_NATIVE = {"amd64": "x86_64", "arm64": "aarch64"}


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def package_name(flavor: str) -> str:
    return "localflight-server" if flavor == "server" else "localflight-desktop"


def output_path(version: str, architecture: str, flavor: str) -> Path:
    return DIST / f"{package_name(flavor)}_{version}_{architecture}.deb"


def control_text(version: str, architecture: str, flavor: str, installed_size: int) -> str:
    package = package_name(flavor)
    if flavor == "server":
        depends = "adduser, init-system-helpers (>= 1.18~), libc6 (>= 2.35), systemd"
        description = "Local-first flight information display headless server"
    else:
        libc_floor = "2.39" if architecture == "arm64" else "2.35"
        depends = (
            f"libc6 (>= {libc_floor}), libasound2, libdbus-1-3, libegl1, libfontconfig1, "
            "libgl1, libglib2.0-0, libice6, libopengl0, libsm6, libwayland-client0, "
            "libwayland-cursor0, libwayland-egl1, libx11-6, libx11-xcb1, libxcomposite1, "
            "libxcursor1, libxext6, libxi6, libxkbcommon0, libxkbcommon-x11-0, libxrender1, "
            "libxcb1, libxcb-cursor0, libxcb-glx0, libxcb-icccm4, libxcb-image0, "
            "libxcb-keysyms1, libxcb-randr0, libxcb-render0, libxcb-render-util0, "
            "libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-util1, libxcb-xfixes0, "
            "libxcb-xinerama0, libxcb-xkb1"
        )
        description = "Local-first flight information display desktop application"
    conflict = "localflight-desktop" if flavor == "server" else "localflight-server"
    return (
        f"Package: {package}\n"
        f"Version: {version}\n"
        "Section: net\n"
        "Priority: optional\n"
        f"Architecture: {architecture}\n"
        f"Installed-Size: {installed_size}\n"
        "Maintainer: Beacon Tools <privacy@beacontools.cc>\n"
        f"Depends: {depends}\n"
        f"Conflicts: {conflict}\n"
        "Homepage: https://beacontools.cc/local-flight\n"
        f"Description: {description}\n"
        " Local Flight runs a private flight display host with LAN and mobile access.\n"
    )


def _copy_maintainer_scripts(flavor: str, debian_dir: Path) -> None:
    source = LINUX_INSTALLERS / "debian" / flavor
    for script in source.iterdir():
        if not script.is_file():
            continue
        target = debian_dir / script.name
        shutil.copy2(script, target)
        target.chmod(0o755)


def stage_package(bundle: Path, architecture: str, flavor: str, version: str) -> Path:
    root = BUILD / f"deb-{flavor}-{architecture}" / package_name(flavor)
    shutil.rmtree(root, ignore_errors=True)
    debian_dir = root / "DEBIAN"
    debian_dir.mkdir(parents=True)

    if flavor == "desktop":
        install_root = root / "opt" / "localflight"
        shutil.copytree(bundle, install_root, symlinks=True)
        executable = install_root / "LocalFlight"
        if not executable.is_file():
            raise RuntimeError(f"Frozen desktop executable is missing: {executable}")

        bin_dir = root / "usr" / "bin"
        bin_dir.mkdir(parents=True)
        os.symlink("../../opt/localflight/LocalFlight", bin_dir / "localflight")
        applications = root / "usr" / "share" / "applications"
        applications.mkdir(parents=True)
        shutil.copy2(
            LINUX_INSTALLERS / "cc.beacontools.localflight.desktop",
            applications / "cc.beacontools.localflight.desktop",
        )
        metainfo = root / "usr" / "share" / "metainfo"
        metainfo.mkdir(parents=True)
        shutil.copy2(
            LINUX_INSTALLERS / "cc.beacontools.localflight.metainfo.xml",
            metainfo / "cc.beacontools.localflight.metainfo.xml",
        )
        icons = root / "usr" / "share" / "icons" / "hicolor" / "512x512" / "apps"
        icons.mkdir(parents=True)
        shutil.copy2(ROOT / "assets" / "icon.png", icons / "cc.beacontools.localflight.png")
    else:
        install_root = root / "opt" / "localflight-server"
        shutil.copytree(bundle, install_root, symlinks=True)
        executable = install_root / "localflight-server"
        if not executable.is_file():
            raise RuntimeError(f"Frozen server executable is missing: {executable}")
        service_dir = root / "lib" / "systemd" / "system"
        service_dir.mkdir(parents=True)
        shutil.copy2(
            LINUX_INSTALLERS / "localflight-server.service",
            service_dir / "localflight-server.service",
        )

    installed_size = max(1, sum(path.stat().st_size for path in root.rglob("*") if path.is_file()) // 1024)
    (debian_dir / "control").write_text(
        control_text(version, architecture, flavor, installed_size),
        encoding="utf-8",
    )
    _copy_maintainer_scripts(flavor, debian_dir)
    return root


def build_deb(root: Path, output: Path) -> None:
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        raise RuntimeError("dpkg-deb is required to build Ubuntu/Debian packages.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".sha256").unlink(missing_ok=True)
    subprocess.run(
        [dpkg_deb, "--root-owner-group", "--build", str(root), str(output)],
        check=True,
        cwd=ROOT,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--flavor", choices=("desktop", "server"), required=True)
    parser.add_argument("--target-arch", choices=("amd64", "arm64"), required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    if not sys.platform.startswith("linux"):
        raise SystemExit("Debian releases must be built on Linux.")
    args = parse_args(argv)
    bundle = args.bundle_dir.resolve()
    try:
        require_native_architecture(DEBIAN_ARCH_TO_NATIVE[args.target_arch])
        validate_public_bundle(bundle)
        validate_frozen_runtime_resources(bundle)
        executable_name = "localflight-server" if args.flavor == "server" else "LocalFlight"
        validate_elf_architecture(
            bundle / executable_name,
            DEBIAN_ARCH_TO_NATIVE[args.target_arch],
        )
        version = project_version()
        root = stage_package(bundle, args.target_arch, args.flavor, version)
        output = output_path(version, args.target_arch, args.flavor)
        build_deb(root, output)
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    checksum = write_sha256(output)
    print(f"Debian package: {output.relative_to(ROOT)}")
    print(f"Checksum: {checksum.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
