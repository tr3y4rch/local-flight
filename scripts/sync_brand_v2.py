#!/usr/bin/env python3
"""Sync Beacon Tools / Local Flight V2 brand assets into repo paths.

The V2 brand folders live outside this repository. This script treats their
SVG masters as source of truth, renders fresh platform assets, and rejects
empty or undersized outputs so stale transparent exports cannot slip into a
release build.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BEACON_ROOT = Path(r"C:\Users\phsch\Beacon Tools Branding\Beacon\brand-v2")
DEFAULT_LOCAL_FLIGHT_ROOT = Path(r"C:\Users\phsch\Beacon Tools Branding\Local-Flight\brand-v2")

WINDOWS_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
MACOS_ICONSET_SIZES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


@dataclass(frozen=True)
class BrandSources:
    beacon: Path
    local_flight: Path

    @property
    def beacon_source(self) -> Path:
        return self.beacon / "source"

    @property
    def local_source(self) -> Path:
        return self.local_flight / "source"


class SvgRenderer:
    """Render SVGs with Chromium when available, otherwise Qt SVG."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:  # pragma: no cover - dependency error path
            self._sync_playwright = None
            self._playwright_error = exc
        else:
            self._sync_playwright = sync_playwright
            self._playwright_error = None
        self._pw = None
        self._browser = None
        self._qt_app = None

    def __enter__(self) -> "SvgRenderer":
        if self._sync_playwright is not None:
            self._pw = self._sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch()
            except Exception:
                self._pw.stop()
                self._pw = None
                self._browser = None
        if self._browser is None:
            try:
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                from PySide6 import QtGui
            except Exception as exc:  # pragma: no cover - dependency error path
                raise RuntimeError(
                    "Brand rendering needs Playwright Chromium or PySide6 QtSvg. "
                    "Install Playwright with `pip install playwright` and "
                    "`python -m playwright install chromium`, or install the "
                    "`native`/`dev` extra for PySide6."
                ) from (self._playwright_error or exc)
            self._qt_app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._pw is not None:
            self._pw.stop()

    def render(self, svg: Path, dst: Path, width: int, height: int) -> None:
        if not svg.exists():
            raise FileNotFoundError(svg)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if self._browser is None:
            self._render_with_qt(svg, dst, width, height)
            assert_image(dst, width, height)
            return
        page = self._browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        try:
            svg_text = svg.read_text(encoding="utf-8")
            html = (
                "<!doctype html><html><head><meta charset='utf-8'><style>"
                "*{margin:0;padding:0;box-sizing:border-box}"
                f"html,body{{width:{width}px;height:{height}px;"
                "background:transparent;overflow:hidden}}"
                f"svg{{width:{width}px;height:{height}px;display:block}}"
                "</style></head><body>"
                f"{svg_text}"
                "</body></html>"
            )
            page.set_content(html, wait_until="load")
            page.screenshot(path=str(dst), omit_background=True, full_page=False)
        finally:
            page.close()
        assert_image(dst, width, height)

    def _render_with_qt(self, svg: Path, dst: Path, width: int, height: int) -> None:
        from PySide6 import QtGui, QtSvg

        renderer = QtSvg.QSvgRenderer(str(svg))
        if not renderer.isValid():
            raise ValueError(f"{svg} is not a valid SVG")
        image = QtGui.QImage(width, height, QtGui.QImage.Format_ARGB32)
        image.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(dst)):
            raise RuntimeError(f"could not write {dst}")


def assert_image(path: Path, width: int | None = None, height: int | None = None) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        if width is not None and height is not None and rgba.size != (width, height):
            raise ValueError(f"{path} has size {rgba.size}, expected {(width, height)}")
        alpha = rgba.getchannel("A")
        if alpha.getbbox() is None:
            raise ValueError(f"{path} is fully transparent")


