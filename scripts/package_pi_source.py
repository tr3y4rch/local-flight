#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import subprocess
from fnmatch import fnmatch
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
EXCLUDED_RELEASE_FILES = {
    ".github/copilot-instructions.md",
    "AGENTS.md",
    "CLAUDE.md",
    "Claude.md",
    "DEV_NOTES.md",
    "DEV_README.md",
    "HANDOFF.md",
    "docs/engineering-changelog.md",
    "docs/native-first-redesign.md",
    "start_network.bat",
}
EXCLUDED_RELEASE_DIRS = (
    ".claude/",
    ".codex/",
    "dev/private/",
    "docs/handoff/",
    "docs/internal/",
    "docs/brand-renditions/",
    "mobile/.expo/",
    "mobile/.layout-smoke/",
    "mobile/.metro-cache/",
    "mobile/android/",
    "mobile/ios/",
    "mobile/node_modules/",
    "operator/",
    "tmp/",
)
EXCLUDED_RELEASE_PATTERNS = (
    "*.handoff.md",
    "*.prompt.md",
    "*.scratch.md",
    "*_HANDOFF.md",
    "*_handoff.md",
    "AGENTS.*.md",
    "CLAUDE.*.md",
    "HANDOFF-*.md",
    "Simulator Screenshot*.png",
    "docs/*handoff*.md",
    "docs/*internal*.md",
    "handoff*.md",
    "simulator_screenshot_*.png",
)

SENSITIVE_RELEASE_SUFFIXES = {
    ".cer",
    ".crt",
    ".jks",
    ".key",
    ".keystore",
    ".mobileprovision",
    ".p12",
    ".p8",
    ".pem",
    ".pfx",
}
SENSITIVE_RELEASE_NAMES = {
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".secrets",
    "GoogleService-Info.plist",
    "credentials.json",
    "google-services.json",
    "secrets.json",
    "service-account.json",
}


def _is_explicit_example(path: Path) -> bool:
    name = path.name.lower()
    return name == ".env.example" or ".example." in name or name.endswith(".example")


def _is_sensitive_release_path(path: Path) -> bool:
    if _is_explicit_example(path):
        return False
    name = path.name
    lower = name.lower()
    if name in SENSITIVE_RELEASE_NAMES or lower in {item.lower() for item in SENSITIVE_RELEASE_NAMES}:
        return True
    if path.suffix.lower() in SENSITIVE_RELEASE_SUFFIXES:
        return True
    if lower.startswith(".env") or lower.startswith(".secrets"):
        return True
    return any(
        marker in lower
        for marker in (
            "app-store-connect",
            "credentials",
            "service-account",
            "service_account",
        )
    )


def _is_release_file(path: Path) -> bool:
    posix = path.as_posix()
    name = path.name
    if name == ".DS_Store" or posix in EXCLUDED_RELEASE_FILES:
        return False
    if any(posix.startswith(prefix) for prefix in EXCLUDED_RELEASE_DIRS):
        return False
    if any(fnmatch(posix, pattern) for pattern in EXCLUDED_RELEASE_PATTERNS):
        return False
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return False
    return True


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _release_files() -> list[Path]:
    """
    Build source bundles from tracked files plus non-ignored local additions.

    The Pi bundle is often used for pre-release hardware tests before a commit
    exists. Using only tracked files can silently omit new modules and produce a
    broken install, while --exclude-standard still keeps secrets/build outputs
    protected by .gitignore.
    """
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Could not list release files with git: {exc}") from exc

    paths = sorted({Path(item) for item in raw.decode("utf-8").split("\0") if item})
    paths = [path for path in paths if (ROOT / path).exists()]
    sensitive = [path.as_posix() for path in paths if _is_sensitive_release_path(path)]
    if sensitive:
        formatted = "\n  - ".join(sensitive)
        raise SystemExit(
            "Refusing to build a source package with credential-like paths:\n"
            f"  - {formatted}\n"
            "Rename the file as an explicit .example template or keep it outside the release tree."
        )
    return [path for path in paths if _is_release_file(path)]


def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum_path


def main() -> None:
    version = _version()
    stage_dir = BUILD_DIR / f"LocalFlight-pi-source-{version}"
    zip_path = DIST_DIR / f"LocalFlight-pi-source-{version}.zip"

    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    for rel_path in _release_files():
        source = ROOT / rel_path
        target = stage_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    zip_path.unlink(missing_ok=True)
    checksum_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    checksum_path.unlink(missing_ok=True)

    archive_base = zip_path.with_suffix("")
    shutil.make_archive(str(archive_base), "zip", BUILD_DIR, stage_dir.name)
    checksum_path = _write_sha256(zip_path)

    print(f"Pi source bundle: {zip_path}")
    print(f"Checksum: {checksum_path}")
    print("Install on Pi: unzip, cd into the folder, then run bash installers/pi/install.sh")
    print("Display options: guided menu by default; use --headless, --native-kiosk, or --kiosk for scripted installs.")


if __name__ == "__main__":
    main()
