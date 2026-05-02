"""Optional native Qt UI for Local Flight."""

from __future__ import annotations

__all__ = ["NativeUiUnavailable"]


class NativeUiUnavailable(RuntimeError):
    """Raised when the optional PySide6 native UI dependency is not installed."""
