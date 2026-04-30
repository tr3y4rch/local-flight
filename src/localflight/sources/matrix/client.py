# ═══════════════════════════════════════════════════════════════════════════════
# Local Flight — Interstate 75 W MicroPython client
# Flash this to your Interstate 75 W (RP2350) board.
#
# Pimoroni MicroPython firmware required:
#   https://github.com/pimoroni/pimoroni-pico/releases
#
# Hardware: Interstate 75 W + 2x 128x64 HUB75 panels (256x64 total)
#
# Controls:
#   Button A     → show departures
#   Button B     → show arrivals
#   A + B (hold) → force refresh now
# ═══════════════════════════════════════════════════════════════════════════════

# ── User config — edit these ───────────────────────────────────────────────────
WIFI_SSID     = "Sunrise_2151269"
WIFI_PASSWORD = ""

API_HOST      = "192.168.1.49"   # IP of machine running Local Flight (e.g. Pi's LAN IP)
API_PORT      = 8000

PANEL_W          = 256   # total width  — must match physical panel chain
PANEL_H          = 64    # panel height — must match physical panel height

# Runtime defaults — overwritten by /api/matrix/config on boot
MAX_ROWS         = 4     # flight rows to display
REFRESH_S        = 60    # flight data fetch interval in seconds
BRIGHTNESS       = 0.8   # 0.0 – 1.0
DEFAULT_VIEW     = "departures"

CONFIG_REFRESH_S = 300   # re-read server config every 5 min
PING_S           = 600   # ping server every 10 min
CLIENT_VER       = "1.0"
# ──────────────────────────────────────────────────────────────────────────────

# Airport is read from the server — no hardcoding needed
_airport_iata = "---"

import time
import network
import urequests
import ujson
from interstate75 import Interstate75, DISPLAY_INTERSTATE75_128X64
from picographics import PicoGraphics, DISPLAY_INTERSTATE75_128X64 as DISPLAY
from pimoroni import Button

# ── Display init ───────────────────────────────────────────────────────────────
i75 = Interstate75(display=DISPLAY_INTERSTATE75_128X64, panels=2)
graphics = PicoGraphics(display=DISPLAY, width=PANEL_W, height=PANEL_H)
graphics.set_font("bitmap8")

WIDTH, HEIGHT = graphics.get_bounds()

# ── Buttons ────────────────────────────────────────────────────────────────────
btn_a = Button(i75.SWITCH_A)
btn_b = Button(i75.SWITCH_B)

# ── Colors ─────────────────────────────────────────────────────────────────────
BLACK = graphics.create_pen(0, 0, 0)
DIMBG = graphics.create_pen(10, 10, 10)

# Skin palettes: primary, text, dim, warning, danger
_SKIN_PALETTES = {
    "standard":  [(0,220,60),   (220,240,220), (0,80,20),   (255,160,0),  (220,30,30)],
    "technical": [(74,158,218), (200,216,232), (26,58,90),  (212,160,32), (192,64,64)],
    "neon":      [(0,255,80),   (0,255,80),    (0,122,40),  (170,255,0),  (255,64,64)],
    "cyan":      [(0,204,255),  (0,255,204),   (0,102,136), (255,204,0),  (255,64,96)],
    "crt":       [(255,170,0),  (255,204,68),  (122,80,0),  (255,221,0),  (255,64,32)],
}
_active_skin = "standard"

def apply_skin(name):
    global GREEN, WHITE, DIM, AMBER, RED, _active_skin
    p = _SKIN_PALETTES.get(name, _SKIN_PALETTES["standard"])
    GREEN = graphics.create_pen(*p[0])
    WHITE = graphics.create_pen(*p[1])
    DIM   = graphics.create_pen(*p[2])
    AMBER = graphics.create_pen(*p[3])
    RED   = graphics.create_pen(*p[4])
    _active_skin = name

apply_skin("standard")

# ── Split-flap animation ───────────────────────────────────────────────────────
FLAP_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:/-+"

class FlapChar:
    def __init__(self, char=" "):
        self.current = char
        self.target  = char
        self.frame   = 0
        self.frames  = 0

    def set_target(self, char):
        char = char.upper() if char in FLAP_CHARS else " "
        if char == self.target:
            return
        self.target = char
        self.frame  = 0
        self.frames = 10  # animation steps

    def step(self):
        if self.frame >= self.frames:
            self.current = self.target
            return
        progress = self.frame / max(1, self.frames)
        speed    = max(1, int((1.0 - progress) * 4))
        if self.frame % speed == 0:
            idx  = FLAP_CHARS.find(self.current)
            tidx = FLAP_CHARS.find(self.target)
            if idx < 0: idx = 0
            next_idx = (idx + 1) % len(FLAP_CHARS)
            if next_idx == tidx:
                self.current = self.target
            else:
                self.current = FLAP_CHARS[next_idx]
        self.frame += 1

    @property
    def settled(self):
        return self.current == self.target


