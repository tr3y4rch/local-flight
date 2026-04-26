# LocalFlight.spec
#
# PyInstaller spec for Local Flight — Windows (.exe) and macOS (.app).
#
# Build with:   python build.py
# Or directly:  pyinstaller LocalFlight.spec --noconfirm

import sys
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files

# Read version from pyproject.toml so the spec never drifts out of sync
_pyproject = Path(SPECPATH) / "pyproject.toml"
_ver_match = re.search(r'^version\s*=\s*"([^"]+)"', _pyproject.read_text(), re.MULTILINE)
_VERSION = _ver_match.group(1) if _ver_match else "0.2.1b2"

is_win = sys.platform == "win32"
is_mac = sys.platform == "darwin"

# ── Collect packages that use dynamic/string-based internal imports ────────────
uvi_d,      uvi_b,      uvi_h      = collect_all("uvicorn")
fapi_d,     fapi_b,     fapi_h     = collect_all("fastapi")
anyio_d,    anyio_b,    anyio_h    = collect_all("anyio")
starlette_d,starlette_b,starlette_h= collect_all("starlette")

a = Analysis(
    ["src/localflight/__main__.py"],
    pathex=["src"],

    binaries=uvi_b + fapi_b + anyio_b + starlette_b,

    datas=[
        # App resources — must mirror the path that Path(__file__).parent resolves to
        ("src/localflight/ui/templates",    "localflight/ui/templates"),
        ("src/localflight/ui/static",       "localflight/ui/static"),
        ("src/localflight/decode/mappings", "localflight/decode/mappings"),
        ("src/localflight/storage/samples", "localflight/storage/samples"),
    ] + uvi_d + fapi_d + anyio_d + starlette_d + collect_data_files("tzdata"),

    hiddenimports=[
        # ── pystray + PIL: conditionally imported inside build_tray() ──────────
        "pystray",
        "PIL", "PIL.Image", "PIL.ImageDraw",

        # ── uvicorn internals loaded by string at startup ──────────────────────
        "uvicorn.logging",
        "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.lifespan.off", "uvicorn.lifespan.on",

        # ── Timezone data ──────────────────────────────────────────────────────
        "zoneinfo", "tzdata",

        # ── Pydantic v2 ────────────────────────────────────────────────────────
        "pydantic_core",

        # ── localflight platform modules (imported conditionally) ──────────────
        "localflight.platform.detect",
        "localflight.platform.browser",
        "localflight.platform.tray",
    ] + uvi_h + fapi_h + anyio_h + starlette_h,

    excludes=["pytest", "httpx", "IPython", "matplotlib", "numpy", "tkinter"],

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

# ── EXE / COLLECT ─────────────────────────────────────────────────────────────

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LocalFlight",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=is_win,       # UPX works on Windows; skip on macOS (arm64 incompatible)
    console=False,    # No terminal window on launch
    icon="assets/icon.ico" if is_win else ("assets/icon.icns" if is_mac else None),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=is_win,
    upx_exclude=[],
    name="LocalFlight",
)

# ── macOS .app bundle ─────────────────────────────────────────────────────────

if is_mac:
    app = BUNDLE(
        coll,
        name="LocalFlight.app",
        icon="assets/icon.icns",
        bundle_identifier="com.localflight.app",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSUIElement": True,               # Tray-only — suppress Dock icon
            "CFBundleShortVersionString": _VERSION,
            "CFBundleName": "Local Flight",
            "CFBundleDisplayName": "Local Flight",
        },
    )
