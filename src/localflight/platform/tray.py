"""
localflight/platform/tray.py

Windows  — hidden taskbar window (ctypes, no extra deps)
           Click taskbar button  → Open Display
           Right-click           → Open Display / Quit
macOS    — pystray system tray icon (unchanged)
Pi/Linux — no-op stub
"""
from __future__ import annotations

import sys
import threading
import webbrowser
from typing import Callable, Optional
from urllib.parse import quote

from localflight.platform.detect import is_desktop

BASE_URL = "http://localhost:8000"


def _splash_url(next_path: str = "/display") -> str:
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/display"
    return f"{BASE_URL}/splash?next={quote(next_path, safe='')}"


# ── No-op stub ─────────────────────────────────────────────────────────────────

class _HeadlessTray:
    def run(self) -> None:
        import time
        print("Running headless — no tray icon (Pi/Linux mode)")
        print("Access the UI at http://localhost:8000")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


# ── Windows taskbar window ─────────────────────────────────────────────────────

def _win_taskbar(on_quit: Callable, on_open_display: Callable) -> None:
    """Win32 message loop — runs in a daemon thread."""
    import ctypes
    import ctypes.wintypes as wt

    user32   = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32  = ctypes.windll.shell32

    WS_OVERLAPPEDWINDOW = 0x00CF0000
    WS_MINIMIZE         = 0x20000000
    WS_EX_APPWINDOW     = 0x00040000
    SW_SHOWMINNOACTIVE  = 7
    CS_HREDRAW          = 0x0002
    CS_VREDRAW          = 0x0001
    WM_DESTROY          = 0x0002
    WM_SYSCOMMAND       = 0x0112
    WM_CONTEXTMENU      = 0x007B
    WM_SETICON          = 0x0080
    SC_RESTORE          = 0xF120
    IMAGE_ICON          = 1
    LR_LOADFROMFILE     = 0x0010
    LR_DEFAULTSIZE      = 0x0040
    MF_STRING           = 0x0000
    MF_SEPARATOR        = 0x0800
    TPM_RIGHTBUTTON     = 0x0002
    TPM_RETURNCMD       = 0x0100
    ICON_SMALL          = 0
    ICON_BIG            = 1
    ID_OPEN             = 1001
    ID_QUIT             = 1002

    def MAKEINTRESOURCE(n: int) -> wt.LPCWSTR:
        return ctypes.cast(ctypes.c_void_p(n), wt.LPCWSTR)

    def _load_icon() -> wt.HICON:
        # Try extracting from the running exe (works in PyInstaller bundle)
        large = (wt.HICON * 1)()
        if shell32.ExtractIconExW(sys.executable, 0, large, None, 1) > 0 and large[0]:
            return large[0]
        # Dev: load from assets/icon.ico relative to project root
        from pathlib import Path
        ico = Path(__file__).parent.parent.parent.parent / "assets" / "icon.ico"
        if ico.exists():
            return user32.LoadImageW(
                None, str(ico), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE,
            )
        return user32.LoadIconW(None, MAKEINTRESOURCE(32512))  # IDI_APPLICATION

    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASSEX(ctypes.Structure):
        _fields_ = [
            ("cbSize",        ctypes.c_uint),
            ("style",         ctypes.c_uint),
            ("lpfnWndProc",   WNDPROC),
            ("cbClsExtra",    ctypes.c_int),
            ("cbWndExtra",    ctypes.c_int),
            ("hInstance",     wt.HINSTANCE),
            ("hIcon",         wt.HICON),
            ("hCursor",       wt.HANDLE),
            ("hbrBackground", wt.HBRUSH),
            ("lpszMenuName",  wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR),
            ("hIconSm",       wt.HICON),
        ]

    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        if msg == WM_SYSCOMMAND and (wparam & 0xFFF0) == SC_RESTORE:
            on_open_display()
            return 0
        if msg == WM_CONTEXTMENU:
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            hmenu = user32.CreatePopupMenu()
            user32.AppendMenuW(hmenu, MF_STRING,    ID_OPEN, "Open Display")
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0,       None)
            user32.AppendMenuW(hmenu, MF_STRING,    ID_QUIT, "Quit Local Flight")
            user32.SetForegroundWindow(hwnd)
            cmd = user32.TrackPopupMenu(
                hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD, x, y, 0, hwnd, None,
            )
            user32.DestroyMenu(hmenu)
            if cmd == ID_OPEN:
                on_open_display()
            elif cmd == ID_QUIT:
                on_quit()
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc_ptr  = WNDPROC(wnd_proc)
    hInstance = kernel32.GetModuleHandleW(None)
    cls_name  = "LocalFlightTaskbar"
    hIcon     = _load_icon()

    wc = WNDCLASSEX()
    wc.cbSize        = ctypes.sizeof(WNDCLASSEX)
    wc.style         = CS_HREDRAW | CS_VREDRAW
    wc.lpfnWndProc   = proc_ptr
    wc.hInstance     = hInstance
    wc.hCursor       = user32.LoadCursorW(None, MAKEINTRESOURCE(32512))  # IDC_ARROW
    wc.hbrBackground = ctypes.cast(ctypes.c_void_p(6), wt.HBRUSH)       # COLOR_WINDOW+1
    wc.lpszClassName = cls_name
    wc.hIcon         = hIcon
    wc.hIconSm       = hIcon
    user32.RegisterClassExW(ctypes.byref(wc))

    hwnd = user32.CreateWindowExW(
        WS_EX_APPWINDOW, cls_name, "Local Flight",
        WS_OVERLAPPEDWINDOW | WS_MINIMIZE,
        0, 0, 400, 300,
        None, None, hInstance, None,
    )
    if hIcon:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hIcon)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG,   hIcon)

    user32.ShowWindow(hwnd, SW_SHOWMINNOACTIVE)
    user32.UpdateWindow(hwnd)

    msg_buf = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg_buf), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg_buf))
        user32.DispatchMessageW(ctypes.byref(msg_buf))