class FlapRow:
    def __init__(self, length=42):
        self.cells = [FlapChar() for _ in range(length)]

    def set_text(self, text):
        text = text.upper()
        for i, cell in enumerate(self.cells):
            cell.set_target(text[i] if i < len(text) else " ")

    def step(self):
        for cell in self.cells:
            cell.step()

    def get_text(self):
        return "".join(c.current for c in self.cells)

    @property
    def settled(self):
        return all(c.settled for c in self.cells)


# ── Row layout ─────────────────────────────────────────────────────────────────
# TIME(5) SP FLIGHT(8) SP DEST(12) SP STATUS(10) SP GATE(4) = 42 chars
ROW_LEN = 42

def build_row_text(row):
    time_s   = (row.get("display_time",   "--:--")[:5]).ljust(5)
    flight_s = (row.get("flight_display", "")[:8]).ljust(8)
    dest_s   = (row.get("route_display",  "")[:12]).ljust(12)
    status_s = (row.get("status_display", "")[:10]).ljust(10)
    gate_s   = (row.get("gate",           "-")[:4]).ljust(4)
    return f"{time_s} {flight_s} {dest_s} {status_s} {gate_s}"

def status_color(status_str):
    s = (status_str or "").lower()
    if "delay" in s:               return AMBER
    if "cancel" in s:              return RED
    if "depart" in s or "land" in s: return DIM
    return GREEN

# ── WiFi ───────────────────────────────────────────────────────────────────────
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        return True

    _draw_message("Connecting WiFi...", GREEN)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    for _ in range(30):
        if wlan.isconnected():
            return True
        time.sleep(0.5)

    _draw_message("WiFi failed!", RED)
    time.sleep(2)
    return False


def ensure_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        return connect_wifi()
    return True

# ── API helpers ────────────────────────────────────────────────────────────────
def fetch_config():
    global _airport_iata
    url = f"http://{API_HOST}:{API_PORT}/api/config"
    try:
        resp = urequests.get(url, timeout=8)
        if resp.status_code == 200:
            data = ujson.loads(resp.text)
            resp.close()
            _airport_iata = (data.get("airport_iata") or "---").upper()
            return True
        resp.close()
    except Exception as e:
        print(f"Config fetch error: {e}")
    return False


def fetch_matrix_config():
    global MAX_ROWS, REFRESH_S, BRIGHTNESS, DEFAULT_VIEW
    url = f"http://{API_HOST}:{API_PORT}/api/matrix/config"
    try:
        resp = urequests.get(url, timeout=8)
        if resp.status_code == 200:
            data = ujson.loads(resp.text)
            resp.close()
            MAX_ROWS     = int(data.get("max_rows",         MAX_ROWS))
            REFRESH_S    = int(data.get("refresh_seconds",  REFRESH_S))
            BRIGHTNESS   = float(data.get("brightness",     BRIGHTNESS))
            DEFAULT_VIEW = data.get("default_view", DEFAULT_VIEW)
            skin = data.get("skin", "standard")
            if skin != _active_skin:
                apply_skin(skin)
            try:
                i75.set_brightness(BRIGHTNESS)
            except Exception:
                pass
            return True
        resp.close()
    except Exception as e:
        print(f"Matrix config fetch error: {e}")
    return False


def fetch_fids(view="departures", limit=4):
    url = f"http://{API_HOST}:{API_PORT}/api/fids?view={view}&limit={limit}"
    try:
        resp = urequests.get(url, timeout=10)
        if resp.status_code == 200:
            data = ujson.loads(resp.text)
            resp.close()
            return data
        resp.close()
    except Exception as e:
        print(f"Fetch error: {e}")
    return []


def ping_server():
    url = f"http://{API_HOST}:{API_PORT}/api/admin/ping?device=matrix&version={CLIENT_VER}"
    try:
        resp = urequests.post(url, timeout=5)
        resp.close()
    except Exception as e:
        print(f"Ping error: {e}")

