#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"


def _version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _tracked_files() -> list[Path]:
    try:
        raw = subprocess.check_output(
            ["git", "ls-files", "-z"],
            cwd=ROOT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Could not list tracked files with git: {exc}") from exc

    paths = [Path(item) for item in raw.decode("utf-8").split("\0") if item]
    return [path for path in paths if path.name != ".DS_Store"]


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

    for rel_path in _tracked_files():
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


if __name__ == "__main__":
    main()
