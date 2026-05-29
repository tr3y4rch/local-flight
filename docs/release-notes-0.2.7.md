# Local Flight 0.2.7 Client Notes

`0.2.7` is the next client-polish release candidate after the `0.2.6`
baseline. The focus is the public Local Flight experience: the native Qt shell
is calmer, FIDS reads more like a passenger board, setup/settings/history/matrix
are friendlier, the LAN browser UI remains a supported access surface, and the
mobile app now has a clear LAN Companion vs Standalone shape.

Current release notes continue at [0.2.8 Client Notes](release-notes-0.2.8.md).
This page is retained as the `0.2.7` client-polish release-candidate archive.

This release does not change the basic setup choices. You can still use
Local Flight Relay, use your own provider keys, or run VATSIM-only virtual
traffic.

Public docs now live under Beacon Tools at
[beacontools.cc/local-flight](https://beacontools.cc/local-flight), with the
public privacy policy at [beacontools.cc/privacy](https://beacontools.cc/privacy)
and the official hosted relay at `https://relay.beacontools.cc`.

---

## Highlights

- **Native Qt shell polish.** The main window now has clearer navigation:
  Display/FIDS/Radar as core viewing pages, UTC/LT as the centered divider,
  Matrix/Settings/Admin/History/Logs/Report as tools, and a small sync dot near
  Power instead of a large "live" banner.
- **Cleaner FIDS header.** FIDS now shows a city/country display name such as
  `Zurich, Switzerland` or `Miami, United States`. It no longer uses long
  formal airport names or IATA/ICAO descriptors in the title.
- **Passenger-friendly weather.** The main FIDS weather card now favors plain
  wording, temperature, and visibility hints instead of raw METAR fragments.
- **Real FIDS style skins.** Classic, PAX, VATSIM, and Nerd now change more
  than columns: row size, spacing, fonts, header chrome, row chrome, status
  chips, palettes, and responsive column hiding all follow the active style.
- **VATSIM details now speak pilot/ATC.** Virtual rows and details are
  callsign-first and focus on aircraft, flight rules, filed route, altitude,
  ground speed, XPDR, track state, and VATSIM freshness. Passenger-only fields
  such as codeshares, sold-as labels, gates, terminals, registrations, ICAO24,
  and delay/gate analytics are hidden in virtual mode.
- **Long-name protection.** Very long airport labels are clamped safely and keep
  the full value as a tooltip in the native GUI.
- **Footer support icons.** The footer now keeps the version/privacy phrase
  compact and uses icon-only GitHub / coffee support buttons with tooltips.
- **Shared app typography and assets.** Native, LAN browser, and mobile surfaces
  use bundled local fonts and local support assets instead of online font/CDN
  dependencies.
- **Mobile Standalone mode.** The same Expo app can now be set up as either
  a LAN Companion for your desktop/Pi server or as a simplified Standalone phone
  board through the hosted relay.
- **Beacon Tools public home.** Public product, privacy, and relay URLs are now
  under `beacontools.cc`, so app metadata, docs links, and support contact copy
  no longer point users at GitHub as the primary public home.
- **Android local development path.** The mobile app remains iOS-first for
  release validation, but Android emulator/device development is wired through
  Expo/Android Studio for local testing.

---

## FIDS And Flight Details

- FIDS title display is now deliberately passenger-facing: city plus country,
  with no airport-name wall of text and no technical code suffix.
- Operating-flight identity remains the main board identity, with marketed or
  sold-as flights shown as secondary/codeshare detail.
- AeroDataBox operating/codeshare evidence is preserved before dedupe. When the
  provider marks one row as the operator and nearby rows as marketed/codeshared,
  Local Flight keeps the operating row as the board identity and folds marketed
  labels into "Sold as" detail instead of showing duplicate movements.
- Aircraft type display stays compact on the board, while richer aircraft,
  source, timing, live-motion, and history context stays in the detail drawer.
- Native and LAN/browser detail views continue to use the shared
  current-source intelligence model. Opening a detail panel reuses data already
  fetched or cached by Local Flight; it should not cause surprise per-row paid
  provider calls.
- Native FIDS styles now have clearer purposes: Classic stays close to the
  normal Local Flight board, PAX favors big passenger-readable rows, VATSIM
  leans into sim-network callsign/phase details, and Nerd keeps a dense
  operator-style board.

---

## Matrix

- Matrix setup/config is now presented as a guided "choose panel, tune preview,
  apply live config, generate main.py" workflow.
- Panel presets, startup lane, row count, weather, gate/stand, brightness,
  palette, animation, and live preview behavior are aligned across native Qt,
  LAN browser, and generated MicroPython.
- Connected i75W boards now report renderer revision and panel geometry, so the
  Matrix page can mirror the board first and warn when `main.py` is stale or the
  configured panel size does not match what the board reports.
- Matrix display labels now use the same operating-first identity contract as
  FIDS. The board receives stable `matrix_*` labels for time, flight, route,
  status, gate, aircraft, and weather so codeshares do not rotate into the
  primary flight-number slot.
- Wide boards such as `256x64` and larger use a full-width layout: airport/lane
  at left, weather centered when enabled, UTC/LT flush right, route given more
  room, and gate/aircraft/status compressed in that order.
- Split-flap remains the default motion, with typewriter and cascade preview
  modes available across native Qt, LAN browser, and generated `main.py`.
- The generated i75W client now carries the `matrix-display-contract-v4`
  renderer marker and uses a server-sent `clock_local_epoch`, fixing cases where
  Qt/LAN preview local time was correct but the physical board's LT was wrong.
- Compact Matrix FIDS headers keep weather inside the existing header space so
  small boards such as `128x128` do not lose a flight row.
- Real-world Matrix boards can show gate/stand data when available. VATSIM
  presets hide gate placeholders because that source does not provide reliable
  gate data.

---

## Mobile

- First-run mobile setup now asks whether the device should be a **LAN
  Companion** or **Standalone** install.
- LAN Companion now has a clearer phone-side job: Board, Radar, History, and
  Control for an existing desktop/Pi host. Help & Reports is reachable from
  Control instead of crowding the bottom nav.
- LAN Companion QR pairing now prefers the server's LAN IP and carries the
  server fingerprint. If `localflight.local` resolves to another Local Flight
  host on a busy test LAN, the mobile app rejects that scan instead of saving
  the wrong server.
- Standalone registers its own mobile relay install, stores its relay activation
  token and airport locally, and talks to relay `/v1/mobile/*` endpoints without
  needing a desktop or Pi on the LAN.
- Standalone is intentionally simpler: FIDS refreshes no faster than every 3
  hours, radar refreshes no faster than every 5 minutes, radar ranges are `1`,
  `3`, `5`, and `10` NM, and Matrix/Admin/server-control tools are hidden.
- Standalone History is local on the device through Expo SQLite and retains 30
  days or 1,000 deduped movements, whichever is smaller.
- Standalone manual/crash reports go directly to the relay reporting gateway.
  Automatic reports require the mobile diagnostics choice to allow them.
- The mobile launch overlay now has a more polished Local Flight feel: shared
  brand text, continuous radar sweep, status fade, breathing status dot, and a
  blinking board LED. Key taps also get subtle haptics and press feedback.

---

## History, Settings, Setup

- History is a dashboard-first view: filters, KPIs, delay buckets, airline
  delay quotas, route/aircraft stats, recent movements, and clean detail panels.
  Counts now mean actual movements: repeated snapshots and linked codeshare
  aliases collapse into one history fact, while raw observations stay local for
  diagnostics.
- Settings is organized around normal user tasks first: airport/source,
  appearance, outputs/radar, and profiles, with diagnostics/docs/advanced
  controls tucked away.
- First-run setup is a six-step wizard with Local Flight branding, airport
  search, source choice, optional keys, diagnostics choice, and a final review
  before the app opens.
  The LAN browser setup is supported wording-wise, not described as a lesser
  path.

---

## Data And Relay Notes

- AeroDataBox is the primary real-schedule path where configured, with
  AviationStack available as compatible sparse fill/fallback.
- Local Flight Relay remains cache-first and may keep serving the last safe shared
  airport snapshot if a live provider is slow, capped, or suspiciously sparse.
- Mobile Standalone uses the same relay provider policy as Local Flight Relay, but
  adds stricter mobile-specific cadence and radar-range limits.
- Public client docs continue to avoid private relay/admin implementation details.
- Existing installs that still point at the Fly.io relay root remain accepted,
  but new setup defaults now use `https://relay.beacontools.cc`.

---

## Operator-Only Network Admin

The separate Network Admin console also received polish in this line:

- coarse "seen within 24h" fleet wording instead of live-online wording
- clearer disconnect/quit behavior
- idle auto-logoff
- calmer operator UI styling
- extracted relay admin SPA assets

This operator console is not part of the normal public client navigation.

---

## Release Packaging

Windows and Raspberry Pi artifacts should be built from the final `0.2.7`
tree after the client-polish, Beacon Tools, Matrix, and support-form changes.
Older `0.2.6` artifacts and any pre-final `0.2.7` artifacts should be treated
as stale.

macOS release packaging now targets a signed/notarized `.pkg` installer. The
package installs **Local Flight.app** into Applications and keeps first-run setup
inside the app, so normal users do not need Python, Terminal, source checkout,
or a manual drag-to-Applications step. The raw `.app` bundle remains a build
intermediate for validation.

---

## Visual-language follow-up

Late in the `0.2.7` cycle a follow-up pass landed that finishes earlier work
and pulls the LAN browser UI into the same design language as the native Qt
shell. No setup choices, data paths, or privacy/diagnostics behaviour change.

### FIDS — four real styles

The four-segment picker in the FIDS header (Classic / PAX / VATSIM / Nerd) now
actually changes the board layout instead of just relabelling columns.

- **Classic.** Original Local Flight board. Rounded cards on a navy panel,
  status rail down the left, blue/cyan accent, pill status chips. Existing
  users see no change unless they switch styles.
- **PAX.** Passenger-friendly oversized board. Larger rounded cards with
  deeper padding, warm sky-blue + amber accents, a tape-style header band,
  friendlier status verbs ("Boarding now", "Significantly late"), and a
  bigger gate badge. Good when the screen is being watched from across a
  lobby.
- **VATSIM.** ATC-scope look. Flat rows on a faint green grid with a
  range-ring marker in the corner, monospace throughout, callsign-first
  columns (callsign, A/C, flight rules, route, ALT/GS, phase), square phase
  chips with codes (TAXI / DESCENT / DELAY / PLAN).
- **Nerd.** Dense operator view. Grid chrome with column separators on every
  row, 13 columns at once (callsign, flight, registration, altitude, ground
  speed, squawk, delay, source...), monospace, dim palette, 3-letter status
  codes (BRD / DLY / SCH).

All four scale with the window: row height, font size, and column widths
interpolate between per-skin minimums and maximums based on viewport width,
and lower-priority columns hide first on narrow viewports rather than
overflowing or squishing.

### Settings — clean disclosure cards

Collapsible sections in Settings used to be gated by a tiny native checkbox
in the top-left of a frame. With more than a few expanded the page felt
busy. Each section is now a disclosure card: an emoji slot, bold title,
muted one-line subtitle that stays visible even when collapsed, a chevron
on the trailing edge that flips on expand, and the whole header bar as
the toggle. The card lights with an accent border when open.

Applies to Relay details, Diagnostics & Docs, Maintenance, and Advanced
Board Timing.

### LAN browser UI — Qt-shell match

Visiting Local Flight in a browser now looks like a continuation of the
native Qt app: brand mark + Local Flight name in Audiowide + monospace
version chip · UTC + LT clock chips · centred segmented destination tabs
with emoji glyphs (Display 🖥, FIDS 🛫, Radar 🛰, Matrix 🟩) · operator
icon-chip bar (⚙ 🛠 📅 📜 💬) with a pulsing green heartbeat · Power
button on the trailing edge. Tokens are identical to the Qt design
palette, so theme and skin choices retint both surfaces the same way.
Shared components (panels, cards, kicker labels, disclosure cards, status
pills, buttons, inputs) round out the page.

### LAN browser UI — mobile view for phones

Open the LAN URL on a phone (for example `http://localflight.local:8000` in
mobile Safari) and the layout automatically switches to a mobile shell:

- The top nav docks to the bottom edge as a thumb-reachable bar with icon
  + caption tabs. iPhone home-indicator / notch safe-area is honoured.
- The FIDS table reflows to a stack of per-flight cards: large time on
  the left, flight + airline + route in the middle, status pill top-right,
  gate badge in a meta row, with a status colour rail on the left edge.
- Settings, Admin, and Setup grids stack to a single column. Inputs pick
  up iOS-friendly sizing (16 px font, 44 px tap targets, defeats Safari
  focus-zoom).
- Radar and Matrix canvases resize to viewport width.

You can preview the same view on desktop by appending `?mobile=1` to any
page URL; `?mobile=0` clears the override.

The public preview gallery was refreshed alongside this pass so the README and
local gallery now show the current mobile Board, Radar, History, and
Settings/Control illustrations rather than older beta artwork.

### LAN browser UI — 7-inch Raspberry Pi screens

The two common 7" Pi touch panels — the official 800×480 screen and
1024×600 IPS panels — get a dedicated compact layout that keeps the
Qt-shell look but tightens every dimension. The top nav drops the brand
text + secondary clock chip; on the 800×480 panel it also drops the UTC
chip and the History/Logs/Report icons (still reachable from a desktop
view). FIDS row height drops to 40 px, fonts step down one notch, and at
the smallest resolution the A/C column hides. Net effect: **8 flights
visible at 800×480** (was 5), **11 at 1024×600**.

These rules trigger automatically on short viewports — no kiosk
configuration required.
