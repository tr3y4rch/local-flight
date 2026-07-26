"""Resolve Local Flight runtime resources in source, wheel, and frozen builds."""
from __future__ import annotations

import sys
from pathlib import Path


def package_resource_candidates(*parts: str) -> tuple[Path, ...]:
    """Return ordered package-resource candidates without requiring PyInstaller."""
    package_root = Path(__file__).resolve().parents[1]
    candidates = [package_root.joinpath(*parts)]

    frozen_root = getattr(sys, "_MEIPASS", "")
    if frozen_root:
        bundle_root = Path(frozen_root)
        candidates.extend(
            (
                bundle_root.joinpath("localflight", *parts),
                bundle_root.joinpath(*parts),
            )
        )

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            key = candidate.resolve()
        except OSError:
            key = candidate
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return tuple(unique)


def resolve_package_resource(*parts: str) -> Path | None:
    """Find a bundled resource while keeping source and wheel installs working."""
    for candidate in package_resource_candidates(*parts):
        if candidate.is_file():
            return candidate
    return None


def require_package_resource(*parts: str) -> Path:
    """Return a required resource or raise a path-safe error."""
    resource = resolve_package_resource(*parts)
    if resource is not None:
        return resource
    logical_name = "/".join(parts)
    raise FileNotFoundError(f"Required Local Flight resource is unavailable: {logical_name}")
