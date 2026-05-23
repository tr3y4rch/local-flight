#!/usr/bin/env python3
"""Render review examples from the four V2 brand master SVG files."""
from __future__ import annotations

import base64
import hashlib
import html
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "brand-renditions" / "v2"
IMG_DIR = OUT_DIR / "images"

BEACON_LOCKUP = Path(r"C:\Users\phsch\Beacon Tools Branding\Beacon\brand-v2\source\lockup_horizontal_dark.svg")
BEACON_MARK = Path(r"C:\Users\phsch\Beacon Tools Branding\Beacon\brand-v2\source\icon_mark.svg")
LOCAL_FLIGHT_DARK = Path(r"C:\Users\phsch\Beacon Tools Branding\Local-Flight\brand-v2\source\icon_dark.svg")
LOCAL_FLIGHT_LIGHT = Path(r"C:\Users\phsch\Beacon Tools Branding\Local-Flight\brand-v2\source\icon_light.svg")

RENDERER = "playwright-chromium"


@dataclass
class Rendition:
    id: str
    title: str
    file: str
    width: int
    height: int
    source: str
    renderer: str
    sha256: str
    notes: str = ""


class Renderer:
    def __enter__(self) -> "Renderer":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self._browser.close()
        self._pw.stop()

    def render_svg(self, svg: Path, output: Path, width: int, height: int) -> None:
        svg_text = svg.read_text(encoding="utf-8")
        page = self._browser.new_page(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
        )
        try:
            page.set_content(
                "<!doctype html><html><head><meta charset='utf-8'><style>"
                "*{box-sizing:border-box;margin:0;padding:0}"
                f"html,body{{width:{width}px;height:{height}px;background:transparent;overflow:hidden}}"
                f"svg{{width:{width}px;height:{height}px;display:block}}"
                "</style></head><body>"
                f"{svg_text}"
                "</body></html>",
                wait_until="load",
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output), omit_background=True, full_page=False)
        finally:
            page.close()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_has_content(path: Path) -> bool:
    with Image.open(path) as image:
        return image.convert("RGBA").getchannel("A").getbbox() is not None


def assert_png(path: Path, size: tuple[int, int]) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        if rgba.size != size:
            raise ValueError(f"{path} is {rgba.size}, expected {size}")
        if rgba.getchannel("A").getbbox() is None:
            raise ValueError(f"{path} is fully transparent")


