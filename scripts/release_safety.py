"""Shared public-release bundle safety checks."""
from __future__ import annotations

import hashlib
import platform
import re
import subprocess
from pathlib import Path


ARCH_ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "arm64": "aarch64",
    "aarch64": "aarch64",
}
SENSITIVE_SUFFIXES = {
    ".cer", ".crt", ".jks", ".key", ".keystore", ".mobileprovision",
    ".p12", ".p8", ".pem", ".pfx",
}
SENSITIVE_NAMES = {
    ".DS_Store", ".env", ".netrc", ".npmrc", ".pypirc", ".secrets",
    "credentials.json", "google-services.json", "GoogleService-Info.plist",
    "secrets.json", "service-account.json",
}
FORBIDDEN_PARTS = {
    ".codex", ".git", "__pycache__", "operator", "node_modules",
}
INTERNAL_NAME_MARKERS = (
    "dev_notes",
    "handoff",
    "internal_notes",
    "operator_notes",
    "review_notes",
)
TEXT_SUFFIXES = {
    ".cfg", ".css", ".desktop", ".html", ".ini", ".js", ".json", ".md",
    ".mjs", ".plist", ".py", ".service", ".sh", ".toml", ".ts", ".tsx",
    ".txt", ".xml", ".yaml", ".yml",
}
MAC_WORKSTATION_PATH_PATTERN = re.compile(r"/Users/[^/\s]+/")
LINUX_HOME_PATH_PATTERN = re.compile(r"/home/([^/\s]+)/")
WINDOWS_WORKSTATION_PATH_PATTERN = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\")
PUBLIC_RUNTIME_HOME_USERS = {"$SERVICE_USER", "localflight", "pi"}
CERTIFI_CA_BUNDLES = {
    "_internal/certifi/cacert.pem",
    "Contents/Resources/certifi/cacert.pem",
}
REQUIRED_FROZEN_RUNTIME_RESOURCES = (
    Path("localflight/sources/matrix/client.py"),
    Path("localflight/ui/templates/base.html"),
    Path("localflight/ui/static/app.css"),
    Path("localflight/decode/mappings/airports_index.json.gz"),
    Path("localflight/ui/docs/README.md"),
    Path("localflight/assets/localflight-logo.svg"),
)
FROZEN_RESOURCE_PREFIXES = (
    Path(),
    Path("_internal"),
    Path("Contents/Resources"),
)


def is_private_install_metadata_path(relative: Path) -> bool:
    """Return whether packaging metadata can disclose its build location.

    ``direct_url.json`` is created by pip for direct/local installs and can
    retain the absolute checkout path. It is not needed by the frozen runtime,
    so release bundles must omit it even when a particular file happens not to
    contain a workstation path.
    """
    return (
        relative.name.lower() == "direct_url.json"
        and relative.parent.name.lower().endswith(".dist-info")
    )


def is_excluded_frozen_data_path(relative: Path) -> bool:
    """Return whether a PyInstaller data entry is unsafe and unnecessary."""
    lower_parts = tuple(part.lower() for part in relative.parts)
    if "__pycache__" in lower_parts or relative.suffix.lower() == ".pyc":
        return True
    if is_private_install_metadata_path(relative):
        return True
    return (
        "sboms" in lower_parts
        and any(part.endswith(".dist-info") for part in lower_parts)
    )


