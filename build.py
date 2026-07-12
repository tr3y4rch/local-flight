#!/usr/bin/env python3
"""
Build Local Flight for the current platform.

Produces:
  Windows  -> dist/LocalFlight/ + dist/LocalFlight-windows.zip + .sha256
              optional Inno Setup installer with --installer
  macOS    -> dist/LocalFlight.app + dist/LocalFlight-<version>-macos.zip + .sha256
              optional signed/notarized .pkg installer with --installer

Usage:
    python build.py           # build
    python build.py --clean   # wipe dist/ and build/ first
    python build.py --installer  # build the platform installer
"""
from __future__ import annotations

import subprocess
import sys
import shutil
import hashlib
import json
import os
import tempfile
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


def _render_svg_with_qt(svg_file: Path) -> "Image.Image | None":
    """Render the SVG master with Qt when cairosvg is not available."""
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6 import QtGui, QtSvg
        from PIL import Image
    except Exception as exc:
        print(f"Qt SVG icon render unavailable ({exc})")
        return None

    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    renderer = QtSvg.QSvgRenderer(str(svg_file))
    if not renderer.isValid():
        print(f"Qt SVG icon render unavailable ({svg_file.name} is not a valid SVG)")
        return None

    image = QtGui.QImage(1024, 1024, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor(0, 0, 0, 0))
    painter = QtGui.QPainter(image)
    renderer.render(painter)
    painter.end()

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        if not image.save(str(tmp_path)):
            print("Qt SVG icon render unavailable (could not write temporary PNG)")
            return None
        rendered = Image.open(tmp_path).convert("RGBA")
        rendered.load()
        print(f"Rendered icon from {svg_file.name} via Qt SVG")
        return rendered
    finally:
        tmp_path.unlink(missing_ok=True)


def _write_macos_iconset(img: "Image.Image", iconset: Path) -> None:
    from PIL import Image

    shutil.rmtree(iconset, ignore_errors=True)
    iconset.mkdir(exist_ok=True)
    # Valid macOS iconset members are 16/32/128/256/512 plus their @2x
    # variants (which cover 32/64/256/512/1024 actual pixel sizes).
    for s in [16, 32, 128, 256, 512]:
        img.resize((s,    s),    Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
        img.resize((s*2,  s*2),  Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")


def make_icons() -> None:
    import io
    from PIL import Image

    ASSETS.mkdir(exist_ok=True)

    svg_file = ASSETS / "localflight-logo.svg"
    png_candidates = [
        ASSETS / "icon.png",
    ]

    img = None
    loaded_synced_png = False
    if svg_file.exists():
        try:
            import cairosvg
            data = cairosvg.svg2png(url=str(svg_file), output_width=1024, output_height=1024)
            img  = Image.open(io.BytesIO(data)).convert("RGBA")
            print(f"Rendered icon from {svg_file.name}")
        except Exception as exc:
            print(f"cairosvg icon render unavailable ({exc}) - trying Qt SVG")
        if img is None:
            img = _render_svg_with_qt(svg_file)
    if img is None:
        for png_file in png_candidates:
            if png_file.exists():
                img = Image.open(png_file).convert("RGBA")
                loaded_synced_png = png_file == ASSETS / "icon.png"
                print(f"Loaded synced V2 icon from {png_file.name}")
                break
    if img is None:
        img = _make_placeholder()
        print("Using placeholder icon (install cairosvg, PySide6 QtSvg, or pre-render SVG to PNG)")

    if not loaded_synced_png:
        img.save(ASSETS / "icon.png")

    if sys.platform == "win32":
        sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        img.save(ASSETS / "icon.ico", format="ICO", sizes=sizes)
        print("Generated assets/icon.ico")

    elif sys.platform == "darwin":
        icns_path = ASSETS / "icon.icns"
        iconset = ASSETS / "icon.iconset"
        _write_macos_iconset(img, iconset)
        if shutil.which("iconutil"):
            subprocess.run(
                ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
                check=True,
            )
            print("Generated assets/icon.icns via iconutil")
        else:
            img.save(icns_path, format="ICNS")
            print("Generated assets/icon.icns via Pillow")

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
        # Keep the bundle internally sealed even when no Developer ID is
        # available. This does not establish publisher trust or notarization,
        # but it catches damaged/tampered bundle contents after packaging.
        subprocess.run(
            ["codesign", "--deep", "--force", "--sign", "-", str(app)],
            check=True,
        )
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(app)],
            check=True,
        )
        print("  Applied ad-hoc bundle signature (no Developer ID trust)")
        print("  Gatekeeper note: users must use Finder Open on first launch")
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


def _archive_macos_app(app: Path, version: str) -> Path:
    """
    Zip the .app bundle for GitHub Releases.
    Prefer zip with COPYFILE_DISABLE to avoid AppleDouble ._ sidecars while
    preserving symlinks; fall back to ditto/shutil if zip is unavailable.
    """
    zip_path = app.parent / f"LocalFlight-{version}-macos.zip"
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


def _ensure_importable(import_name: str, package_spec: str) -> None:
    try:
        __import__(import_name)
        return
    except ImportError:
        print(f"Installing {package_spec} for release packaging...")
    subprocess.run([sys.executable, "-m", "pip", "install", package_spec], check=True)


def _project_version() -> str:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _ensure_project_metadata() -> None:
    """Keep editable package metadata in sync before PyInstaller freezes it."""
    expected = _project_version()
    reinstall_reason = ""
    try:
        from importlib.metadata import distribution, version

        installed = version("localflight")
        dist = distribution("localflight")
        direct_url = dist.read_text("direct_url.json") or ""
        try:
            direct = json.loads(direct_url)
        except json.JSONDecodeError:
            direct = {}
        source_url = str(direct.get("url") or "")
        root_marker = ROOT.resolve().as_posix()
        points_here = root_marker in source_url.replace("\\", "/")
        if installed != expected:
            reinstall_reason = f"metadata version is {installed}, expected {expected}"
        elif not points_here:
            reinstall_reason = "editable install does not point at this checkout"
    except Exception as exc:
        reinstall_reason = f"localflight metadata unavailable ({exc})"

    if not reinstall_reason:
        print(f"Local Flight package metadata OK ({expected})")
        return

    print(f"Refreshing Local Flight editable install: {reinstall_reason}")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", f"{ROOT}[native]"], check=True)


def main() -> None:
    build_installer = "--installer" in sys.argv

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

    # Packaged desktop clients are now native-first; fail early if Qt is not
    # available instead of silently producing a browser-dependent artifact.
    _ensure_project_metadata()
    _ensure_importable("PySide6", "PySide6>=6.7")

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
        if build_installer:
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "package_windows_installer.py")],
                check=True,
                cwd=ROOT,
            )
    elif sys.platform == "darwin":
        app = dist / "LocalFlight.app"
        if build_installer:
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "package_macos_installer.py")],
                check=True,
                cwd=ROOT,
            )
        else:
            _sign_macos(app)
            zip_path = _archive_macos_app(app, _project_version())
            checksum_path = _write_sha256(zip_path)
            print(f"\nDone: dist/LocalFlight.app")
            print(f"Direct-download zip: {zip_path.relative_to(ROOT)}")
            print(f"Checksum: {checksum_path.relative_to(ROOT)}")
            print("This build is ad-hoc signed and not notarized; document Finder Open for first launch.")
            print("A future Developer ID release can still use --installer to produce the signed .pkg.")
    else:
        print(f"\nDone: dist/LocalFlight/")


if __name__ == "__main__":
    main()