def alpha_composite_on(source: Path, output: Path, background: Image.Image) -> None:
    with Image.open(source) as image:
        foreground = image.convert("RGBA")
    canvas = background.convert("RGBA")
    x = (canvas.width - foreground.width) // 2
    y = (canvas.height - foreground.height) // 2
    canvas.alpha_composite(foreground, (x, y))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def checkerboard(size: tuple[int, int], cell: int = 24) -> Image.Image:
    image = Image.new("RGBA", size, (240, 244, 248, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(205, 214, 224, 255))
    return image


def resize_contain(source: Path, output: Path, size: tuple[int, int], background: tuple[int, int, int, int]) -> None:
    with Image.open(source) as image:
        foreground = image.convert("RGBA")
    scale = min(size[0] / foreground.width, size[1] / foreground.height)
    resized = foreground.resize((round(foreground.width * scale), round(foreground.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGBA", size, background)
    canvas.alpha_composite(resized, ((size[0] - resized.width) // 2, (size[1] - resized.height) // 2))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def crop_center(source: Path, output: Path, size: tuple[int, int]) -> None:
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
    left = max(0, (rgba.width - size[0]) // 2)
    top = max(0, (rgba.height - size[1]) // 2)
    crop = rgba.crop((left, top, left + size[0], top + size[1]))
    output.parent.mkdir(parents=True, exist_ok=True)
    crop.save(output)


def label_font(size: int = 16) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def contact_sheet(items: list[tuple[str, Path]], output: Path, title: str, swatch: tuple[int, int] = (136, 136)) -> None:
    padding = 24
    title_h = 44
    label_h = 36
    width = padding * 2 + len(items) * swatch[0] + max(0, len(items) - 1) * 16
    height = padding * 2 + title_h + swatch[1] + label_h
    canvas = Image.new("RGBA", (width, height), (14, 23, 35, 255))
    draw = ImageDraw.Draw(canvas)
    title_font = label_font(20)
    small_font = label_font(13)
    draw.text((padding, padding), title, fill=(232, 244, 255, 255), font=title_font)
    x = padding
    y = padding + title_h
    for label, path in items:
        draw.rounded_rectangle([x, y, x + swatch[0], y + swatch[1]], radius=8, fill=(238, 244, 249, 255))
        with Image.open(path) as image:
            art = image.convert("RGBA")
        scale = min((swatch[0] - 20) / art.width, (swatch[1] - 20) / art.height)
        art = art.resize((max(1, round(art.width * scale)), max(1, round(art.height * scale))), Image.LANCZOS)
        canvas.alpha_composite(art, (x + (swatch[0] - art.width) // 2, y + (swatch[1] - art.height) // 2))
        draw.text((x, y + swatch[1] + 10), label, fill=(190, 210, 225, 255), font=small_font)
        x += swatch[0] + 16
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output)


def make_record(path: Path, title: str, source: Path, notes: str = "") -> Rendition:
    with Image.open(path) as image:
        width, height = image.size
    return Rendition(
        id=path.stem,
        title=title,
        file=f"images/{path.name}",
        width=width,
        height=height,
        source=str(source),
        renderer=RENDERER,
        sha256=sha256(path),
        notes=notes,
    )


def verify_lockup_wording(path: Path) -> None:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    right = rgba.crop((rgba.width // 3, 0, rgba.width, rgba.height))
    alpha = right.getchannel("A")
    if alpha.getbbox() is None:
        raise ValueError(f"{path} has no visible content in the wordmark area")
    gray = right.convert("L")
    if ImageChops.invert(gray).getbbox() is None:
        raise ValueError(f"{path} wordmark area has no contrast")


def render_examples() -> list[Rendition]:
    for master in (BEACON_LOCKUP, BEACON_MARK, LOCAL_FLIGHT_DARK, LOCAL_FLIGHT_LIGHT):
        if not master.exists():
            raise FileNotFoundError(master)

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    records: list[Rendition] = []
    with Renderer() as renderer:
        lockup_master = IMG_DIR / "beacon-lockup-master-1620x420.png"
        renderer.render_svg(BEACON_LOCKUP, lockup_master, 1620, 420)
        verify_lockup_wording(lockup_master)
        records.append(make_record(lockup_master, "Beacon Tools lockup master render", BEACON_LOCKUP))

        lockup_1200 = IMG_DIR / "beacon-lockup-1200x311.png"
        renderer.render_svg(BEACON_LOCKUP, lockup_1200, 1200, 311)
        verify_lockup_wording(lockup_1200)
        records.append(make_record(lockup_1200, "Beacon Tools lockup scaled", BEACON_LOCKUP))

        for name, title, background in (
            ("beacon-lockup-on-dark-1280x420.png", "Beacon lockup on dark context", Image.new("RGBA", (1280, 420), (4, 9, 17, 255))),
            ("beacon-lockup-on-light-1280x420.png", "Beacon lockup on light context", Image.new("RGBA", (1280, 420), (246, 250, 253, 255))),
            ("beacon-lockup-on-checker-1280x420.png", "Beacon lockup on checkerboard context", checkerboard((1280, 420), 28)),
        ):
            out = IMG_DIR / name
            resize_contain(lockup_1200, out, (1280, 420), (0, 0, 0, 0))
            with Image.open(out) as image:
                placed = image.convert("RGBA")
            background.alpha_composite(placed)
            background.save(out)
            records.append(make_record(out, title, BEACON_LOCKUP, "Context preview; master artwork is unchanged."))

        for name, title, size in (
            ("beacon-lockup-header-fit-1200x180.png", "Beacon lockup narrow header fit", (1200, 180)),
            ("beacon-lockup-header-crop-1200x180.png", "Beacon lockup narrow header crop", (1200, 180)),
        ):
            out = IMG_DIR / name
            if "fit" in name:
                resize_contain(lockup_1200, out, size, (4, 9, 17, 255))
            else:
                crop_center(lockup_1200, out, size)
            verify_lockup_wording(out)
            records.append(make_record(out, title, BEACON_LOCKUP))

        mark_paths: list[tuple[str, Path]] = []
        for size in (16, 32, 64, 96, 180, 512):
            out = IMG_DIR / f"beacon-mark-{size}.png"
            renderer.render_svg(BEACON_MARK, out, size, size)
            records.append(make_record(out, f"Beacon mark {size}px", BEACON_MARK))
            mark_paths.append((f"{size}px", out))

        for name, title, background in (
            ("beacon-mark-on-dark-512.png", "Beacon mark on dark context", Image.new("RGBA", (512, 512), (4, 9, 17, 255))),
            ("beacon-mark-on-light-512.png", "Beacon mark on light context", Image.new("RGBA", (512, 512), (246, 250, 253, 255))),
            ("beacon-mark-on-checker-512.png", "Beacon mark on checkerboard context", checkerboard((512, 512), 32)),
        ):
            out = IMG_DIR / name
            alpha_composite_on(IMG_DIR / "beacon-mark-512.png", out, background)
            records.append(make_record(out, title, BEACON_MARK))

        icon_rows: list[tuple[str, Path]] = []
        for variant, source in (("dark", LOCAL_FLIGHT_DARK), ("light", LOCAL_FLIGHT_LIGHT)):
            for size in (1024, 512, 256, 128, 64, 32, 16):
                out = IMG_DIR / f"local-flight-{variant}-icon-{size}.png"
                renderer.render_svg(source, out, size, size)
                records.append(make_record(out, f"Local Flight {variant} icon {size}px", source))
                if size in (128, 64, 32, 16):
                    icon_rows.append((f"{variant} {size}px", out))

    contact_outputs = [
        (
            "beacon-mark-size-contact-sheet.png",
            "Beacon mark size legibility",
            mark_paths,
        ),
        (
            "local-flight-icon-size-contact-sheet.png",
            "Local Flight icon small-size comparison",
            icon_rows,
        ),
        (
            "brand-overview-contact-sheet.png",
            "Brand overview",
            [
                ("Beacon lockup", IMG_DIR / "beacon-lockup-1200x311.png"),
                ("Beacon mark", IMG_DIR / "beacon-mark-512.png"),
                ("LF dark", IMG_DIR / "local-flight-dark-icon-512.png"),
                ("LF light", IMG_DIR / "local-flight-light-icon-512.png"),
            ],
        ),
    ]
    for filename, title, items in contact_outputs:
        out = IMG_DIR / filename
        contact_sheet(items, out, title)
        records.append(make_record(out, title, Path("derived-contact-sheet"), "Derived from rendered master examples."))

    for record in records:
        assert_png(OUT_DIR / record.file, (record.width, record.height))
    return records


def write_manifest(records: list[Rendition]) -> None:
    manifest = {
        "version": 1,
        "renderer": RENDERER,
        "masters": {
            "beacon_lockup": str(BEACON_LOCKUP),
            "beacon_mark": str(BEACON_MARK),
            "local_flight_dark": str(LOCAL_FLIGHT_DARK),
            "local_flight_light": str(LOCAL_FLIGHT_LIGHT),
        },
        "renditions": [asdict(record) for record in records],
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_gallery(records: list[Rendition]) -> None:
    cards = []
    for record in records:
        src = html.escape(record.file)
        cards.append(
            "<article class='card'>"
            f"<a href='{src}'><img src='{src}' alt='{html.escape(record.title)}'></a>"
            f"<h2>{html.escape(record.title)}</h2>"
            f"<p>{record.width}x{record.height}</p>"
            f"<p>{html.escape(record.notes)}</p>"
            f"<code>{html.escape(record.sha256[:16])}</code>"
            "</article>"
        )
    master_list = "".join(
        f"<li><code>{html.escape(str(path))}</code></li>"
        for path in (BEACON_LOCKUP, BEACON_MARK, LOCAL_FLIGHT_DARK, LOCAL_FLIGHT_LIGHT)
    )
    html_text = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Beacon Tools / Local Flight V2 Brand Renditions</title>"
        "<style>"
        ":root{color-scheme:dark;--bg:#060b12;--panel:#101b28;--text:#e8f4ff;--muted:#9eb5c9;--line:#203349}"
        "body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,Arial,sans-serif}"
        "main{max-width:1180px;margin:0 auto;padding:40px 24px 64px}"
        "h1{font-size:32px;margin:0 0 12px}p{color:var(--muted);line-height:1.5}"
        "ul{color:var(--muted);line-height:1.6}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:18px;margin-top:28px}"
        ".card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;min-width:0}"
        ".card img{display:block;width:100%;height:180px;object-fit:contain;background:#06101a;border-radius:6px}"
        ".card h2{font-size:15px;margin:12px 0 4px}.card p{font-size:13px;margin:4px 0}.card code{font-size:12px;color:#74d8ff}"
        "</style></head><body><main>"
        "<h1>Beacon Tools / Local Flight V2 Brand Renditions</h1>"
        "<p>Review-only examples rendered from the four master SVG files. These images do not implement branding across the app or website.</p>"
        f"<ul>{master_list}</ul>"
        "<p><a href='manifest.json'>Manifest JSON</a></p>"
        f"<section class='grid'>{''.join(cards)}</section>"
        "</main></body></html>"
    )
    (OUT_DIR / "index.html").write_text(html_text, encoding="utf-8")


def embedded_image_refs(html_path: Path) -> Iterable[Path]:
    import re

    text = html_path.read_text(encoding="utf-8")
    for match in re.finditer(r"(?:src|href)='([^']+)'", text):
        ref = match.group(1)
        if ref.endswith(".png"):
            yield html_path.parent / ref


def verify_gallery() -> None:
    index = OUT_DIR / "index.html"
    if not index.exists():
        raise FileNotFoundError(index)
    missing = [path for path in embedded_image_refs(index) if not path.exists()]
    if missing:
        raise FileNotFoundError(f"gallery references missing files: {missing}")
    manifest = json.loads((OUT_DIR / "manifest.json").read_text(encoding="utf-8"))
    if len(manifest["renditions"]) < 1:
        raise ValueError("manifest has no renditions")
    lockup = OUT_DIR / "images" / "beacon-lockup-master-1620x420.png"
    verify_lockup_wording(lockup)


def main() -> None:
    records = render_examples()
    write_manifest(records)
    write_gallery(records)
    verify_gallery()
    print(f"Rendered {len(records)} V2 brand rendition examples to {OUT_DIR}")


if __name__ == "__main__":
    main()
