#!/usr/bin/env python3
"""
Create a macOS .app bundle for a Local Flight source checkout.

Usage (called by install.sh):
    python scripts/make_app_bundle.py <project_root> <venv_path> <output_dir>

Creates:
    <output_dir>/LocalFlight.app/
        Contents/
            Info.plist
            MacOS/LocalFlight    (compiled Mach-O stub — required by Launch Services)
            MacOS/launcher.sh    (shell script with baked project root)
            Resources/AppIcon.icns
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _load_version(root: Path) -> str:
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        import tomli as tomllib  # type: ignore
    try:
        data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return data["project"]["version"]
    except Exception:
        return "0.0.0"


def _make_icns(root: Path, iconset_dir: Path) -> Path:
    """Render the macOS app icon source -> iconset -> .icns. Returns .icns path."""
    assets = root / "assets"
    icns_out = assets / "icon.icns"

    img = None

    # 1. Try cairosvg
    svg_candidates = [
        assets / "localflight-logo.svg",
    ]
    svg = next((candidate for candidate in svg_candidates if candidate.exists()), None)
    if svg is not None:
        try:
            import cairosvg
            from PIL import Image
            data = cairosvg.svg2png(url=str(svg), output_width=1024, output_height=1024)
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            print(f"  Icon: rendered from {svg.name} (cairosvg)")
        except Exception:
            pass

    # 2. Fall back to pre-rendered PNG
    if img is None:
        png_candidates = [
            assets / "icon.png",
        ]
        png = next((candidate for candidate in png_candidates if candidate.exists()), None)
        if png is not None:
            from PIL import Image
            img = Image.open(png).convert("RGBA")
            print(f"  Icon: loaded from {png.name}")

    # 3. PIL placeholder
    if img is None:
        from scripts.macos_icon import draw_macos_icon

        print("  Icon: generated macOS icon via Pillow fallback")
        img = draw_macos_icon(1024)

    from PIL import Image
    try:
        img.save(icns_out, format="ICNS")
        print(f"  Icon: generated {icns_out.name} via Pillow")
        return icns_out
    except Exception:
        shutil.rmtree(iconset_dir, ignore_errors=True)
        iconset_dir.mkdir(parents=True, exist_ok=True)
        for s in [16, 32, 128, 256, 512]:
            img.resize((s, s), Image.LANCZOS).save(iconset_dir / f"icon_{s}x{s}.png")
            img.resize((s * 2, s * 2), Image.LANCZOS).save(iconset_dir / f"icon_{s}x{s}@2x.png")

        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_out)],
            check=True,
        )
        shutil.rmtree(iconset_dir)
        print(f"  Icon: generated {icns_out.name} via iconutil")
    return icns_out


def _write_info_plist(contents: Path, version: str) -> None:
    plist = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Local Flight</string>
    <key>CFBundleDisplayName</key>
    <string>Local Flight</string>
    <key>CFBundleIdentifier</key>
    <string>com.localflight.app</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleVersion</key>
    <string>{version}</string>
    <key>CFBundleShortVersionString</key>
    <string>{version}</string>
    <key>CFBundleExecutable</key>
    <string>LocalFlight</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleGetInfoString</key>
    <string>Local Flight {version}</string>
    <key>NSHumanReadableCopyright</key>
    <string>MIT License - Philipp Schumacher</string>
    <key>NSPrincipalClass</key>
    <string>NSApplication</string>
    <key>LSApplicationCategoryType</key>
    <string>public.app-category.utilities</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
</dict>
</plist>
"""
    (contents / "Info.plist").write_text(plist, encoding="utf-8")


def _write_launcher(macos_dir: Path, project_root: Path, venv: Path) -> None:
    """Write launcher.sh with baked paths, and compile LocalFlight Mach-O stub."""
    script = textwrap.dedent(f"""\
        #!/usr/bin/env bash
        ROOT="{project_root}"
        VENV="{venv}"
        REQUESTED_GUI_MODE="${{LOCALFLIGHT_GUI_MODE:-}}"

        if [ ! -x "$VENV/bin/python" ]; then
            osascript -e 'display alert "Local Flight" message "Virtual environment not found.\\nRun installers/macos/install.sh first." as critical'
            exit 1
        fi

        if [ -f "$ROOT/.env" ]; then
            set -a
            # shellcheck disable=SC1091
            source "$ROOT/.env"
            set +a
        fi

        if [ -n "$REQUESTED_GUI_MODE" ]; then
            export LOCALFLIGHT_GUI_MODE="$REQUESTED_GUI_MODE"
        elif [ -z "${{LOCALFLIGHT_GUI_MODE:-}}" ]; then
            export LOCALFLIGHT_GUI_MODE="native"
        fi

        exec -a "Local Flight" "$VENV/bin/python" -m localflight
    """)
    sh = macos_dir / "launcher.sh"
    sh.write_text(script, encoding="utf-8")
    sh.chmod(0o755)

    _compile_stub(macos_dir / "LocalFlight")


def _compile_stub(out: Path) -> None:
    """
    Compile a minimal Mach-O binary that exec's launcher.sh in the same directory.
    macOS Launch Services requires a real binary as CFBundleExecutable — shell
    scripts are silently rejected when the app is opened from Finder.
    """
    import tempfile
    src = textwrap.dedent("""\
        #include <unistd.h>
        #include <stdint.h>
        #include <string.h>
        #include <mach-o/dyld.h>

        int main(void) {
            char exe[4096];
            uint32_t size = sizeof(exe);
            if (_NSGetExecutablePath(exe, &size) != 0) return 1;
            char *slash = strrchr(exe, '/');
            if (!slash) return 1;
            strcpy(slash + 1, "launcher.sh");
            char * const args[] = {"/bin/bash", exe, (char *)0};
            execv("/bin/bash", args);
            return 1;
        }
    """)
    with tempfile.NamedTemporaryFile(suffix=".c", mode="w", delete=False) as f:
        f.write(src)
        src_path = f.name
    try:
        subprocess.run(
            ["cc", "-O2", "-o", str(out), src_path],
            check=True,
        )
    finally:
        Path(src_path).unlink(missing_ok=True)
    out.chmod(0o755)
    print("  Stub: compiled LocalFlight binary")


def main() -> None:
    if len(sys.argv) < 4:
        print("Usage: make_app_bundle.py <project_root> <venv_path> <output_dir>")
        sys.exit(1)

    root       = Path(sys.argv[1]).resolve()
    venv       = Path(sys.argv[2]).resolve()
    output_dir = Path(sys.argv[3]).resolve()

    app      = output_dir / "LocalFlight.app"
    contents = app / "Contents"
    macos    = contents / "MacOS"
    resources = contents / "Resources"

    # Remove old bundle if present
    if app.exists():
        shutil.rmtree(app)

    for d in (macos, resources):
        d.mkdir(parents=True, exist_ok=True)

    version = _load_version(root)
    print(f"Building LocalFlight.app  v{version}")

    icns = _make_icns(root, root / "assets" / "icon.iconset")
    shutil.copy2(icns, resources / "AppIcon.icns")

    _write_info_plist(contents, version)
    _write_launcher(macos, root, venv)

    print(f"  Bundle: {app}")
    print("Done.")


if __name__ == "__main__":
    main()
