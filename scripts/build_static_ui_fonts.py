"""Build static DM Sans weights for the native Qt shell.

The canonical ``DMSans.ttf`` is a variable font (``opsz`` and ``wght`` axes).
Browsers handle it well, so the LAN pages and the public site keep using it.
Qt does not: it registers only the default instance, its family name carries
the optical-size suffix (``DM Sans 9pt``), and Windows and macOS then resolve
the ``DM Sans`` stylesheet request differently. Windows also rasterizes the
variable outlines poorly, which is what made setup text unreadable there.

This script instantiates the four weights the native stylesheet asks for and
rewrites their name tables so every platform registers one ``DM Sans`` family
with proper weights. Run it only when the canonical variable font changes:

    python -m pip install fonttools
    python scripts/build_static_ui_fonts.py

The generated files are committed next to the variable font.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "src" / "localflight" / "ui" / "static" / "fonts"
SOURCE = FONT_DIR / "DMSans.ttf"
OPTICAL_SIZE = 14
WEIGHTS = (
    ("Regular", 400),
    ("Bold", 700),
    ("ExtraBold", 800),
    ("Black", 900),
)
FAMILY = "DM Sans"
RIBBI = {"Regular", "Bold"}


def _set_names(font, style: str, weight: int) -> None:
    name = font["name"]
    legacy_family = FAMILY if style in RIBBI else f"{FAMILY} {style}"
    legacy_style = style if style in RIBBI else "Regular"
    full_name = FAMILY if style == "Regular" else f"{FAMILY} {style}"
    postscript = f"DMSans-{style}"
    records = {
        1: legacy_family,
        2: legacy_style,
        3: f"{FAMILY};{style};static",
        4: full_name,
        6: postscript,
        16: FAMILY,
        17: style,
    }
    for name_id, value in records.items():
        name.setName(value, name_id, 3, 1, 0x409)
        name.setName(value, name_id, 1, 0, 0)
    os2 = font["OS/2"]
    os2.usWeightClass = weight
    # fsSelection: bit 5 = BOLD, bit 6 = REGULAR, bit 8 = WWS. Only the RIBBI
    # "Bold" instance is flagged bold; the heavier weights use the legacy
    # "Regular" style of their own legacy family and rely on usWeightClass.
    os2.fsSelection &= ~0b1100000
    os2.fsSelection |= 0b100000 if legacy_style == "Bold" else 0b1000000
    os2.fsSelection |= 1 << 8
    font["head"].macStyle = 1 if legacy_style == "Bold" else 0


def main() -> int:
    try:
        from fontTools.ttLib import TTFont
        from fontTools.varLib import instancer
    except ImportError:
        print("fontTools is required: python -m pip install fonttools", file=sys.stderr)
        return 1
    if not SOURCE.exists():
        print(f"Missing canonical variable font: {SOURCE}", file=sys.stderr)
        return 1
    for style, weight in WEIGHTS:
        font = TTFont(SOURCE)
        static = instancer.instantiateVariableFont(
            font,
            {"opsz": OPTICAL_SIZE, "wght": weight},
            updateFontNames=False,
        )
        _set_names(static, style, weight)
        target = FONT_DIR / f"DMSans-{style}.ttf"
        static.save(target)
        print(f"wrote {target.relative_to(ROOT)} ({weight})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