def assert_ico(path: Path, sizes: Iterable[int]) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    expected = {(size, size) for size in sizes}
    with Image.open(path) as image:
        ico = getattr(image, "ico", None)
        found = set(ico.sizes()) if ico is not None else set(image.info.get("sizes", {image.size}))
        for size in expected & found:
            frame = ico.getimage(size) if ico is not None else image
            if frame.convert("RGBA").getchannel("A").getbbox() is None:
                raise ValueError(f"{path} frame {size} is fully transparent")
    missing = expected - found
    if missing:
        raise ValueError(f"{path} is missing ICO frames: {sorted(missing)}")


def copy_svg(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def render_icon_series(renderer: SvgRenderer, svg: Path, sizes: Iterable[int]) -> list[Path]:
    rendered: list[Path] = []
    tmpdir = Path(tempfile.mkdtemp(prefix="localflight-brand-"))
    for size in sizes:
        out = tmpdir / f"icon_{size}.png"
        renderer.render(svg, out, size, size)
        rendered.append(out)
    return rendered


def write_ico(svg: Path, dst: Path, renderer: SvgRenderer) -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="localflight-brand-"))
    largest_png = tmpdir / "icon_256.png"
    renderer.render(svg, largest_png, 256, 256)
    largest = Image.open(largest_png).convert("RGBA")
    dst.parent.mkdir(parents=True, exist_ok=True)
    largest.save(
        dst,
        format="ICO",
        sizes=[(size, size) for size in WINDOWS_ICO_SIZES],
    )
    largest.close()
    assert_ico(dst, WINDOWS_ICO_SIZES)


def write_iconset(svg: Path, dst: Path, renderer: SvgRenderer) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for filename, size in MACOS_ICONSET_SIZES:
        renderer.render(svg, dst / filename, size, size)


