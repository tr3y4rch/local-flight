#!/usr/bin/env python3
"""Generate Local Flight logo assets from the master brand mark."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.brand_assets import draw_master_logo, write_master_svg

ASSETS = ROOT / "assets"
WEB_STATIC = ROOT / "src" / "localflight" / "ui" / "static"
MOBILE_ASSETS = ROOT / "mobile" / "assets"
IOS_ASSETS = ROOT / "mobile" / "ios" / "LocalFlightCompanion" / "Images.xcassets"
MOBILE_FONTS = MOBILE_ASSETS / "fonts"
STATIC_FONTS = WEB_STATIC / "fonts"


def _save_png(path: Path, size: int, *, filled_background: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    draw_master_logo(size, filled_background=filled_background).save(path)


def _save_resized(path: Path, source: Image.Image, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    source.resize((size, size), Image.LANCZOS).save(path)


def _make_ico(path: Path, source: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    source.save(path, format="ICO", sizes=sizes)


def _make_icns(path: Path, source: Image.Image) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source.save(path, format="ICNS")
        return
    except Exception:
        iconset = ASSETS / "icon.iconset"
        shutil.rmtree(iconset, ignore_errors=True)
        iconset.mkdir(parents=True, exist_ok=True)
        for s in [16, 32, 128, 256, 512]:
            source.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            source.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(path)], check=True)
        shutil.rmtree(iconset, ignore_errors=True)


def _copy_mobile_fonts() -> None:
    MOBILE_FONTS.mkdir(parents=True, exist_ok=True)
    for filename in (
        "DMSans.ttf",
        "Audiowide-Regular.ttf",
        "SpaceMono-Regular.ttf",
        "SpaceMono-Bold.ttf",
        "OFL-DMSans.txt",
        "OFL-Audiowide.txt",
        "OFL-SpaceMono.txt",
    ):
        shutil.copyfile(STATIC_FONTS / filename, MOBILE_FONTS / filename)


def generate() -> None:
    ASSETS.mkdir(exist_ok=True)
    WEB_STATIC.mkdir(parents=True, exist_ok=True)
    MOBILE_ASSETS.mkdir(parents=True, exist_ok=True)

    master_svg = ASSETS / "localflight-logo.svg"
    if not master_svg.exists():
        write_master_svg(master_svg)
    shutil.copyfile(master_svg, WEB_STATIC / "localflight-logo.svg")

    transparent_1024 = draw_master_logo(1024, filled_background=False)
    filled_1024 = draw_master_logo(1024, filled_background=True)

    transparent_1024.save(ASSETS / "icon.png")
    _make_ico(ASSETS / "icon.ico", transparent_1024)
    _make_icns(ASSETS / "icon.icns", transparent_1024)

    transparent_1024.save(WEB_STATIC / "localflight-icon.png")
    filled_1024.save(WEB_STATIC / "localflight-app-icon.png")
    transparent_1024.save(MOBILE_ASSETS / "localflight-logo.png")
    filled_1024.save(MOBILE_ASSETS / "localflight-icon.png")

    app_icon = IOS_ASSETS / "AppIcon.appiconset" / "App-Icon-1024x1024@1x.png"
    filled_1024.convert("RGB").save(app_icon)

    splash_dir = IOS_ASSETS / "SplashScreenLogo.imageset"
    for filename, size in {
        "image.png": 172,
        "image@2x.png": 344,
        "image@3x.png": 516,
        "dark_image.png": 172,
        "dark_image@2x.png": 344,
        "dark_image@3x.png": 516,
    }.items():
        _save_resized(splash_dir / filename, transparent_1024, size)

    _copy_mobile_fonts()


def main() -> None:
    generate()
    print("Generated Local Flight brand assets from assets/localflight-logo.svg")


if __name__ == "__main__":
    main()
