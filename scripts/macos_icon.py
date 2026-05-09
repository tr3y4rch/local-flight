"""Build-time fallback renderer for the Local Flight macOS app icon."""
from __future__ import annotations

from typing import Any


def draw_macos_icon(size: int = 1024) -> Any:
    """Return a rounded-square PIL image when SVG rendering is unavailable."""
    from PIL import Image, ImageDraw, ImageFilter

    scale = size / 1024

    def n(value: float) -> int:
        return int(round(value * scale))

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # macOS-style tile shadow and rounded-square silhouette.
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [n(92), n(98), n(932), n(940)],
        radius=n(204),
        fill=(0, 0, 0, 120),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(n(30)))
    img.alpha_composite(shadow)

    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    for y in range(n(80), n(945)):
        t = (y - n(80)) / max(1, n(864))
        r = int(23 * (1 - t) + 7 * t)
        g = int(40 * (1 - t) + 16 * t)
        b = int(58 * (1 - t) + 24 * t)
        tile_draw.line([(n(80), y), (n(944), y)], fill=(r, g, b, 255))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([n(80), n(80), n(944), n(944)], radius=n(206), fill=255)
    img.alpha_composite(Image.composite(tile, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([n(84), n(84), n(940), n(940)], radius=n(202), outline="#294a68", width=max(1, n(3)))

    for radius, color, width in [(370, "#1d3d59", 2), (288, "#153047", 2), (206, "#0e2538", 2)]:
        draw.ellipse(
            [n(512 - radius), n(512 - radius), n(512 + radius), n(512 + radius)],
            outline=color,
            width=max(1, n(width)),
        )

    draw.rounded_rectangle([n(430), n(112), n(594), n(912)], radius=n(18), fill="#101d2b")
    draw.rounded_rectangle([n(454), n(112), n(570), n(912)], radius=n(12), fill="#0b121c")
    y = 142
    while y < 884:
        draw.line([(n(512), n(y)), (n(512), n(y + 30))], fill="#f0b429", width=max(2, n(7)))
        y += 60

    draw.rounded_rectangle([n(152), n(575), n(872), n(739)], radius=n(24), fill="#0c1722")
    for y, alpha in [(608, 255), (662, 210), (716, 160)]:
        draw.line([(n(182), n(y)), (n(842), n(y))], fill=(36, 71, 99, alpha), width=max(1, n(2)))

    for y, color in [(636, "#2ba8ff"), (690, "#24d27c"), (744, "#f0b429")]:
        draw.ellipse([n(204), n(y - 10), n(224), n(y + 10)], fill=color)

    rows = [
        (626, 142, 208, 82, 0.92),
        (680, 128, 178, 102, 0.78),
        (734, 164, 150, 74, 0.62),
    ]
    for y, first, second, third, opacity in rows:
        fill1 = (58, 111, 152, int(255 * opacity))
        fill2 = (33, 71, 103, int(255 * opacity))
        draw.rounded_rectangle([n(246), n(y), n(246 + first), n(y + 12)], radius=n(6), fill=fill1)
        draw.rounded_rectangle([n(414), n(y), n(414 + second), n(y + 12)], radius=n(6), fill=fill2)
        draw.rounded_rectangle([n(704), n(y), n(704 + third), n(y + 12)], radius=n(6), fill=fill1)

    # Aircraft glyph, intentionally text-free so it stays legible in the Dock.
    plane = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plane_draw = ImageDraw.Draw(plane)
    cx, cy = n(512), n(414)
    plane_draw.polygon(
        [(cx - n(13), cy + n(52)), (cx - n(4), cy - n(56)), (cx, cy - n(168)), (cx + n(4), cy - n(56)), (cx + n(13), cy + n(52)), (cx, cy + n(45))],
        fill="#edf5ff",
    )
    plane_draw.polygon(
        [(cx - n(97), cy + n(12)), (cx - n(48), cy), (cx, cy + n(7)), (cx + n(48), cy), (cx + n(97), cy + n(12)), (cx, cy + n(23))],
        fill="#c9dbef",
    )
    plane_draw.polygon(
        [(cx - n(44), cy + n(42)), (cx - n(20), cy + n(30)), (cx, cy + n(34)), (cx + n(20), cy + n(30)), (cx + n(44), cy + n(42)), (cx, cy + n(50))],
        fill="#a9c4e2",
    )
    plane = plane.rotate(-17, resample=Image.Resampling.BICUBIC, center=(cx, cy))
    img.alpha_composite(plane)

    for x, y in [(512, 178), (512, 848), (178, 512), (846, 512)]:
        draw.ellipse([n(x - 7), n(y - 7), n(x + 7), n(y + 7)], fill="#2ba8ff")

    return img
