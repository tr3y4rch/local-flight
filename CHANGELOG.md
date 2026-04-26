# Changelog

All notable changes to Local Flight are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.2b2] - 2026-04-26

### Added
- **Scheduler control API** — new `src/localflight/scheduler/control.py`, `GET /api/admin/scheduler`, and `POST /api/admin/scheduler/restart`; desktop Settings and mobile Settings can now restart the sleeping scheduler manually
- **Config sync WebSocket events** — server now broadcasts `config_updated` and `scheduler_restarted` through `src/localflight/ui/events.py` so desktop display windows, Admin, and the mobile companion stay in sync when airport/source/update interval changes
- **`/api/feedback/crash`** server endpoint — new `POST` route accepting `message`, `traceback`, `context`, and `client_context`; returns `409` for server-side duplicates, `502` for Linear errors
- **Richer bug report context** — `/api/feedback` and `bug_reporter.py` now accept and forward `client_context` so mobile-reported issues include the client OS, app version, and server config alongside server-side system info
- **macOS release zip** — `python build.py` on macOS now produces `dist/LocalFlight-macos.zip` and `dist/LocalFlight-macos.zip.sha256` alongside `dist/LocalFlight.app` for GitHub release uploads
- **README preview gallery** — new `docs/previews/` HTML gallery and SVG preview panels for FIDS, Radar, and Settings using clearly labeled sample data

### Mobile Companion (Work In Progress)
- The mobile companion remains a developer preview in `mobile/`; it is not a finished public iOS or Android release yet
- Public iOS and Android companion builds are planned for a later milestone after the LAN pairing/security model is ready
- **Matrix configurator screen** — mobile Settings now opens a dedicated Matrix panel tool with panel size presets (64×32 → 384×64), row count, brightness, DEP/ARR view, live ASCII preview, and copyable MicroPython client config
- **Mobile airport/config sheet** — companion app can search airports, switch real/VATSIM source, change the server update interval, and save/apply local airport profiles via SecureStore
- **Animated launch overlay** — custom fade/scale launch animation coordinated with `expo-splash-screen`; prevents the blank white flash on cold start; splash plugin now uses the circular app icon and dark background
- **Flight Island** — persistent dynamic-island-style widget pinned to the top of the FIDS board showing the pinned or most relevant active flight; survives tab switches
- **Flight Action Sheet** — long-press any FIDS row to open actions such as pin/unpin and flight detail; normal tap still opens the detail sheet
- **In-app feedback form** — Settings → Send Feedback sends title + description to `/api/feedback` with auto-attached client context (app version, OS, server URL, airport, source); routes to developer's Linear board
- **Mobile crash reporting** — `mobile/src/crash/reporter.ts` installs a global `ErrorUtils` handler and `CrashBoundary.tsx` wraps the React tree; both auto-route caught errors to the new `/api/feedback/crash` endpoint with 10-minute client-side deduplication
- **Pinned flight persistence** — `mobile/src/storage/settings.ts` gains `loadPinnedFlight` / `savePinnedFlight` backed by SecureStore key `localflight.pinnedFlight`
- **Admin updates + connections in API client** — `getUpdates()` → `/api/admin/updates` and `getConnections()` → `/api/admin/connections` added; `AdminUpdates` and `AdminConnections` types added; `DashboardSnapshot` extended with both fields
- **SafeAreaProvider** — `react-native-safe-area-context` replaces RN's built-in `SafeAreaView` for correct inset handling across notched iPhones and iPads

### Changed
- Version bumped to `0.2.2b2` for Python metadata, runtime fallbacks, mobile package metadata, Expo metadata, and docs
- Scheduler-relevant config changes now wake/restart the scheduler immediately instead of waiting for the previous sleep interval to expire; mobile also uses the server interval as a fallback refresh cadence
- Desktop `display.html`, FIDS, Radar, and Admin now listen for sync WebSocket events so host windows update after settings/mobile changes
- Bug report context now distinguishes server platform from mobile reporter environment
- Release docs now distinguish source-checkout installers from uploadable PyInstaller artifacts for Windows and macOS
- README now clearly separates desktop release installation from the work-in-progress mobile companion developer preview
- Mobile main navigation now contains only FIDS, RADAR, HISTORY, and SETTINGS; Matrix and Admin are tucked into Settings
- Mobile top bar now shows departure airport + live/source status on the left and UTC + local time on the right
- Pinned flights persist locally, sort back to the top of the FIDS stack, and drive the Flight Island when available
- Mobile `submitFeedback` and `submitCrashReport` use a new generic `sendJson` POST helper in `client.ts`, consistent with `fetchJson`
- `statusShort`, `routeMeta`, `mobileClientContext`, `matrixPreviewLines` helper functions extracted to keep component code declarative

