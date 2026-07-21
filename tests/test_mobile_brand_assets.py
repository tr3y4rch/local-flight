from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from scripts.mobile_brand_assets import (
    MOBILE_ASSET_SIZES,
    OPAQUE_MOBILE_ASSETS,
    TRANSPARENT_MOBILE_ASSETS,
    generate_mobile_brand_assets,
    sha256,
    validate_mobile_brand_assets,
)


ROOT = Path(__file__).resolve().parents[1]
MOBILE_ASSETS = ROOT / "mobile" / "assets"


def test_mobile_brand_generator_is_deterministic_and_mobile_only(tmp_path: Path) -> None:
    desktop_icon = ROOT / "assets" / "icon.png"
    desktop_hash = sha256(desktop_icon)

    first = generate_mobile_brand_assets(tmp_path)
    second = generate_mobile_brand_assets(tmp_path)

    assert first == second
    assert set(first) == set(MOBILE_ASSET_SIZES)
    assert sha256(desktop_icon) == desktop_hash


def test_active_mobile_brand_assets_follow_platform_alpha_contracts() -> None:
    validate_mobile_brand_assets(MOBILE_ASSETS)

    for filename in OPAQUE_MOBILE_ASSETS:
        with Image.open(MOBILE_ASSETS / filename) as source:
            image = source.convert("RGBA")
        assert image.getchannel("A").getextrema() == (255, 255)
        assert len(
            {
                image.getpixel((0, 0)),
                image.getpixel((image.width - 1, 0)),
                image.getpixel((0, image.height - 1)),
                image.getpixel((image.width - 1, image.height - 1)),
            }
        ) == 1

    for filename in TRANSPARENT_MOBILE_ASSETS:
        with Image.open(MOBILE_ASSETS / filename) as source:
            image = source.convert("RGBA")
        assert image.getchannel("A").getextrema() == (0, 255)
        assert image.getpixel((0, 0))[3] == 0


def test_android_monochrome_asset_is_a_single_color_mask() -> None:
    with Image.open(MOBILE_ASSETS / "localflight-android-monochrome.png") as source:
        image = source.convert("RGBA")

    visible_colors = {
        (red, green, blue)
        for red, green, blue, alpha in image.get_flattened_data()
        if alpha
    }
    assert visible_colors == {(255, 255, 255)}


def test_mobile_brand_manifest_hashes_match_active_outputs() -> None:
    manifest = json.loads((ROOT / "assets" / "brand-manifest.json").read_text(encoding="utf-8"))
    mobile_records = {
        record["path"].removeprefix("mobile/assets/"): record
        for record in manifest["active_outputs"]
        if record["path"].startswith("mobile/assets/")
    }

    assert set(mobile_records) == set(MOBILE_ASSET_SIZES)
    for filename, expected_size in MOBILE_ASSET_SIZES.items():
        record = mobile_records[filename]
        assert (record["width"], record["height"]) == expected_size
        assert record["sha256"] == sha256(MOBILE_ASSETS / filename)
