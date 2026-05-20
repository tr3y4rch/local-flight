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
HARDWARE_BRAND = "Pimoroni"
HARDWARE_MODEL = "Interstate 75 W"
HARDWARE_NAME  = "Pimoroni Interstate 75 W"

PANEL_W          = 256   # total physical pixel width
PANEL_H          = 64    # total physical pixel height

# Runtime defaults — overwritten by /api/matrix/config on boot
MAX_ROWS         = 4     # flight rows to display
REFRESH_S        = 60    # flight data fetch interval in seconds
PAGE_ROTATION_S  = 10    # rotate to the next local board page when overflow exists
CODE_SHARE_ROTATION_S = 4 # legacy setting retained; matrix flight labels stay stable
BRIGHTNESS       = 0.8   # 0.0 – 1.0
DEFAULT_VIEW     = "departures"
ANIMATION_ENABLED = True
ANIMATION_MODE   = "split_flap"
ANIMATION_SPEED  = 3
STATUS_ANIMATION_ENABLED = True
SHOW_WEATHER    = True
SHOW_GATE_INFO  = True
PRESET           = "real_fids"
PALETTE          = "pax_blue"
RENDERER         = "modern_fids"
MATRIX_CONFIG_REV = 0

CONFIG_REFRESH_S = 60    # re-read server config every minute
PING_S           = 600   # ping server every 10 min
CLIENT_VER       = "2.0"
CLIENT_RENDERER_REV = "matrix-display-contract-v3"
SUPPORTED_RENDERERS = ["modern_fids", "vatsim_pilot", "vatsim_atc"]
SUPPORTED_ANIMATIONS = ["split_flap", "typewriter", "cascade", "slide_left", "slide_right", "static"]
# ──────────────────────────────────────────────────────────────────────────────

# Airport is read from the server — no hardcoding needed
_airport_iata = "---"
_airport_label = "LOCAL"
_device_id = None
_clock_utc_epoch = None
_clock_sync_ticks = 0
_clock_offset_minutes = 0
_clock_timezone = "UTC"
_matrix_metar = None
_matrix_pages = None
_matrix_weather_page = None
_matrix_message = ""

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
    "pax_blue":        [(29,140,255),  (246,251,255), (44,95,146),  (255,189,69),  (255,77,95)],
    "solari_amber":    [(255,173,47),  (255,230,168), (140,90,18),  (255,225,92),  (255,85,56)],
    "tower_scope":     [(56,255,117),  (217,255,230), (27,122,60),  (255,216,74),  (255,76,76)],
    "vatsim_scope":    [(116,255,95),  (216,255,208), (43,122,47),  (255,224,102), (255,91,91)],
    "night_ops":       [(75,184,255),  (216,247,255), (39,80,110),  (244,201,93),  (255,93,122)],
    "sunset_terminal": [(255,122,61),  (255,242,230), (142,63,85),  (255,209,102), (255,56,100)],
    "ice_white":       [(189,233,255), (255,255,255), (106,129,149), (255,211,90),  (255,82,82)],
    "crt":              [(255,204,68),  (255,238,170), (122,80,0),    (255,221,0),   (255,64,32)],
    "neon":             [(0,255,80),    (220,255,220), (0,122,40),    (170,255,0),   (255,64,64)],
    "amber":            [(255,174,46),  (255,235,180), (126,84,22),   (255,223,85),  (255,87,56)],
    "green":            [(40,247,110),  (220,255,230), (34,124,62),   (255,201,74),  (255,77,77)],
    "cyan":             [(0,204,255),   (215,252,255), (0,102,136),   (255,204,0),   (255,64,96)],
    "technical":        [(74,158,218),  (210,230,248), (80,116,148),  (212,160,32),  (192,64,64)],
    "phosphor":         [(57,255,20),   (205,255,198), (58,138,24),   (170,255,0),   (255,50,50)],
    "indigo_night":     [(130,114,255), (216,212,255), (85,72,184),   (255,216,74),  (255,107,138)],
    "rose_gold":        [(255,126,203), (255,216,238), (160,72,120),  (255,209,102), (255,56,100)],
}
_active_skin = "pax_blue"

def _scaled_rgb(rgb, scale):
    return tuple(max(0, min(255, int(part * scale))) for part in rgb)

def apply_skin(name):
    global GREEN, WHITE, DIM, AMBER, RED, ACTIVE_BREATH, AMBER_BREATH, _active_skin
    p = _SKIN_PALETTES.get(name, _SKIN_PALETTES["pax_blue"])
    GREEN = graphics.create_pen(*p[0])
    WHITE = graphics.create_pen(*p[1])
    DIM   = graphics.create_pen(*p[2])
    AMBER = graphics.create_pen(*p[3])
    RED   = graphics.create_pen(*p[4])
    ACTIVE_BREATH = [graphics.create_pen(*_scaled_rgb(p[0], s)) for s in (0.42, 0.58, 0.76, 0.94, 1.0, 0.94, 0.76, 0.58)]
    AMBER_BREATH = [graphics.create_pen(*_scaled_rgb(p[3], s)) for s in (0.38, 0.56, 0.74, 0.92, 1.0, 0.92, 0.74, 0.56)]
    _active_skin = name

apply_skin(PALETTE)

