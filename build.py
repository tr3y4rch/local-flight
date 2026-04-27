#!/usr/bin/env python3
"""
Build Local Flight for the current platform.

Produces:
  Windows  -> dist/LocalFlight/ + dist/LocalFlight-windows.zip + .sha256
  macOS    -> dist/LocalFlight.app + dist/LocalFlight-macos.zip + .sha256

Usage:
    python build.py           # build
    python build.py --clean   # wipe dist/ and build/ first
"""
from __future__ import annotations

import subprocess
import sys
import shutil
import hashlib
import os
from pathlib import Path

ROOT   = Path(__file__).parent
ASSETS = ROOT / "assets"


# ── Icon generation ────────────────────────────────────────────────────────────

def _make_placeholder() -> "Image.Image":
    from PIL import Image, ImageDraw
    size = 512
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    d.ellipse([4, 4, size - 4, size - 4], fill="#1D9E75")
    cx, cy = size // 2, size // 2
    d.polygon([(cx, cy-160),(cx+36,cy+20),(cx,cy-20),(cx-36,cy+20)], fill="white")
    d.polygon([(cx-140,cy+40),(cx+140,cy+40),(cx,cy-20)], fill="white")
    d.polygon([(cx-56,cy+100),(cx+56,cy+100),(cx,cy+20)], fill="white")
    return img


def make_icons() -> None:
    import io
    from PIL import Image

    ASSETS.mkdir(exist_ok=True)

    is_win   = sys.platform == "win32"
    svg_file = ASSETS / ("icon_square.svg" if is_win else "icon_circle.svg")
    png_candidates = [
        ASSETS / ("icon_square.png" if is_win else "icon_circle.png"),
        ASSETS / "icon_circle.png",
        ASSETS / "icon.png",
    ]

    img = None
    if svg_file.exists():
        try:
            import cairosvg
            data = cairosvg.svg2png(url=str(svg_file), output_width=512, output_height=512)
            img  = Image.open(io.BytesIO(data)).convert("RGBA")
            print(f"Rendered icon from {svg_file.name}")
        except ImportError:
            print("cairosvg not installed — checking for pre-rendered PNG")
    if img is None:
        for png_file in png_candidates:
            if png_file.exists():
                img = Image.open(png_file).convert("RGBA")
                print(f"Loaded icon from {png_file.name}")
                break
    if img is None:
        img = _make_placeholder()
        print("Using placeholder icon (install cairosvg or pre-render SVG to PNG)")

    img.save(ASSETS / "icon.png")

    if sys.platform == "win32":
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        frames = [img.resize(s, Image.LANCZOS) for s in sizes]
        frames[0].save(
            ASSETS / "icon.ico", format="ICO",
            sizes=sizes, append_images=frames[1:],
        )
        print("Generated assets/icon.ico")

    elif sys.platform == "darwin":
        iconset = ASSETS / "icon.iconset"
        iconset.mkdir(exist_ok=True)
        for s in [16, 32, 64, 128, 256, 512]:
            img.resize((s,    s),    Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
            img.resize((s*2,  s*2),  Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "icon.icns")],
            check=True,
        )
        shutil.rmtree(iconset)
        print("Generated assets/icon.icns")

    else:
        print("Generated assets/icon.png  (Linux — no .ico/.icns needed)")


# ── Code signing ──────────────────────────────────────────────────────────────

def _sign_windows(exe: Path) -> None:
    """
    Optionally sign the Windows EXE with signtool.
    Requires:
      SIGNTOOL_CERT  — path to .pfx certificate file
      SIGNTOOL_PASS  — certificate password
    Without these, build succeeds but SmartScreen will show an "Unknown publisher"
    warning on first run. Users can bypass it via More info → Run anyway.
    """
    import os
    cert = os.getenv("SIGNTOOL_CERT", "").strip()
    if not cert:
        print("  Signing skipped (set SIGNTOOL_CERT + SIGNTOOL_PASS to enable)")
        return
    pw = os.getenv("SIGNTOOL_PASS", "")
    signtool = shutil.which("signtool") or r"C:\Program Files (x86)\Windows Kits\10\bin\x64\signtool.exe"
    try:
        subprocess.run([
            signtool, "sign",
            "/f", cert,
            "/p", pw,
            "/tr", "http://timestamp.digicert.com",
            "/td", "sha256",
            "/fd", "sha256",
            str(exe),
        ], check=True)
        print(f"  Signed: {exe.name}")
    except Exception as e:
        print(f"  Signing failed (non-fatal): {e}")


