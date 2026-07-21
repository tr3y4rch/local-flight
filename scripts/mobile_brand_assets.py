#!/usr/bin/env python3
"""Generate the platform-specific Local Flight mobile brand assets.

The desktop/package icon intentionally has a different contract.  Mobile uses
one compact mark: a bold aircraft over a single radar sweep.  Platform masks
own the icon silhouette, so these sources never bake in a rounded tile, border,
shadow, or glow.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "mobile" / "assets"
BRAND_FONT = DEFAULT_OUTPUT_DIR / "fonts" / "Audiowide-Regular.ttf"
UI_FONT = DEFAULT_OUTPUT_DIR / "fonts" / "DMSans.ttf"
BOARD_FONT = DEFAULT_OUTPUT_DIR / "fonts" / "SpaceMono-Bold.ttf"

ICON_SIZE = 1024
MARK_SIZE = 1024
SPLASH_SIZE = (1200, 520)
FEATURE_GRAPHIC_SIZE = (1024, 500)
SUPERSAMPLE = 2
GENERATOR_ID = "pillow-supersampled-mobile-mark-v1"


@dataclass(frozen=True)
class MobilePalette:
    background: str | None
    plane: str
    sweep: str


IOS_LIGHT = MobilePalette(background="#F5F1E8", plane="#132638", sweep="#2F6F9F")
IOS_DARK = MobilePalette(background="#08141D", plane="#F5F0E8", sweep="#74B5DE")
IOS_TINTED = MobilePalette(background="#F2F2F2", plane="#171717", sweep="#666666")
ANDROID = MobilePalette(background="#132638", plane="#F5F0E8", sweep="#74B5DE")
IN_APP_LIGHT = MobilePalette(background=None, plane="#132638", sweep="#2F6F9F")
IN_APP_DARK = MobilePalette(background=None, plane="#F5F0E8", sweep="#74B5DE")
MONOCHROME = MobilePalette(background=None, plane="#FFFFFF", sweep="#FFFFFF")


MOBILE_ASSET_SIZES: dict[str, tuple[int, int]] = {
    "localflight-ios-light.png": (ICON_SIZE, ICON_SIZE),
    "localflight-ios-dark.png": (ICON_SIZE, ICON_SIZE),
    "localflight-ios-tinted.png": (ICON_SIZE, ICON_SIZE),
    "localflight-android-foreground.png": (ICON_SIZE, ICON_SIZE),
    "localflight-android-background.png": (ICON_SIZE, ICON_SIZE),
    "localflight-android-monochrome.png": (ICON_SIZE, ICON_SIZE),
    "localflight-android-legacy.png": (ICON_SIZE, ICON_SIZE),
    "localflight-mark-light.png": (MARK_SIZE, MARK_SIZE),
    "localflight-mark-dark.png": (MARK_SIZE, MARK_SIZE),
    "localflight-splash-light.png": SPLASH_SIZE,
    "localflight-splash-dark.png": SPLASH_SIZE,
    "store/android/feature-graphic-1024x500.png": FEATURE_GRAPHIC_SIZE,
}
OPAQUE_MOBILE_ASSETS = {
    "localflight-ios-light.png",
    "localflight-ios-dark.png",
    "localflight-ios-tinted.png",
    "localflight-android-background.png",
    "localflight-android-legacy.png",
    "store/android/feature-graphic-1024x500.png",
}
TRANSPARENT_MOBILE_ASSETS = set(MOBILE_ASSET_SIZES) - OPAQUE_MOBILE_ASSETS


# Top-down aircraft silhouette, authored on a 1024-unit square.  The geometry
# stays deliberately chunky so it remains distinct under launcher masks and at
# small notification/setup sizes.
_PLANE_POINTS = (
    (512, 166),
    (548, 226),
    (556, 394),
    (790, 520),
    (790, 578),
    (554, 518),
    (548, 698),
    (638, 768),
    (638, 812),
    (512, 778),
    (386, 812),
    (386, 768),
    (476, 698),
    (470, 518),
    (234, 578),
    (234, 520),
    (468, 394),
    (476, 226),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = value.removeprefix("#")
    if len(value) != 6:
        raise ValueError(f"expected six-digit color, got {value!r}")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4)) + (alpha,)


def _resample(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if image.mode == "RGBA":
        # Resample premultiplied alpha so transparent assets do not pick up a
        # dark fringe around the white aircraft.
        return image.convert("RGBa").resize(size, Image.Resampling.LANCZOS).convert("RGBA")
    return image.resize(size, Image.Resampling.LANCZOS)


def _draw_mark(
    *,
    size: int,
    palette: MobilePalette,
    artwork_scale: float,
) -> Image.Image:
    work_size = size * SUPERSAMPLE
    unit = work_size / 1024
    transparent = (0, 0, 0, 0)
    canvas = Image.new(
        "RGBA",
        (work_size, work_size),
        _rgba(palette.background) if palette.background else transparent,
    )

    mark_layer = Image.new("RGBA", canvas.size, transparent)
    draw = ImageDraw.Draw(mark_layer)

    sweep_box = tuple(round(value * unit) for value in (156, 156, 868, 868))
    sweep_color = _rgba(palette.sweep)
    # One open sweep replaces the old concentric rings and target pings.
    draw.arc(
        sweep_box,
        start=198,
        end=326,
        fill=sweep_color,
        width=max(1, round(62 * unit)),
    )

    plane_mask = Image.new("L", canvas.size, 0)
    plane_draw = ImageDraw.Draw(plane_mask)
    plane_draw.polygon(
        [(round(x * unit), round(y * unit)) for x, y in _PLANE_POINTS],
        fill=255,
    )
    plane_mask = plane_mask.rotate(
        -38,
        resample=Image.Resampling.BICUBIC,
        center=(work_size // 2, work_size // 2),
    )
    plane_layer = Image.new("RGBA", canvas.size, _rgba(palette.plane))
    plane_layer.putalpha(plane_mask)
    mark_layer.alpha_composite(plane_layer)

    if artwork_scale != 1:
        scaled_size = max(1, round(work_size * artwork_scale))
        scaled = _resample(mark_layer, (scaled_size, scaled_size))
        mark_layer = Image.new("RGBA", canvas.size, transparent)
        mark_layer.alpha_composite(
            scaled,
            ((work_size - scaled_size) // 2, (work_size - scaled_size) // 2),
        )

    canvas.alpha_composite(mark_layer)
    return _resample(canvas, (size, size))


def _write_png(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False, compress_level=9)


def validate_mobile_brand_assets(output_dir: Path) -> None:
    """Validate platform fill, transparency, sizing, and adaptive safe area."""
    for filename, expected_size in MOBILE_ASSET_SIZES.items():
        path = output_dir / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        with Image.open(path) as source:
            if source.format != "PNG" or source.size != expected_size:
                raise ValueError(
                    f"{filename} must be a {expected_size[0]}x{expected_size[1]} PNG"
                )
            image = source.convert("RGBA")
        alpha = image.getchannel("A")
        alpha_extrema = alpha.getextrema()
        if filename in OPAQUE_MOBILE_ASSETS:
            if alpha_extrema != (255, 255):
                raise ValueError(f"{filename} must be full-bleed and opaque")
            corners = {
                image.getpixel((0, 0)),
                image.getpixel((image.width - 1, 0)),
                image.getpixel((0, image.height - 1)),
                image.getpixel((image.width - 1, image.height - 1)),
            }
            if len(corners) != 1:
                raise ValueError(f"{filename} has a baked edge treatment")
        else:
            if alpha_extrema != (0, 255) or image.getpixel((0, 0))[3] != 0:
                raise ValueError(f"{filename} must have a transparent outer canvas")

    for filename in (
        "localflight-android-foreground.png",
        "localflight-android-monochrome.png",
    ):
        with Image.open(output_dir / filename) as source:
            bounds = source.convert("RGBA").getchannel("A").getbbox()
        if bounds is None or bounds[0] < 180 or bounds[1] < 180 or bounds[2] > 844 or bounds[3] > 844:
            raise ValueError(f"{filename} escapes the adaptive-icon safe area: {bounds}")

    hashes = [sha256(output_dir / filename) for filename in MOBILE_ASSET_SIZES]
    if len(hashes) != len(set(hashes)):
        raise ValueError("mobile brand variants must not be duplicate files")


def _draw_splash_lockup(palette: MobilePalette) -> Image.Image:
    width, height = SPLASH_SIZE
    canvas = Image.new("RGBA", SPLASH_SIZE, (0, 0, 0, 0))

    mark = _draw_mark(size=360, palette=palette, artwork_scale=0.94)
    canvas.alpha_composite(mark, (44, 80))

    font_path = BRAND_FONT
    if not font_path.is_file():
        raise FileNotFoundError(f"mobile brand font is missing: {font_path}")
    font = ImageFont.truetype(str(font_path), 86)
    draw = ImageDraw.Draw(canvas)
    local = "LOCAL"
    flight = "FLIGHT"
    gap = 24
    local_width = round(draw.textlength(local, font=font))
    flight_width = round(draw.textlength(flight, font=font))
    text_width = local_width + gap + flight_width
    text_x = 424
    if text_x + text_width > canvas.width - 30:
        raise ValueError("splash wordmark does not fit its canvas")
    text_box = draw.textbbox((0, 0), f"{local} {flight}", font=font)
    text_height = text_box[3] - text_box[1]
    text_y = (canvas.height - text_height) // 2 - text_box[1]
    draw.text((text_x, text_y), local, font=font, fill=_rgba(palette.plane))
    draw.text(
        (text_x + local_width + gap, text_y),
        flight,
        font=font,
        fill=_rgba(palette.sweep),
    )
    return canvas


def _draw_feature_graphic() -> Image.Image:
    """Render the Play listing graphic in the warm Mobile V2 language."""
    width, height = FEATURE_GRAPHIC_SIZE
    canvas = Image.new("RGBA", FEATURE_GRAPHIC_SIZE, _rgba("#08141D"))
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Quiet horizon and route geometry keep the aviation cue atmospheric; the
    # launcher mark itself remains free of a baked tile, border, glow, or mask.
    draw.ellipse((-300, 210, 640, 1150), outline=_rgba("#74B5DE", 30), width=3)
    draw.ellipse((-210, 280, 500, 990), outline=_rgba("#59C1A5", 24), width=2)
    draw.arc((330, -230, 1130, 570), start=194, end=324, fill=_rgba("#74B5DE", 32), width=3)

    mark = _draw_mark(size=196, palette=IN_APP_DARK, artwork_scale=0.95)
    canvas.alpha_composite(mark, (48, 45))

    brand_font = ImageFont.truetype(str(BRAND_FONT), 47)
    ui_font = ImageFont.truetype(str(UI_FONT), 27)
    ui_small = ImageFont.truetype(str(UI_FONT), 18)
    board_small = ImageFont.truetype(str(BOARD_FONT), 15)
    board_tiny = ImageFont.truetype(str(BOARD_FONT), 13)

    draw.text((50, 264), "LOCAL FLIGHT", font=brand_font, fill=_rgba("#F5F0E8"))
    draw.text((52, 331), "Your airport, at a glance.", font=ui_font, fill=_rgba("#F5F0E8"))
    draw.text((52, 378), "Board  ·  Radar  ·  History", font=ui_small, fill=_rgba("#A4B3BE"))

    panel = (506, 38, 974, 462)
    draw.rounded_rectangle(panel, radius=34, fill=_rgba("#102330"))
    draw.rounded_rectangle((530, 62, 950, 128), radius=20, fill=_rgba("#17303F"))
    draw.text((550, 75), "ZURICH AIRPORT", font=ui_small, fill=_rgba("#F5F0E8"))
    draw.text((550, 101), "ZRH  ·  DEPARTURES", font=board_tiny, fill=_rgba("#74B5DE"))
    weather = "9°  ·  LIGHT WIND"
    weather_width = round(draw.textlength(weather, font=board_tiny))
    draw.text((930 - weather_width, 87), weather, font=board_tiny, fill=_rgba("#A4B3BE"))

    columns = (538, 602, 690, 862)
    headings = ("TIME", "FLIGHT", "TO", "STATUS")
    for x, label in zip(columns, headings, strict=True):
        draw.text((x, 150), label, font=board_tiny, fill=_rgba("#A4B3BE"))

    rows = (
        ("17:10", "LX 2808", "Bordeaux", "BOARDING", "#59C1A5"),
        ("18:05", "BA 713", "London", "ON TIME", "#74B5DE"),
        ("18:40", "LH 1191", "Frankfurt", "DELAYED", "#E3AD58"),
    )
    for index, (time, flight, route, status, tone) in enumerate(rows):
        y = 190 + index * 76
        if index:
            draw.line((538, y - 17, 942, y - 17), fill=_rgba("#345061", 150), width=1)
        draw.text((columns[0], y), time, font=board_small, fill=_rgba("#F5F0E8"))
        draw.text((columns[1], y), flight, font=board_small, fill=_rgba("#F5F0E8"))
        draw.text((columns[2], y), route, font=ui_small, fill=_rgba("#CCD5D9"))
        draw.text((columns[3], y), status, font=board_tiny, fill=_rgba(tone))

    draw.text((538, 423), "UPDATED NOW", font=board_tiny, fill=_rgba("#A4B3BE"))
    draw.line((865, 431, 940, 431), fill=_rgba("#59C1A5"), width=3)
    opaque = Image.new("RGBA", FEATURE_GRAPHIC_SIZE, _rgba("#08141D"))
    opaque.alpha_composite(canvas)
    return opaque


def prune_stale_mobile_brand_assets(output_dir: Path) -> None:
    """Remove superseded generated Local Flight PNGs from the output folder."""
    keep = set(MOBILE_ASSET_SIZES)
    for path in output_dir.glob("localflight-*.png"):
        if path.name not in keep:
            path.unlink()


def generate_mobile_brand_assets(output_dir: Path) -> dict[str, str]:
    """Generate every active mobile brand asset and return its SHA-256."""
    output_dir.mkdir(parents=True, exist_ok=True)
    prune_stale_mobile_brand_assets(output_dir)

    generated = {
        "localflight-ios-light.png": _draw_mark(size=ICON_SIZE, palette=IOS_LIGHT, artwork_scale=0.94),
        "localflight-ios-dark.png": _draw_mark(size=ICON_SIZE, palette=IOS_DARK, artwork_scale=0.94),
        "localflight-ios-tinted.png": _draw_mark(size=ICON_SIZE, palette=IOS_TINTED, artwork_scale=0.94),
        "localflight-android-foreground.png": _draw_mark(
            size=ICON_SIZE,
            palette=MobilePalette(background=None, plane=ANDROID.plane, sweep=ANDROID.sweep),
            artwork_scale=0.76,
        ),
        "localflight-android-background.png": Image.new(
            "RGBA", (ICON_SIZE, ICON_SIZE), _rgba(ANDROID.background or "#132638")
        ),
        "localflight-android-monochrome.png": _draw_mark(
            size=ICON_SIZE,
            palette=MONOCHROME,
            artwork_scale=0.76,
        ),
        "localflight-android-legacy.png": _draw_mark(
            size=ICON_SIZE,
            palette=ANDROID,
            artwork_scale=0.88,
        ),
        "localflight-mark-light.png": _draw_mark(
            size=MARK_SIZE,
            palette=IN_APP_LIGHT,
            artwork_scale=0.96,
        ),
        "localflight-mark-dark.png": _draw_mark(
            size=MARK_SIZE,
            palette=IN_APP_DARK,
            artwork_scale=0.96,
        ),
        "localflight-splash-light.png": _draw_splash_lockup(IN_APP_LIGHT),
        "localflight-splash-dark.png": _draw_splash_lockup(IN_APP_DARK),
        "store/android/feature-graphic-1024x500.png": _draw_feature_graphic(),
    }

    for filename, image in generated.items():
        expected_size = MOBILE_ASSET_SIZES[filename]
        if image.size != expected_size:
            raise ValueError(f"{filename} has size {image.size}, expected {expected_size}")
        _write_png(image, output_dir / filename)

    validate_mobile_brand_assets(output_dir)
    return {filename: sha256(output_dir / filename) for filename in sorted(generated)}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate Local Flight mobile brand assets.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    hashes = generate_mobile_brand_assets(args.output_dir)
    print(f"Generated {len(hashes)} mobile brand assets with {GENERATOR_ID}.")


if __name__ == "__main__":
    main()
