#!/usr/bin/env python3
"""Build a Local Flight release bundle for the current native platform.

Public artifacts are always built on their matching operating system and CPU.
The script deliberately refuses cross-compilation and never installs or
rewrites dependencies/assets. CI and release operators must first install the
checked-in hash-pinned release requirements.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
REQUIREMENTS = ROOT / "requirements"

ARCH_ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}


@dataclass(frozen=True)
class BuildTarget:
    platform: str
    architecture: str
    flavor: str
    artifact: str

    @property
    def build_key(self) -> str:
        return f"{self.platform}-{self.architecture}-{self.flavor}"

    @property
    def bundle_name(self) -> str:
        return "localflight-server" if self.flavor == "server" else "LocalFlight"


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def host_platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    raise SystemExit(f"Unsupported build platform: {sys.platform}")


def normalize_architecture(value: str) -> str:
    normalized = ARCH_ALIASES.get(value.strip().lower())
    if normalized is None:
        raise ValueError(f"Unsupported architecture: {value}")
    return normalized


def host_architecture() -> str:
    try:
        return normalize_architecture(platform.machine())
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def validate_target(target: BuildTarget, *, actual_arch: str | None = None) -> None:
    host_arch = actual_arch or host_architecture()
    if target.architecture != host_arch:
        raise ValueError(
            "Cross-compilation is not supported: "
            f"requested {target.architecture}, running on {host_arch}."
        )
    if target.platform == "windows":
        if target.architecture != "x86_64" or target.flavor != "desktop":
            raise ValueError("Windows releases support the x86-64 desktop flavor only.")
        allowed = {"bundle", "installer"}
    elif target.platform == "macos":
        if target.flavor != "desktop":
            raise ValueError("macOS releases support the desktop flavor only.")
        allowed = {"bundle", "installer"}
    else:
        allowed = {"bundle", "deb"} if target.flavor == "server" else {
            "bundle",
            "appimage",
            "deb",
            "linux-release",
        }
    if target.artifact not in allowed:
        raise ValueError(
            f"Artifact {target.artifact!r} is not valid for "
            f"{target.platform}/{target.flavor}; choose one of {sorted(allowed)}."
        )


def lock_path(flavor: str) -> Path:
    return REQUIREMENTS / ("release-server.txt" if flavor == "server" else "release-native.txt")


def _locked_requirements(path: Path) -> list[Requirement]:
    requirements: list[Requirement] = []
    logical = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        logical += line.removesuffix("\\").strip() + " "
        if line.endswith("\\"):
            continue
        requirement_text = logical.split("--hash=", 1)[0].strip()
        logical = ""
        if requirement_text:
            requirements.append(Requirement(requirement_text))
    return requirements


def validate_release_environment(flavor: str) -> None:
    path = lock_path(flavor)
    if not path.exists():
        raise SystemExit(f"Missing release lock: {path.relative_to(ROOT)}")
    missing_or_wrong: list[str] = []
    for requirement in _locked_requirements(path):
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing_or_wrong.append(f"{requirement.name} is not installed")
            continue
        if requirement.specifier and installed not in requirement.specifier:
            missing_or_wrong.append(
                f"{requirement.name}=={installed} does not match {requirement.specifier}"
            )
    try:
        installed_project = importlib.metadata.version("localflight")
    except importlib.metadata.PackageNotFoundError:
        installed_project = ""
    if installed_project != project_version():
        missing_or_wrong.append(
            f"localflight metadata is {installed_project or 'missing'}, expected {project_version()}"
        )
    if missing_or_wrong:
        details = "\n  - ".join(missing_or_wrong)
        raise SystemExit(
            "Release environment does not match the checked-in lock:\n"
            f"  - {details}\n"
            f"Install with: python -m pip install --require-hashes -r {path.relative_to(ROOT)}"
        )
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True, cwd=ROOT)


def validate_release_inputs(version: str, target: BuildTarget) -> None:
    required = [
        ROOT / "assets" / "icon.png",
        ROOT / "docs" / f"release-notes-{version}.md",
    ]
    if target.platform == "windows":
        required.append(ROOT / "assets" / "icon.ico")
    if target.platform == "macos":
        required.append(ROOT / "assets" / "icon.icns")
    missing = [path.relative_to(ROOT).as_posix() for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing release inputs: " + ", ".join(missing))


def write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    output = path.with_suffix(path.suffix + ".sha256")
    output.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return output


def build_bundle(target: BuildTarget, *, clean: bool) -> Path:
    bundle_root = DIST / "bundles" / target.build_key
    work_root = BUILD / "pyinstaller" / target.build_key
    if clean:
        shutil.rmtree(bundle_root, ignore_errors=True)
        shutil.rmtree(work_root, ignore_errors=True)
    bundle_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["LOCALFLIGHT_BUILD_FLAVOR"] = target.flavor
    spec_architecture = (
        "arm64"
        if target.platform == "macos" and target.architecture == "aarch64"
        else target.architecture
    )
    env["LOCALFLIGHT_TARGET_ARCH"] = spec_architecture
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "LocalFlight.spec",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(bundle_root),
        "--workpath",
        str(work_root),
    ]
    if target.platform == "macos":
        command.extend(["--target-architecture", spec_architecture])
    subprocess.run(command, check=True, cwd=ROOT, env=env)

    bundle = bundle_root / ("LocalFlight.app" if target.platform == "macos" else target.bundle_name)
    if not bundle.exists():
        raise SystemExit(f"PyInstaller did not create expected bundle: {bundle}")
    return bundle


def package_artifacts(target: BuildTarget, bundle: Path, version: str) -> list[Path]:
    if target.artifact == "bundle":
        return [bundle]
    if target.platform == "windows":
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "package_windows_installer.py"),
                "--app-dir",
                str(bundle),
            ],
            check=True,
            cwd=ROOT,
        )
        return [DIST / f"LocalFlight-{version}-Setup.exe"]
    if target.platform == "macos":
        mac_arch = "arm64" if target.architecture == "aarch64" else "x86_64"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "package_macos_installer.py"),
                "--app",
                str(bundle),
                "--target-arch",
                mac_arch,
            ],
            check=True,
            cwd=ROOT,
        )
        return [DIST / f"LocalFlight-{version}-macos-{mac_arch}.pkg"]

    outputs: list[Path] = []
    public_arch = target.architecture
    deb_arch = "amd64" if public_arch == "x86_64" else "arm64"
    if target.artifact in {"appimage", "linux-release"}:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "package_linux_appimage.py"),
                "--bundle-dir",
                str(bundle),
                "--target-arch",
                public_arch,
            ],
            check=True,
            cwd=ROOT,
        )
        outputs.append(DIST / f"LocalFlight-{version}-linux-{public_arch}.AppImage")
    if target.artifact in {"deb", "linux-release"}:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "package_linux_deb.py"),
                "--bundle-dir",
                str(bundle),
                "--flavor",
                target.flavor,
                "--target-arch",
                deb_arch,
            ],
            check=True,
            cwd=ROOT,
        )
        package = "localflight-server" if target.flavor == "server" else "localflight-desktop"
        outputs.append(DIST / f"{package}_{version}_{deb_arch}.deb")
    return outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        choices=("bundle", "installer", "appimage", "deb", "linux-release"),
        default="bundle",
    )
    parser.add_argument("--flavor", choices=("desktop", "server"), default="desktop")
    parser.add_argument("--target-arch", default=host_architecture())
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    target = BuildTarget(
        platform=host_platform(),
        architecture=normalize_architecture(args.target_arch),
        flavor=args.flavor,
        artifact=args.artifact,
    )
    try:
        validate_target(target)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    version = project_version()
    validate_release_inputs(version, target)
    validate_release_environment(target.flavor)
    bundle = build_bundle(target, clean=args.clean)
    outputs = package_artifacts(target, bundle, version)
    print(f"Built {target.build_key} from locked dependencies.")
    for output in outputs:
        print(f"  {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
