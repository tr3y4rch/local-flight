#!/usr/bin/env python3
"""Build the Windows Inno Setup installer from dist/LocalFlight."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "LocalFlight"
ISS_PATH = ROOT / "installers" / "windows" / "LocalFlight.iss"
BRANDING_DIR = ROOT / "build" / "windows-installer-branding"
BEACON_LOGO = ROOT / "site" / "assets" / "beacon-tools-logo.png"
BEACON_MARK = ROOT / "site" / "assets" / "beacon-tools-icon-512.png"
PRODUCT_ICON = ROOT / "assets" / "icon.png"
APP_NAME = "Local Flight"
APP_PUBLISHER = "Beacon Tools"

WIZARD_IMAGE_SIZE = (164, 314)
WIZARD_SMALL_IMAGE_SIZE = (55, 55)
COLOR_BG = (8, 15, 24)
COLOR_PANEL = (13, 25, 38)
COLOR_ACCENT = (29, 158, 117)
COLOR_TEXT = (240, 247, 250)
COLOR_MUTED = (142, 163, 172)


def _project_version() -> str:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum_path


@dataclass(frozen=True)
class InstallerBranding:
    app_name: str
    app_version: str
    publisher: str
    product_icon: Path
    beacon_logo: Path
    beacon_mark: Path


def _font(size: int, *, bold: bool = False):
    from PIL import ImageFont

    font_names = ["seguisb.ttf", "segoeuib.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]
    font_dirs = [
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts",
        Path(r"C:\Windows\Fonts"),
    ]
    for font_dir in font_dirs:
        for font_name in font_names:
            font_path = font_dir / font_name
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size)
    return ImageFont.load_default()


def _fit_text(draw, text: str, max_width: int, start_size: int, *, bold: bool = False):
    size = start_size
    while size > 7:
        font = _font(size, bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 1
    return _font(size, bold=bold)


def _paste_contained(canvas, source_path: Path, box: tuple[int, int, int, int]) -> None:
    from PIL import Image

    with Image.open(source_path) as source:
        image = source.convert("RGBA")
    x1, y1, x2, y2 = box
    max_width = x2 - x1
    max_height = y2 - y1
    ratio = min(max_width / image.width, max_height / image.height)
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    image = image.resize(size, Image.LANCZOS)
    x = x1 + (max_width - image.width) // 2
    y = y1 + (max_height - image.height) // 2
    canvas.alpha_composite(image, (x, y))


def _draw_separator(draw, y: int, width: int) -> None:
    draw.line((18, y, width - 18, y), fill=(24, 44, 62), width=1)
    draw.line((18, y + 1, width - 18, y + 1), fill=(10, 20, 30), width=1)


def _generate_wizard_image(branding: InstallerBranding, output_path: Path) -> None:
    from PIL import Image, ImageDraw

    width, height = WIZARD_IMAGE_SIZE
    canvas = Image.new("RGBA", (width, height), COLOR_BG + (255,))
    draw = ImageDraw.Draw(canvas)

    draw.rectangle((0, 0, width, height), fill=COLOR_PANEL)
    draw.rectangle((0, 0, 5, height), fill=COLOR_ACCENT)
    draw.rectangle((5, 0, width, 24), fill=(10, 20, 31))
    draw.rectangle((5, height - 84, width, height), fill=(8, 16, 25))

    _paste_contained(canvas, branding.beacon_logo, (18, 28, width - 16, 72))
    draw.text((18, 82), "installer", fill=COLOR_MUTED, font=_font(9))
    _draw_separator(draw, 104, width)

    _paste_contained(canvas, branding.product_icon, (48, 143, 116, 211))
    product_font = _fit_text(draw, branding.app_name, width - 32, 16, bold=True)
    product_bbox = draw.textbbox((0, 0), branding.app_name, font=product_font)
    product_x = (width - (product_bbox[2] - product_bbox[0])) // 2
    draw.text((product_x, 222), branding.app_name, fill=COLOR_TEXT, font=product_font)

    version_text = f"v{branding.app_version}"
    version_font = _font(9)
    version_bbox = draw.textbbox((0, 0), version_text, font=version_font)
    draw.text(
        ((width - (version_bbox[2] - version_bbox[0])) // 2, 244),
        version_text,
        fill=COLOR_MUTED,
        font=version_font,
    )

    draw.text((18, height - 52), branding.publisher, fill=COLOR_TEXT, font=_font(11, bold=True))
    draw.text((18, height - 34), "local-first tools", fill=COLOR_MUTED, font=_font(8))
    canvas.convert("RGB").save(output_path, format="BMP")


def _generate_wizard_small_image(branding: InstallerBranding, output_path: Path) -> None:
    from PIL import Image, ImageDraw

    width, height = WIZARD_SMALL_IMAGE_SIZE
    canvas = Image.new("RGBA", (width, height), COLOR_BG + (255,))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, width, height), fill=(10, 20, 31))
    draw.rectangle((0, 0, 4, height), fill=COLOR_ACCENT)
    _paste_contained(canvas, branding.beacon_mark, (10, 7, 49, 46))
    canvas.convert("RGB").save(output_path, format="BMP")


def _generate_installer_branding(version: str) -> tuple[Path, Path]:
    for path in (BEACON_LOGO, BEACON_MARK, PRODUCT_ICON):
        if not path.exists():
            raise SystemExit(f"Missing installer branding asset: {path}")

    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    branding = InstallerBranding(
        app_name=APP_NAME,
        app_version=version,
        publisher=APP_PUBLISHER,
        product_icon=PRODUCT_ICON,
        beacon_logo=BEACON_LOGO,
        beacon_mark=BEACON_MARK,
    )
    wizard_image = BRANDING_DIR / "wizard-image.bmp"
    wizard_small_image = BRANDING_DIR / "wizard-small.bmp"
    _generate_wizard_image(branding, wizard_image)
    _generate_wizard_small_image(branding, wizard_small_image)
    return wizard_image, wizard_small_image


def _find_iscc() -> str:
    env_path = os.getenv("INNO_SETUP_COMPILER", "").strip()
    candidates = [
        Path(env_path) if env_path else None,
        Path(shutil.which("ISCC.exe") or "") if shutil.which("ISCC.exe") else None,
        Path(shutil.which("ISCC") or "") if shutil.which("ISCC") else None,
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    raise SystemExit(
        "Inno Setup compiler not found. Install Inno Setup 6 or set "
        "INNO_SETUP_COMPILER to ISCC.exe."
    )


def _sign_windows(path: Path) -> None:
    cert = os.getenv("SIGNTOOL_CERT", "").strip()
    if not cert:
        print("Signing skipped (set SIGNTOOL_CERT + SIGNTOOL_PASS to enable)")
        return
    signtool = shutil.which("signtool") or r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
    try:
        subprocess.run(
            [
                signtool,
                "sign",
                "/f",
                cert,
                "/p",
                os.getenv("SIGNTOOL_PASS", ""),
                "/tr",
                "http://timestamp.digicert.com",
                "/td",
                "sha256",
                "/fd",
                "sha256",
                str(path),
            ],
            check=True,
        )
        print(f"Signed: {path.name}")
    except Exception as exc:
        print(f"Signing failed (non-fatal): {exc}")


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("The Inno Setup installer can only be built on Windows.")
    if not (APP_DIR / "LocalFlight.exe").exists():
        raise SystemExit("Missing dist/LocalFlight/LocalFlight.exe. Run python build.py first.")
    if not ISS_PATH.exists():
        raise SystemExit(f"Missing installer definition: {ISS_PATH}")

    version = _project_version()
    output = DIST_DIR / f"LocalFlight-{version}-Setup.exe"
    output.unlink(missing_ok=True)
    output.with_suffix(output.suffix + ".sha256").unlink(missing_ok=True)
    wizard_image, wizard_small_image = _generate_installer_branding(version)

    iscc = _find_iscc()
    subprocess.run(
        [
            iscc,
            f"/DAppVersion={version}",
            f"/DSourceDir={APP_DIR}",
            f"/DOutputDir={DIST_DIR}",
            f"/DWizardImageFile={wizard_image}",
            f"/DWizardSmallImageFile={wizard_small_image}",
            str(ISS_PATH),
        ],
        check=True,
        cwd=ROOT,
    )

    if not output.exists():
        raise SystemExit(f"Inno Setup finished, but {output} was not created.")

    _sign_windows(output)
    checksum_path = _write_sha256(output)
    print(f"Windows installer: {output.relative_to(ROOT)}")
    print(f"Checksum: {checksum_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
