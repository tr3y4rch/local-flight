"""Native UI launch bootstrap.

This module is the public launch boundary used by ``localflight.native.app``.
It intentionally lazy-loads the heavier shell implementation only when the
native GUI is actually started.
"""
from __future__ import annotations

import os
import sys


def _is_first_launch() -> bool:
    try:
        from localflight.storage.config import config_path

        return not (config_path().parent / "setup_complete").exists()
    except Exception:
        return True


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def launch_native_app(*, base_url: str, first_launch: bool, fullscreen: bool = False) -> int:
    from localflight.native._legacy_app import launch_native_app as _compat_launch

    return _compat_launch(base_url=base_url, first_launch=first_launch, fullscreen=fullscreen)


def main() -> None:
    try:
        code = launch_native_app(
            base_url=os.environ.get("LOCALFLIGHT_NATIVE_BASE_URL", "http://127.0.0.1:8000"),
            first_launch=_is_first_launch(),
            fullscreen=_env_truthy("LOCALFLIGHT_NATIVE_FULLSCREEN"),
        )
    except Exception as exc:
        print(f"Local Flight native UI unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    raise SystemExit(code)
