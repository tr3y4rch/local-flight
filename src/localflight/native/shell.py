"""Native shell compatibility boundary.

The full shell still lives in the compatibility module during the first extraction pass.
Keeping this module gives future work a stable place to move ``NativeMainWindow``
without changing launchers or tests again.
"""
from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    if name == "NativeMainWindow":
        from localflight.native._legacy_app import NativeMainWindow

        return NativeMainWindow
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
