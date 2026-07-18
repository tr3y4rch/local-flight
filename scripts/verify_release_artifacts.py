#!/usr/bin/env python3
"""Verify the complete Local Flight release artifact/checksum matrix."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ArtifactContract:
    """Expected identity carried by one public release package."""

    name: str
    platform: str
    architecture: str
    flavor: str
    kind: str


INSPECTION_METHODS = {
    "installer": "windows-installer-and-frozen-payload-pe-v1",
    "pkg": "macos-expanded-pkg-bundle-and-mach-o-v1",
    "appimage": "appimage-extracted-metadata-and-elf-v1",
    "deb": "debian-control-and-extracted-elf-v1",
    "zip": "pi-source-embedded-metadata-v1",
}


def inspection_method(contract: ArtifactContract) -> str:
    return INSPECTION_METHODS[contract.kind]


def project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def artifact_contracts(version: str) -> tuple[ArtifactContract, ...]:
    return (
        ArtifactContract(f"LocalFlight-{version}-Setup.exe", "windows", "x86_64", "desktop", "installer"),
        ArtifactContract(f"LocalFlight-{version}-macos-arm64.pkg", "macos", "aarch64", "desktop", "pkg"),
        ArtifactContract(f"LocalFlight-{version}-macos-x86_64.pkg", "macos", "x86_64", "desktop", "pkg"),
        ArtifactContract(
            f"LocalFlight-{version}-linux-x86_64.AppImage",
            "linux",
            "x86_64",
            "desktop",
            "appimage",
        ),
        ArtifactContract(
            f"LocalFlight-{version}-linux-aarch64.AppImage",
            "linux",
            "aarch64",
            "desktop",
            "appimage",
        ),
        ArtifactContract(
            f"localflight-desktop_{version}_amd64.deb",
            "linux",
            "x86_64",
            "desktop",
            "deb",
        ),
        ArtifactContract(
            f"localflight-desktop_{version}_arm64.deb",
            "linux",
            "aarch64",
            "desktop",
            "deb",
        ),
        ArtifactContract(
            f"localflight-server_{version}_amd64.deb",
            "linux",
            "x86_64",
            "server",
            "deb",
        ),
        ArtifactContract(
            f"localflight-server_{version}_arm64.deb",
            "linux",
            "aarch64",
            "server",
            "deb",
        ),
        ArtifactContract(
            f"LocalFlight-pi-source-{version}.zip",
            "raspberry-pi",
            "source",
            "source",
            "zip",
        ),
    )


def artifact_names(version: str) -> tuple[str, ...]:
    return tuple(contract.name for contract in artifact_contracts(version))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_checksum(artifact: Path, checksum: Path) -> None:
    fields = checksum.read_text(encoding="ascii").strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != artifact.name:
        raise ValueError(f"Malformed checksum file: {checksum.name}")
    actual = sha256_file(artifact)
    if fields[0].lower() != actual:
        raise ValueError(f"Checksum mismatch: {artifact.name}")


def verify_release_directory(directory: Path, version: str) -> list[Path]:
    expected = artifact_names(version)
    expected_entries = {name for artifact in expected for name in (artifact, f"{artifact}.sha256")}
    actual_entries = {path.name for path in directory.iterdir()}
    unexpected = sorted(actual_entries - expected_entries)
    if unexpected:
        raise ValueError("Unexpected release files: " + ", ".join(unexpected))
    missing: list[str] = []
    verified: list[Path] = []
    for name in expected:
        artifact = directory / name
        checksum = directory / f"{name}.sha256"
        if not artifact.is_file():
            missing.append(name)
        if not checksum.is_file():
            missing.append(checksum.name)
        if artifact.is_file() and checksum.is_file():
            verify_checksum(artifact, checksum)
            verified.extend((artifact, checksum))
    if missing:
        raise ValueError("Missing release files: " + ", ".join(missing))
    return verified


def attestation_name(artifact_name: str) -> str:
    return f"{artifact_name}.attestation.json"


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Malformed attestation {label}")
    return value


def _read_attestation(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Malformed attestation file: {path.name}") from exc
    return _require_mapping(value, path.name)


def verify_release_attestations(
    directory: Path,
    artifacts_directory: Path,
    version: str,
    *,
    source_sha: str,
) -> list[Path]:
    """Verify CI-only package inspection records against the final bytes."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Source SHA must be a full lowercase Git commit SHA")

    contracts = artifact_contracts(version)
    expected_entries = {attestation_name(contract.name) for contract in contracts}
    actual_entries = {path.name for path in directory.iterdir()}
    unexpected = sorted(actual_entries - expected_entries)
    if unexpected:
        raise ValueError("Unexpected attestation files: " + ", ".join(unexpected))
    missing = sorted(expected_entries - actual_entries)
    if missing:
        raise ValueError("Missing attestation files: " + ", ".join(missing))

    verified: list[Path] = []
    for contract in contracts:
        path = directory / attestation_name(contract.name)
        record = _read_attestation(path)
        artifact_record = _require_mapping(record.get("artifact"), f"{path.name}:artifact")
        release_record = _require_mapping(record.get("release"), f"{path.name}:release")
        inspection_record = _require_mapping(record.get("inspection"), f"{path.name}:inspection")
        artifact = artifacts_directory / contract.name

        expected_top_level = {"schema_version", "source_sha", "artifact", "release", "inspection"}
        if set(record) != expected_top_level or record.get("schema_version") != 1:
            raise ValueError(f"Unsupported attestation schema: {path.name}")
        if record.get("source_sha") != source_sha:
            raise ValueError(f"Source SHA mismatch: {contract.name}")
        if not artifact.is_file():
            raise ValueError(f"Attested artifact is missing: {contract.name}")

        expected_artifact = {
            "name": contract.name,
            "sha256": sha256_file(artifact),
            "size": artifact.stat().st_size,
        }
        if artifact_record != expected_artifact:
            raise ValueError(f"Artifact attestation mismatch: {contract.name}")
        expected_release = {
            "version": version,
            "platform": contract.platform,
            "architecture": contract.architecture,
            "flavor": contract.flavor,
            "kind": contract.kind,
        }
        if release_record != expected_release:
            raise ValueError(f"Release identity attestation mismatch: {contract.name}")
        method = inspection_record.get("method")
        if set(inspection_record) != {"method"} or method != inspection_method(contract):
            raise ValueError(f"Malformed inspection attestation: {contract.name}")
        verified.append(path)
    return verified


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--attestations",
        type=Path,
        help="CI-only artifact inspection records to bind to the package hashes",
    )
    parser.add_argument("--source-sha", help="full Git commit SHA expected in every attestation")
    args = parser.parse_args()
    directory = args.directory.resolve()
    try:
        verified = verify_release_directory(directory, project_version())
        attested: list[Path] = []
        if args.attestations is not None:
            if not args.source_sha:
                raise ValueError("--source-sha is required with --attestations")
            attested = verify_release_attestations(
                args.attestations.resolve(),
                directory,
                project_version(),
                source_sha=args.source_sha,
            )
        elif args.source_sha:
            raise ValueError("--attestations is required with --source-sha")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Verified {len(verified)} release files in {directory}")
    if attested:
        print(f"Verified {len(attested)} package inspection attestations")


if __name__ == "__main__":
    main()