def normalize_architecture(value: str) -> str:
    try:
        return ARCH_ALIASES[value.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported release architecture: {value}") from exc


def require_native_architecture(target: str) -> str:
    requested = normalize_architecture(target)
    actual = normalize_architecture(platform.machine())
    if requested != actual:
        raise RuntimeError(
            f"Refusing cross-architecture package: requested {requested}, running on {actual}."
        )
    return requested


def validate_elf_architecture(executable: Path, architecture: str) -> None:
    if not executable.is_file():
        raise RuntimeError(f"Missing frozen executable: {executable}")
    description = subprocess.check_output(
        ["file", "-b", str(executable)],
        text=True,
        stderr=subprocess.STDOUT,
    )
    expected = "x86-64" if architecture == "x86_64" else "ARM aarch64"
    if "ELF 64-bit" not in description or expected not in description:
        raise RuntimeError(
            f"Frozen executable architecture does not match {architecture}: {description.strip()}"
        )


def is_sensitive_release_path(relative: Path) -> bool:
    # Certifi's bundled public CA trust store is runtime data rather than a
    # credential. Keep this exception exact so every other PEM remains blocked.
    if relative.as_posix() in CERTIFI_CA_BUNDLES:
        return False
    if is_excluded_frozen_data_path(relative):
        return True
    lower_parts = {part.lower() for part in relative.parts}
    name = relative.name
    lower_name = name.lower()
    if name == "AGENTS.md" or lower_name.startswith("agents."):
        return True
    normalized_name = lower_name.replace("-", "_").replace(" ", "_")
    if any(marker in normalized_name for marker in INTERNAL_NAME_MARKERS):
        return True
    if lower_parts & FORBIDDEN_PARTS:
        return True
    if lower_name == ".env.example":
        return False
    if name in SENSITIVE_NAMES or lower_name in {item.lower() for item in SENSITIVE_NAMES}:
        return True
    if relative.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    if lower_name.startswith(".env") or lower_name.startswith(".secrets"):
        return True
    return any(
        marker in lower_name
        for marker in ("app-store-connect", "credentials", "service-account", "service_account")
    )


def _contains_workstation_path(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 4 * 1024 * 1024:
        return False
    data = path.read_bytes()
    if b"\0" in data:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if MAC_WORKSTATION_PATH_PATTERN.search(text) or WINDOWS_WORKSTATION_PATH_PATTERN.search(text):
        return True
    return any(
        match.group(1) not in PUBLIC_RUNTIME_HOME_USERS
        for match in LINUX_HOME_PATH_PATTERN.finditer(text)
    )


def validate_public_bundle(bundle: Path) -> None:
    if not bundle.is_dir():
        raise RuntimeError(f"Missing frozen bundle directory: {bundle}")
    root = bundle.resolve()
    unsafe: list[str] = []
    for path in bundle.rglob("*"):
        relative = path.relative_to(bundle)
        if is_sensitive_release_path(relative):
            unsafe.append(relative.as_posix())
        elif not path.is_symlink() and path.is_file() and _contains_workstation_path(path):
            unsafe.append(f"{relative.as_posix()} (workstation path)")
        if path.is_symlink():
            try:
                path.resolve(strict=True).relative_to(root)
            except (FileNotFoundError, ValueError):
                unsafe.append(f"{relative.as_posix()} (external or broken symlink)")
    if unsafe:
        raise RuntimeError(
            "Refusing to package unsafe public-release paths:\n  - " + "\n  - ".join(sorted(set(unsafe)))
        )


def frozen_runtime_resource_path(bundle: Path, relative: Path) -> Path | None:
    """Locate a runtime data file in Windows/Linux or macOS bundle layouts."""
    for prefix in FROZEN_RESOURCE_PREFIXES:
        candidate = bundle / prefix / relative
        if candidate.is_file():
            return candidate
    return None


def validate_frozen_runtime_resources(bundle: Path) -> None:
    """Fail packaging when a filesystem-backed runtime resource is missing."""
    if not bundle.is_dir():
        raise RuntimeError(f"Missing frozen bundle directory: {bundle}")
    missing: list[str] = []
    empty: list[str] = []
    for relative in REQUIRED_FROZEN_RUNTIME_RESOURCES:
        path = frozen_runtime_resource_path(bundle, relative)
        if path is None:
            missing.append(relative.as_posix())
        elif path.stat().st_size <= 0:
            empty.append(relative.as_posix())
    if missing or empty:
        details = [*(f"missing: {item}" for item in missing), *(f"empty: {item}" for item in empty)]
        raise RuntimeError(
            "Frozen bundle is missing required runtime resources:\n  - "
            + "\n  - ".join(details)
        )


def write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum = path.with_suffix(path.suffix + ".sha256")
    checksum.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum
