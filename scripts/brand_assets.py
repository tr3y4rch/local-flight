"""Local Flight master brand artwork.

The version-B mark is the single source for app icons, splash marks, window
icons, web/kiosk marks, and companion images. The SVG is the canonical vector
source; the Pillow renderer mirrors it for environments without an SVG
rasterizer.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable


MASTER_LOGO_SVG = """<svg width="1024" height="1024" viewBox="0 0 1024 1024" role="img" xmlns="http://www.w3.org/2000/svg">
  <title>Local Flight master logo</title>
  <desc>Rounded airport display tile with runway, aircraft, radar rings, and FIDS board rows.</desc>
  <defs>
    <linearGradient id="tile" x1="120" y1="58" x2="900" y2="966" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#12334c"/>
      <stop offset="0.52" stop-color="#091a29"/>
      <stop offset="1" stop-color="#061019"/>
    </linearGradient>
    <radialGradient id="glow" cx="50%" cy="36%" r="62%">
      <stop offset="0" stop-color="#61c8ff" stop-opacity="0.38"/>
      <stop offset="0.50" stop-color="#31e289" stop-opacity="0.10"/>
      <stop offset="1" stop-color="#051019" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="runway" x1="512" y1="110" x2="512" y2="915" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#10283d"/>
      <stop offset="1" stop-color="#07131f"/>
    </linearGradient>
    <filter id="soft-shadow" x="-25%" y="-25%" width="150%" height="155%">
      <feDropShadow dx="0" dy="26" stdDeviation="30" flood-color="#000000" flood-opacity="0.42"/>
    </filter>
    <clipPath id="tile-clip">
      <rect x="72" y="72" width="880" height="880" rx="196"/>
    </clipPath>
  </defs>
  <rect x="72" y="72" width="880" height="880" rx="196" fill="url(#tile)" filter="url(#soft-shadow)"/>
  <rect x="76" y="76" width="872" height="872" rx="192" fill="none" stroke="#2f719d" stroke-width="4" opacity="0.82"/>
  <g clip-path="url(#tile-clip)">
    <rect width="1024" height="1024" fill="url(#glow)"/>
    <circle cx="512" cy="512" r="348" fill="none" stroke="#245a7c" stroke-width="2" opacity="0.72"/>
    <circle cx="512" cy="512" r="252" fill="none" stroke="#16384f" stroke-width="2" opacity="0.61"/>
    <rect x="438" y="110" width="148" height="805" rx="18" fill="url(#runway)" opacity="0.97"/>
    <rect x="462" y="110" width="100" height="805" rx="12" fill="#07121c" opacity="0.70"/>
    <line x1="512" y1="144" x2="512" y2="881" stroke="#ffbf3d" stroke-width="7" stroke-linecap="round" stroke-dasharray="30 30"/>
    <rect x="166" y="610" width="692" height="140" rx="24" fill="#081520" opacity="0.94"/>
    <rect x="166" y="610" width="692" height="140" rx="24" fill="none" stroke="#2d668e" stroke-opacity="0.58" stroke-width="3"/>
    <rect x="196" y="644" width="632" height="2" fill="#2d668e" opacity="0.75"/>
    <circle cx="228" cy="671" r="9" fill="#61c8ff"/>
    <rect x="260" y="662" width="120" height="12" rx="6" fill="#5ca8cf" opacity="0.90"/>
    <rect x="430" y="662" width="190" height="12" rx="6" fill="#2c668d" opacity="0.72"/>
    <rect x="690" y="662" width="82" height="12" rx="6" fill="#5ca8cf" opacity="0.82"/>
    <rect x="196" y="673" width="632" height="2" fill="#2d668e" opacity="0.62"/>
    <circle cx="228" cy="700" r="9" fill="#31e289"/>
    <rect x="260" y="691" width="132" height="12" rx="6" fill="#5ca8cf" opacity="0.78"/>
    <rect x="430" y="691" width="175" height="12" rx="6" fill="#2c668d" opacity="0.60"/>
    <rect x="690" y="691" width="90" height="12" rx="6" fill="#5ca8cf" opacity="0.70"/>
    <rect x="196" y="703" width="632" height="2" fill="#2d668e" opacity="0.49"/>
    <circle cx="228" cy="730" r="9" fill="#f7bd38"/>
    <rect x="260" y="721" width="144" height="12" rx="6" fill="#5ca8cf" opacity="0.66"/>
    <rect x="430" y="721" width="160" height="12" rx="6" fill="#2c668d" opacity="0.48"/>
    <rect x="690" y="721" width="98" height="12" rx="6" fill="#5ca8cf" opacity="0.58"/>
    <g transform="translate(512 402) rotate(-17) scale(1.16)" filter="url(#soft-shadow)">
      <path d="M-13 52 C-6 12 -3 -56 0 -168 C3 -56 6 12 13 52 C6 47 3 45 0 45 C-3 45 -6 47 -13 52Z" fill="#ffffff"/>
      <path d="M-97 12 C-48 0 -16 2 0 7 C16 2 48 0 97 12 C49 28 15 27 0 23 C-15 27 -49 28 -97 12Z" fill="#d9ecff"/>
      <path d="M-44 42 C-20 30 -8 31 0 34 C8 31 20 30 44 42 C22 53 8 53 0 50 C-8 53 -22 53 -44 42Z" fill="#b2d1ef"/>
      <path d="M0 -168 L-8 -139 L8 -139 Z" fill="#ffffff"/>
    </g>
    <circle cx="512" cy="170" r="7" fill="#61c8ff"/>
    <circle cx="512" cy="854" r="7" fill="#61c8ff"/>
    <circle cx="176" cy="512" r="7" fill="#31e289"/>
    <circle cx="848" cy="512" r="7" fill="#f7bd38"/>
  </g>
</svg>
"""


def write_master_svg(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(MASTER_LOGO_SVG, encoding="utf-8")


def draw_master_logo(size: int = 1024, *, filled_background: bool = False) -> "Image.Image":
    """Return the master mark as a PIL RGBA image.

    ``filled_background`` is for OS home-screen/app-store icon slots that cannot
    carry alpha. In-app, splash, window, and favicon assets should keep alpha.
    """
    from PIL import Image, ImageDraw, ImageFilter

    scale = size / 1024

    def n(value: float) -> int:
        return int(round(value * scale))

    def rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
        value = hex_color.lstrip("#")
        return (
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
            alpha,
        )

    def rounded_mask(box_size: tuple[int, int], radius: int) -> "Image.Image":
        mask = Image.new("L", box_size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, box_size[0] - 1, box_size[1] - 1],
            radius=radius,
            fill=255,
        )
        return mask

    def gradient(box_size: tuple[int, int], stops: Iterable[str]) -> "Image.Image":
        colors = [rgba(stop) for stop in stops]
        img = Image.new("RGBA", box_size)
        draw = ImageDraw.Draw(img)
        for y in range(box_size[1]):
            t = y / max(1, box_size[1] - 1)
            if t < 0.52:
                u = t / 0.52
                a, b = colors[0], colors[1]
            else:
                u = (t - 0.52) / 0.48
                a, b = colors[1], colors[2]
            color = tuple(int(a[i] * (1 - u) + b[i] * u) for i in range(4))
            draw.line([(0, y), (box_size[0], y)], fill=color)
        return img

    def dashed_vertical(draw: "ImageDraw.ImageDraw", x: int, y0: int, y1: int) -> None:
        y = y0
        while y < y1:
            draw.line([(x, y), (x, min(y + n(30), y1))], fill=rgba("#ffbf3d"), width=max(1, n(7)))
            y += n(60)

    def transform(points: list[tuple[float, float]], cx: int, cy: int, deg: float, ratio: float) -> list[tuple[float, float]]:
        angle = math.radians(deg)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        transformed: list[tuple[float, float]] = []
        for x, y in points:
            x *= ratio
            y *= ratio
            transformed.append((cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a))
        return transformed

    def draw_plane(draw: "ImageDraw.ImageDraw") -> None:
        cx, cy = n(512), n(402)
        ratio = 1.16 * scale
        rotation = -17
        fuselage = [(-13, 52), (-6, 12), (-3, -56), (0, -168), (3, -56), (6, 12), (13, 52), (6, 47), (0, 45), (-6, 47)]
        wing = [(-97, 12), (-48, 0), (-16, 2), (0, 7), (16, 2), (48, 0), (97, 12), (49, 28), (15, 27), (0, 23), (-15, 27), (-49, 28)]
        tail = [(-44, 42), (-20, 30), (-8, 31), (0, 34), (8, 31), (20, 30), (44, 42), (22, 53), (8, 53), (0, 50), (-8, 53), (-22, 53)]
        nose = [(0, -168), (-8, -139), (8, -139)]
        draw.polygon(transform(wing, cx + n(7), cy + n(10), rotation, ratio), fill=(0, 0, 0, 55))
        draw.polygon(transform(wing, cx, cy, rotation, ratio), fill=rgba("#d9ecff"))
        draw.polygon(transform(fuselage, cx, cy, rotation, ratio), fill=rgba("#ffffff"))
        draw.polygon(transform(tail, cx, cy, rotation, ratio), fill=rgba("#b2d1ef"))
        draw.polygon(transform(nose, cx, cy, rotation, ratio), fill=rgba("#ffffff"))

    img = Image.new("RGBA", (size, size), rgba("#061019") if filled_background else (0, 0, 0, 0))

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle([n(72), n(72), n(952), n(952)], radius=n(196), fill=(0, 0, 0, 118))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, n(30))))
    img.alpha_composite(shadow)

    tile = gradient((n(880), n(880)), ["#12334c", "#091a29", "#061019"])
    tile_mask = rounded_mask((n(880), n(880)), n(196))
    tile.putalpha(tile_mask)
    img.alpha_composite(tile, (n(72), n(72)))

    content = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(content)
    draw.ellipse([n(512 - 348), n(512 - 348), n(512 + 348), n(512 + 348)], outline=rgba("#245a7c", 184), width=max(1, n(2)))
    draw.ellipse([n(512 - 252), n(512 - 252), n(512 + 252), n(512 + 252)], outline=rgba("#16384f", 156), width=max(1, n(2)))
    draw.rounded_rectangle([n(438), n(110), n(586), n(915)], radius=n(18), fill=rgba("#10283d", 247))
    draw.rounded_rectangle([n(462), n(110), n(562), n(915)], radius=n(12), fill=(7, 18, 28, 178))
    dashed_vertical(draw, n(512), n(144), n(881))
    draw.rounded_rectangle([n(166), n(610), n(858), n(750)], radius=n(24), fill=rgba("#081520", 240), outline=rgba("#2d668e", 148), width=max(1, n(3)))
    rows = [
        (644, 671, "#61c8ff", 120, 190, 82, 230),
        (673, 700, "#31e289", 132, 175, 90, 199),
        (703, 730, "#f7bd38", 144, 160, 98, 168),
    ]
    for i, (line_y, dot_y, dot, a, b, c, alpha) in enumerate(rows):
        draw.rectangle([n(196), n(line_y), n(828), n(line_y + 2)], fill=rgba("#2d668e", max(80, 190 - i * 33)))
        draw.ellipse([n(219), n(dot_y - 9), n(237), n(dot_y + 9)], fill=rgba(dot))
        draw.rounded_rectangle([n(260), n(line_y + 18), n(260 + a), n(line_y + 30)], radius=n(6), fill=rgba("#5ca8cf", alpha))
        draw.rounded_rectangle([n(430), n(line_y + 18), n(430 + b), n(line_y + 30)], radius=n(6), fill=rgba("#2c668d", max(90, alpha - 46)))
        draw.rounded_rectangle([n(690), n(line_y + 18), n(690 + c), n(line_y + 30)], radius=n(6), fill=rgba("#5ca8cf", max(120, alpha - 20)))
    draw_plane(draw)
    for x, y, color in [(512, 170, "#61c8ff"), (512, 854, "#61c8ff"), (176, 512, "#31e289"), (848, 512, "#f7bd38")]:
        draw.ellipse([n(x - 7), n(y - 7), n(x + 7), n(y + 7)], fill=rgba(color))

    clip = Image.new("L", (size, size), 0)
    clip_draw = ImageDraw.Draw(clip)
    clip_draw.rounded_rectangle([n(72), n(72), n(952), n(952)], radius=n(196), fill=255)
    content.putalpha(Image.composite(content.getchannel("A"), Image.new("L", (size, size), 0), clip))
    img.alpha_composite(content)
    ImageDraw.Draw(img).rounded_rectangle(
        [n(76), n(76), n(948), n(948)],
        radius=n(192),
        outline=rgba("#2f719d", 210),
        width=max(1, n(4)),
    )
    if filled_background:
        img.putalpha(255)
    return img
