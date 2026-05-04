# ═══════════════════════════════════════════════════════════════════════════════
# Local Flight — Interstate 75 W MicroPython client
# Flash this to your Interstate 75 W (RP2350) board.
#
# Pimoroni MicroPython firmware required:
#   https://github.com/pimoroni/pimoroni-pico/releases
#
# Hardware default: Interstate 75 W + 2x 128x64 HUB75 panels side-by-side (256x64)
#
# Controls:
#   Button A     → show departures
#   Button B     → show arrivals
#   A + B (hold) → force refresh now
# ═══════════════════════════════════════════════════════════════════════════════

# ── User config — edit these ───────────────────────────────────────────────────
WIFI_SSID     = "your_wifi_name"
WIFI_PASSWORD = "your_wifi_password"

API_HOST      = "localflight.local"   # LAN name or IP of the machine running Local Flight
API_PORT      = 8000
DEVICE_LABEL = "Interstate 75 W"

PANEL_W          = 256   # total physical pixel width
PANEL_H          = 64    # total physical pixel height

# Runtime defaults — overwritten by /api/matrix/config on boot
MAX_ROWS         = 4     # flight rows to display
REFRESH_S        = 60    # flight data fetch interval in seconds
PAGE_ROTATION_S  = 10    # rotate to the next local board page when overflow exists
BRIGHTNESS       = 0.8   # 0.0 – 1.0
DEFAULT_VIEW     = "departures"
ANIMATION_ENABLED = True
ANIMATION_MODE   = "split_flap"
ANIMATION_SPEED  = 3
STATUS_ANIMATION_ENABLED = True
PRESET           = "classic_split_flap"
RENDERER         = "split_flap"
MATRIX_CONFIG_REV = 0

CONFIG_REFRESH_S = 300   # re-read server config every 5 min
PING_S           = 600   # ping server every 10 min
CLIENT_VER       = "2.0"
SUPPORTED_RENDERERS = ["split_flap", "modern_fids", "terminal_minimal", "radar_strip"]
SUPPORTED_ANIMATIONS = ["split_flap", "slide_left", "slide_right", "static"]
# ──────────────────────────────────────────────────────────────────────────────

# Airport is read from the server — no hardcoding needed
_airport_iata = "---"
_device_id = None

import time
import network
import urequests
import ujson
try:
    import machine
    import ubinascii
except Exception:
    machine = None
    ubinascii = None
import interstate75 as interstate75_module
from interstate75 import Interstate75
try:
    from picographics import PicoGraphics
except Exception:
    PicoGraphics = None

# ── Display init ───────────────────────────────────────────────────────────────
def _display_constant(name, fallback=None):
    value = getattr(interstate75_module, name, None)
    if value is None:
        value = getattr(Interstate75, name, None)
    return fallback if value is None else value