def _sign_macos(app: Path) -> None:
    """
    Optionally sign and notarize the macOS .app bundle.
    Requires:
      CODESIGN_IDENTITY  — Developer ID Application: Your Name (TEAMID)
      NOTARIZE_PROFILE   — notarytool keychain profile name (see README)
    Without these, Gatekeeper will block the app. Users can bypass via
    System Settings → Privacy & Security → Open Anyway.
    """
    import os
    identity = os.getenv("CODESIGN_IDENTITY", "").strip()
    if not identity:
        print("  Signing skipped (set CODESIGN_IDENTITY to enable)")
        print("  Gatekeeper note: users must right-click → Open on first launch")
        return
    try:
        cmd = [
            "codesign", "--deep", "--force", "--options", "runtime",
            "--sign", identity,
        ]
        entitlements = ROOT / "assets" / "entitlements.plist"
        if entitlements.exists():
            cmd.extend(["--entitlements", str(entitlements)])
        cmd.append(str(app))
        subprocess.run(cmd, check=True)
        print(f"  Signed: {app.name}")
    except Exception as e:
        print(f"  codesign failed (non-fatal): {e}")
        return

    profile = os.getenv("NOTARIZE_PROFILE", "").strip()
    if not profile:
        print("  Notarization skipped (set NOTARIZE_PROFILE to enable)")
        return
    try:
        zip_path = app.parent / "LocalFlight-notarize.zip"
        subprocess.run(["ditto", "-c", "-k", "--keepParent", "--norsrc", str(app), str(zip_path)], check=True)
        subprocess.run([
            "xcrun", "notarytool", "submit", str(zip_path),
            "--keychain-profile", profile,
            "--wait",
        ], check=True)
        subprocess.run(["xcrun", "stapler", "staple", str(app)], check=True)
        zip_path.unlink(missing_ok=True)
        print(f"  Notarized and stapled: {app.name}")
    except Exception as e:
        print(f"  Notarization failed (non-fatal): {e}")


# ── Main ───────────────────────────────────────────────────────────────────────

def _write_sha256(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {path.name}\n", encoding="ascii")
    return checksum_path


def _archive_macos_app(app: Path) -> Path:
    """
    Zip the .app bundle for GitHub Releases.
    Prefer zip with COPYFILE_DISABLE to avoid AppleDouble ._ sidecars while
    preserving symlinks; fall back to ditto/shutil if zip is unavailable.
    """
    zip_path = app.parent / "LocalFlight-macos.zip"
    zip_path.unlink(missing_ok=True)
    if shutil.which("zip"):
        env = os.environ.copy()
        env["COPYFILE_DISABLE"] = "1"
        subprocess.run(["zip", "-qry", zip_path.name, app.name], cwd=app.parent, env=env, check=True)
        return zip_path
    if shutil.which("ditto"):
        subprocess.run(["ditto", "-c", "-k", "--keepParent", "--norsrc", str(app), str(zip_path)], check=True)
        return zip_path
    return Path(shutil.make_archive(str(zip_path.with_suffix("")), "zip", app.parent, app.name))


def main() -> None:
    if "--clean" in sys.argv:
        for name in ("dist", "build"):
            shutil.rmtree(ROOT / name, ignore_errors=True)
        print("Cleaned dist/ and build/")

    # Ensure PyInstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller…")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"],
            check=True,
        )

    make_icons()

    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "LocalFlight.spec", "--noconfirm"],
        check=True,
        cwd=ROOT,
    )

    dist = ROOT / "dist"
    if sys.platform == "win32":
        _sign_windows(dist / "LocalFlight" / "LocalFlight.exe")
        out = dist / "LocalFlight-windows"
        zip_path = Path(shutil.make_archive(str(out), "zip", dist, "LocalFlight"))
        checksum_path = _write_sha256(zip_path)
        print(f"\nDone: dist/LocalFlight-windows.zip")
        print(f"Checksum: {checksum_path.relative_to(ROOT)}")
        print("Distribute: unzip, then double-click LocalFlight.exe")
    elif sys.platform == "darwin":
        app = dist / "LocalFlight.app"
        _sign_macos(app)
        zip_path = _archive_macos_app(app)
        checksum_path = _write_sha256(zip_path)
        print(f"\nDone: dist/LocalFlight.app")
        print(f"Release zip: {zip_path.relative_to(ROOT)}")
        print(f"Checksum: {checksum_path.relative_to(ROOT)}")
        print("Distribute: upload the zip; users unzip, then drag LocalFlight.app to /Applications")
    else:
        print(f"\nDone: dist/LocalFlight/")


if __name__ == "__main__":
    main()
