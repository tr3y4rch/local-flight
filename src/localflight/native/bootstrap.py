"""Native UI launch bootstrap.

This module is the public launch boundary used by ``localflight.native.app``.
It intentionally lazy-loads the heavier shell implementation only when the
native GUI is actually started.
"""
from __future__ import annotations

import sys


def launch_native_app(*, base_url: str, first_launch: bool, fullscreen: bool = False) -> int:
    from localflight.native._legacy_app import launch_native_app as _legacy_launch

    return _legacy_launch(base_url=base_url, first_launch=first_launch, fullscreen=fullscreen)


def main() -> None:
    try:
        code = launch_native_app(base_url="http://127.0.0.1:8000", first_launch=False)
    except Exception as exc:
        print(f"Local Flight native UI unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(code)