class _WindowsTaskbar:
    def __init__(self, on_quit: Callable, on_open_display: Callable) -> None:
        threading.Thread(
            target=_win_taskbar, args=(on_quit, on_open_display), daemon=True,
        ).start()

    def run(self) -> None:
        threading.Event().wait()


# ── macOS pystray ──────────────────────────────────────────────────────────────

def _draw_icon(color: str = "#1D9E75"):
    from PIL import Image, ImageDraw
    size = 64
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([2, 2, size - 2, size - 2], fill=color)
    cx, cy = size // 2, size // 2
    draw.polygon([(cx-18,cy+4),(cx+20,cy),(cx-18,cy-4)], fill="white")
    draw.polygon([(cx-4,cy-2),(cx+4,cy-2),(cx-2,cy-14),(cx-10,cy-14)], fill="white")
    draw.polygon([(cx-18,cy-2),(cx-12,cy-2),(cx-16,cy-8)], fill="white")
    return img


def _status_color() -> str:
    try:
        from localflight.storage.state import load_state
        state = load_state()
        if state.ok:                 return "#1D9E75"
        elif state.last_success_utc: return "#BA7517"
        else:                        return "#A32D2D"
    except Exception:
        return "#888780"


def _update_icon_loop(icon, stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        try:
            icon.icon = _draw_icon(_status_color())
        except Exception:
            pass


# ── Public API ─────────────────────────────────────────────────────────────────

def build_tray(
    on_quit: Callable,
    on_restart_scheduler: Optional[Callable] = None,
    on_open_display: Optional[Callable] = None,
):
    """
    Returns a tray/taskbar object with a .run() method that blocks until quit.
    Windows  — hidden taskbar window; .run() blocks on Event.wait()
    macOS    — pystray icon;          .run() blocks until icon.stop()
    Pi/Linux — no-op stub;            .run() blocks until KeyboardInterrupt
    """
    if not is_desktop():
        return _HeadlessTray()

    if sys.platform == "win32":
        return _WindowsTaskbar(
            on_quit=on_quit,
            on_open_display=on_open_display or (lambda: webbrowser.open(_splash_url("/display"))),
        )

    # macOS — pystray
    import pystray
    color      = _status_color()
    img        = _draw_icon(color)
    stop_event = threading.Event()

    def _open_display(icon, item):
        (on_open_display or (lambda: webbrowser.open(_splash_url("/display"))))()

    def _open(path: str):
        return lambda icon, item: webbrowser.open(f"{BASE_URL}{path}")

    def _quit(icon, item):
        stop_event.set()
        icon.stop()
        on_quit()

    icon = pystray.Icon(
        name="localflight",
        icon=img,
        title="Local Flight",
        menu=pystray.Menu(
            pystray.MenuItem("Local Flight", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Display",  _open_display),
            pystray.MenuItem("Open FIDS",     _open("/fids")),
            pystray.MenuItem("Open Radar",    _open("/radar")),
            pystray.MenuItem("Open Settings", _open("/")),
            pystray.MenuItem("Open Admin",    _open("/admin")),
            pystray.MenuItem("Open History",  _open("/history")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        ),
    )
    threading.Thread(target=_update_icon_loop, args=(icon, stop_event), daemon=True).start()
    return icon