_GLYPHS = {
    "dep": ["00100", "01110", "10101", "00100", "01010"],
    "arr": ["01010", "00100", "10101", "01110", "00100"],
    "plane": ["00100", "10101", "11111", "00100", "01010"],
    "warn": ["00100", "01110", "01110", "00000", "00100"],
    "sun": ["10101", "01110", "11111", "01110", "10101"],
    "partly": ["10100", "01110", "11111", "11110", "00000"],
    "cloud": ["00000", "01110", "11111", "11110", "00000"],
    "rain": ["01110", "11111", "00000", "01010", "10100"],
    "storm": ["01110", "11111", "00100", "01000", "10000"],
    "fog": ["00000", "11110", "00000", "01111", "00000"],
    "mist": ["00000", "11110", "00000", "01111", "00000"],
    "snow": ["10101", "01010", "10101", "01010", "10101"],
    "ice": ["10101", "01010", "10101", "01010", "10101"],
    "wind": ["10000", "11110", "00001", "01111", "00000"],
    "temp": ["00100", "01010", "01010", "10001", "01110"],
    "unknown": ["00000", "01110", "11111", "11110", "00000"],
}

def draw_glyph(name, x, y, color):
    mask = _GLYPHS.get(name, _GLYPHS["unknown"])
    graphics.set_pen(color)
    for yy, row in enumerate(mask):
        for xx, bit in enumerate(row):
            if bit == "1":
                try:
                    graphics.pixel(int(x + xx), int(y + yy))
                except Exception:
                    graphics.rectangle(int(x + xx), int(y + yy), 1, 1)

# ── Split-flap animation ───────────────────────────────────────────────────────
FLAP_CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:/-+"

_ASCII_REPLACEMENTS = {
    "\u00c4": "AE", "\u00d6": "OE", "\u00dc": "UE", "\u00e4": "AE", "\u00f6": "OE", "\u00fc": "UE",
    "\u00c0": "A", "\u00c1": "A", "\u00c2": "A", "\u00c3": "A", "\u00c5": "A", "\u00c6": "AE",
    "\u00e0": "A", "\u00e1": "A", "\u00e2": "A", "\u00e3": "A", "\u00e5": "A", "\u00e6": "AE",
    "\u00c7": "C", "\u00e7": "C", "\u00c8": "E", "\u00c9": "E", "\u00ca": "E", "\u00cb": "E",
    "\u00e8": "E", "\u00e9": "E", "\u00ea": "E", "\u00eb": "E", "\u00cc": "I", "\u00cd": "I",
    "\u00ce": "I", "\u00cf": "I", "\u00ec": "I", "\u00ed": "I", "\u00ee": "I", "\u00ef": "I",
    "\u00d1": "N", "\u00f1": "N", "\u00d2": "O", "\u00d3": "O", "\u00d4": "O", "\u00d5": "O",
    "\u00d8": "O", "\u0152": "OE", "\u00f2": "O", "\u00f3": "O", "\u00f4": "O", "\u00f5": "O",
    "\u00f8": "O", "\u0153": "OE", "\u00d9": "U", "\u00da": "U", "\u00db": "U", "\u00f9": "U",
    "\u00fa": "U", "\u00fb": "U", "\u00dd": "Y", "\u0178": "Y", "\u00fd": "Y", "\u00ff": "Y",
    "\u00df": "SS", "\u0160": "S", "\u0161": "S", "\u017d": "Z", "\u017e": "Z",
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
}

def _ascii_text(value):
    text = str(value or "")
    out = ""
    for ch in text:
        repl = _ASCII_REPLACEMENTS.get(ch)
        if repl is not None:
            out += repl
        elif 32 <= ord(ch) <= 126:
            out += ch
        else:
            out += " "
    return out

def fit_text(value, length):
    text = _ascii_text(value)
    if len(text) > length:
        return text[:length]
    return text + (" " * (length - len(text)))

def fit(value, length):
    return fit_text(value, length)

def _upper_text(value):
    try:
        return _ascii_text(value).strip().upper()
    except Exception:
        return ""

def marquee(value, width, step=None):
    text = _upper_text(value)
    width = max(1, int(width))
    if len(text) <= width:
        return fit_text(text, width)
    if step is None:
        try:
            step = int(time.time() * 3)
        except Exception:
            step = 0
    canvas = text + "   "
    start = int(step) % len(canvas)
    return (canvas + canvas)[start:start + width]

def code_preserve(value, code, width):
    text = _upper_text(value)
    code = _upper_text(code)
    width = max(1, int(width))
    if not code or code in text[:width] or len(text) <= width:
        return fit_text(text, width)
    if len(code) >= width:
        return code[:width]
    prefix_len = max(0, width - len(code) - 1)
    prefix = text[:prefix_len].rstrip()
    return fit_text((prefix + " " + code).strip(), width)