def _display_for_size(width, height):
    width = int(width)
    height = int(height)
    name = "DISPLAY_INTERSTATE75_{}X{}".format(width, height)
    display = _display_constant(name)
    if display is not None:
        return display, None
    if height == 64 and width % 128 == 0:
        base = _display_constant("DISPLAY_INTERSTATE75_128X64")
        if base is not None:
            return base, max(1, width // 128)
    if height == 32 and width % 64 == 0:
        base = _display_constant("DISPLAY_INTERSTATE75_64X32")
        if base is not None:
            return base, max(1, width // 64)
    raise RuntimeError("Unsupported Interstate 75 display size: {}x{}".format(width, height))

DISPLAY, DISPLAY_PANELS = _display_for_size(PANEL_W, PANEL_H)
try:
    if DISPLAY_PANELS is None:
        i75 = Interstate75(display=DISPLAY)
    else:
        i75 = Interstate75(display=DISPLAY, panels=DISPLAY_PANELS)
except TypeError:
    i75 = Interstate75(display=DISPLAY)
graphics = getattr(i75, "display", None)
if graphics is None:
    if PicoGraphics is None:
        raise RuntimeError("PicoGraphics display buffer is unavailable")
    graphics = PicoGraphics(display=DISPLAY, width=PANEL_W, height=PANEL_H)
graphics.set_font("bitmap8")

WIDTH, HEIGHT = graphics.get_bounds()

def update_display():
    try:
        i75.update(graphics)
    except TypeError:
        i75.update()

# ── Buttons ────────────────────────────────────────────────────────────────────
SWITCH_A = _display_constant("SWITCH_A", 0)
SWITCH_B = _display_constant("SWITCH_B", 1)

def switch_pressed(switch):
    try:
        return bool(i75.switch_pressed(switch))
    except Exception:
        return False

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
    "amber":     [(255,170,0),  (255,210,92),  (110,70,0),  (255,221,0),  (255,64,32)],
    "green":     [(0,255,80),   (210,255,220), (0,80,24),   (255,180,0),  (255,48,48)],
    "white":     [(210,235,255), (240,248,255), (80,92,104), (255,200,0),  (255,60,60)],
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

def fit_text(value, length):
    text = str(value or "")
    if len(text) > length:
        return text[:length]
    return text + (" " * (length - len(text)))

class FlapChar:
    def __init__(self, char=" "):
        self.current = char
        self.target  = char
        self.frame   = 0
        self.frames  = 0

    def set_target(self, char):
        char = char.upper() if char in FLAP_CHARS else " "
        if not ANIMATION_ENABLED:
            self.current = char
            self.target = char
            self.frame = 0
            self.frames = 0
            return
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
        self.length = length
        self.mode = "split_flap"
        self.current_text = " " * length
        self.target_text = " " * length
        self.source_text = " " * length
        self.slide_frame = 0
        self.slide_frames = 0

    def set_mode(self, mode):
        self.mode = mode if mode in SUPPORTED_ANIMATIONS else "split_flap"

    def set_text(self, text):
        text = fit_text(text, self.length).upper()
        if self.mode == "static" or not ANIMATION_ENABLED:
            self.current_text = text
            self.target_text = text
            self.source_text = text
            self.slide_frame = 0
            self.slide_frames = 0
            for i, cell in enumerate(self.cells):
                cell.current = text[i]
                cell.target = text[i]
                cell.frame = 0
                cell.frames = 0
            return
        if self.mode in ("slide_left", "slide_right"):
            if text == self.target_text and self.slide_frame < self.slide_frames:
                return
            if text == self.current_text:
                self.target_text = text
                return
            self.source_text = self.current_text
            self.target_text = text
            self.slide_frame = 0
            self.slide_frames = max(6, 18 - int(ANIMATION_SPEED) * 2)
            return
        for i, cell in enumerate(self.cells):
            cell.set_target(text[i] if i < len(text) else " ")
        self.target_text = text

    def step(self):
        if self.mode in ("slide_left", "slide_right"):
            if self.slide_frame < self.slide_frames:
                self.slide_frame += 1
                if self.slide_frame >= self.slide_frames:
                    self.current_text = self.target_text
            return
        for cell in self.cells:
            cell.step()
        self.current_text = "".join(c.current for c in self.cells)

    def get_text(self):
        if self.mode in ("slide_left", "slide_right") and self.slide_frame < self.slide_frames:
            gap = "   "
            progress = self.slide_frame / max(1, self.slide_frames)
            span = self.length + len(gap)
            offset = int(progress * span)
            if self.mode == "slide_left":
                canvas = self.source_text + gap + self.target_text
                return fit_text(canvas[offset:offset + self.length], self.length)
            canvas = self.target_text + gap + self.source_text
            return fit_text(canvas[span - offset:span - offset + self.length], self.length)
        if self.mode in ("slide_left", "slide_right", "static"):
            return self.current_text
        return "".join(c.current for c in self.cells)

    @property
    def settled(self):
        return all(c.settled for c in self.cells)


# ── Row layout ─────────────────────────────────────────────────────────────────
# TIME(5) SP FLIGHT(8) SP DEST(12) SP STATUS(10) SP GATE(4) = 42 chars
ROW_LEN = 42

def _text_field(value, fallback=""):
    if value is None:
        value = fallback
    try:
        return str(value)
    except Exception:
        return str(fallback)

def build_row_text(row):
    time_s   = fit_text(_text_field(row.get("display_time") or row.get("time"), "--:--"), 5)
    flight_s = fit_text(_text_field(row.get("flight_display") or row.get("flight") or row.get("flight_number")), 8)
    dest_s   = fit_text(_text_field(row.get("route_display") or row.get("route")), 12)
    status_s = fit_text(_text_field(row.get("status_display") or row.get("status")), 10)
    gate_s   = fit_text(_text_field(row.get("gate"), "-"), 4)
    return f"{time_s} {flight_s} {dest_s} {status_s} {gate_s}"

def build_detail_text(row):
    op = row.get("operating_airline") or row.get("operator") or row.get("airline_display") or ""
    sold = row.get("sold_as") or row.get("codeshare") or row.get("codeshare_display") or ""
    aircraft = row.get("aircraft") or row.get("aircraft_type") or ""
    parts = []
    if op:
        parts.append("OP " + op)
    if sold:
        parts.append("SOLD " + sold.replace("Also ", ""))
    if aircraft:
        parts.append(aircraft)
    return " | ".join(parts)

def _status_key(row_or_status):
    if isinstance(row_or_status, dict):
        value = row_or_status.get("status_kind") or row_or_status.get("status_class") or row_or_status.get("status") or row_or_status.get("status_display") or ""
    else:
        value = row_or_status or ""
    return str(value).lower().replace("-", "_").replace(" ", "_")

def _blink_fast():
    if not STATUS_ANIMATION_ENABLED:
        return True
    return int(time.time() * 2) % 2 == 0

def _pulse_on():
    if not STATUS_ANIMATION_ENABLED:
        return True
    return int(time.time() * 3) % 3 != 0

def status_color(row_or_status):
    s = _status_key(row_or_status)
    if "delay" in s:               return AMBER
    if "cancel" in s:              return RED
    if "boarding" in s or "gate" in s: return AMBER if _pulse_on() else GREEN
    if "depart" in s or "arriv" in s or "approach" in s: return GREEN if _pulse_on() else WHITE
    if "land" in s: return DIM
    return GREEN

def is_cancelled(row):
    return "cancel" in _status_key(row)

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


def _clamp_int(value, minimum, maximum, fallback):
    try:
        parsed = int(value)
    except Exception:
        return fallback
    return max(minimum, min(maximum, parsed))


def _clamp_float(value, minimum, maximum, fallback):
    try:
        parsed = float(value)
    except Exception:
        return fallback
    return max(minimum, min(maximum, parsed))


def _normalize_view(value, fallback):
    view = (value or "").strip().lower()
    return view if view in ("departures", "arrivals") else fallback


def _normalize_airport_iata(value):
    code = (value or "").strip().upper()
    if len(code) == 3 and all("A" <= ch <= "Z" for ch in code):
        return code
    return "---"


def device_id():
    global _device_id
    if _device_id:
        return _device_id
    try:
        if machine and ubinascii:
            raw = ubinascii.hexlify(machine.unique_id()).decode()
            _device_id = "i75w-" + raw[-8:]
        else:
            _device_id = "i75w-dev"
    except Exception:
        _device_id = "i75w-dev"
    return _device_id


def _api_url(path):
    return f"http://{API_HOST}:{API_PORT}{path}"


def _get_json(path, timeout=8):
    try:
        # Some Pimoroni MicroPython urequests builds do not accept timeout=.
        resp = urequests.get(_api_url(path))
        if resp.status_code == 200:
            data = ujson.loads(resp.text)
            resp.close()
            return data
        resp.close()
    except Exception as e:
        print(f"GET {path} error: {e}")
    return None


def _post_json(path, payload, timeout=8):
    try:
        resp = urequests.post(
            _api_url(path),
            data=ujson.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code in (200, 201):
            data = ujson.loads(resp.text)
            resp.close()
            return data
        resp.close()
    except Exception as e:
        print(f"POST {path} error: {e}")
    return None

# ── API helpers ────────────────────────────────────────────────────────────────
def fetch_config():
    global _airport_iata
    data = _get_json("/api/config", timeout=8)
    if not isinstance(data, dict):
        return False
    _airport_iata = _normalize_airport_iata(data.get("airport_iata"))
    return True


def checkin_matrix_device():
    payload = {
        "device_id": device_id(),
        "label": DEVICE_LABEL,
        "panel_w": PANEL_W,
        "panel_h": PANEL_H,
        "firmware": CLIENT_VER,
        "renderers": SUPPORTED_RENDERERS,
    }
    data = _post_json("/api/matrix/v2/devices/checkin", payload, timeout=8)
    return isinstance(data, dict) and bool(data.get("ok"))


def fetch_matrix_config():
    global MAX_ROWS, REFRESH_S, PAGE_ROTATION_S, BRIGHTNESS, DEFAULT_VIEW
    global ANIMATION_ENABLED, ANIMATION_MODE, ANIMATION_SPEED, STATUS_ANIMATION_ENABLED
    global PRESET, RENDERER, MATRIX_CONFIG_REV
    data = _get_json(f"/api/matrix/v2/devices/{device_id()}/config", timeout=8)
    if not isinstance(data, dict):
        data = _get_json("/api/matrix/config", timeout=8)
    if not isinstance(data, dict):
        return False
    MAX_ROWS     = _clamp_int(data.get("max_rows", MAX_ROWS), 1, 8, MAX_ROWS)
    REFRESH_S    = _clamp_int(data.get("refresh_seconds", REFRESH_S), 10, 3600, REFRESH_S)
    PAGE_ROTATION_S = _clamp_int(data.get("page_rotation_seconds", PAGE_ROTATION_S), 3, 120, PAGE_ROTATION_S)
    BRIGHTNESS   = _clamp_float(data.get("brightness", BRIGHTNESS), 0.05, 1.0, BRIGHTNESS)
    DEFAULT_VIEW = _normalize_view(data.get("default_view", DEFAULT_VIEW), DEFAULT_VIEW)
    ANIMATION_ENABLED = bool(data.get("animation_enabled", ANIMATION_ENABLED))
    ANIMATION_MODE = data.get("animation_mode", ANIMATION_MODE)
    if ANIMATION_MODE not in SUPPORTED_ANIMATIONS:
        ANIMATION_MODE = "split_flap"
    if not ANIMATION_ENABLED:
        ANIMATION_MODE = "static"
    ANIMATION_SPEED = _clamp_int(data.get("animation_speed", ANIMATION_SPEED), 1, 5, ANIMATION_SPEED)
    STATUS_ANIMATION_ENABLED = bool(data.get("status_animation_enabled", STATUS_ANIMATION_ENABLED))
    PRESET = data.get("preset", PRESET)
    RENDERER = data.get("renderer", RENDERER)
    MATRIX_CONFIG_REV = data.get("config_rev", MATRIX_CONFIG_REV)
    skin = data.get("palette") or data.get("skin") or "standard"
    if skin != _active_skin:
        apply_skin(skin)
    try:
        i75.set_brightness(BRIGHTNESS)
    except Exception:
        pass
    return True


def fetch_fids(view="departures", limit=4):
    view = _normalize_view(view, "departures")
    limit = _clamp_int(limit, 1, 32, max(MAX_ROWS, limit))
    data = _get_json(f"/api/fids?view={view}&limit={limit}", timeout=10)
    if isinstance(data, list):
        return data
    data = _get_json(f"/api/matrix/v2/devices/{device_id()}/feed?view={view}", timeout=10)
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        return data.get("rows") or []
    return []


def ping_server():
    _post_json("/api/matrix/v2/devices/checkin", {
        "device_id": device_id(),
        "label": DEVICE_LABEL,
        "panel_w": PANEL_W,
        "panel_h": PANEL_H,
        "firmware": CLIENT_VER,
        "renderers": SUPPORTED_RENDERERS,
    }, timeout=5)

# ── Drawing helpers ────────────────────────────────────────────────────────────
def _draw_message(msg, color=WHITE):
    graphics.set_pen(BLACK)
    graphics.clear()
    graphics.set_pen(color)
    graphics.set_font("bitmap8")
    graphics.text(msg, 2, HEIGHT // 2 - 4, WIDTH, 1)
    update_display()

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
    s_color = status_color(row_data or "")
    cancelled = bool(row_data and is_cancelled(row_data))
    cancel_flash = cancelled and _blink_fast()
    if cancel_flash:
        graphics.set_pen(RED)
        graphics.rectangle(0, y - 1, WIDTH, 9)

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
    graphics.set_pen(WHITE if cancel_flash else s_color)
    sx = 116 if PANEL_W < 200 else 212
    graphics.text(text[28:38], sx, y, 80, 1)


def draw_terminal_minimal(page_rows):
    draw_header(DEFAULT_VIEW)
    if not page_rows:
        graphics.set_pen(AMBER)
        graphics.text("NO FLIGHTS", 4, 24, WIDTH, 2)
        return
    hero = page_rows[0]
    time_s = (hero.get("time") or hero.get("display_time") or "--:--")[:5]
    flight_s = (hero.get("flight") or hero.get("flight_display") or "-")[:9]
    route_s = (hero.get("route") or hero.get("route_display") or "-")[:16]
    status_s = (hero.get("status") or hero.get("status_display") or "-")[:12]
    detail_s = build_detail_text(hero)[:28]
    if is_cancelled(hero) and _blink_fast():
        graphics.set_pen(RED)
        graphics.rectangle(0, 12, WIDTH, 42)
    graphics.set_pen(WHITE)
    graphics.text(f"{time_s} {flight_s}", 2, 14, WIDTH, 2)
    graphics.set_pen(GREEN)
    graphics.text(route_s, 2, 32, WIDTH, 1)
    graphics.set_pen(status_color(hero))
    graphics.text(status_s, 2, 44, WIDTH, 1)
    if detail_s:
        graphics.set_pen(DIM)
        graphics.text(detail_s, 70, 44, WIDTH - 70, 1)
    y = 54
    for row in page_rows[1:3]:
        graphics.set_pen(DIM)
        graphics.text(build_row_text(row)[:34], 2, y, WIDTH, 1)
        y += 9


def draw_radar_strip(page_rows):
    graphics.set_pen(BLACK)
    graphics.clear()
    graphics.set_pen(GREEN)
    graphics.text(f"{_airport_iata} RADAR {DEFAULT_VIEW[:3].upper()}", 0, 0, WIDTH, 1)
    cx = WIDTH // 2
    cy = HEIGHT // 2 + 4
    radius = min(WIDTH, HEIGHT) // 2 - 6
    graphics.set_pen(DIM)
    for r in (radius, radius * 2 // 3, radius // 3):
        graphics.circle(cx, cy, r)
    graphics.line(cx - radius, cy, cx + radius, cy)
    graphics.line(cx, cy - radius, cx, cy + radius)
    graphics.set_pen(GREEN)
    graphics.circle(cx, cy, 2)
    y = HEIGHT - 10
    label = "NO TRAFFIC"
    if page_rows:
        first = page_rows[0]
        label = (first.get("flight") or first.get("flight_display") or first.get("callsign") or "TRAFFIC")[:14]
    graphics.set_pen(WHITE)
    graphics.text(label, 2, y, WIDTH, 1)


def draw_classic_board(flap_rows, page_data, view):
    draw_header(view)
    row_h      = (HEIGHT - 11) // MAX_ROWS
    data_start = 11
    for i in range(MAX_ROWS):
        y        = data_start + i * row_h
        row_data = page_data[i] if i < len(page_data) else None
        draw_row(flap_rows[i], row_data, y)
        if i < MAX_ROWS - 1:
            graphics.set_pen(DIMBG)
            graphics.line(0, y + row_h - 1, WIDTH, y + row_h - 1)

# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    flight_data      = []
    page_data        = []
    last_fetch       = 0
    last_ping        = 0
    last_config      = 0
    last_page_rotate = 0
    force_fetch      = True

    i75.set_led(0, 100, 0)  # green LED = running

    if not connect_wifi():
        i75.set_led(100, 0, 0)
        _draw_message("No WiFi. Retrying...", RED)
        time.sleep(5)
    else:
        _draw_message("WiFi OK", GREEN)
        time.sleep(0.2)
        _draw_message("Loading config...", GREEN)
        fetch_config()
        checkin_matrix_device()
        fetch_matrix_config()
        last_config = time.time()
        last_ping = time.time()

    view      = DEFAULT_VIEW
    flap_rows = [FlapRow(ROW_LEN) for _ in range(MAX_ROWS)]

    def _chunk_pages(rows):
        pages = []
        step = max(1, MAX_ROWS)
        for idx in range(0, len(rows), step):
            pages.append(rows[idx:idx + step])
        return pages or [[]]

    def _apply_visible_page(rows):
        for flap in flap_rows:
            flap.set_mode(ANIMATION_MODE)
        for i, row in enumerate(rows[:MAX_ROWS]):
            flap_rows[i].set_text(build_row_text(row))
        for i in range(len(rows), MAX_ROWS):
            flap_rows[i].set_text(" " * ROW_LEN)

    while True:
        now = time.time()

        # ── Button handling ────────────────────────────────────────────────────
        a = switch_pressed(SWITCH_A)
        b = switch_pressed(SWITCH_B)

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
                old_mode = ANIMATION_MODE
                fetch_matrix_config()
                # Resize flap_rows if MAX_ROWS changed
                if len(flap_rows) != MAX_ROWS:
                    flap_rows = [FlapRow(ROW_LEN) for _ in range(MAX_ROWS)]
                    page_data = []
                    force_fetch = True
                elif old_mode != ANIMATION_MODE:
                    _apply_visible_page(page_data)
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
            _draw_message("Fetching flights...", GREEN)

            if ensure_wifi():
                data = fetch_fids(view=view, limit=MAX_ROWS)
                if data:
                    flight_data = data
                    pages = _chunk_pages(flight_data)
                    page_data = pages[0]
                    _apply_visible_page(page_data)
                    last_page_rotate = now
                    i75.set_led(0, 100, 0)  # green = ok
                else:
                    flight_data = []
                    page_data = []
                    _apply_visible_page([])
                    last_page_rotate = now
                    i75.set_led(100, 50, 0)  # amber = no data
                last_fetch = now
            else:
                i75.set_led(100, 0, 0)  # red = no wifi
                last_fetch = now

        if len(flight_data) > MAX_ROWS and (now - last_page_rotate) >= PAGE_ROTATION_S:
            pages = _chunk_pages(flight_data)
            if pages:
                try:
                    page_idx = pages.index(page_data)
                except ValueError:
                    page_idx = 0
                page_data = pages[(page_idx + 1) % len(pages)]
                _apply_visible_page(page_data)
                last_page_rotate = now

        # ── Animate ───────────────────────────────────────────────────────────
        for flap in flap_rows:
            flap.step()

        # ── Draw ──────────────────────────────────────────────────────────────
        graphics.set_pen(BLACK)
        graphics.clear()

        if RENDERER == "terminal_minimal":
            draw_terminal_minimal(page_data)
        elif RENDERER == "radar_strip":
            draw_radar_strip(page_data)
        else:
            draw_classic_board(flap_rows, page_data, view)

        update_display()
        time.sleep(0.08 if ANIMATION_SPEED <= 2 else 0.05 if ANIMATION_SPEED == 3 else 0.03)


# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
