#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_MODE = 0o600


def credential_candidates() -> list[Path]:
    candidates = [ROOT / ".env"]
    mobile = ROOT / "mobile"
    if mobile.exists():
        candidates.extend(mobile.glob("*service-account*.json"))
        candidates.extend(mobile.glob("*ServiceAccount*.json"))
        candidates.extend(mobile.glob("localflightandroid-*.json"))
        candidates.extend(mobile.glob("*app-store-connect*.json"))
        candidates.extend(mobile.glob("*AppStoreConnect*.json"))
        for name in ("google-services.json", "GoogleService-Info.plist"):
            candidates.extend(mobile.rglob(name))
    return sorted({path for path in candidates if path.is_file()})


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local credential file permissions without reading their contents.")
    parser.add_argument(
        "--fix-permissions",
        action="store_true",
        help="On POSIX, change discovered credential files to mode 0600.",
    )
    args = parser.parse_args()

    if os.name == "nt":
        print("Credential permission mode checks are skipped on Windows; use Windows ACLs for local protection.")
        return 0

    bad: list[Path] = []
    for path in credential_candidates():
        if mode(path) != PRIVATE_MODE:
            bad.append(path)
            if args.fix_permissions:
                try:
                    path.chmod(PRIVATE_MODE)
                except OSError as exc:
                    print(f"Could not protect {path.relative_to(ROOT)}: {exc}")
                    continue
                print(f"Protected {path.relative_to(ROOT)} (0600)")
            else:
                print(f"Needs owner-only permissions: {path.relative_to(ROOT)} (mode {mode(path):04o})")

    if bad and not args.fix_permissions:
        print("Run: python scripts/security_preflight.py --fix-permissions")
        return 2
    if not bad:
        print("Local credential file permissions look private")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