# ── Drawing helpers ────────────────────────────────────────────────────────────
def _draw_message(msg, color=WHITE):
    graphics.set_pen(BLACK)
    graphics.clear()
    graphics.set_pen(color)
    graphics.set_font("bitmap8")
    graphics.text(msg, 2, HEIGHT // 2 - 4, WIDTH, 1)
    i75.update(graphics)

def draw_header(view, connected=True):
    label = f"{_airport_iata} {'DEP' if view == 'departures' else 'ARR'}"
    graphics.set_pen(GREEN)
    graphics.set_font("bitmap8")
    graphics.text(label, 0, 0, WIDTH, 1)

    # UTC time top right
    try:
        import utime
        t = utime.gmtime()
        ts = f"{t[3]:02d}:{t[4]:02d}"
        graphics.set_pen(DIM)
        tw = len(ts) * 8
        graphics.text(ts, WIDTH - tw - 2, 0, WIDTH, 1)
    except Exception:
        pass

    # Separator
    graphics.set_pen(DIM)
    graphics.line(0, 9, WIDTH, 9)

def draw_row(flap_row, row_data, y):
    text    = flap_row.get_text()
    s_color = status_color(row_data.get("status_display", "") if row_data else "")

    # Time (chars 0-4) — green
    graphics.set_pen(GREEN)
    graphics.set_font("bitmap8")
    graphics.text(text[0:5], 0, y, 50, 1)

    # Flight (chars 6-13) — white
    graphics.set_pen(WHITE)
    graphics.text(text[6:14], 52, y, 80, 1)

    # Dest (chars 15-26) — white
    graphics.set_pen(WHITE)
    if PANEL_W >= 200:
        graphics.text(text[15:27], 116, y, 96, 1)

    # Status (chars 28-37) — color
    graphics.set_pen(s_color)
    sx = 116 if PANEL_W < 200 else 212
    graphics.text(text[28:38], sx, y, 80, 1)

# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    flight_data      = []
    last_fetch       = 0
    last_ping        = 0
    last_config      = 0
    force_fetch      = True

    i75.set_led(0, 100, 0)  # green LED = running

    if not connect_wifi():
        i75.set_led(100, 0, 0)
        _draw_message("No WiFi. Retrying...", RED)
        time.sleep(5)
    else:
        fetch_config()
        fetch_matrix_config()
        last_config = time.time()
        ping_server()
        last_ping = time.time()

    view      = DEFAULT_VIEW
    flap_rows = [FlapRow(ROW_LEN) for _ in range(MAX_ROWS)]

    while True:
        now = time.time()

        # ── Button handling ────────────────────────────────────────────────────
        a = btn_a.read()
        b = btn_b.read()

        if a and b:
            # Both held — force refresh
            force_fetch = True
            _draw_message("Refreshing...", AMBER)
            time.sleep(0.5)
        elif a and view != "departures":
            view        = "departures"
            force_fetch = True
        elif b and view != "arrivals":
            view        = "arrivals"
            force_fetch = True

        # ── Periodic config refresh (picks up airport + matrix setting changes) ─
        if now - last_config >= CONFIG_REFRESH_S:
            if ensure_wifi():
                fetch_config()
                fetch_matrix_config()
                # Resize flap_rows if MAX_ROWS changed
                if len(flap_rows) != MAX_ROWS:
                    flap_rows = [FlapRow(ROW_LEN) for _ in range(MAX_ROWS)]
                    force_fetch = True
            last_config = now

        # ── Periodic ping ─────────────────────────────────────────────────────
        if now - last_ping >= PING_S:
            if ensure_wifi():
                ping_server()
            last_ping = now

        # ── Fetch ─────────────────────────────────────────────────────────────
        if force_fetch or (now - last_fetch >= REFRESH_S):
            force_fetch = False
            i75.set_led(0, 0, 100)  # blue = fetching

            if ensure_wifi():
                data = fetch_fids(view=view, limit=MAX_ROWS)
                if data:
                    flight_data = data
                    for i, row in enumerate(flight_data[:MAX_ROWS]):
                        flap_rows[i].set_text(build_row_text(row))
                    # Clear unused rows
                    for i in range(len(flight_data), MAX_ROWS):
                        flap_rows[i].set_text(" " * ROW_LEN)
                    last_fetch = now
                    i75.set_led(0, 100, 0)  # green = ok
                else:
                    i75.set_led(100, 50, 0)  # amber = no data
            else:
                i75.set_led(100, 0, 0)  # red = no wifi

        # ── Animate ───────────────────────────────────────────────────────────
        for flap in flap_rows:
            flap.step()

        # ── Draw ──────────────────────────────────────────────────────────────
        graphics.set_pen(BLACK)
        graphics.clear()

        draw_header(view)

        row_h      = (HEIGHT - 11) // MAX_ROWS
        data_start = 11

        for i in range(MAX_ROWS):
            y        = data_start + i * row_h
            row_data = flight_data[i] if i < len(flight_data) else None
            draw_row(flap_rows[i], row_data, y)

            # Row separator
            if i < MAX_ROWS - 1:
                graphics.set_pen(DIMBG)
                graphics.line(0, y + row_h - 1, WIDTH, y + row_h - 1)

        i75.update(graphics)
        time.sleep(0.05)  # ~20fps


# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()