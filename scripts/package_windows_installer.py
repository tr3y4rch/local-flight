#!/usr/bin/env python3
"""Build the Windows Inno Setup installer from dist/LocalFlight."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "LocalFlight"
ISS_PATH = ROOT / "installers" / "windows" / "LocalFlight.iss"


def _project_version() -> str:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum_path


def _find_iscc() -> str:
    env_path = os.getenv("INNO_SETUP_COMPILER", "").strip()
    candidates = [
        Path(env_path) if env_path else None,
        Path(shutil.which("ISCC.exe") or "") if shutil.which("ISCC.exe") else None,
        Path(shutil.which("ISCC") or "") if shutil.which("ISCC") else None,
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    raise SystemExit(
        "Inno Setup compiler not found. Install Inno Setup 6 or set "
        "INNO_SETUP_COMPILER to ISCC.exe."
    )


def _sign_windows(path: Path) -> None:
    cert = os.getenv("SIGNTOOL_CERT", "").strip()
    if not cert:
        print("Signing skipped (set SIGNTOOL_CERT + SIGNTOOL_PASS to enable)")
        return
    signtool = shutil.which("signtool") or r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
    try:
        subprocess.run(
            [
                signtool,
                "sign",
                "/f",
                cert,
                "/p",
                os.getenv("SIGNTOOL_PASS", ""),
                "/tr",
                "http://timestamp.digicert.com",
                "/td",
                "sha256",
                "/fd",
                "sha256",
                str(path),
            ],
            check=True,
        )
        print(f"Signed: {path.name}")
    except Exception as exc:
        print(f"Signing failed (non-fatal): {exc}")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("The Inno Setup installer can only be built on Windows.")
    if not (APP_DIR / "LocalFlight.exe").exists():
        raise SystemExit("Missing dist/LocalFlight/LocalFlight.exe. Run python build.py first.")
    if not ISS_PATH.exists():
        raise SystemExit(f"Missing installer definition: {ISS_PATH}")

    version = _project_version()
    output = DIST_DIR / f"LocalFlight-{version}-Setup.exe"
    output.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".sha256").unlink(missing_ok=True)

    iscc = _find_iscc()
    subprocess.run(
        [
            iscc,
            f"/DAppVersion={version}",
            f"/DSourceDir={APP_DIR}",
            f"/DOutputDir={DIST_DIR}",
            str(ISS_PATH),
        ],
        check=True,
        cwd=ROOT,
    )

    if not output.exists():
        raise SystemExit(f"Inno Setup finished, but {output} was not created.")

    _sign_windows(output)
    checksum_path = _write_sha256(output)
    print(f"Windows installer: {output.relative_to(ROOT)}")
    print(f"Checksum: {checksum_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