### Fixed
- Expo/Metro dependency metadata now includes the splash/safe-area/vector-icon stack and keeps the companion package/lock versions aligned at `0.2.2-b2`
- macOS code signing no longer fails solely because an optional `assets/entitlements.plist` file is absent

---

## [0.2.2b1] - 2026-04-26

### Added
- **macOS source-checkout `.app` bundle** — `installers/macos/install.sh` now builds a proper `LocalFlight.app` in `~/Applications/` with the SVG-derived icon; uses a compiled Mach-O stub (`cc`) as the bundle executable (required by macOS Launch Services) that exec's a baked shell launcher; `scripts/make_app_bundle.py` orchestrates icon generation + `iconutil` + plist + stub compile
- **Pre-rendered icon** — `assets/icon_circle.png` committed (1024×1024 RGBA) so `make_app_bundle.py` works without `cairosvg` at install time
- **React Native mobile companion Phase 1** - new `mobile/` Expo app scaffold for iOS-first testing on iPhone/iPad
- **Mockup-inspired mobile shell** - native header, pseudo dynamic island/status bar, airport badge, live pill, METAR strip, tab bar, FIDS direction toggle, pinned flight card, compact FIDS rows, admin cards, settings, and bottom nav
- **Mobile API client** - reads `/api/health`, `/api/config`, `/api/admin/system`, `/api/admin/budget`, `/api/fids`, and `/api/metar`; listens for `/ws` `snapshot_updated` events
- **On-device server setting** - stores the Local Flight LAN server URL with Expo SecureStore

### Changed
- Version bumped to `0.2.2b1` for the Python app, runtime fallbacks, PyInstaller fallback, docs, and release guidance
- Mobile package metadata uses npm-safe prerelease form `0.2.2-b1`; Expo display metadata stays at `0.2.2` with `extra.localFlightVersion` set to `0.2.2b1`
- Mobile dependency pins were checked against the npm registry; `expo-secure-store` now matches Expo SDK 55 with `~55.0.13`

### Notes
- Node/npm are not installed on the current Windows workspace, so mobile install/build verification should be run on the Mac/Xcode machine.

---

## [0.2.1b2] - 2026-04-26

### Added
- **Versioned launch splash** - `/splash` shows a short animated Local Flight boot screen with the current app version before setup/display
- **Regression coverage** - important scheduler, storage, route, and runtime state behaviours now have tests
- **Windows checksum artifact** - `build.py` writes `dist/LocalFlight-windows.zip.sha256` next to the release zip
- **Platform abstraction layer** (`platform/`) — unified Windows, macOS, Pi/Linux startup
- **Cross-platform kiosk browser launcher** — Edge/Chrome app window on desktop, Chromium kiosk service on Pi
- **Cross-platform system tray** — pystray on Windows/macOS, no-op stub on Pi/Linux
- **Raspberry Pi installer** (`installers/pi/install.sh`) — venv, two systemd services, mDNS (`localflight.local`)
- **Pi management helper** (`lf.sh`) — start/stop/logs/update in one command
- **Shared nav bar** (`_nav.html`) — consistent navigation macro across all pages
- **FIDS board improvements** — ARR/DEP toggle visible in all modes including split-view embedded iframes
- **Flight detail drawer** — click any FIDS row for a slide-in panel with times, position, ops data, and 7-day history
- **Settings page** — active skin highlighted on load, compact status line in header
- **Admin hub** — scheduler status, API budget, WebSocket client count, history DB stats, METAR, live log tail
- **History database** — SQLite, 90-day retention, browse tab + aggregate stats tab
- **5 skins** — standard, technical, neon, cyan, crt
- **PyInstaller bundle** — `python build.py` produces `dist/LocalFlight-windows.zip` (Windows) or `dist/LocalFlight.app` (macOS)
- **Version field** — `v{version}` shown in nav bar and Admin → System card, sourced from package metadata
- **Bad API key banner** — FIDS board shows a red warning banner when the scheduler has a persistent error
- **Quit button modal** — inline confirmation dialog replacing native `confirm()`, with "Shutting down…" feedback state
- **Bug reporter** — 🐛 Report nav button on every page; `/feedback` form auto-attaches version, platform, airport; routes to developer's Linear (no user config required)
- **Setup wizard — RapidAPI key validation** — "Test connection" button for ADS-B Exchange key mirrors AviationStack step; `GET /api/setup/test-rapidapi` endpoint validates key without saving
- **Admin — Buy Me a Coffee** — subtle attribution strip at bottom of Admin hub
- **`/api/fids/detail`** — per-callsign detail endpoint with live position + 7-day history
- **Setup re-run** — "Re-run setup wizard" button in Settings to reset configuration from scratch
- **Auto-update check** — Admin hub shows a notice when a newer GitHub release is available

