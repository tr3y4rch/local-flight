"""Build-time fallback renderer for the Local Flight macOS app icon."""
from __future__ import annotations

from typing import Any

from scripts.brand_assets import draw_master_logo


def draw_macos_icon(size: int = 1024) -> Any:
    """Return the master rounded-square logo as a transparent Dock tile."""
    return draw_master_logo(size, filled_background=False)