def cycle_chunks(value, width, code=""):
    text = _upper_text(value)
    code = _upper_text(code)
    width = max(1, int(width))
    if not text:
        return fit_text(code or "-", width)
    if len(text) <= width:
        return code_preserve(text, code, width)
    words = text.replace("(", " ").replace(")", " ").split()
    chunks = []
    current = ""
    for word in words:
        if not current:
            current = word[:width] if len(word) > width else word
        elif len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            chunks.append(current)
            current = word[:width] if len(word) > width else word
    if current:
        chunks.append(current)
    if code and not any(code in chunk for chunk in chunks):
        chunks.append(code[:width])
    try:
        slot = int(time.time() // 3)
    except Exception:
        slot = 0
    return code_preserve(chunks[slot % max(1, len(chunks))], code if slot % max(1, len(chunks)) == len(chunks) - 1 else "", width)

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
        self.typewriter_pos = 0

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
            self.typewriter_pos = len(text)
            for i, cell in enumerate(self.cells):
                cell.current = text[i]
                cell.target = text[i]
                cell.frame = 0
                cell.frames = 0
            return
        if self.mode in ("typewriter", "cascade"):
            if text == self.target_text and self.typewriter_pos < len(text):
                return
            self.target_text = text
            self.typewriter_pos = 0
            self.current_text = " " * self.length
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
        if self.mode in ("typewriter", "cascade"):
            step = max(1, int(ANIMATION_SPEED))
            self.typewriter_pos = min(self.length, self.typewriter_pos + step)
            visible = max(0, self.typewriter_pos)
            self.current_text = fit_text(self.target_text[:visible], self.length)
            return
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
        if self.mode in ("typewriter", "cascade"):
            return self.current_text
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
        if self.mode in ("typewriter", "cascade"):
            return self.typewriter_pos >= self.length
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

def _clean_flight_number(value):
    text = _text_field(value)
    text = text.replace("Sold as ", "").replace("SOLD AS ", "")
    text = text.replace("Also ", "").replace("ALSO ", "").strip()
    text = text.replace(",", " ").replace("|", " ").replace("  ", " ")
    if not text or text.startswith("+"):
        return ""
    parts = text.split()
    if not parts:
        return ""
    if len(parts) >= 2:
        return (parts[0] + " " + parts[1]).strip()
    return parts[0]

def _codeshare_flights(row):
    values = []
    for key in ("codeshares", "codeshare_display", "codeshare", "sold_as"):
        raw = row.get(key)
        if not raw:
            continue
        if isinstance(raw, list):
            parts = raw
        else:
            parts = (
                str(raw)
                .replace("Sold as ", "")
                .replace("SOLD AS ", "")
                .replace("Also ", "")
                .replace("ALSO ", "")
                .replace("|", "/")
                .replace(",", "/")
                .split("/")
            )
        for part in parts:
            code = _clean_flight_number(part)
            if code and code not in values:
                values.append(code)
    return values

def _flight_cycle_display(row):
    if not isinstance(row, dict):
        return "-"
    # Matrix boards need a stable operating-first identity. Codeshares stay in
    # the payload/details, but never rotate through the primary flight column.
    primary = _clean_flight_number(
        row.get("matrix_flight_label")
        or row.get("flight_display")
        or row.get("flight")
        or row.get("flight_number")
    )
    if primary:
        return primary
    return _clean_flight_number(row.get("operating_callsign") or row.get("callsign")) or "-"

def _page_has_codeshares(rows):
    return False

def _route_code(row):
    return _upper_text(row.get("route_code") or "")

def _route_label(row):
    return _upper_text(row.get("matrix_route_label") or row.get("route_matrix_label") or row.get("route_display") or row.get("route") or "-")

def _route_chunk(row, chars):
    return cycle_chunks(_route_label(row), chars, _route_code(row)).rstrip()

def _status_chunk(row, chars):
    delta = row.get("time_delta_label") or ""
    status = row.get("matrix_status_label") or row.get("status_display") or row.get("status") or "-"
    if delta and "delay" not in str(status).lower() and "early" not in str(status).lower():
        status = "{} {}".format(status, delta)
    return cycle_chunks(status, chars).rstrip()

def _is_vatsim_preset():
    return str(PRESET or "").lower().startswith("vatsim_") or RENDERER in ("vatsim_pilot", "vatsim_atc")

def _gate_label(row):
    if _is_vatsim_preset() or not SHOW_GATE_INFO or not isinstance(row, dict):
        return ""
    for key in ("matrix_gate_label", "gate_label", "terminal_gate_display", "gate_display", "gate"):
        value = _upper_text(row.get(key) or "").strip()
        if value and value != "-":
            return value
    return ""

def _gate_chip(row, chars):
    gate = _gate_label(row)
    if not gate:
        return ""
    return ("G " + gate)[:chars].strip()

def _status_or_gate_chunk(row, chars):
    gate = _gate_chip(row, chars)
    if gate and WIDTH < 180:
        try:
            if int(time.time() // 4) % 2 == 1:
                return gate
        except Exception:
            pass
    return _status_chunk(row, chars)

def build_row_text(row):
    time_s   = fit_text(_text_field(row.get("matrix_time_label") or row.get("display_time") or row.get("time"), "--:--"), 5)
    flight_s = fit_text(_flight_cycle_display(row), 8)
    dest_s   = fit_text(_route_label(row), 12)
    status_s = fit_text(_text_field(row.get("matrix_status_label") or row.get("status_display") or row.get("status")), 10)
    gate_s   = fit_text(_gate_label(row), 4)
    return f"{time_s} {flight_s} {dest_s} {status_s} {gate_s}"

def build_detail_text(row):
    op = row.get("operating_airline") or row.get("operator") or row.get("airline_display") or ""
    sold = row.get("sold_as") or row.get("codeshare") or row.get("codeshare_display") or ""
    aircraft = row.get("matrix_aircraft_label") or row.get("aircraft") or row.get("aircraft_type") or ""
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

def _breath_index():
    if not STATUS_ANIMATION_ENABLED:
        return 4
    try:
        return int(time.time() * 5) % len(ACTIVE_BREATH)
    except Exception:
        return 4

def status_color(row_or_status):
    s = _status_key(row_or_status)
    if isinstance(row_or_status, dict):
        tone = _upper_text(row_or_status.get("tone") or "").lower()
        delay_kind = _upper_text(row_or_status.get("delay_kind") or "").lower()
        if tone == "red" or delay_kind == "bad": return RED
        if tone == "amber" or delay_kind == "warn": return AMBER
        if tone == ("gr" + "een") or delay_kind == "early": return GREEN
        if tone == "dim": return DIM
    if "delayed_bad" in s or "cancel" in s: return RED
    if "delay" in s:               return AMBER
    if "cancel" in s:              return RED
    if "boarding" in s or "gate" in s or "ground" in s: return AMBER_BREATH[_breath_index()]
    if "depart" in s or "arriv" in s or "approach" in s: return ACTIVE_BREATH[_breath_index()]
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


def _normalize_airport_label(data):
    if not isinstance(data, dict):
        return _airport_iata
    label = (
        data.get("airport_label")
        or data.get("airport_display_name")
        or data.get("airport_city")
        or data.get("airport_name")
        or data.get("airport_iata")
        or _airport_iata
    )
    text = _upper_text(label).strip()
    return text or _airport_iata


def _truthy(value, fallback=True):
    if value is None:
        return fallback
    text = str(value).strip().lower()
    if text in ("0", "false", "no", "off"):
        return False
    if text in ("1", "true", "yes", "on"):
        return True
    return bool(value)


def _sync_clock_from_config(data):
    global _clock_utc_epoch, _clock_sync_ticks, _clock_offset_minutes, _clock_timezone
    if not isinstance(data, dict) or data.get("clock_utc_epoch") is None:
        return
    try:
        _clock_utc_epoch = int(data.get("clock_utc_epoch"))
        _clock_sync_ticks = time.time()
        _clock_offset_minutes = _clamp_int(data.get("clock_local_offset_minutes", 0), -720, 840, 0)
        _clock_timezone = str(data.get("timezone") or "UTC")
    except Exception as e:
        print(f"Clock sync error: {e}")


def _clock_epoch_now():
    if _clock_utc_epoch is None:
        return None
    try:
        return int(_clock_utc_epoch + (time.time() - _clock_sync_ticks))
    except Exception:
        return _clock_utc_epoch


def _clock_hhmm(offset_minutes=0):
    epoch = _clock_epoch_now()
    if epoch is None:
        return "--:--"
    try:
        t = time.gmtime(epoch + int(offset_minutes) * 60)
        return "{:02d}:{:02d}".format(t[3], t[4])
    except Exception:
        return "--:--"


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
    global _airport_iata, _airport_label
    data = _get_json("/api/config", timeout=8)
    if not isinstance(data, dict):
        return False
    _airport_iata = _normalize_airport_iata(data.get("airport_iata"))
    _airport_label = _normalize_airport_label(data)
    _sync_clock_from_config(data)
    return True


def checkin_matrix_device():
    payload = {
        "device_id": device_id(),
        "label": DEVICE_LABEL,
        "kind": "led_matrix",
        "brand": HARDWARE_BRAND,
        "model": HARDWARE_MODEL,
        "hardware": HARDWARE_NAME,
        "hardware_name": HARDWARE_NAME,
        "panel_w": PANEL_W,
        "panel_h": PANEL_H,
        "firmware": CLIENT_VER,
        "renderer_revision": CLIENT_RENDERER_REV,
        "renderers": SUPPORTED_RENDERERS,
    }
    data = _post_json("/api/matrix/v2/devices/checkin", payload, timeout=8)
    return isinstance(data, dict) and bool(data.get("ok"))


def fetch_matrix_config():
    global MAX_ROWS, REFRESH_S, PAGE_ROTATION_S, BRIGHTNESS, DEFAULT_VIEW
    global ANIMATION_ENABLED, ANIMATION_MODE, ANIMATION_SPEED, STATUS_ANIMATION_ENABLED
    global SHOW_WEATHER, SHOW_GATE_INFO, PRESET, PALETTE, RENDERER, MATRIX_CONFIG_REV, _airport_iata, _airport_label
    data = _get_json(f"/api/matrix/v2/devices/{device_id()}/config", timeout=8)
    if not isinstance(data, dict):
        data = _get_json("/api/matrix/config", timeout=8)
    if not isinstance(data, dict):
        return False
    _airport_iata = _normalize_airport_iata(data.get("airport_iata", _airport_iata))
    _airport_label = _normalize_airport_label(data)
    _sync_clock_from_config(data)
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
    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    SHOW_WEATHER = _truthy(options.get("show_metar", options.get("show_weather")), SHOW_WEATHER)
    SHOW_GATE_INFO = _truthy(data.get("show_gate_info", options.get("show_gate_info")), SHOW_GATE_INFO)
    PRESET = data.get("preset", PRESET)
    RENDERER = data.get("renderer", RENDERER)
    if RENDERER not in SUPPORTED_RENDERERS:
        RENDERER = "modern_fids"
    if _is_vatsim_preset():
        SHOW_GATE_INFO = False
    MATRIX_CONFIG_REV = data.get("config_rev", MATRIX_CONFIG_REV)
    PALETTE = data.get("palette") or data.get("skin") or PALETTE or "pax_blue"
    if PALETTE != _active_skin:
        apply_skin(PALETTE)
    try:
        i75.set_brightness(BRIGHTNESS)
    except Exception:
        pass
    return True


def fetch_fids(view="departures", limit=4):
    global DEFAULT_VIEW, _matrix_metar, _matrix_pages, _matrix_weather_page, _matrix_message, _airport_iata, _airport_label
    view = _normalize_view(view, "departures")
    limit = _clamp_int(limit, 1, 32, max(MAX_ROWS, limit))
    data = _get_json(f"/api/matrix/v2/devices/{device_id()}/feed?view={view}", timeout=10)
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        DEFAULT_VIEW = _normalize_view(data.get("view", DEFAULT_VIEW), DEFAULT_VIEW)
        _airport_iata = _normalize_airport_iata(data.get("airport_iata", _airport_iata))
        _airport_label = _normalize_airport_label(data)
        _matrix_metar = data.get("metar") if isinstance(data.get("metar"), dict) else None
        _matrix_pages = data.get("pages") if isinstance(data.get("pages"), dict) else None
        _matrix_weather_page = data.get("weather_page") if isinstance(data.get("weather_page"), dict) else None
        _matrix_message = _upper_text(data.get("message") or "")
        return data.get("rows") or []
    data = _get_json(f"/api/fids?view={view}&limit={limit}", timeout=10)
    if isinstance(data, list):
        _matrix_metar = None
        _matrix_pages = None
        _matrix_weather_page = None
        _matrix_message = ""
        return data
    return []


def ping_server():
    _post_json("/api/matrix/v2/devices/checkin", {
        "device_id": device_id(),
        "label": DEVICE_LABEL,
        "kind": "led_matrix",
        "brand": HARDWARE_BRAND,
        "model": HARDWARE_MODEL,
        "hardware": HARDWARE_NAME,
        "hardware_name": HARDWARE_NAME,
        "panel_w": PANEL_W,
        "panel_h": PANEL_H,
        "firmware": CLIENT_VER,
        "renderer_revision": CLIENT_RENDERER_REV,
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

def _weather_glyph_name():
    if not isinstance(_matrix_metar, dict):
        return "unknown"
    icon = _upper_text(
        _matrix_metar.get("matrix_weather_icon")
        or _matrix_metar.get("weather_icon")
        or _matrix_metar.get("condition_display")
        or _matrix_metar.get("weather_label")
        or _matrix_metar.get("summary")
    ).lower()
    if "storm" in icon or "thunder" in icon:
        return "storm"
    if "ice" in icon or "freez" in icon or "hail" in icon:
        return "ice"
    if "rain" in icon or "shower" in icon or "drizzle" in icon:
        return "rain"
    if "snow" in icon or "flurr" in icon:
        return "snow"
    if "wind" in icon or "gust" in icon:
        return "wind"
    if "mist" in icon or "fog" in icon or "haze" in icon or "smoke" in icon or "dust" in icon or "ash" in icon:
        return "fog"
    if "part" in icon or "few" in icon or "scatter" in icon:
        return "partly"
    if "cloud" in icon or "overcast" in icon or "broken" in icon:
        return "cloud"
    if "sun" in icon or "clear" in icon or "vfr" in icon or "cavok" in icon:
        return "sun"
    return "cloud"

def _weather_line(chars=18):
    if not SHOW_WEATHER:
        return ""
    if not isinstance(_matrix_metar, dict):
        return ""
    condition = _upper_text(
        _matrix_metar.get("matrix_weather_label")
        or _matrix_metar.get("condition_display")
        or _matrix_metar.get("weather_label")
        or _matrix_metar.get("summary")
        or _matrix_metar.get("weather_display")
    )
    temp = (
        _matrix_metar.get("matrix_weather_temp")
        or _matrix_metar.get("temperature_short")
        or _matrix_metar.get("temperature_display")
        or _matrix_metar.get("temp_c")
        or _matrix_metar.get("temperature_c")
    )
    temp_s = ""
    if temp is not None:
        temp_s = str(temp).replace(" C", "C").replace(" ", "").upper()
        if temp_s and not temp_s.endswith("C"):
            temp_s += "C"
    text = " ".join(part for part in (condition, temp_s) if part)
    return marquee(text, chars).rstrip() if len(text) > chars else text[:chars]

def _weather_temp_text():
    if not SHOW_WEATHER or not isinstance(_matrix_metar, dict):
        return ""
    temp = (
        _matrix_metar.get("matrix_weather_temp")
        or _matrix_metar.get("temperature_short")
        or _matrix_metar.get("temperature_display")
        or _matrix_metar.get("temp_c")
        or _matrix_metar.get("temperature_c")
    )
    if temp is None:
        return ""
    temp_s = str(temp).replace(" C", "C").replace(" ", "").upper()
    if temp_s and not temp_s.endswith("C"):
        temp_s += "C"
    return temp_s

def draw_weather_mini(x, y, max_width):
    if not SHOW_WEATHER or not isinstance(_matrix_metar, dict):
        return 0
    temp_s = _weather_temp_text()
    if not temp_s:
        return 0
    width = 7 + len(temp_s) * 8
    if width > max_width:
        return 0
    glyph = _weather_glyph_name()
    draw_glyph(glyph, x, y + 1, AMBER if glyph in ("sun", "storm") else DIM)
    graphics.set_pen(AMBER)
    graphics.text(temp_s, x + 7, y, max_width, 1)
    return width

def draw_weather_compact(x, y, max_width):
    if not SHOW_WEATHER or not isinstance(_matrix_metar, dict):
        return 0
    glyph = _weather_glyph_name()
    condition = _upper_text(
        _matrix_metar.get("matrix_weather_label")
        or _matrix_metar.get("condition_display")
        or _matrix_metar.get("weather_label")
        or _matrix_metar.get("summary")
    )
    temp = (
        _matrix_metar.get("matrix_weather_temp")
        or _matrix_metar.get("temperature_short")
        or _matrix_metar.get("temperature_display")
        or _matrix_metar.get("temp_c")
        or _matrix_metar.get("temperature_c")
    )
    temp_s = ""
    if temp is not None:
        temp_s = str(temp).replace(" C", "C").replace(" ", "").upper()
        if temp_s and not temp_s.endswith("C"):
            temp_s += "C"
    draw_glyph(glyph, x, y + 1, AMBER if glyph in ("sun", "storm") else DIM)
    cursor = x + 7
    chars = max(3, (max_width - 14) // 8)
    if temp_s:
        chars = max(3, chars - len(temp_s) - 1)
    label = marquee(condition, chars).rstrip() if len(condition) > chars else condition[:chars]
    graphics.set_pen(DIM)
    graphics.text(label, cursor, y, max_width, 1)
    cursor += len(label) * 8 + 2
    if temp_s and cursor + 13 < x + max_width:
        draw_glyph("temp", cursor, y + 1, AMBER)
        graphics.set_pen(AMBER)
        graphics.text(temp_s, cursor + 6, y, max_width, 1)
    return cursor - x

def draw_smart_header(view):
    header_name = _airport_label or _airport_iata
    lane = "DEP" if view == "departures" else "ARR"
    weather_temp = _weather_temp_text()
    clock = _clock_label(compact=WIDTH < 200)

    if WIDTH < 200:
        compact_name = _airport_iata if weather_temp else header_name
        label = "{} {}".format(marquee(compact_name, max(6, WIDTH // 8 - 4)).rstrip(), lane)
        graphics.set_pen(GREEN)
        graphics.set_font("bitmap8")
        graphics.text(label[:max(8, WIDTH // 8)], 0, 0, WIDTH, 1)
        top_weather_drawn = False
        if weather_temp:
            weather_width = 7 + len(weather_temp) * 8
            weather_x = WIDTH - weather_width - 1
            if weather_x > len(label) * 8 + 4:
                top_weather_drawn = bool(draw_weather_mini(weather_x, 0, weather_width + 1))
        second = clock
        second_pen = DIM
        if weather_temp and not top_weather_drawn and int(time.time() // 8) % 2 == 1:
            second = weather_temp
            second_pen = AMBER
        graphics.set_pen(second_pen)
        graphics.text(second[:max(8, WIDTH // 8)], 0, 10, WIDTH, 1)
        return

    clock_x = max(0, WIDTH - len(clock) * 8 - 2)
    graphics.set_pen(DIM)
    graphics.text(clock, clock_x, 0, WIDTH, 1)

    weather_start = clock_x
    weather = _weather_line(max(8, WIDTH // 8 - 1))
    if weather or weather_temp:
        desired = min(24, max(8, (clock_x - 96) // 8)) if WIDTH >= 384 else 10
        weather_text = (weather or weather_temp)[:desired]
        weather_w = 10 + len(weather_text) * 8
        weather_x = max(0, clock_x - weather_w - 8)
        if weather_x > (96 if WIDTH >= 320 else 54):
            draw_weather_compact(weather_x, 0, clock_x - weather_x - 4)
            weather_start = weather_x
        elif HEIGHT >= 96 and weather:
            draw_weather_compact(0, 10, WIDTH)
            graphics.set_pen(DIM)
            graphics.line(0, 19, WIDTH, 19)

    label = "{} {}".format(header_name, lane).upper()
    label_chars = max(8, (weather_start - 4) // 8)
    if len(label) > label_chars:
        label = marquee(label, label_chars).rstrip()
    graphics.set_pen(GREEN)
    graphics.text(label, 0, 0, max(1, weather_start - 4), 1)

def _weather_page_lines(chars):
    page = _matrix_weather_page if isinstance(_matrix_weather_page, dict) else None
    lines = page.get("lines") if page else None
    if not isinstance(lines, list) or not lines:
        lines = ["NO VATSIM ATIS"] if RENDERER == "vatsim_atc" else [_weather_line(chars)]
    clean = []
    for line in lines:
        text = _upper_text(line)
        if text:
            clean.append(text)
    if not clean:
        clean = ["NO WX"]
    return [marquee(line, chars).rstrip() if len(line) > chars else line[:chars] for line in clean]

def _clock_label(compact=False):
    utc_ts = _clock_hhmm(0)
    local_ts = _clock_hhmm(_clock_offset_minutes)
    if compact:
        return "U{} L{}".format(utc_ts, local_ts)
    return "UTC{} LT{}".format(utc_ts, local_ts)

def _header_height():
    if WIDTH < 200:
        return 20
    return 20 if HEIGHT >= 96 else 11

def _visible_rows():
    if WIDTH < 180:
        return max(1, min(MAX_ROWS, (HEIGHT - _header_height()) // 27))
    return MAX_ROWS

def draw_source_message():
    graphics.set_pen(BLACK)
    graphics.clear()
    graphics.set_font("bitmap8")
    graphics.set_pen(DIM)
    graphics.text(_clock_label(compact=WIDTH < 200)[:max(8, WIDTH // 8)], 0, 0, WIDTH, 1)
    msg = _matrix_message or "NO DATA"
    chars = max(8, WIDTH // 8)
    lines = cycle_chunks(msg, chars).split("|") if "|" in msg else [cycle_chunks(msg, chars)]
    graphics.set_pen(AMBER)
    graphics.text(lines[0], 2, max(0, HEIGHT // 2 - 8), WIDTH, 1)
    if HEIGHT >= 32:
        graphics.set_pen(DIM)
        graphics.text("CHECK SETTINGS", 2, HEIGHT // 2 + 2, WIDTH, 1)

def draw_vatsim_weather_page():
    graphics.set_pen(BLACK)
    graphics.clear()
    graphics.set_font("bitmap8")
    chars = max(8, WIDTH // 8 - 1)
    title = "VATSIM WX"
    if isinstance(_matrix_weather_page, dict):
        title = _upper_text(_matrix_weather_page.get("title") or title)
    graphics.set_pen(GREEN)
    title_text = f"{_airport_label} {title}"[:chars]
    graphics.text(title_text, 0, 0, WIDTH, 1)
    clock = _clock_label(compact=WIDTH < 200)
    if WIDTH >= 200:
        clock_x = WIDTH - len(clock) * 8 - 2
        if clock_x > len(title_text) * 8 + 4:
            graphics.set_pen(DIM)
            graphics.text(clock, clock_x, 0, WIDTH, 1)
    else:
        graphics.set_pen(DIM)
        graphics.text(clock[:chars], 0, 10, WIDTH, 1)
    graphics.set_pen(DIM)
    graphics.line(0, _header_height() - 2, WIDTH, _header_height() - 2)
    y = _header_height() + 1
    glyph = _weather_glyph_name()
    draw_glyph(glyph, 0, y + 1, AMBER if glyph in ("sun", "storm") else DIM)
    lines = _weather_page_lines(chars)
    line_h = 9
    max_lines = max(1, (HEIGHT - y) // line_h)
    start = 0
    if len(lines) > max_lines:
        try:
            start = int(time.time() // 3) % len(lines)
        except Exception:
            start = 0
    for idx in range(max_lines):
        line = lines[(start + idx) % len(lines)]
        graphics.set_pen(WHITE if idx == 0 else DIM)
        graphics.text(line, 8 if idx == 0 else 0, y + idx * line_h, WIDTH, 1)

def _vatsim_atc_page():
    pages = ("departures", "arrivals")
    if SHOW_WEATHER and isinstance(_matrix_weather_page, dict):
        pages = ("departures", "arrivals", "weather")
    try:
        slot = int(time.time() // max(3, PAGE_ROTATION_S)) % len(pages)
    except Exception:
        slot = 0
    return pages[slot]

def draw_header(view, connected=True):
    draw_smart_header(view)

    # Separator
    graphics.set_pen(DIM)
    graphics.line(0, _header_height() - 2, WIDTH, _header_height() - 2)

def draw_row(flap_row, row_data, y, row_h):
    text    = flap_row.get_text()
    s_color = status_color(row_data or "")
    cancelled = bool(row_data and is_cancelled(row_data))
    cancel_flash = cancelled and _blink_fast()
    compact = WIDTH < 180
    if cancel_flash:
        graphics.set_pen(RED)
        graphics.rectangle(0, y - 1, WIDTH, max(9, row_h - 1))

    if compact:
        # Narrow/tall boards such as 128x128 use vertical space instead of
        # squeezing a 42-character airport row into 128 pixels.
        row_data = row_data or {}
        chars = max(8, WIDTH // 8)
        graphics.set_font("bitmap8")
        glyph = "arr" if DEFAULT_VIEW == "arrivals" else "dep"
        draw_glyph("warn" if cancelled else glyph, 0, y + 1, RED if cancelled else DIM)
        time_label = fit_text(_text_field(row_data.get("matrix_time_label") or row_data.get("display_time") or row_data.get("time"), "--:--"), 5)
        flight_label = fit_text(_flight_cycle_display(row_data), 8)
        graphics.set_pen(WHITE if cancel_flash else GREEN)
        graphics.text(time_label, 8, y, 42, 1)
        graphics.set_pen(WHITE)
        graphics.text(flight_label, 50, y, 62, 1)

        if row_h >= 18:
            graphics.set_pen(WHITE)
            graphics.text(_route_chunk(row_data, chars)[:chars], 0, y + 8, WIDTH, 1)
            status_y = y + 16
        else:
            status_y = y + 8

        if status_y + 7 <= y + row_h:
            graphics.set_pen(WHITE if cancel_flash else s_color)
            status_text = _status_or_gate_chunk(row_data, chars)
            gate = _gate_label(row_data)
            aircraft = _upper_text(row_data.get("aircraft_type") or row_data.get("aircraft") or "")
            if row_h >= 27 and aircraft and not gate:
                status_text = fit_text(status_text, max(1, chars - 5)).rstrip()
                extra = aircraft
                status_text = (status_text + " " + extra[:4]).strip()
            graphics.text(status_text, 0, status_y, WIDTH, 1)
        return

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
    if WIDTH >= 245:
        graphics.set_pen(DIM)
        graphics.text(text[39:43], WIDTH - 28, y, 28, 1)


def draw_modern_fids(flap_rows, page_data, view):
    draw_header(view)
    data_start = _header_height()
    rows = _visible_rows()
    row_h = max(14, (HEIGHT - data_start) // rows)
    compact = WIDTH < 190
    for i in range(rows):
        y = data_start + i * row_h
        if y + 7 > HEIGHT:
            break
        row = page_data[i] if i < len(page_data) else None
        if not row:
            continue
        text = flap_rows[i].get_text() if flap_rows else build_row_text(row)
        if compact:
            time_label = fit_text(_text_field(row.get("matrix_time_label") or row.get("display_time") or row.get("time"), "--:--"), 5)
            flight_label = fit_text(_flight_cycle_display(row), 8)
        else:
            time_label = fit_text(text[0:5].strip() or _text_field(row.get("matrix_time_label") or row.get("display_time") or row.get("time"), "--:--"), 5)
            flight_label = fit_text(text[6:14].strip() or _flight_cycle_display(row), 8)
        cancelled = is_cancelled(row)
        if cancelled and _blink_fast():
            graphics.set_pen(RED)
            graphics.rectangle(0, y - 1, WIDTH, max(9, row_h - 1))
        draw_glyph("arr" if view == "arrivals" else "dep", 0, y + 1, DIM)
        graphics.set_pen(GREEN if not cancelled else WHITE)
        graphics.text(time_label, 8, y, 44, 1)
        graphics.set_pen(WHITE)
        graphics.text(flight_label, 52, y, 64, 1)
        if compact:
            route_y = y + 8
            status_y = y + 16
            graphics.set_pen(WHITE)
            graphics.text(_route_chunk(row, max(8, WIDTH // 8))[:max(8, WIDTH // 8)], 0, route_y, WIDTH, 1)
            if row_h >= 25 and status_y + 7 <= y + row_h:
                graphics.set_pen(status_color(row))
                status = _status_or_gate_chunk(row, max(8, WIDTH // 8))
                graphics.text(status, 0, status_y, WIDTH, 1)
        else:
            status_x = int(WIDTH * 0.60) if WIDTH >= 420 else int(WIDTH * 0.56) if WIDTH >= 300 else 116
            gate_x = int(WIDTH * 0.80) if WIDTH >= 360 else WIDTH - 28
            aircraft_x = int(WIDTH * 0.89) if WIDTH >= 420 else WIDTH - 28
            route_chars = max(8, (status_x - 118) // 8)
            graphics.text(_route_chunk(row, route_chars)[:route_chars], 116, y, max(40, status_x - 118), 1)
            if row_h >= 17:
                graphics.set_pen(status_color(row))
                status_chars = max(7, ((gate_x if WIDTH >= 360 else WIDTH) - status_x - 4) // 8)
                status = _status_or_gate_chunk(row, status_chars) or text[28:38].strip()
                if RENDERER in ("vatsim_pilot", "vatsim_atc"):
                    ac = _upper_text(row.get("aircraft_type") or row.get("aircraft") or "")
                    cs = _upper_text(row.get("callsign") or "")
                    status = " ".join(part for part in (status, ac or cs) if part)
                else:
                    gate = _gate_label(row)
                    aircraft = _upper_text(row.get("aircraft_type") or row.get("aircraft") or "")
                    if gate and WIDTH >= 260:
                        graphics.set_pen(DIM)
                        graphics.text(gate[:5], gate_x, y, max(8, WIDTH - gate_x), 1)
                    if aircraft and WIDTH >= 420:
                        graphics.set_pen(DIM)
                        graphics.text(aircraft[:5], aircraft_x, y, max(8, WIDTH - aircraft_x), 1)
                    graphics.set_pen(status_color(row))
                graphics.text(status[:status_chars], status_x, y, max(8, WIDTH - status_x), 1)
            else:
                graphics.set_pen(status_color(row))
                graphics.text(text[28:38], max(116, int(WIDTH * 0.60)), y, 76, 1)
        if i < MAX_ROWS - 1:
            graphics.set_pen(DIMBG)
            graphics.line(0, y + row_h - 1, WIDTH, y + row_h - 1)


def draw_vatsim_atc(flap_rows, fallback_rows, fallback_view):
    page = _vatsim_atc_page()
    if page == "weather":
        draw_vatsim_weather_page()
        return
    rows = fallback_rows
    if isinstance(_matrix_pages, dict) and isinstance(_matrix_pages.get(page), list):
        rows = _matrix_pages.get(page) or []
    draw_modern_fids(None, rows, page)


def draw_classic_board(flap_rows, page_data, view):
    draw_header(view)
    data_start = _header_height()
    rows = _visible_rows()
    row_h      = max(9, (HEIGHT - data_start) // rows)
    for i in range(rows):
        y        = data_start + i * row_h
        row_data = page_data[i] if i < len(page_data) else None
        draw_row(flap_rows[i], row_data, y, row_h)
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
    last_codeshare_rotate = 0
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
        step = max(1, _visible_rows())
        for idx in range(0, len(rows), step):
            pages.append(rows[idx:idx + step])
        return pages or [[]]

    def _apply_visible_page(rows):
        for flap in flap_rows:
            flap.set_mode(ANIMATION_MODE)
        visible_rows = _visible_rows()
        texts = [build_row_text(row) for row in rows[:visible_rows]]
        if ANIMATION_MODE == "cascade" and ANIMATION_ENABLED:
            for i, text in enumerate(texts):
                flap_rows[i].target_text = fit_text(text, ROW_LEN).upper()
                flap_rows[i].typewriter_pos = -i * 4
                flap_rows[i].current_text = " " * ROW_LEN
        else:
            for i, text in enumerate(texts):
                flap_rows[i].set_text(text)
        for i in range(min(len(rows), visible_rows), MAX_ROWS):
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
                old_view = view
                fetch_matrix_config()
                if DEFAULT_VIEW != old_view:
                    view = DEFAULT_VIEW
                    flight_data = []
                    page_data = []
                    force_fetch = True
                    last_page_rotate = now
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
                data = fetch_fids(view=view, limit=min(_visible_rows() * 4, 32))
                view = DEFAULT_VIEW
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

        if page_data and _page_has_codeshares(page_data) and (now - last_codeshare_rotate) >= CODE_SHARE_ROTATION_S:
            _apply_visible_page(page_data)
            last_codeshare_rotate = now

        # ── Animate ───────────────────────────────────────────────────────────
        for flap in flap_rows:
            flap.step()

        # ── Draw ──────────────────────────────────────────────────────────────
        graphics.set_pen(BLACK)
        graphics.clear()

        if _matrix_message:
            draw_source_message()
        elif RENDERER == "vatsim_atc":
            draw_vatsim_atc(flap_rows, page_data, view)
        elif RENDERER in ("modern_fids", "vatsim_pilot"):
            draw_modern_fids(flap_rows, page_data, view)
        else:
            draw_classic_board(flap_rows, page_data, view)

        update_display()
        time.sleep(0.08 if ANIMATION_SPEED <= 2 else 0.05 if ANIMATION_SPEED == 3 else 0.03)


# ── Entry ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()
