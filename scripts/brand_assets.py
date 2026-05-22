"""Compatibility helpers for the synced Local Flight V2 brand assets."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
V2_LOCAL_SOURCE = Path(r"C:\Users\phsch\Beacon Tools Branding\Local-Flight\brand-v2\source")


def write_master_svg(path: Path) -> None:
    """Write the current V2 Local Flight SVG master to ``path``."""
    source = V2_LOCAL_SOURCE / "icon_dark.svg"
    if not source.exists():
        source = ASSETS / "localflight-logo.svg"
    if not source.exists():
        raise FileNotFoundError(source)
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, path)


def draw_master_logo(size: int = 1024, *, filled_background: bool = False) -> Any:
    """Return the synced V2 app icon as an RGBA Pillow image."""
    source = ASSETS / "icon.png"
    if not source.exists():
        raise FileNotFoundError(
            f"{source} is missing; run `python scripts/sync_brand_v2.py` first"
        )
    with Image.open(source) as image:
        icon = image.convert("RGBA").resize((size, size), Image.LANCZOS)
    if filled_background:
        background = Image.new("RGBA", icon.size, (8, 12, 18, 255))
        background.alpha_composite(icon)
        return background
    return icon
