#!/usr/bin/env python3
"""Inspect one finished release package and emit a CI-only hash attestation.

The JSON record is uploaded as a workflow artifact, never as a public release
asset. The final assembly job binds the inspected version, architecture, and
flavor to the exact package SHA-256 before it creates the draft release.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

try:
    from scripts.release_safety import validate_elf_architecture
    from scripts.verify_release_artifacts import (
        ArtifactContract,
        artifact_contracts,
        attestation_name,
        inspection_method,
        project_version,
        sha256_file,
        verify_checksum,
    )
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    from release_safety import validate_elf_architecture
    from verify_release_artifacts import (
        ArtifactContract,
        artifact_contracts,
        attestation_name,
        inspection_method,
        project_version,
        sha256_file,
        verify_checksum,
    )


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_IDENTIFIER = "com.localflight.app.pkg"
BUNDLE_IDENTIFIER = "com.localflight.app"
ARCH_ALIASES = {"amd64": "x86_64", "arm64": "aarch64"}


def contract_for_artifact(path: Path, version: str) -> ArtifactContract:
    matches = [contract for contract in artifact_contracts(version) if contract.name == path.name]
    if len(matches) != 1:
        raise RuntimeError(f"Artifact is not in the {version} public matrix: {path.name}")
    return matches[0]


def release_identity(contract: ArtifactContract, version: str) -> dict[str, str]:
    return {
        "version": version,
        "platform": contract.platform,
        "architecture": contract.architecture,
        "flavor": contract.flavor,
        "kind": contract.kind,
    }


def embedded_metadata(contract: ArtifactContract, version: str) -> dict[str, Any]:
    return {"schema_version": 1, **release_identity(contract, version)}


def _read_json_bytes(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Malformed embedded release metadata: {label}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Malformed embedded release metadata: {label}")
    return value


def _require_embedded_metadata(
    value: dict[str, Any],
    contract: ArtifactContract,
    version: str,
    label: str,
) -> None:
    expected = embedded_metadata(contract, version)
    if value != expected:
        raise RuntimeError(
            f"Embedded release identity mismatch in {label}: expected {expected}, got {value}"
        )


def _run_output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()


def inspect_debian(artifact: Path, contract: ArtifactContract, version: str) -> None:
    dpkg_deb = shutil.which("dpkg-deb")
    if not dpkg_deb:
        raise RuntimeError("dpkg-deb is required to inspect Debian packages")
    expected_package = "localflight-server" if contract.flavor == "server" else "localflight-desktop"
    expected_debian_arch = "arm64" if contract.architecture == "aarch64" else "amd64"
    fields = {
        name: _run_output([dpkg_deb, "--field", str(artifact), name])
        for name in ("Package", "Version", "Architecture")
    }
    expected_fields = {
        "Package": expected_package,
        "Version": version,
        "Architecture": expected_debian_arch,
    }
    if fields != expected_fields:
        raise RuntimeError(f"Debian package metadata mismatch: expected {expected_fields}, got {fields}")

    with tempfile.TemporaryDirectory(prefix="localflight-deb-attest-") as temporary:
        root = Path(temporary) / "root"
        subprocess.run([dpkg_deb, "--extract", str(artifact), str(root)], check=True)
        executable = (
            root / "opt" / "localflight-server" / "localflight-server"
            if contract.flavor == "server"
            else root / "opt" / "localflight" / "LocalFlight"
        )
        validate_elf_architecture(executable, contract.architecture)


def inspect_appimage(artifact: Path, contract: ArtifactContract, version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="localflight-appimage-attest-") as temporary:
        work = Path(temporary)
        subprocess.run(
            [str(artifact), "--appimage-extract"],
            cwd=work,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        extracted = work / "squashfs-root"
        metadata_path = extracted / "usr" / "share" / "localflight" / "release-metadata.json"
        if not metadata_path.is_file():
            raise RuntimeError("AppImage is missing embedded release metadata")
        metadata = _read_json_bytes(metadata_path.read_bytes(), str(metadata_path.relative_to(extracted)))
        _require_embedded_metadata(metadata, contract, version, "AppImage")
        validate_elf_architecture(
            extracted / "usr" / "lib" / "localflight" / "LocalFlight",
            contract.architecture,
        )


def _macos_architecture(value: str) -> str:
    normalized = ARCH_ALIASES.get(value, value)
    if normalized not in {"x86_64", "aarch64"}:
        raise RuntimeError(f"Unsupported Mach-O architecture: {value}")
    return normalized


def inspect_macos_pkg(artifact: Path, contract: ArtifactContract, version: str) -> None:
    if not shutil.which("pkgutil") or not shutil.which("lipo"):
        raise RuntimeError("pkgutil and lipo are required to inspect macOS packages")
    with tempfile.TemporaryDirectory(prefix="localflight-pkg-attest-") as temporary:
        expanded = Path(temporary) / "expanded"
        subprocess.run(["pkgutil", "--expand-full", str(artifact), str(expanded)], check=True)

        package_versions: list[str] = []
        for package_info in expanded.rglob("PackageInfo"):
            try:
                root = ET.parse(package_info).getroot()
            except ET.ParseError as exc:
                raise RuntimeError(f"Malformed PackageInfo in {artifact.name}") from exc
            if root.attrib.get("identifier") == PACKAGE_IDENTIFIER:
                package_versions.append(root.attrib.get("version", ""))
        if package_versions != [version]:
            raise RuntimeError(
                f"macOS package version mismatch: expected one {version!r}, got {package_versions!r}"
            )

        app_plists: list[tuple[Path, dict[str, Any]]] = []
        for info_path in expanded.rglob("Info.plist"):
            try:
                info = plistlib.loads(info_path.read_bytes())
            except (OSError, plistlib.InvalidFileException):
                continue
            if isinstance(info, dict) and info.get("CFBundleIdentifier") == BUNDLE_IDENTIFIER:
                app_plists.append((info_path, info))
        if len(app_plists) != 1:
            raise RuntimeError(f"Expected one Local Flight app in {artifact.name}, found {len(app_plists)}")
        info_path, info = app_plists[0]
        if info.get("CFBundleShortVersionString") != version or info.get("CFBundleVersion") != version:
            raise RuntimeError(f"macOS app version mismatch in {artifact.name}")
        executable = info_path.parent / "MacOS" / "LocalFlight"
        if not executable.is_file():
            raise RuntimeError(f"macOS package is missing its app executable: {artifact.name}")
        slices = {_macos_architecture(value) for value in _run_output(["lipo", "-archs", str(executable)]).split()}
        if slices != {contract.architecture}:
            raise RuntimeError(
                f"macOS package architecture mismatch: expected {contract.architecture}, got {sorted(slices)}"
            )


def _pe_strings(path: Path) -> tuple[int, dict[str, str]]:
    try:
        import pefile
    except ImportError as exc:  # pragma: no cover - release lock supplies pefile on Windows
        raise RuntimeError("pefile is required to inspect Windows release binaries") from exc

    image = pefile.PE(str(path), fast_load=False)
    try:
        values: dict[str, str] = {}
        for group in getattr(image, "FileInfo", []) or []:
            entries = group if isinstance(group, list) else [group]
            for entry in entries:
                if getattr(entry, "Key", b"") != b"StringFileInfo":
                    continue
                for table in getattr(entry, "StringTable", []) or []:
                    for key, value in table.entries.items():
                        decoded_key = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
                        decoded_value = (
                            value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
                        )
                        values[decoded_key] = decoded_value.rstrip("\0")
        return int(image.FILE_HEADER.Machine), values
    finally:
        image.close()


def _version_matches(actual: str, expected: str) -> bool:
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", actual):
        return False
    actual_parts = tuple(int(part) for part in actual.split("."))
    expected_parts = tuple(int(part) for part in expected.split("."))
    return actual_parts[: len(expected_parts)] == expected_parts and all(
        part == 0 for part in actual_parts[len(expected_parts) :]
    )


def inspect_windows_installer(
    artifact: Path,
    payload: Path | None,
    contract: ArtifactContract,
    version: str,
) -> None:
    if payload is None:
        raise RuntimeError("Windows installer attestation requires --payload-executable")
    if not payload.is_file():
        raise RuntimeError(f"Frozen Windows payload is missing: {payload}")
    _, installer_strings = _pe_strings(artifact)
    payload_machine, payload_strings = _pe_strings(payload)
    if payload_machine != 0x8664:
        raise RuntimeError(f"Frozen Windows payload is not x86-64: PE machine {payload_machine:#x}")
    for label, values in (("installer", installer_strings), ("payload", payload_strings)):
        actual = values.get("ProductVersion", "")
        if not _version_matches(actual, version):
            raise RuntimeError(f"Windows {label} ProductVersion mismatch: {actual!r}")
    if contract.architecture != "x86_64":  # defensive: only one Windows contract exists
        raise RuntimeError(f"Unsupported Windows architecture contract: {contract.architecture}")


def inspect_pi_source(artifact: Path, contract: ArtifactContract, version: str) -> None:
    try:
        archive = zipfile.ZipFile(artifact)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(f"Malformed Raspberry Pi source archive: {artifact.name}") from exc
    with archive:
        metadata_names = [name for name in archive.namelist() if name.endswith("/release-metadata.json")]
        pyproject_names = [name for name in archive.namelist() if name.endswith("/pyproject.toml")]
        if len(metadata_names) != 1 or len(pyproject_names) != 1:
            raise RuntimeError("Pi source archive must contain one metadata file and one pyproject.toml")
        metadata = _read_json_bytes(archive.read(metadata_names[0]), metadata_names[0])
        _require_embedded_metadata(metadata, contract, version, "Raspberry Pi source archive")
        try:
            source_version = str(tomllib.loads(archive.read(pyproject_names[0]).decode("utf-8"))["project"]["version"])
        except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
            raise RuntimeError("Pi source archive has malformed project metadata") from exc
        if source_version != version:
            raise RuntimeError(
                f"Pi source version mismatch: expected {version}, found {source_version}"
            )


def inspect_artifact(
    artifact: Path,
    contract: ArtifactContract,
    version: str,
    *,
    payload_executable: Path | None = None,
) -> None:
    if contract.kind == "deb":
        inspect_debian(artifact, contract, version)
    elif contract.kind == "appimage":
        inspect_appimage(artifact, contract, version)
    elif contract.kind == "pkg":
        inspect_macos_pkg(artifact, contract, version)
    elif contract.kind == "installer":
        inspect_windows_installer(artifact, payload_executable, contract, version)
    elif contract.kind == "zip":
        inspect_pi_source(artifact, contract, version)
    else:  # pragma: no cover - contracts are closed above
        raise RuntimeError(f"No inspector for release kind: {contract.kind}")


def create_attestation(
    artifact: Path,
    output_directory: Path,
    *,
    source_sha: str,
    payload_executable: Path | None = None,
) -> Path:
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise RuntimeError("Source SHA must be a full lowercase Git commit SHA")
    artifact = artifact.resolve()
    output_directory = output_directory.resolve()
    if not artifact.is_file():
        raise RuntimeError(f"Release artifact is missing: {artifact}")
    version = project_version()
    contract = contract_for_artifact(artifact, version)
    checksum = artifact.with_suffix(artifact.suffix + ".sha256")
    if not checksum.is_file():
        raise RuntimeError(f"Release checksum is missing: {checksum.name}")
    try:
        verify_checksum(artifact, checksum)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    artifact_sha256 = sha256_file(artifact)
    inspect_artifact(
        artifact,
        contract,
        version,
        payload_executable=payload_executable.resolve() if payload_executable else None,
    )
    try:
        verify_checksum(artifact, checksum)
    except ValueError as exc:
        raise RuntimeError(f"Artifact changed while it was being inspected: {exc}") from exc
    final_sha256 = sha256_file(artifact)
    if final_sha256 != artifact_sha256:
        raise RuntimeError("Artifact changed while it was being inspected")

    record = {
        "schema_version": 1,
        "source_sha": source_sha,
        "artifact": {
            "name": artifact.name,
            "sha256": artifact_sha256,
            "size": artifact.stat().st_size,
        },
        "release": release_identity(contract, version),
        "inspection": {"method": inspection_method(contract)},
    }
    output_directory.mkdir(parents=True, exist_ok=True)
    output = output_directory / attestation_name(artifact.name)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--payload-executable", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        current_sha = _run_output(["git", "rev-parse", "HEAD"])
        if current_sha != args.source_sha:
            raise RuntimeError(
                f"Attestation source mismatch: checked out {current_sha}, expected {args.source_sha}"
            )
        output = create_attestation(
            args.artifact,
            args.output_dir,
            source_sha=args.source_sha,
            payload_executable=args.payload_executable,
        )
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Release attestation: {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
