#!/usr/bin/env python3
"""Generate the staged V2 brand pipeline outputs.

This script handles the source pipeline, package/app icons, Qt/native shared
static assets, LAN browser shared static assets, mobile app assets, and the
public Beacon Tools website shell/product assets. It stages every generated
file, validates it, then copies the approved outputs into active module paths.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "build" / "brand-v2" / "package-icons-stage"
ASSETS = ROOT / "assets"
STATIC = ROOT / "src" / "localflight" / "ui" / "static"
MOBILE_ASSETS = ROOT / "mobile" / "assets"
SITE_ASSETS = ROOT / "site" / "assets"

BEACON_LOCKUP = Path(r"C:\Users\phsch\Beacon Tools Branding\Beacon\brand-v2\source\lockup_horizontal_dark.svg")
BEACON_MARK = Path(r"C:\Users\phsch\Beacon Tools Branding\Beacon\brand-v2\source\icon_mark.svg")
LOCAL_FLIGHT_DARK = Path(r"C:\Users\phsch\Beacon Tools Branding\Local-Flight\brand-v2\source\icon_dark.svg")
LOCAL_FLIGHT_LIGHT = Path(r"C:\Users\phsch\Beacon Tools Branding\Local-Flight\brand-v2\source\icon_light.svg")

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
MOBILE_BRAND_ASSETS = (
    "localflight-icon.png",
    "localflight-icon-dark.png",
    "localflight-icon-light.png",
    "localflight-logo.png",
    "localflight-logo-dark.png",
    "localflight-logo-light.png",
)
SITE_BRAND_ASSETS = (
    "apple-touch-icon.png",
    "beacon-tools-icon-512.png",
    "beacon-tools-logo.png",
    "beacon-tools-mark.png",
    "beacon-tools-mark-64.png",
    "beacon-tools-mark-96.png",
    "favicon.ico",
    "favicon-32.png",
    "localflight-icon.png",
    "localflight-icon-light.png",
)
STALE_SITE_BRAND_ALIASES = (
    "fids-preview.svg",
    "history-preview.svg",
    "matrix-preview.svg",
    "radar-preview.svg",
)


@dataclass(frozen=True)
class OutputRecord:
    role: str
    path: str
    width: int | None
    height: int | None
    sha256: str


class SvgRenderer:
    """Render SVG masters with Chromium when available, otherwise Qt SVG."""

    def __init__(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            self._sync_playwright = None
            self._playwright_error = exc
        else:
            self._sync_playwright = sync_playwright
            self._playwright_error = None
        self.name = "qt-svg"
        self._pw = None
        self._browser = None
        self._qt_app = None

    def __enter__(self) -> "SvgRenderer":
        if self._sync_playwright is not None:
            self._pw = self._sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch()
                self.name = "playwright-chromium"
            except Exception:
                self._pw.stop()
                self._pw = None
                self._browser = None
        if self._browser is None:
            try:
                os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
                from PySide6 import QtGui
            except Exception as exc:
                raise RuntimeError(
                    "Brand rendering needs Playwright Chromium or PySide6 QtSvg. "
                    "Install the dev/native dependencies before syncing brand assets."
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
        else:
            self._render_with_chromium(svg, dst, width, height)
        assert_image(dst, width, height)

    def _render_with_chromium(self, svg: Path, dst: Path, width: int, height: int) -> None:
        page = self._browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        try:
            svg_text = svg.read_text(encoding="utf-8")
            page.set_content(
                "<!doctype html><html><head><meta charset='utf-8'><style>"
                "*{margin:0;padding:0;box-sizing:border-box}"
                f"html,body{{width:{width}px;height:{height}px;background:transparent;overflow:hidden}}"
                f"svg{{width:{width}px;height:{height}px;display:block}}"
                "</style></head><body>"
                f"{svg_text}"
                "</body></html>",
                wait_until="load",
            )
            page.screenshot(path=str(dst), omit_background=True, full_page=False)
        finally:
            page.close()

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


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_image(path: Path, width: int | None = None, height: int | None = None) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        if width is not None and height is not None and rgba.size != (width, height):
            raise ValueError(f"{path} has size {rgba.size}, expected {(width, height)}")
        if rgba.getchannel("A").getbbox() is None:
            raise ValueError(f"{path} is fully transparent")


def assert_images_differ(first: Path, second: Path) -> None:
    with Image.open(first) as first_image, Image.open(second) as second_image:
        if first_image.convert("RGB").tobytes() == second_image.convert("RGB").tobytes():
            raise ValueError(f"{first} and {second} are pixel-identical")


def resize_contain(source: Path, dst: Path, width: int, height: int) -> None:
    with Image.open(source) as image:
        foreground = image.convert("RGBA")
    scale = min(width / foreground.width, height / foreground.height)
    resized = foreground.resize(
        (max(1, round(foreground.width * scale)), max(1, round(foreground.height * scale))),
        Image.LANCZOS,
    )
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((width - resized.width) // 2, (height - resized.height) // 2))
    dst.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst)
    assert_image(dst, width, height)


def verify_lockup_wording(path: Path) -> None:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    wordmark_area = rgba.crop((rgba.width // 3, 0, rgba.width, rgba.height))
    if wordmark_area.getchannel("A").getbbox() is None:
        raise ValueError(f"{path} has no visible Beacon Tools wordmark area")


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


def assert_svg(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "<svg" not in text or "</svg>" not in text:
        raise ValueError(f"{path} does not look like an SVG file")


def copy_master_svg(src: Path, dst: Path) -> None:
    assert_svg(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def write_ico(source_png: Path, dst: Path) -> None:
    with Image.open(source_png) as image:
        largest = image.convert("RGBA")
    dst.parent.mkdir(parents=True, exist_ok=True)
    largest.save(
        dst,
        format="ICO",
        sizes=[(size, size) for size in WINDOWS_ICO_SIZES],
    )
    assert_ico(dst, WINDOWS_ICO_SIZES)


def write_iconset(renderer: SvgRenderer, icon_svg: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for filename, size in MACOS_ICONSET_SIZES:
        renderer.render(icon_svg, dst / filename, size, size)


def write_icns(iconset: Path, dst: Path) -> None:
    icon_1024 = iconset / "icon_512x512@2x.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        Image.open(icon_1024).save(dst, format="ICNS")
    except Exception:
        if sys.platform != "darwin":
            raise
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dst)], check=True)
    if not dst.exists() or dst.stat().st_size == 0:
        raise ValueError(f"{dst} was not generated")


def stage_package_icons(renderer: SvgRenderer) -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True, exist_ok=True)

    copy_master_svg(LOCAL_FLIGHT_DARK, STAGE / "localflight-logo.svg")
    renderer.render(LOCAL_FLIGHT_DARK, STAGE / "icon.png", 1024, 1024)
    write_ico(STAGE / "icon.png", STAGE / "icon.ico")
    write_iconset(renderer, LOCAL_FLIGHT_DARK, STAGE / "icon.iconset")
    write_icns(STAGE / "icon.iconset", STAGE / "icon.icns")


def stage_qt_lan_static(renderer: SvgRenderer) -> None:
    qt_lan = STAGE / "qt-lan-static"
    qt_lan.mkdir(parents=True, exist_ok=True)
    copy_master_svg(LOCAL_FLIGHT_DARK, qt_lan / "localflight-logo.svg")
    renderer.render(LOCAL_FLIGHT_DARK, qt_lan / "localflight-icon.png", 1024, 1024)
    renderer.render(LOCAL_FLIGHT_DARK, qt_lan / "localflight-app-icon.png", 1024, 1024)


def stage_mobile_assets(renderer: SvgRenderer) -> None:
    mobile = STAGE / "mobile-assets"
    mobile.mkdir(parents=True, exist_ok=True)
    renderer.render(LOCAL_FLIGHT_DARK, mobile / "localflight-icon-dark.png", 1024, 1024)
    renderer.render(LOCAL_FLIGHT_LIGHT, mobile / "localflight-icon-light.png", 1024, 1024)
    shutil.copyfile(mobile / "localflight-icon-dark.png", mobile / "localflight-icon.png")
    shutil.copyfile(mobile / "localflight-icon-dark.png", mobile / "localflight-logo-dark.png")
    shutil.copyfile(mobile / "localflight-icon-light.png", mobile / "localflight-logo-light.png")
    shutil.copyfile(mobile / "localflight-logo-dark.png", mobile / "localflight-logo.png")


def stage_site_assets(renderer: SvgRenderer) -> None:
    site = STAGE / "site-assets"
    site.mkdir(parents=True, exist_ok=True)

    lockup_master = site / "beacon-tools-logo-master.png"
    renderer.render(BEACON_LOCKUP, lockup_master, 1620, 420)
    verify_lockup_wording(lockup_master)
    resize_contain(lockup_master, site / "beacon-tools-logo.png", 1200, 349)
    verify_lockup_wording(site / "beacon-tools-logo.png")

    for filename, size in (
        ("beacon-tools-mark.png", 512),
        ("beacon-tools-mark-96.png", 96),
        ("beacon-tools-mark-64.png", 64),
        ("beacon-tools-icon-512.png", 512),
        ("apple-touch-icon.png", 180),
        ("favicon-32.png", 32),
    ):
        renderer.render(BEACON_MARK, site / filename, size, size)
    write_ico(site / "beacon-tools-mark.png", site / "favicon.ico")

    renderer.render(LOCAL_FLIGHT_DARK, site / "localflight-icon.png", 1024, 1024)
    renderer.render(LOCAL_FLIGHT_LIGHT, site / "localflight-icon-light.png", 1024, 1024)
    assert_images_differ(site / "localflight-icon.png", site / "localflight-icon-light.png")


def validate_masters() -> None:
    for path in (BEACON_LOCKUP, BEACON_MARK, LOCAL_FLIGHT_DARK, LOCAL_FLIGHT_LIGHT):
        if not path.exists():
            raise FileNotFoundError(path)
        assert_svg(path)


def validate_stage() -> None:
    assert_svg(STAGE / "localflight-logo.svg")
    assert_image(STAGE / "icon.png", 1024, 1024)
    assert_ico(STAGE / "icon.ico", WINDOWS_ICO_SIZES)
    for filename, size in MACOS_ICONSET_SIZES:
        assert_image(STAGE / "icon.iconset" / filename, size, size)
    if not (STAGE / "icon.icns").exists():
        raise FileNotFoundError(STAGE / "icon.icns")
    assert_svg(STAGE / "qt-lan-static" / "localflight-logo.svg")
    assert_image(STAGE / "qt-lan-static" / "localflight-icon.png", 1024, 1024)
    assert_image(STAGE / "qt-lan-static" / "localflight-app-icon.png", 1024, 1024)
    for filename in MOBILE_BRAND_ASSETS:
        assert_image(STAGE / "mobile-assets" / filename, 1024, 1024)
    assert_images_differ(
        STAGE / "mobile-assets" / "localflight-icon-dark.png",
        STAGE / "mobile-assets" / "localflight-icon-light.png",
    )
    site = STAGE / "site-assets"
    for filename, expected_size in (
        ("apple-touch-icon.png", (180, 180)),
        ("beacon-tools-icon-512.png", (512, 512)),
        ("beacon-tools-logo.png", (1200, 349)),
        ("beacon-tools-mark.png", (512, 512)),
        ("beacon-tools-mark-64.png", (64, 64)),
        ("beacon-tools-mark-96.png", (96, 96)),
        ("favicon-32.png", (32, 32)),
        ("localflight-icon.png", (1024, 1024)),
        ("localflight-icon-light.png", (1024, 1024)),
    ):
        assert_image(site / filename, *expected_size)
    assert_ico(site / "favicon.ico", WINDOWS_ICO_SIZES)
    assert_images_differ(site / "localflight-icon.png", site / "localflight-icon-light.png")


def sanitize_module_brand_files(module_dir: Path, keep: set[str]) -> None:
    """Remove stale Local Flight logo/icon derivatives from a module folder."""
    module_dir.mkdir(parents=True, exist_ok=True)
    patterns = (
        "icon*.png",
        "icon*.ico",
        "icon*.icns",
        "icon*.iconset",
        "localflight-logo*.svg",
        "localflight-logo*.png",
        "localflight-icon*.png",
        "localflight-app-icon*.png",
    )
    for pattern in patterns:
        for path in module_dir.glob(pattern):
            if path.name not in keep:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
    brand_dir = module_dir / "brand"
    if brand_dir.exists():
        shutil.rmtree(brand_dir)


def sanitize_site_brand_files() -> None:
    """Remove stale/generated site brand files that are not part of the V2 site set."""
    SITE_ASSETS.mkdir(parents=True, exist_ok=True)
    patterns = (
        "apple-touch-icon.png",
        "beacon-tools-*.png",
        "favicon*.png",
        "favicon*.ico",
        "localflight-icon*.png",
    )
    keep = set(SITE_BRAND_ASSETS)
    for pattern in patterns:
        for path in SITE_ASSETS.glob(pattern):
            if path.name not in keep:
                path.unlink()
    for filename in STALE_SITE_BRAND_ALIASES:
        path = SITE_ASSETS / filename
        if path.exists():
            path.unlink()


def copy_validated_outputs() -> None:
    ASSETS.mkdir(exist_ok=True)
    sanitize_module_brand_files(
        ASSETS,
        {"localflight-logo.svg", "icon.png", "icon.ico", "icon.icns", "icon.iconset"},
    )
    shutil.copyfile(STAGE / "localflight-logo.svg", ASSETS / "localflight-logo.svg")
    shutil.copyfile(STAGE / "icon.png", ASSETS / "icon.png")
    shutil.copyfile(STAGE / "icon.ico", ASSETS / "icon.ico")
    shutil.copyfile(STAGE / "icon.icns", ASSETS / "icon.icns")
    dst_iconset = ASSETS / "icon.iconset"
    if dst_iconset.exists():
        shutil.rmtree(dst_iconset)
    shutil.copytree(STAGE / "icon.iconset", dst_iconset)

    sanitize_module_brand_files(
        STATIC,
        {"localflight-logo.svg", "localflight-icon.png", "localflight-app-icon.png"},
    )
    shutil.copyfile(STAGE / "qt-lan-static" / "localflight-logo.svg", STATIC / "localflight-logo.svg")
    shutil.copyfile(STAGE / "qt-lan-static" / "localflight-icon.png", STATIC / "localflight-icon.png")
    shutil.copyfile(STAGE / "qt-lan-static" / "localflight-app-icon.png", STATIC / "localflight-app-icon.png")

    sanitize_module_brand_files(
        MOBILE_ASSETS,
        set(MOBILE_BRAND_ASSETS),
    )
    for filename in MOBILE_BRAND_ASSETS:
        shutil.copyfile(STAGE / "mobile-assets" / filename, MOBILE_ASSETS / filename)

    sanitize_site_brand_files()
    for filename in SITE_BRAND_ASSETS:
        shutil.copyfile(STAGE / "site-assets" / filename, SITE_ASSETS / filename)


def output_record(role: str, path: Path) -> OutputRecord:
    width: int | None = None
    height: int | None = None
    if path.suffix.lower() in {".png", ".ico", ".icns"}:
        with Image.open(path) as image:
            width, height = image.size
    return OutputRecord(
        role=role,
        path=path.relative_to(ROOT).as_posix(),
        width=width,
        height=height,
        sha256=sha256(path),
    )


def write_manifest(renderer_name: str) -> None:
    outputs = [
        output_record("local-flight-master-svg-copy", ASSETS / "localflight-logo.svg"),
        output_record("local-flight-package-png", ASSETS / "icon.png"),
        output_record("local-flight-windows-ico", ASSETS / "icon.ico"),
        output_record("local-flight-macos-icns", ASSETS / "icon.icns"),
    ]
    for filename, _size in MACOS_ICONSET_SIZES:
        outputs.append(output_record("local-flight-macos-iconset-member", ASSETS / "icon.iconset" / filename))
    outputs.extend(
        [
            output_record("qt-native-brand-svg", STATIC / "localflight-logo.svg"),
            output_record("qt-native-brand-png", STATIC / "localflight-icon.png"),
            output_record("lan-browser-brand-svg", STATIC / "localflight-logo.svg"),
            output_record("lan-browser-touch-icon", STATIC / "localflight-app-icon.png"),
            output_record("mobile-app-icon", MOBILE_ASSETS / "localflight-icon.png"),
            output_record("mobile-app-icon-dark", MOBILE_ASSETS / "localflight-icon-dark.png"),
            output_record("mobile-app-icon-light", MOBILE_ASSETS / "localflight-icon-light.png"),
            output_record("mobile-splash-logo", MOBILE_ASSETS / "localflight-logo.png"),
            output_record("mobile-splash-logo-dark", MOBILE_ASSETS / "localflight-logo-dark.png"),
            output_record("mobile-splash-logo-light", MOBILE_ASSETS / "localflight-logo-light.png"),
        ]
    )
    outputs.extend(
        [
            output_record("site-beacon-apple-touch-icon", SITE_ASSETS / "apple-touch-icon.png"),
            output_record("site-beacon-favicon-ico", SITE_ASSETS / "favicon.ico"),
            output_record("site-beacon-favicon-32", SITE_ASSETS / "favicon-32.png"),
            output_record("site-beacon-icon-512", SITE_ASSETS / "beacon-tools-icon-512.png"),
            output_record("site-beacon-lockup", SITE_ASSETS / "beacon-tools-logo.png"),
            output_record("site-beacon-mark-512", SITE_ASSETS / "beacon-tools-mark.png"),
            output_record("site-beacon-mark-96", SITE_ASSETS / "beacon-tools-mark-96.png"),
            output_record("site-beacon-mark-64", SITE_ASSETS / "beacon-tools-mark-64.png"),
            output_record("site-local-flight-product-icon", SITE_ASSETS / "localflight-icon.png"),
            output_record("site-local-flight-product-icon-light", SITE_ASSETS / "localflight-icon-light.png"),
        ]
    )
    manifest = {
        "version": 1,
        "phase": "package-qt-lan-mobile-site",
        "renderer": renderer_name,
        "masters": {
            "beacon_lockup": str(BEACON_LOCKUP),
            "beacon_mark": str(BEACON_MARK),
            "local_flight_dark": str(LOCAL_FLIGHT_DARK),
            "local_flight_light": str(LOCAL_FLIGHT_LIGHT),
        },
        "active_outputs": [asdict(record) for record in outputs],
        "excluded_until_later_phases": [],
    }
    (ASSETS / "brand-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def validate_active_outputs() -> None:
    assert_svg(ASSETS / "localflight-logo.svg")
    assert_image(ASSETS / "icon.png", 1024, 1024)
    assert_ico(ASSETS / "icon.ico", WINDOWS_ICO_SIZES)
    for filename, size in MACOS_ICONSET_SIZES:
        assert_image(ASSETS / "icon.iconset" / filename, size, size)
    if not (ASSETS / "icon.icns").exists():
        raise FileNotFoundError(ASSETS / "icon.icns")
    assert_svg(STATIC / "localflight-logo.svg")
    assert_image(STATIC / "localflight-icon.png", 1024, 1024)
    assert_image(STATIC / "localflight-app-icon.png", 1024, 1024)
    for filename in MOBILE_BRAND_ASSETS:
        assert_image(MOBILE_ASSETS / filename, 1024, 1024)
    assert_images_differ(
        MOBILE_ASSETS / "localflight-icon-dark.png",
        MOBILE_ASSETS / "localflight-icon-light.png",
    )
    for filename, expected_size in (
        ("apple-touch-icon.png", (180, 180)),
        ("beacon-tools-icon-512.png", (512, 512)),
        ("beacon-tools-logo.png", (1200, 349)),
        ("beacon-tools-mark.png", (512, 512)),
        ("beacon-tools-mark-64.png", (64, 64)),
        ("beacon-tools-mark-96.png", (96, 96)),
        ("favicon-32.png", (32, 32)),
        ("localflight-icon.png", (1024, 1024)),
        ("localflight-icon-light.png", (1024, 1024)),
    ):
        assert_image(SITE_ASSETS / filename, *expected_size)
    assert_ico(SITE_ASSETS / "favicon.ico", WINDOWS_ICO_SIZES)
    assert_images_differ(SITE_ASSETS / "localflight-icon.png", SITE_ASSETS / "localflight-icon-light.png")
    for filename in STALE_SITE_BRAND_ALIASES:
        if (SITE_ASSETS / filename).exists():
            raise ValueError(f"stale site brand alias still exists: {filename}")
    manifest = json.loads((ASSETS / "brand-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("phase") != "package-qt-lan-mobile-site":
        raise ValueError("brand manifest phase mismatch")


def main() -> None:
    validate_masters()
    with SvgRenderer() as renderer:
        stage_package_icons(renderer)
        stage_qt_lan_static(renderer)
        stage_mobile_assets(renderer)
        stage_site_assets(renderer)
        validate_stage()
        copy_validated_outputs()
        write_manifest(renderer.name)
    validate_active_outputs()
    print("Synced V2 package, Qt/LAN, mobile, and site brand assets from masters.")


if __name__ == "__main__":
    main()