### Changed
- Desktop launchers and Pi kiosk service now open `/splash?next=/display` so release builds show the same startup flourish across targets
- Version bumped to `0.2.1b2` across package metadata, runtime fallbacks, PyInstaller, docs, and release guidance
- `psutil` and `packaging` are now required runtime dependencies so Admin system info and version comparison work in installed builds
- Runtime JSON snapshots now live under `~/.localflight/storage/data/<IATA>/snapshots`; legacy source-tree snapshots are still read as a fallback
- macOS and Raspberry Pi installers are documented as source-checkout installers, matching the Windows source installer vs self-contained release zip split
- README rewritten from end-user perspective — install-first flow, removed dev-cycle language
- Installer structure reorganised into `installers/windows|macos|pi/`
- Windows source installer clarified as source-only; GitHub release zip remains unzip-and-run with bundled dependencies
- `__main__.py` split into `_run_desktop()` / `_run_headless()` paths
- Terminal closes automatically on quit (no `pause` in launcher scripts)
- Quit endpoint uses `os._exit(0)` after terminating the browser process

### Fixed
- Scheduler snapshot pruning now runs inside both real and mock snapshot jobs instead of relying on a separate process wrapper
- Failed scheduler cycles preserve the previous `last_success_utc` instead of clearing a known-good success timestamp
- Duplicate `/api/config` registration was removed and setup/admin route fallbacks now use the current version
- Local AviationStack file loading now checks canonical and legacy snapshot locations consistently
- `.env.example` no longer exposes operator Linear variables intended only for private scheduler auto-filing
- Windows source installer now detects Python robustly, supports `-NoShortcut`, `-SkipDependencyInstall`, `-Launch`, and `-NoPause`, and writes a safer source launcher
- `start.bat` — UTF-8 box-drawing chars in `::` comments caused cmd.exe byte-eating bug on `chcp 65001`; replaced with ASCII dashes
- Setup wizard — RapidAPI signup URL corrected (`adsbexchange` → `adsbx` provider slug); OpenSky registration URL updated from stale Joomla path to `/login?view=registration`
- Tray icon quit — `sys.exit(0)` inside pystray callback raised `SystemExit` and logged a spurious crash; changed to `os._exit(0)`
- VATSIM aircraft type extraction now handles `H/B748/L` heavy-prefix format
- Jinja2 `TemplateSyntaxError` in `_nav.html` (unclosed block comment)
- `UnicodeEncodeError` on Windows console (cp1252) in build script output

---

## [0.1.0] — 2025-03-01

### Added
- Initial release — FastAPI web server, FIDS board, WebSocket live push
- AviationStack schedule data source with monthly budget guard
- ADS-B Exchange position enrichment (RapidAPI)
- OpenSky Network position fallback
- VATSIM virtual/sim source
- METAR weather bar
- Radar view with sweep animation
- Split-view display with draggable divider
- Matrix preview (LED simulator + split-flap animation)
- MicroPython client for Pimoroni Interstate 75 W
- First-run setup wizard
- SQLite flight history (90 days)
- dump1090 / RTL-SDR ADS-B client for Pi
