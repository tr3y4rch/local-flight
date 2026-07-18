# LocalFlight.spec
#
# Flavor-aware PyInstaller specification for Local Flight desktop and Linux
# server release bundles. build.py supplies LOCALFLIGHT_BUILD_FLAVOR and the
# native target architecture; do not invoke this file directly for a release.

import os
import re
import sys
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files


ROOT = Path(SPECPATH)
_pyproject = ROOT / "pyproject.toml"
_VERSION = str(tomllib.loads(_pyproject.read_text(encoding="utf-8"))["project"]["version"])
_APP_NAME = "Local Flight"
_BUNDLE_IDENTIFIER = "com.localflight.app"
_BUILD_FLAVOR = os.environ.get("LOCALFLIGHT_BUILD_FLAVOR", "desktop").strip().lower()
_TARGET_ARCH = os.environ.get("LOCALFLIGHT_TARGET_ARCH", "").strip() or None

if _BUILD_FLAVOR not in {"desktop", "server"}:
    raise ValueError(f"Unsupported LOCALFLIGHT_BUILD_FLAVOR: {_BUILD_FLAVOR}")

is_win = sys.platform == "win32"
is_mac = sys.platform == "darwin"
is_server = _BUILD_FLAVOR == "server"
if is_server and (is_win or is_mac):
    raise ValueError("The frozen server flavor is supported on Linux only")

executable_name = "localflight-server" if is_server else "LocalFlight"
current_release_notes = ROOT / "docs" / f"release-notes-{_VERSION}.md"
if not current_release_notes.exists():
    raise FileNotFoundError(f"Missing current release notes: {current_release_notes}")


def _windows_version_tuple(version):
    parts = [int(part) for part in re.findall(r"\d+", version)[:4]]
    return tuple((parts + [0, 0, 0, 0])[:4])


windows_version_file = None
if is_win:
    version_tuple = _windows_version_tuple(_VERSION)
    windows_version_file = ROOT / "build" / "localflight_version_info.txt"
    windows_version_file.parent.mkdir(parents=True, exist_ok=True)
    windows_version_file.write_text(
        f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={version_tuple}, prodvers={version_tuple}, mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Beacon Tools'),
      StringStruct('FileDescription', 'Local Flight'),
      StringStruct('FileVersion', '{_VERSION}'),
      StringStruct('InternalName', 'LocalFlight'),
      StringStruct('OriginalFilename', 'LocalFlight.exe'),
      StringStruct('ProductName', 'Local Flight'),
      StringStruct('ProductVersion', '{_VERSION}')
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding="utf-8",
    )


uvi_d, uvi_b, uvi_h = collect_all("uvicorn")
fapi_d, fapi_b, fapi_h = collect_all("fastapi")
anyio_d, anyio_b, anyio_h = collect_all("anyio")
starlette_d, starlette_b, starlette_h = collect_all("starlette")

shared_hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops", "uvicorn.loops.auto", "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.lifespan.off", "uvicorn.lifespan.on",
    "zoneinfo", "tzdata", "pydantic_core",
    "localflight.platform.detect",
    "localflight.platform.browser",
    "localflight.platform.gui_mode",
    "localflight.platform.gui_launcher",
    "localflight.radar",
    "localflight.radar.classify",
    "localflight.radar.geo",
    "localflight.radar.map_layers",
    "localflight.radar.normalize",
    "localflight.radar.runways",
]

native_hiddenimports = [] if is_server else [
    "pystray", "PIL", "PIL.Image", "PIL.ImageDraw",
    "localflight.platform.tray",
    "localflight.native",
    "localflight.native._legacy_app",
    "localflight.native.api_client",
    "localflight.native.app",
    "localflight.native.async_tools",
    "localflight.native.bootstrap",
    "localflight.native.canvas",
    "localflight.native.canvas.matrix",
    "localflight.native.canvas.radar",
    "localflight.native.design",
    "localflight.native.identity",
    "localflight.native.live",
    "localflight.native.loader",
    "localflight.native.models",
    "localflight.native.network_admin",
    "localflight.native.pages",
    "localflight.native.pages.admin",
    "localflight.native.pages.display",
    "localflight.native.pages.feedback",
    "localflight.native.pages.fids",
    "localflight.native.pages.history",
    "localflight.native.pages.logs",
    "localflight.native.pages.matrix",
    "localflight.native.pages.radar",
    "localflight.native.pages.requests",
    "localflight.native.pages.settings",
    "localflight.native.pages.setup",
    "localflight.native.qt_compat",
    "localflight.native.registry",
    "localflight.native.routes",
    "localflight.native.service",
    "localflight.native.shell",
    "localflight.native.widgets",
    "PySide6", "shiboken6",
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtNetwork",
    "PySide6.QtSvg", "PySide6.QtWebSockets", "PySide6.QtWidgets",
]

datas = [
    ("src/localflight/ui/templates", "localflight/ui/templates"),
    ("src/localflight/ui/static", "localflight/ui/static"),
    ("assets/icon.png", "localflight/assets"),
    ("assets/localflight-logo.svg", "localflight/assets"),
    ("assets/brand-manifest.json", "localflight/assets"),
    ("docs/previews", "localflight/docs/previews"),
    ("README.md", "localflight/ui/docs"),
    ("docs/install.md", "localflight/ui/docs"),
    ("docs/display-modes.md", "localflight/ui/docs"),
    (str(current_release_notes), "localflight/ui/docs"),
    ("docs/release-notes-0.2.7.md", "localflight/ui/docs"),
    ("PRIVACY.md", "localflight/ui/docs"),
    ("CHANGELOG.md", "localflight/ui/docs"),
    ("THIRD_PARTY_NOTICES.md", "localflight/ui/docs"),
    ("src/localflight/decode/mappings", "localflight/decode/mappings"),
    ("src/localflight/storage/samples", "localflight/storage/samples"),
] + uvi_d + fapi_d + anyio_d + starlette_d + collect_data_files("tzdata")

excludes = ["pytest", "httpx", "IPython", "matplotlib", "numpy", "tkinter"]
if is_server:
    excludes += ["PySide6", "shiboken6", "pystray", "localflight.native"]

a = Analysis(
    ["src/localflight/__main__.py"],
    pathex=["src"],
    binaries=uvi_b + fapi_b + anyio_b + starlette_b,
    datas=datas,
    hiddenimports=(
        shared_hiddenimports
        + native_hiddenimports
        + uvi_h + fapi_h + anyio_h + starlette_h
    ),
    excludes=excludes,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=executable_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=is_win,
    console=is_server,
    icon="assets/icon.ico" if is_win else ("assets/icon.icns" if is_mac else None),
    version=str(windows_version_file) if is_win else None,
    target_arch=_TARGET_ARCH if is_mac else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=is_win,
    upx_exclude=[],
    name=executable_name,
)

if is_mac and not is_server:
    app = BUNDLE(
        coll,
        name="LocalFlight.app",
        icon="assets/icon.icns",
        bundle_identifier=_BUNDLE_IDENTIFIER,
        info_plist={
            "CFBundleExecutable": "LocalFlight",
            "CFBundleGetInfoString": f"{_APP_NAME} {_VERSION}",
            "CFBundleIconFile": "icon.icns",
            "CFBundleIdentifier": _BUNDLE_IDENTIFIER,
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleName": _APP_NAME,
            "CFBundleDisplayName": _APP_NAME,
            "CFBundlePackageType": "APPL",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "MIT License - Philipp Schumacher",
            "NSPrincipalClass": "NSApplication",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "12.0",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "CFBundleVersion": _VERSION,
            "CFBundleShortVersionString": _VERSION,
        },
    )