def try_write_icns(iconset: Path, dst: Path) -> None:
    """Write an ICNS when the host toolchain can do it.

    macOS uses iconutil. Pillow can write ICNS in some environments, so try it
    as a convenience on Windows/Linux too. If both paths fail, keep the iconset.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    icon_1024 = iconset / "icon_512x512@2x.png"
    try:
        Image.open(icon_1024).save(dst, format="ICNS")
        return
    except Exception:
        pass
    if sys.platform == "darwin":
        import subprocess

        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dst)], check=True)


def paste_center(source: Path, dst: Path, canvas: tuple[int, int]) -> None:
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
    out = Image.new("RGBA", canvas, (0, 0, 0, 0))
    x = (canvas[0] - rgba.width) // 2
    y = (canvas[1] - rgba.height) // 2
    out.alpha_composite(rgba, (x, y))
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    assert_image(dst, *canvas)


def resize_png(src: Path, dst: Path, size: tuple[int, int]) -> None:
    with Image.open(src) as image:
        resized = image.convert("RGBA").resize(size, Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    resized.save(dst)
    assert_image(dst, *size)


def sync_local_flight(sources: BrandSources, renderer: SvgRenderer) -> None:
    src = sources.local_source
    icon_dark = src / "icon_dark.svg"

    assets = ROOT / "assets"
    static = ROOT / "src" / "localflight" / "ui" / "static"
    mobile = ROOT / "mobile" / "assets"
    site_assets = ROOT / "site" / "assets"

    copy_svg(icon_dark, assets / "localflight-logo.svg")
    copy_svg(icon_dark, static / "localflight-logo.svg")
    copy_svg(icon_dark, site_assets / "localflight-logo.svg")

    renderer.render(icon_dark, assets / "icon.png", 1024, 1024)
    write_ico(icon_dark, assets / "icon.ico", renderer)
    write_iconset(icon_dark, assets / "icon.iconset", renderer)
    try_write_icns(assets / "icon.iconset", assets / "icon.icns")

    renderer.render(icon_dark, static / "localflight-icon.png", 1024, 1024)
    renderer.render(icon_dark, static / "localflight-app-icon.png", 1024, 1024)
    renderer.render(icon_dark, mobile / "localflight-icon.png", 1024, 1024)
    renderer.render(icon_dark, mobile / "localflight-logo.png", 1024, 1024)
    renderer.render(icon_dark, site_assets / "localflight-icon.png", 1024, 1024)


def sync_beacon_tools(sources: BrandSources, renderer: SvgRenderer) -> None:
    src = sources.beacon_source
    icon_dark = src / "icon_dark.svg"
    icon_mark = src / "icon_mark.svg"
    lockup = src / "lockup_horizontal_transparent.svg"

    site_assets = ROOT / "site" / "assets"

    tmpdir = Path(tempfile.mkdtemp(prefix="beacon-brand-"))
    lockup_natural = tmpdir / "beacon-lockup-1200x311.png"
    renderer.render(lockup, lockup_natural, 1200, 311)
    paste_center(lockup_natural, site_assets / "beacon-tools-logo.png", (1200, 349))

    renderer.render(icon_mark, site_assets / "beacon-tools-mark.png", 512, 512)
    resize_png(site_assets / "beacon-tools-mark.png", site_assets / "beacon-tools-mark-96.png", (96, 96))
    resize_png(site_assets / "beacon-tools-mark.png", site_assets / "beacon-tools-mark-64.png", (64, 64))

    renderer.render(icon_dark, site_assets / "beacon-tools-icon-512.png", 512, 512)
    renderer.render(icon_dark, site_assets / "apple-touch-icon.png", 180, 180)
    resize_png(site_assets / "beacon-tools-mark.png", site_assets / "favicon-32.png", (32, 32))
    write_ico(icon_mark, site_assets / "favicon.ico", renderer)


def validate_required_outputs() -> None:
    checks = {
        ROOT / "assets" / "icon.png": (1024, 1024),
        ROOT / "assets" / "icon.icns": None,
        ROOT / "src" / "localflight" / "ui" / "static" / "localflight-logo.svg": None,
        ROOT / "src" / "localflight" / "ui" / "static" / "localflight-icon.png": (1024, 1024),
        ROOT / "mobile" / "assets" / "localflight-icon.png": (1024, 1024),
        ROOT / "mobile" / "assets" / "localflight-logo.png": (1024, 1024),
        ROOT / "site" / "assets" / "beacon-tools-logo.png": (1200, 349),
        ROOT / "site" / "assets" / "beacon-tools-mark.png": (512, 512),
        ROOT / "site" / "assets" / "beacon-tools-mark-96.png": (96, 96),
        ROOT / "site" / "assets" / "beacon-tools-mark-64.png": (64, 64),
        ROOT / "site" / "assets" / "beacon-tools-icon-512.png": (512, 512),
        ROOT / "site" / "assets" / "apple-touch-icon.png": (180, 180),
        ROOT / "site" / "assets" / "favicon-32.png": (32, 32),
        ROOT / "site" / "assets" / "localflight-icon.png": (1024, 1024),
    }
    for path, size in checks.items():
        if path.suffix.lower() == ".svg":
            if not path.exists() or path.stat().st_size == 0:
                raise ValueError(f"{path} is missing or empty")
            continue
        if path.suffix.lower() == ".icns":
            if path.exists() and path.stat().st_size > 0:
                continue
            if (ROOT / "assets" / "icon.iconset").exists():
                continue
            raise ValueError(f"{path} is missing and no icon.iconset fallback exists")
        assert_image(path, *(size or (None, None)))
    assert_ico(ROOT / "assets" / "icon.ico", WINDOWS_ICO_SIZES)
    assert_ico(ROOT / "site" / "assets" / "favicon.ico", WINDOWS_ICO_SIZES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--beacon-root", type=Path, default=DEFAULT_BEACON_ROOT)
    parser.add_argument("--local-flight-root", type=Path, default=DEFAULT_LOCAL_FLIGHT_ROOT)
    return parser.parse_args()


def main() -> None:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    args = parse_args()
    sources = BrandSources(
        beacon=args.beacon_root.resolve(),
        local_flight=args.local_flight_root.resolve(),
    )
    for required in (sources.beacon_source, sources.local_source):
        if not required.exists():
            raise FileNotFoundError(required)

    with SvgRenderer() as renderer:
        sync_local_flight(sources, renderer)
        sync_beacon_tools(sources, renderer)
    validate_required_outputs()
    print("Synced Beacon Tools / Local Flight V2 brand assets.")


if __name__ == "__main__":
    main()
