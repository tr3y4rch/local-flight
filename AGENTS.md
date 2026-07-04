# Local Flight — Codex Context

## What this project is

A local-first, self-hosted **Flight Information Display System (FIDS)** that runs on Windows, macOS, and Raspberry Pi. Fetches real and simulated flight data, displays it as a proper airport-style departure/arrival board — in the Chrome-free native Qt shell, supported LAN browser UI, an LED matrix panel, or a dedicated HDMI screen.

Built with: Python 3.11+, FastAPI, uvicorn, SQLite, WebSocket, Jinja2, PIL, and PySide6/Qt for the primary native desktop/display UI. The mobile app uses React Native / Expo. pystray on macOS only (Windows uses a ctypes taskbar window).

**Repo:** https://github.com/tr3y4rch/local-flight
**Issues:** https://github.com/tr3y4rch/local-flight/issues
**Dev studio/home domain:** Beacon Tools — `beacontools.cc`, owned via Cloudflare at about `$8/year`. Public Local Flight home is `https://beacontools.cc/local-flight`; mobile trust page is `https://beacontools.cc/local-flight/mobile`; support/contact/bug reports start at `https://beacontools.cc/support`; public network/relay notes are at `https://beacontools.cc/network`; privacy policy is `https://beacontools.cc/privacy`; privacy choices/reset guidance is `https://beacontools.cc/privacy/choices`; privacy contact remains `privacy@beacontools.cc`.

---

## Current 0.5.1 handoff snapshot (2026-06-30)

- Active package target is now `0.5.1` for the public desktop/Raspberry Pi hardening line. `pyproject.toml` remains the source of truth; keep runtime fallbacks, native docs, mobile metadata, installer defaults, public site copy, and bundled release docs aligned with it.
- Desktop and Pi are the public release path for this milestone. Mobile is store-bound after the Remote Companion connectivity/privacy proof pass, with Beacon-owned bundle/package IDs `cc.beacontools.localflight`, URL scheme `localflight`, iOS build number `1`, and Android versionCode `1` unless store uploads have already consumed those counters.
- The preliminary `0.2.8` notes have been folded into `0.5.1`; keep `docs/release-notes-0.5.1.md` and the top of `CHANGELOG.md` as the public release summary.
- This hardening pass addresses the known blocker slice from the previous handoff: browser/display clock timezone drift, mobile setup copy drift, preview gallery/brand asset drift, macOS executable-bit testing on Windows, relay/shared schedule metadata, and Expo SDK patch drift.
- Phase 2 automated desktop/Pi hardening is now covered in tests: setup/re-setup provider-mode cleanup for BYOK, managed relay, community relay, and virtual; `.env` authority for Local Flight-owned provider/relay keys; stale process-secret log redaction; native Qt setup-window transitions that do not quit the backend; Matrix v4 local clock/gate/weather contract; FIDS/Radar/History route contracts; and stale-safe relay schedule behavior.
- Manual Phase 2 smoke still remains before release artifacts: fresh install/upgrade on Windows, signed/notarized macOS, and Raspberry Pi; Pi headless/Chromium kiosk/native kiosk services; physical Matrix/i75W script generation and live gate/weather toggles; and live real/VATSIM/BYOK/community/managed/virtual mode walkthroughs against the actual relay/provider setup.
- Existing `dist/` artifacts from `0.2.7` are stale for public release. Rebuild expected artifacts after validation: `LocalFlight-0.5.1-Setup.exe`, `LocalFlight-0.5.1-macos.pkg`, and `LocalFlight-pi-source-0.5.1.zip`.

### Historical 0.2.7 / preliminary 0.2.8 snapshot follows

- Active package target: `0.2.7` as the client-polish/release-candidate line. `pyproject.toml` remains the source of truth; keep runtime fallbacks, native docs, mobile metadata, and preview/release docs aligned with it.
- Current validation history: after the Beacon relay cutover on 2026-05-22, the focused relay/native suite passed with `392 passed`, compileall passed, mobile `npm run typecheck` passed, and `git diff --check` passed. After the public/docs refresh, the doc/native regression slice passed with `287 passed`, HTML parsing for `site/` and preview pages passed, and Cloudflare served the updated copy. After the Beacon Tools mobile/trust site pass, all `site/**/*.html` parsed, `/assets/*` references resolved, stale URL scans passed, local static routes returned `200`, and Cloudflare served `/local-flight/mobile/`, `/support/`, `/network/`, `/privacy/choices/`, with `/local-flight/privacy` still redirecting to `/privacy`. After Matrix v4 renderer/live-settings/local-clock/web-preview hardening, focused Matrix checks passed and the full Windows/Codex suite returned `432 passed`. The final Windows/Pi docs-and-package sweep passed HTML reference checks, compileall, and full `.venv\Scripts\python.exe -m pytest tests -q` with `441 passed`. On macOS/Codex, `.venv/bin/python build.py --clean` repacked the unsigned local/dev `dist/LocalFlight.app` and `dist/LocalFlight-macos.zip`; `codesign --verify --deep --strict` passed, the zip checksum verified, and `spctl` rejection is expected until Developer ID signing/notarization is available. `npm audit --omit=dev` still reports 4 moderate advisories through Expo's Metro/PostCSS dependency chain, but the suggested `npm audit fix --force` would install a breaking Expo version, so do not force it inside this release-candidate sweep.
- Preliminary `0.2.8` documentation state (2026-05-27): no package version bump yet. `CHANGELOG.md` and `docs/release-notes-0.2.8.md` now track the next polish line while `0.2.7` remains the artifact target. Current preliminary scope is LAN browser Settings parity with Qt Settings, browser-side Pair Mobile QR/manual pairing, paired-device refresh/copy/reset actions, preview source assets under `assets/previews/`, Cloudflare Worker + Assets deploy guidance, and mobile private-beta store readiness now that Apple App Store Connect and Google Play Console access is available.
- Mobile private-beta prep is staged but not uploaded: Expo identity now uses `cc.beacontools.localflight` for both iOS bundle ID and Android package, `ios.buildNumber` is `"1"`, `android.versionCode` is `1`, app version remains `0.2.7`, URL scheme remains `localflight`, `mobile/eas.json` has a store-distribution `beta` profile, and `mobile/metro.config.js` is intentionally tracked so Expo Doctor stays green. Future dormant support-tip/widget identifiers were moved to the Beacon prefix too. The generated `mobile/android/` native files are ignored/prebuild output; treat `mobile/app.json` and EAS config as the durable source and let Expo/EAS regenerate native Android state on macOS if needed.
- Mobile validation from this Windows/Codex pass: `cd mobile && npm run verify` passed (`typecheck`, widget contract, Expo Doctor 19/19), `npm run a11y` passed, `npx expo config --type public` showed the Beacon bundle/package IDs and build counters, focused store identity + relay mobile IAP tests passed, `compileall` for `relay`/`tests` passed, and `git diff --check` passed with CRLF warnings only. Full `.venv\Scripts\python.exe -m pytest tests -q` is not currently clean (`464 passed, 7 failed`); the failures are existing/non-store-pass issues around browser/display clock assertion drift, mobile setup copy assertion drift, preview gallery/brand asset assertion drift, macOS executable-bit testing on Windows, and relay shared-schedule metadata assertions.
- Windows and Pi artifacts were rebuilt from the final Windows/Codex workspace on 2026-05-22 after the Beacon Tools support forms, Cloudflare Worker route repair, docs sweep, relay SMTP/contact hardening, and Matrix v4 polish. Fresh artifact hashes:
  - `dist/LocalFlight-windows.zip` — SHA256 `da43e5a8fb96a0326e99d4e584a0519b08bbb409832a7b6502cd7aaaa5141fcc`
  - `dist/LocalFlight-pi-source-0.2.7.zip` — SHA256 `fe578f0e7dd110bd17aae70b6eae2436408cd804f57f7048afb5c0359d5d49cc`
- macOS local/dev packaging has been refreshed from this source state: `dist/LocalFlight.app`, `dist/LocalFlight-macos.zip`, and `dist/LocalFlight-macos.zip.sha256` exist for local testing. Public macOS release packaging still needs the signed/notarized `.pkg` pass after Apple Developer ID credentials are available. Do not reuse stale `0.2.5b5`, `0.2.6`, or pre-standalone/pre-Matrix-integrity `0.2.7` macOS/Pi handoff notes.
- Recent client-facing changes to preserve in smoke tests: Beacon Tools website/privacy/relay URLs plus the mobile/support/network/privacy-choices trust pages, public support message/bug-report forms, native shell top-bar grouping and footer support icons, city/country FIDS title, passenger-friendly weather hero, long-title clamping, true visual FIDS style skins for Classic/PAX/VATSIM/Nerd, VATSIM pilot/ATC display contract with passenger-field suppression, native/browser History analytics dashboard, deduped History movement counts with raw-observation diagnostics, Matrix configurator parity, board-mirror Matrix preview, Matrix v4 renderer warnings, compact Matrix weather header, Matrix display-contract labels/weather icons in Qt/LAN/MicroPython, split-flap/typewriter/cascade Matrix motion, real-only Matrix gate labels, correct i75W LT via `clock_local_epoch`, Settings/setup dashboard polish, LAN browser Settings parity with Qt disclosure folders and Pair Mobile QR/manual/Remote Companion pairing, FIDS/Radar current-source intelligence details, LAN radar parity with Qt radar behavior, LAN browser phone/7-inch Pi layouts, refreshed public preview gallery/mobile SVGs, mobile preview source screenshots, mobile Companion IA with LAN/REMOTE/OFFLINE state, mobile branded launch/interaction polish, Android local mobile dev path, Remote Companion relay fallback, and the mobile Standalone setup/data/reporting path.
- Preview source assets now live in `assets/previews/`: `assets/previews/mobile/iOS/` for iPhone/iPad companion imagery, `assets/previews/mobile/Android/` for Android companion imagery, and `assets/previews/shell/` for native Qt shell screenshots. Treat these screenshots as documentation/website implementation source assets; prefer using or deriving from them for public docs/site previews instead of inventing fresh mockups.
- Preview hierarchy of functional importance for docs/site imagery: FIDS first, then Radar, History, Setup, Display, and Splash. When space is limited, prioritize screenshots and copy in that order so the core board/radar/history value is visible before onboarding or launch polish.
- Schedule-provider work to preserve in relay/client smoke tests: AeroDataBox primary FIDS source, AviationStack sparse fill/fallback, hard upstream caps, 24h stale-cache serving, source-cache re-merge, canonical provider meta, and fused rows compiling through both `/api/fids` and Qt `FlightBoardModel`.
- Mobile Standalone relay work to preserve in smoke tests: `/v1/airports/search`, `/v1/airports/resolve`, `/v1/mobile/summary`, `/v1/mobile/fids`, `/v1/mobile/radar`, `/v1/mobile/metar`; activation with `requested_mode=mobile_standalone`; standalone FIDS 3h policy; standalone radar 1/3/5/10 NM + 5m cache; local SQLite movement history; direct relay reports with mobile diagnostics gating.
- Separation of power still applies: public docs stay user-focused; relay operator/admin details belong only in `AGENTS.md`, `DEV_README.md`, `CLAUDE.md`, and operator tooling. Cloudflare Worker + Assets serves the no-build public site from `site/`; edits there only go live after a real Worker deploy from the repo, not from a dashboard preview alone. Public pages may mention `network.beacontools.cc/admin` only as operator-only/admin-separated context and must not expose credentials, Fly secrets, admin API details, or internal runbooks.

---

## Project structure

```
local-flight/
├── build.py                     # PyInstaller build script — icons, signing, zip
├── LocalFlight.spec             # PyInstaller spec — datas, hiddenimports, BUNDLE
├── LICENSE                      # MIT — Philipp Schumacher 2025
├── CHANGELOG.md
├── .gitattributes               # LF for sh/command, CRLF for bat/ps1
├── assets/
│   ├── icon.png / icon.icns / icon.iconset/  # Generated app icon outputs from localflight-logo.svg
│   ├── localflight-logo.svg      # Source logo master for app/package icon generation
│   └── previews/
│       ├── mobile/
│       │   ├── iOS/              # iOS companion preview screenshots for docs/site
│       │   └── Android/          # Android companion preview screenshots for docs/site
│       └── shell/                # Native Qt shell preview screenshots for docs/site
├── src/localflight/
│   ├── __main__.py              # Entry point — platform-aware startup; installs sys/threading crash hooks
│   ├── platform/                # Cross-platform abstraction layer
│   │   ├── detect.py            # Platform detection (Windows/macOS/Pi/Linux)
│   │   ├── browser.py           # Cross-platform kiosk browser launcher
│   │   └── tray.py              # Windows: ctypes taskbar window; macOS: pystray; Pi: stub
│   ├── core/
│   │   ├── airports.py          # Airport DB lookup (IATA/ICAO)
│   │   ├── config.py
│   │   └── models.py            # Flight, FlightPosition, FlightDirection, etc.
│   ├── decode/
│   │   ├── dedupe.py            # Codeshare deduplication
│   │   ├── metar.py             # Local Flight semantic METAR mood/icon decorator
│   │   ├── normalize.py         # Raw records → Flight objects
│   │   ├── opensky.py           # OpenSky enrichment
│   │   └── mappings/
│   │       ├── aviationstack.py
│   │       └── aerodatabox.py
│   ├── display/
│   │   └── fids_from_flights.py # PAX-friendly flight number formatting
│   ├── render/
│   │   └── fids.py              # Build Jinja2 template context
│   ├── scheduler/
│   │   ├── jobs.py              # Main fetch job — AeroDataBox/AviationStack + enrichment chain
│   │   ├── runtime.py           # run_loop(); stop_event-aware sleeps + crash reporting
│   │   ├── control.py           # In-process scheduler start/status/restart controller
│   │   └── run_scheduler.py
│   ├── sources/
│   │   ├── web/
│   │   │   ├── aviationstack_client.py  # BYOK + community relay budget guard; activation token; lazy env reads
│   │   │   ├── aerodatabox_client.py    # BYOK AeroDataBox FIDS client + local atomic budget guard
│   │   │   ├── schedule_fusion.py       # AeroDataBox primary + AviationStack fill merge policy
│   │   │   ├── local_usage.py           # Local SQLite usage counters for direct provider caps
│   │   │   ├── aviationstack_mock.py
│   │   │   ├── adsbexchange_client.py   # RapidAPI + relay radar proxy; primary position enrichment
│   │   │   ├── opensky_radar.py         # fetch_radar_blips(), bounding_box()
│   │   │   ├── airport_surface.py       # OSM/Overpass airport surface normalization + payload schema
│   │   │   ├── vatsim_client.py         # VATSIM v3, aircraft type extraction
│   │   │   ├── metar_client.py          # aviationweather.gov, 30min cache
│   │   │   ├── linear_client.py         # Linear GraphQL API — file_error() (operator auto-filing)
│   │   │   ├── private_keys.py          # Dev-only community key lookup (dev/private/community_keys.json, gitignored)
│   │   │   ├── relay_defaults.py        # Hosted relay URL + admin host constants
│   │   │   ├── aviationstack_files.py   # Local file loading (canonical + legacy paths)
│   │   │   └── bug_reporter.py          # Sanitized report forwarder — powers /feedback + crash reports via relay
│   │   ├── adsb/
│   │   │   └── adsb_client.py           # dump1090 client (RTL-SDR, Pi)
│   │   └── matrix/
│   │       └── client.py                # MicroPython for Interstate 75 W
│   ├── storage/
│   │   ├── config.py            # AppConfig dataclass, load/save
│   │   ├── flights_store.py     # JSON snapshot storage under ~/.localflight, legacy fallback
│   │   ├── history.py           # SQLite raw observations + deduped movement history, 90-day retention
│   │   ├── install.py           # Machine fingerprint + activation token (get/set_activation_token)
│   │   ├── logging_setup.py     # RotatingFileHandler, pruning
│   │   ├── profiles.py          # Airport profiles
│   │   ├── request_log.py       # Anonymized traffic log (SQLite) — client_type/client_id/platform
│   │   ├── samples/             # Sample AviationStack payloads (mock source)
│   │   └── state.py             # AppState (last fetch, errors, latency)
│   └── ui/
│       ├── server.py            # FastAPI app, WebSocket, setup gate middleware
│       ├── api.py               # All JSON API endpoints
│       ├── events.py            # Non-fatal WebSocket publisher: snapshot/config/scheduler events
│       ├── static/
│       │   ├── app.css
│       │   ├── skins.css        # 5 skins: standard/technical/neon/cyan/crt
│       │   └── splash_mark.svg  # Versioned launch splash mark
│       └── templates/
│           ├── _nav.html        # Shared nav macro — version badge, quit modal
│           ├── base.html        # Base layout, clock, nav CSS
│           ├── fids.html        # FIDS board — error banner, detail drawer, WebSocket
│           ├── radar.html       # Radar canvas + sweep + METAR + optional surface overlay
│           ├── display.html     # Split-view FIDS+Radar, draggable divider
│           ├── matrix_preview.html  # LED simulator + split-flap animation
│           ├── settings.html    # Airport picker, skins, re-run setup button
│           ├── admin.html       # Admin hub — scheduler/budget/updates/system
│           ├── feedback.html    # Bug reporter form — title, description, auto-attached system info
│           ├── history.html     # History browser — filterable table + detail panel
│           ├── setup.html       # First-run setup wizard (strict gate)
│           ├── splash.html      # Short versioned launch splash -> setup/display
│           ├── logs.html        # Live log viewer
│           ├── requests.html    # Anonymized local traffic log viewer
│           ├── icons_pictogram.html  # Aircraft SVG icons (standard skin)
│           └── icons_technical.html  # Vector icons (neon/cyan/crt skins)
│
├── mobile/
│   ├── App.tsx                  # Expo mobile provider entrypoint
│   ├── app.json                 # Expo app metadata, splash config, iOS local-network plist
│   ├── assets/
│   │   └── icon_circle.png      # Companion icon + splash image
│   └── src/
│       ├── api/                 # LAN API client, standalone relay client, response types
│       ├── app/AppShell.tsx     # Mobile coordinator: setup mode, refresh, shell chrome, style factory
│       ├── components/          # Shared chrome/components such as bottom nav and launch overlay
│       ├── crash/               # CrashBoundary + mobile crash reporter
│       ├── device/identity.ts   # Companion identity: companionId, platform, deviceType, appVersion
│       ├── domain/              # Pure mobile helpers/constants for flights, radar, matrix, formatting
│       ├── hooks/               # Launch/bootstrap, flight detail, matrix draft/save/reset hooks
│       ├── screens/             # FIDS/Radar/History/Matrix/Admin/Settings screens and sheets
│       ├── storage/             # SecureStore setup state + Expo SQLite standalone history
│       └── theme/               # Mobile visual tokens, runtime provider, style bridge
│
├── installers/
│   ├── windows/
│   │   ├── install.ps1          # Windows source checkout installer
│   │   └── LocalFlight.bat      # Windows source checkout launcher
│   ├── macos/
│   │   ├── install.sh
│   │   ├── LocalFlight.command  # Double-clickable launcher
│   │   └── start.sh
│   └── pi/
│       ├── install.sh           # Full Pi setup — venv, systemd, mDNS
│       ├── localflight.service  # Python app systemd service
│       ├── localflight-kiosk.service  # Chromium kiosk systemd service
│       └── lf.sh                # Management helper (start/stop/logs/update)
│
├── start.bat                    # Native-first dev launcher (Windows, project root)
├── start.command                # Native-first dev launcher (macOS, project root)
└── start_network.bat            # Local ignored native operator Network Admin launcher
```

Native/Chrome-free additions:
- `src/localflight/platform/gui_mode.py` parses `LOCALFLIGHT_GUI_MODE=auto|native|browser|headless` with native as the blank/invalid default.
- `src/localflight/platform/gui_launcher.py` makes the final platform launch decision from requested mode, platform, display availability, and PySide6/Qt availability.
- `src/localflight/native/app.py` is now the thin public compatibility facade for native launch/test imports. The current extracted native runtime lives across `bootstrap.py`, `shell.py`, `async_tools.py`, `loader.py`, `pages/`, `canvas/`, and private compatibility code in `_legacy_app.py` while the behavior-preserving split continues.
- `src/localflight/native/network_admin.py` is the separate operator-only Network Admin Qt shell, pointed at redacted relay `/admin/api/*` JSON plus admin action endpoints. It now has a fleet/dev operations console shape with Overview, Fleet, Traffic, Schedules, Surfaces, Activations, Reports, Providers, and Maintenance.
- `src/localflight/native/design.py` and `routes.py` hold browser-parity Qt theme/skin tokens, shared styling/widgets, native media/doc resolution, bundled public doc metadata, and declared native HTTP actions so buttons do not drift from real routes.
- `src/localflight/native/api_client.py` and `qt_compat.py` keep HTTP access and PySide6 imports lazy so non-native builds keep working.
- `start.bat`, `start.command`, Windows/macOS source installers, macOS app-bundle launcher, and PyInstaller builds install/verify the `native` extra so PySide6/Qt is present before native launch. Release apps, the macOS source-built `~/Applications/LocalFlight.app`, and the Windows source installer desktop shortcut are intended to be quiet/branded end-user launch paths; `start.*`, `installers/macos/start.sh`, `.command`, and direct `python -m localflight` remain visible-console dev/debug paths.
- `start_network.bat` is a local ignored operator launcher that opens the native operator console against the hosted relay by default. Keep relay runtime secrets in Fly/dashboard secrets, not in repo-tracked files.

---

## Architecture decisions

### Platform model
- `platform/detect.py` — `detect()` returns `Platform` enum, cached. `is_desktop()` / `is_headless()` helpers.
- `LOCALFLIGHT_GUI_MODE=auto|native|browser|headless` is parsed by `gui_mode.py`; `gui_launcher.py` then resolves the actual launch shell. Blank or invalid values fall back to `native`.
- Native is the product default: Windows/macOS open the PySide6/Qt shell when available, Pi/Linux with a display can open native fullscreen when Qt is installed, desktop falls back to browser only when Qt is unavailable, and display-less Pi/Linux remains headless.
- Desktop browser mode (Windows/macOS): supported LAN browser UI in a kiosk-style browser window + system tray + full GUI.
- Native mode: starts the same local FastAPI backend, then opens the Qt shell instead of Chrome/Edge/Chromium. Browser UI remains reachable manually at `http://localhost:8000`.
- Headless (Pi/Linux): uvicorn + scheduler only, no window management. Chromium kiosk is a separate systemd service; native Qt kiosk is explicit via `installers/pi/install.sh --native-kiosk` and now runs as split services: backend stays headless in `localflight.service`, while a user-session `localflight-native-kiosk.service` owns the fullscreen Qt display.
- `__main__.py` logs the full `GuiLaunchDecision` and dispatches to `_run_native_gui()`, `_run_desktop()`, or `_run_headless()` based on the resolved platform launch layer.
- Browser/LAN UI and Chromium Pi kiosk first hit `/splash?next=/display`; first-run browser mode uses `/splash?next=/setup`. Native first-run uses the standalone setup window before creating the main shell.

### Data enrichment chain (source=real)
```
AeroDataBox FIDS (primary schedule: dense airport board, times/status, gates/terminals/aircraft when present)
    ↓ sparse/missing-field fill
AviationStack (conditional schedule fill/fallback; fills empty board fields without overwriting AeroDataBox times/status)
    ↓
Schedule fusion (canonical Local Flight rows; deterministic flight identity; source evidence kept in meta)
    ↓
ADS-B Exchange via RapidAPI (primary: position + aircraft type + registration)
    ↓ fallback
OpenSky Network (position fallback)
    ↓ fallback
Schedule data only
    ↓
Dedupe codeshares → save JSON snapshot → write SQLite raw observations + movement history → WebSocket broadcast
    ↓ on error
Linear issue filed (deduplicated per 6h via ~/.localflight/linear_dedup.json)
```

Provider selection stays inside `source=real`: `LOCALFLIGHT_REAL_SCHEDULE_PROVIDER` / `RELAY_SCHEDULE_PROVIDER` can be `auto`, `aerodatabox`, or `aviationstack`. `auto` prefers AeroDataBox when configured/enabled and uses AviationStack only as sparse fill or fallback. The public app mode remains `real|virtual`.

### WebSocket live push
- `ConnectionManager` in `server.py` tracks connections, drains async queue
- `ui/events.py` is the shared non-fatal publisher for `snapshot_updated`, `config_updated`, and `scheduler_restarted`
- Scheduler calls `_broadcast_update()` after each snapshot; settings/API/profile/setup saves call `notify_config_updated()`
- Scheduler-relevant config changes (`airport_iata`, `airport_icao`, `refresh_seconds`, `source`) queue `restart_scheduler_and_notify()` so the new interval takes effect immediately
- `display.html` holds one WS connection, reloads on `config_updated`, and forwards other messages via `postMessage` to iframes
- FIDS/Radar/Admin/mobile refresh on push events and still keep lightweight fallback polling
- Clients reconnect with exponential backoff

### Relay heartbeat and Network Admin routing
- This is an operator-only visibility path, not a user-facing feature and not a billing/usage signal. Keep details in `AGENTS.md`, `DEV_README.md`, `CLAUDE.md`, tests, and operator tooling only.
- Local app startup creates the async heartbeat task from `ui/server.py` lifespan. The sender lives in `sources/web/relay_beat.py`; the safe metadata builder lives in `sources/web/relay_heartbeat.py`.
- Normal heartbeat cadence is intentionally low: one startup attempt after roughly 45s plus jitter, then about every 30 minutes with ±5 minutes jitter. Do not shorten this interval for convenience; we do not want a hobbyist app hammering Fly.io or the relay with keepalive traffic.
- Heartbeats should stay silent-failure, fire-and-forget, and non-blocking. A failed relay heartbeat must never break setup, FIDS, radar, scheduler, matrix, mobile, or local LAN browser behavior.
- Heartbeats are meant for real-source community relay installs after setup is complete. BYOK users, virtual/VATSIM-only users, and incomplete setup should not need periodic relay presence pings.
- Current immediate heartbeat triggers exist after first-run setup completion and desktop settings saves so Network Admin can notice changed client shape sooner. They must pass the same local eligibility gate as the periodic loop and a sender-side 5-minute debounce before any outbound call reaches Fly.
- The relay endpoint is `POST /v1/heartbeat`. It validates the raw install UUID, records only coarse install-profile metadata, and has a relay-side cooldown of 5 minutes per install via `_HEARTBEAT_MIN_INTERVAL_S`. It does not write to `request_log` and does not count as schedule/radar/report usage.
- Heartbeat payload metadata is intentionally coarse: app version, OS family/version, arch, requested/effective GUI mode, source mode, diagnostics mode, companion count, matrix count, and matrix online count. Never add raw IPs, raw activation tokens, local paths, API keys, flight history, airport history, logs, report bodies, or companion device IDs to heartbeat payloads.
- Relay stores heartbeat freshness in `install_profiles.last_seen`. Network Admin reads this through redacted `/admin/api/fleet` and `/admin/api/overview` payloads; it shows public install fingerprints/action refs only, never raw install IDs.
- Network Admin routing stays split from the public relay. Public clients use `/v1/*` endpoints such as schedule, radar, airport surface, reports, activation, client check-in, and heartbeat. Operator UI uses Basic-Auth/admin-host-gated `/admin/api/*` read/action endpoints and must remain redacted.
- Fleet "active" means seen within roughly 24 hours from heartbeat, relay usage, client interest, activation token, or activation request timestamps. Treat it as coarse operational presence, not an exact online status.
- Heartbeat hardening test coverage currently lives in `tests/test_relay_beat.py` and `tests/test_heartbeat_relay.py`: local eligibility/debounce, silent client failures, relay cooldown, install-profile writes, malformed install rejection, and "do not log heartbeat to request_log".

### Setup gate
- `SetupGateMiddleware` in `server.py` redirects all routes to `/setup` until `~/.localflight/setup_complete` exists
- Exempt paths: `/setup`, `/api/setup/*`, `/api/airports/search`, `/static`, `/health`, `/ws`
- On first launch, scheduler is deferred. Setup watcher thread polls for `setup_complete` and auto-starts scheduler when detected.
- Native first launch opens a standalone setup window first, not the main shell. It asks for airport/source/provider keys plus the diagnostics/reporting mode, posts `diagnostics_mode` through `/api/setup/complete`, saves it in `AppConfig`, clears stale native API cache, and only then opens the Display shell.
- `/api/setup/reset` deletes the marker — triggers re-run wizard. Button in Settings footer.
- Install identity is deliberately separate from resettable setup state. `storage/install.py` keeps the legacy `~/.localflight/install_id`, writes a versioned `~/.localflight/install_identity.json`, and mirrors it to `~/.localflight_identity.json` so a dev wipe of `~/.localflight` can recover the same install ID without creating a new relay install. `new_install_identity()` is the explicit dev/operator escape hatch and clears the local activation token because old tokens are bound to the old install ID.
- Relay activation is now verify-first. If a local activation token exists, `/api/setup/activate` checks `/v1/client/status` before asking `/v1/activate` for a fresh token. Relay failures are normalized to stable local statuses such as `token_invalid`, `token_bound_elsewhere`, `manual_review`, `rate_limited`, and `relay_unreachable`, so setup UI should not show raw HTTP/JSON errors.
- Relay-side known-install reissues do not count as anonymous new-install network bursts. Unknown new installs from the same network still hit manual review after the configured safety limits, but a reset/reissue for an already-known install remains self-service unless the install was explicitly blocked.

### API call budget
- Local direct-provider budgets are enforced before outbound calls. New code uses SQLite counters in `~/.localflight/api_usage.sqlite` and keeps legacy `~/.localflight/api_usage.json` readable for display/backward compatibility.
- AeroDataBox BYOK default: enabled only when `AERODATABOX_API_KEY` and `LOCALFLIGHT_AERODATABOX_ENABLED=1` are present. API.Market is the default gateway (`LOCALFLIGHT_AERODATABOX_MARKETPLACE=apimarket`); existing RapidAPI subscriptions can use `rapidapi`. Default local monthly unit cap is `LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT=24000`, with daily cap defaulting to `ceil(monthly/30)` unless `LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT` is set. FIDS Tier 2 requests count as 2 units each.
- AviationStack BYOK default: 90 calls/month unless `LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT` is set. Local direct calls are now guarded atomically per request/page.
- Community relay default: 50 relay schedule accesses/month per install
- Community and managed relay-backed installs share airport snapshots on the relay; upstream AeroDataBox units/requests and AviationStack pages are counted separately from per-install accesses and guarded before each upstream call.
- ADS-B Exchange / RapidAPI default: 10,000 calls/month
- Relay schedule admission is cache-first and fail-closed: unknown airports are rejected, windows are bucketed, cheap RPM/new-key limits run before DB-heavy work, provider monthly/daily caps are checked before upstream, and cap exhaustion is handled like an upstream outage so stale cache can serve.
- All env vars read lazily at call time (not module import time) to avoid race with `_load_dotenv()`

### Linear issue tracker
Two separate integrations — do not confuse them:
- **Operator auto-filing** (`sources/web/linear_client.py`): `file_error()` called from `scheduler/runtime.py` on every cycle error. Uses `LINEAR_API_KEY` / `LINEAR_TEAM_ID` env vars pointing at the operator's own Linear workspace. Optional, completely silent, deduplicates per 6h.
- **User/developer report gateway** (`sources/web/bug_reporter.py` + relay `POST /v1/reports`): local app sanitizes report payloads and forwards them to the hosted relay. The relay owns `LINEAR_REPORTER_API_KEY` plus per-platform team IDs as Fly secrets, applies rate limits/dedupe, then files into Linear. Manual reports are always available. First-run setup must ask for diagnostics/reporting mode and save it locally. Automatic crash diagnostics are gated by server `diagnostics_mode`; mobile auto-reporting additionally requires the mobile-local diagnostics choice. Local reports include requested/effective GUI shell context so native GUI, browser/LAN UI, and headless service runs stay distinguishable without creating new Linear routing paths.
- **Public website support forms** (`POST /v1/site/contact`, `POST /v1/site/bug-report`): `site/support/index.html` posts to the public relay. Contact messages route through relay-owned SMTP/mailbox secrets; website bug reports file sanitized Linear issues without requiring a Local Flight install ID. Uploaded logs are text-only, capped, redacted, and embedded as excerpts rather than stored as raw attachments.

### Version
- Single source of truth: `version` field in `pyproject.toml`
- Read at runtime via `importlib.metadata.version("localflight")` with `"0.5.1"` fallback
- Injected as `app_version` Jinja2 global in `server.py` → available in all templates
- Shown in the native footer/brand surfaces and Admin → System card (`v0.5.1`)
- `LocalFlight.spec` reads it from `pyproject.toml` at build time for macOS `CFBundleShortVersionString`

### Auto-update check
- `GET /api/admin/updates` checks GitHub releases API for `tr3y4rch/local-flight`
- 1-hour in-process cache to avoid hammering GitHub
- Admin → System card shows "Up to date" (green) or "vX.Y.Z available ↗" (amber link)

---

### Mobile app: Companion, Remote Companion, and Standalone
- Mobile beta lives in `mobile/` as an iOS-first React Native / Expo app. It is one app with two first-run setup modes: `lan_companion` and `standalone`.
- Companion is still the full paired-server flow. The Python/FastAPI desktop/Pi app remains the server of record; mobile stores the Local Flight server URL with Expo SecureStore and expects a reachable LAN URL, not phone-local `localhost`.
- Companion QR pairing from native/browser Settings is IP-first and fingerprint-bound. Remote Companion adds a short-lived remote QR for relay-linked hosts; mobile stores the grant nested under `lan_companion` and still tries LAN first.
- Companion prefers `GET /api/mobile/summary` for host status/config/budget/update/scheduler/METAR rollup, and still reads `/api/fids`, `/api/fids/detail`, `/api/radar`, `/api/history`, `/api/history/summary`, `/api/admin/companion/checkin`, and `PATCH /api/config`. Remote Companion wraps the same allowlisted requests in AES-GCM envelopes through the relay only after LAN fetch failure.
- Companion listens to `/ws` for `snapshot_updated`, `config_updated`, and `scheduler_restarted` on LAN; when remote event relay is unavailable, it falls back to polling. The mobile UI exposes `LAN`, `REMOTE`, and `OFFLINE` state.
- Companion's main bottom nav is `Board`, `Radar`, `History`, and `Control`. `Control` is the safe-remote-actions surface: host health, saved server, airport/source/cadence access through the config sheet, local airport profiles, scheduler restart, diagnostics visibility, Matrix live controls, setup rerun, and Help & Reports. Help remains an internal/support surface, not a bottom-nav destination.
- Standalone uses the hosted relay directly and does not need a desktop/Pi LAN server. Setup stores `localflight.mobileRelayInstallId`, `localflight.mobileRelayActivationToken`, `localflight.standaloneAirport`, `localflight.mobileSetupState`, and `localflight.mobileDiagnosticsMode` locally.
- Standalone activation calls relay `/v1/activate` with `requested_mode=mobile_standalone`, then reads `/v1/mobile/summary`, `/v1/mobile/fids`, `/v1/mobile/radar`, and `/v1/mobile/metar`. Airport setup uses relay `/v1/airports/search` and `/v1/airports/resolve`.
- Standalone intentionally hides WebSocket, Matrix, Admin, scheduler restart, server URL tools, LAN companion check-in, and server-control panels. Bottom nav is `Board`, `Radar`, `History`, and `Settings`.
- Standalone client policy: FIDS auto-refresh no faster than every 3 hours; radar no faster than every 5 minutes while visible; radar ranges only `1`, `3`, `5`, `10` NM. Relay enforces the same policy so a tampered client cannot burn upstream tokens.
- Standalone History uses `expo-sqlite` in `mobile/src/storage/standaloneHistory.ts`, upserting successful FIDS rows into a deduped local movement table and pruning to 30 days or 1,000 movements. No relay-side per-install flight history is stored in this pass.
- Mobile crash reporting lives in `mobile/src/crash/`. Companion auto-reporting requires both mobile diagnostics and connected-server diagnostics to allow it. Standalone auto-reporting requires the mobile diagnostics choice (`auto` or `auto_logs`) and posts directly to relay `/v1/reports`.
- Current shell still follows the iOS airport-board mockup direction for the live surfaces: Flight Island, departure-airport/live header, UTC/local clock, METAR strip, FIDS tabs, pinned flight, compact rows, and bottom nav.
- Mobile now ships with a longer branded launch overlay that mirrors the desktop splash direction with progress/status messaging, shared brand text, continuous radar sweep, status fade, breathing live dot, and blinking board LED. Key screen actions use light haptics/press-scale feedback where available.
- Validation after this pass: `cd mobile && npm run typecheck && npm run doctor` passed on the Mac/Codex workspace. Full visual verification still belongs on the Mac/Xcode machine via `npm run ios` or `npm run ios:device`.

### Mobile app iconset streamlining status
- Current Mac pass completed the safe icon-registry foundation. `mobile/src/theme/icons.tsx` is now the only companion source file that imports `@expo/vector-icons/MaterialCommunityIcons`; bottom nav and screen-level icons go through `LocalFlightIcon` plus semantic nav/action/tool/status/source/weather/support/setup maps.
- Weather icon selection now lives in the registry and maps server-provided semantic METAR values first, with text heuristics as a fallback. Missing weather uses a neutral unavailable glyph instead of a broken or one-off screen glyph.
- Keep brand assets separate from generic icons. Prefer the existing companion PNG assets for Expo app icon/splash until a deliberate metadata sweep is done. For in-app brand/support surfaces, add or mirror bundled local assets under `mobile/assets/brand/` only if the React Native asset pipeline can load them cleanly; otherwise use the semantic icon wrapper as the safe default. Do not redraw/recolor third-party GitHub or Buy Me a Coffee marks unless using their official provided variants.
- Acceptance check after this pass: `cd mobile && npm run typecheck && npm run doctor` passed, and `rg "MaterialCommunityIcons" mobile/src` shows the expected registry-only import. `npm run ios` / device visual validation still belongs on the Mac/Xcode machine.

## Environment variables (.env)

```
# Community relay / activation
LOCALFLIGHT_ACTIVATION_TOKEN=
LOCALFLIGHT_RELAY_URL=https://relay.beacontools.cc
LOCALFLIGHT_GUI_MODE=native

# BYOK AviationStack (leave blank to use community relay)
AVIATIONSTACK_API_KEY=
LOCALFLIGHT_AVIATIONSTACK_ENABLED=1
LOCALFLIGHT_AVIATIONSTACK_MONTHLY_LIMIT=90
LOCALFLIGHT_RELAY_MONTHLY_LIMIT=50

# BYOK AeroDataBox schedule provider
AERODATABOX_API_KEY=
LOCALFLIGHT_AERODATABOX_MARKETPLACE=apimarket
LOCALFLIGHT_AERODATABOX_ENABLED=0
LOCALFLIGHT_AERODATABOX_MONTHLY_UNITS_LIMIT=24000
LOCALFLIGHT_REAL_SCHEDULE_PROVIDER=auto

OPENSKY_CLIENT_ID=
OPENSKY_CLIENT_SECRET=

RAPIDAPI_KEY=
LOCALFLIGHT_RAPIDAPI_MONTHLY_LIMIT=10000
```

Optional local direct-provider daily caps: `LOCALFLIGHT_AERODATABOX_DAILY_UNITS_LIMIT` and `LOCALFLIGHT_AVIATIONSTACK_DAILY_LIMIT`; both default to `ceil(monthly/30)`.

Relay server env vars (relay/.env / Fly secrets): `RELAY_ADMIN_PASSWORD`, `DB_PATH`, `RELAY_PUBLIC_HOST`, `RELAY_ADMIN_HOST`, `AERODATABOX_API_KEY`, `RELAY_AERODATABOX_MARKETPLACE`, `AVIATIONSTACK_API_KEY`, `RELAY_SCHEDULE_PROVIDER`, `RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT`, `RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT`, `RELAY_AERODATABOX_FIDS_TIER2_UNITS`, `RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT`, `RELAY_AVIATIONSTACK_UPSTREAM_DAILY_LIMIT`, `RELAY_SCHEDULE_STALE_IF_ERROR_HOURS`, `RELAY_SCHEDULE_NETWORK_RPM_LIMIT`, `RELAY_SCHEDULE_INSTALL_RPM_LIMIT`, `RELAY_SCHEDULE_GLOBAL_RPM_LIMIT`, `RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT`, `RELAY_SCHEDULE_NEW_KEYS_GLOBAL_DAILY_LIMIT`, `RELAY_PROVIDER_FAILURE_COOLDOWN_SECONDS`, `RELAY_COMMUNITY_SCHEDULE_LIMIT`, `RELAY_RADAR_MONTHLY_LIMIT`, `RELAY_MANAGED_SCHEDULE_LIMIT`, `RELAY_MANAGED_RADAR_LIMIT`, `RELAY_STANDALONE_SCHEDULE_LIMIT`, `RELAY_STANDALONE_RADAR_LIMIT`, `RELAY_STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS`, `RELAY_STANDALONE_RADAR_MIN_REFRESH_SECONDS`, `RELAY_RADAR_CACHE_SECONDS`, `RELAY_AIRPORT_SURFACE_ENABLED`, `RELAY_AIRPORT_SURFACE_CACHE_HOURS`, `RELAY_AIRPORT_SURFACE_STALE_DAYS`, `RELAY_OVERPASS_URL`, `RELAY_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT`, `RELAY_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT`, `LINEAR_REPORTER_API_KEY`, `LINEAR_TEAM_IOS_ID`, `LINEAR_TEAM_DESKTOP_ID`, `LINEAR_TEAM_SERVER_ID`, `LINEAR_TEAM_RELAY_ID`, `LINEAR_TEAM_DEFAULT_ID`

Standalone relay defaults when not overridden: `RELAY_STANDALONE_SCHEDULE_LIMIT=600`, `RELAY_STANDALONE_RADAR_LIMIT=3000`, `RELAY_STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS=10800`, `RELAY_STANDALONE_RADAR_MIN_REFRESH_SECONDS=300`.

---

## Hosted relay deployment checklist

Use this when moving back to the Windows dev machine and deploying the relay/reporting gateway directly.

### One-time sanity checks
- Work from a clean/current checkout of `https://github.com/tr3y4rch/local-flight`.
- Confirm Fly CLI is installed and authenticated: `fly auth login`
- Confirm the target app exists: `fly status -a localflight-community-relay`
- Relay deploys from the repo root with explicit config/dockerfile paths. Do not deploy from inside `relay/`; the Dockerfile copies `src/localflight`, so the build context must be the repo root.
- Do not put provider or Linear secrets in `.env`, `fly.toml`, GitHub, desktop code, mobile code, or docs. They belong only in Fly secrets / dashboard env.
- Do not publish operator-only relay/admin routes, provider quotas, or Fly secret names in public docs. Public docs may say the hosted relay uses cached shared schedule snapshots and multiple providers.

### Deploy updated relay code

```powershell
fly deploy --remote-only --config relay/fly.toml --dockerfile relay/Dockerfile -a localflight-community-relay
```

If Fly asks which app to use, choose `localflight-community-relay`. The GitHub Actions deploy workflow must use the same repo-root shape:

```yaml
flyctl deploy --remote-only --config relay/fly.toml --dockerfile relay/Dockerfile
```

### Add/update schedule provider secrets

Set these in the Fly dashboard for `localflight-community-relay` or through the CLI. Values are examples for the current paid tiers; keep the actual provider keys only in Fly secrets.

Required/expected schedule-provider secrets:
- `AERODATABOX_API_KEY`
- `RELAY_AERODATABOX_MARKETPLACE=apimarket` for API.Market keys, or `rapidapi` for RapidAPI subscriptions
- `RELAY_SCHEDULE_PROVIDER=auto`
- `RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT=24000`
- `RELAY_AERODATABOX_FIDS_TIER2_UNITS=2`
- `RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT=10000`
- `RELAY_SCHEDULE_STALE_IF_ERROR_HOURS=24`

Optional hardening overrides:
- `RELAY_AERODATABOX_UPSTREAM_DAILY_UNITS_LIMIT` default `ceil(monthly/30)`
- `RELAY_AVIATIONSTACK_UPSTREAM_DAILY_LIMIT` default `ceil(monthly/30)`
- `RELAY_SCHEDULE_NETWORK_RPM_LIMIT=120`
- `RELAY_SCHEDULE_INSTALL_RPM_LIMIT=30`
- `RELAY_SCHEDULE_GLOBAL_RPM_LIMIT=600`
- `RELAY_SCHEDULE_NEW_KEYS_NETWORK_DAILY_LIMIT=20`
- `RELAY_SCHEDULE_NEW_KEYS_GLOBAL_DAILY_LIMIT=200`
- `RELAY_PROVIDER_FAILURE_COOLDOWN_SECONDS=600`
- `RELAY_STANDALONE_SCHEDULE_LIMIT=600`
- `RELAY_STANDALONE_RADAR_LIMIT=3000`
- `RELAY_STANDALONE_SCHEDULE_MIN_REFRESH_SECONDS=10800`
- `RELAY_STANDALONE_RADAR_MIN_REFRESH_SECONDS=300`

PowerShell CLI form:

```powershell
fly secrets set -a localflight-community-relay `
  AERODATABOX_API_KEY="<aerodatabox-api-key>" `
  RELAY_AERODATABOX_MARKETPLACE="apimarket" `
  RELAY_SCHEDULE_PROVIDER="auto" `
  RELAY_AERODATABOX_UPSTREAM_MONTHLY_UNITS_LIMIT="24000" `
  RELAY_AERODATABOX_FIDS_TIER2_UNITS="2" `
  RELAY_AVIATIONSTACK_UPSTREAM_MONTHLY_LIMIT="10000" `
  RELAY_SCHEDULE_STALE_IF_ERROR_HOURS="24"
```

Confirm secret names are present without printing values:

```powershell
fly secrets list -a localflight-community-relay
```

### Add/update Linear reporting secrets

Set these in the Fly dashboard for `localflight-community-relay` or through the CLI. The dashboard path is: app → Secrets / Environment → add secret values → save → restart/redeploy machine if Fly does not do it automatically.

Required report-gateway secrets:
- `LINEAR_REPORTER_API_KEY`
- `LINEAR_TEAM_IOS_ID`
- `LINEAR_TEAM_DESKTOP_ID`
- `LINEAR_TEAM_SERVER_ID`
- `LINEAR_TEAM_RELAY_ID`
- `LINEAR_TEAM_DEFAULT_ID`

PowerShell CLI form:

```powershell
fly secrets set -a localflight-community-relay `
  LINEAR_REPORTER_API_KEY="<linear-api-key>" `
  LINEAR_TEAM_IOS_ID="<ios-team-id>" `
  LINEAR_TEAM_DESKTOP_ID="<desktop-team-id>" `
  LINEAR_TEAM_SERVER_ID="<server-team-id>" `
  LINEAR_TEAM_RELAY_ID="<relay-team-id>" `
  LINEAR_TEAM_DEFAULT_ID="<default-team-id>"
```

PowerShell line-continuation backticks must be the final character on the line; no trailing spaces after them. Confirm the secret names are present with:

```powershell
fly secrets list -a localflight-community-relay
```

Fly secrets are injected as runtime environment variables at machine boot. `fly secrets set` normally restarts/updates Machines; if secrets were staged or added via dashboard without a restart, redeploy from the repo root:

```powershell
fly deploy --remote-only --config relay/fly.toml --dockerfile relay/Dockerfile -a localflight-community-relay
```

### Verify relay health

```powershell
curl.exe -I --max-time 20 https://relay.beacontools.cc/health
```

Expected: HTTP `200`.

Then smoke a fresh schedule lane. If an old cached lane already exists, either choose another known airport/window bucket or clear shared schedule snapshots through the operator maintenance flow before testing provider selection.

```powershell
$installId = [guid]::NewGuid().ToString()
$uri = "https://relay.beacontools.cc/v1/schedule?airport_iata=ZRH&timezone=Europe%2FZurich&display_grace_minutes=120&display_horizon_hours=24&refresh_seconds=3600&install_id=$installId&app_version=0.2.7-smoke&os_family=windows&requested_gui=native&effective_gui=native&source_mode=real&diagnostics_mode=manual"
$schedule = Invoke-RestMethod -Method Get -Uri $uri
$schedule.provider
$schedule.cache_state
$schedule.meta.schedule_provider_mode
$schedule.meta.provider_record_counts
```

Expected after the AeroDataBox relay build is live: provider is `aerodatabox` or `aerodatabox+aviationstack`, `meta.schedule_provider_mode` is `auto`, and `meta.provider_record_counts` is present. If a cache miss returns `provider=aviationstack` with `planner_version=fair-v3` and no provider-fusion meta, provider-fusion validation failed and the relay image/config needs investigation.

Optional synthetic report smoke test after secrets are live:

```powershell
$body = @{
  report_type = "manual"
  origin = "desktop"
  install_id = "00000000-0000-4000-8000-000000000001"
  install_fingerprint = "11e594f48195"
  title = "Relay smoke test"
  description = "Safe test from deployment checklist"
  app_version = "0.2.7"
  platform = "Windows"
  diagnostics_mode = "manual"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "https://relay.beacontools.cc/v1/reports" `
  -ContentType "application/json" `
  -Body $body
```

Expected success shape: `{ ok: true, team: "desktop", deduped: false }`. Re-running the same test within 30 minutes should return `deduped: true` and should not create another Linear issue.

### After successful report test
- Rotate/revoke the old Linear key that was previously embedded in shipped code.
- Submit one real desktop `/feedback` report from the local app and confirm it lands in the Desktop Linear team.
- Trigger or simulate one diagnostics-gated crash only after confirming diagnostics mode is `auto` or `auto_logs`.
- Keep `sources/web/linear_client.py` unchanged for optional operator-owned `LINEAR_API_KEY` / `LINEAR_TEAM_ID`; it is separate from developer/user reporting.

---

## AppConfig schema

```python
airport_iata: str = "ZRH"
airport_icao: str = "LSZH"
refresh_seconds: int = 3600
display_name: str = "Local Flight"
theme: str = "dark"
source: str = "real"          # "real" | "virtual"
timezone: str = "Europe/Zurich"
skin: str = "standard"        # standard | technical | neon | cyan | crt
display_outputs: List[str] = ["web"]  # web | matrix | hdmi
diagnostics_mode: str = "unset"  # unset | manual | auto | auto_logs
web_row_limit: int = 20
web_rotation_seconds: int = 8
display_grace_minutes: int = 30
display_horizon_hours: int = 12
radar_surface_enabled: bool = False
```

Config lives at `~/.localflight/config.json`

---

## Key API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/config` | Current server config |
| `PATCH /api/config` | Update config fields; broadcasts `config_updated`; restarts scheduler for airport/source/interval changes |
| `GET /api/fids` | JSON FIDS rows |
| `GET /api/fids/detail` | Per-callsign detail — live position + 7-day history + additive `flight-intel-v1` evidence model |
| `GET /api/radar` | Aircraft positions plus normalized safe display fields for real/VATSIM blips |
| `GET /api/radar/surface` | Airport surface geometry for the configured airport, capped to 1-5 NM; relay-cached OSM when available, labeled local estimate when not |
| `GET /api/metar` | Decoded + raw METAR plus Local Flight semantic weather mood/icon fields |
| `GET /api/history` | Recent flights from SQLite; supports `hours`, `direction`, `status`, `callsign`, `airline_iata`, and `limit` filters |
| `GET /api/history/flight` | Callsign history |
| `GET /api/history/summary` | Shared native/browser History movement analytics: delay buckets, status mix, airline delay quotas, routes, daily/hourly volume, aircraft stats, raw-observation diagnostics |
| `GET /api/history/stats` | DB size, row count |
| `GET /api/admin/system` | Uptime, memory, CPU, version |
| `GET /api/admin/budget` | API call budgets |
| `GET /api/admin/requests` | Anonymized local traffic log summary (only when network tools are enabled) |
| `GET /api/admin/connections` | WS count + device pings |
| `GET /api/admin/updates` | GitHub release update check (1h cache) |
| `GET /api/admin/scheduler` | Scheduler thread status |
| `POST /api/admin/scheduler/restart` | Stop sleeping scheduler loop, reload config/env, start fresh cycle, broadcast `scheduler_restarted` |
| `POST /api/feedback` | Submit manual bug report `{title, description, client_context}` — sanitizes locally, then forwards to relay `/v1/reports` |
| `POST /api/feedback/crash` | Automatic mobile/server crash route; blocked unless diagnostics settings allow it |
| `POST /api/matrix/v2/devices/checkin` | Matrix device check-in with assigned config, geometry, renderer revision, and heartbeat metadata |
| `POST /api/admin/ping` | Legacy device ping compatibility route |
| `POST /api/setup/complete` | Save setup, write .env, mark complete |
| `POST /api/setup/reset` | Delete setup_complete marker → re-run wizard |
| `POST /api/setup/test-aviationstack` | Test AviationStack key (body) without saving |
| `POST /api/setup/test-rapidapi` | Test RapidAPI key (body) without saving |
| `GET /api/setup/client-info` | Machine fingerprint, relay URL, token presence, managed status |
| `POST /api/setup/activate` | Store managed activation token |
| `POST /api/setup/client-status` | Check relay client status |
| `POST /api/setup/request-activation` | Request activation from relay |
| `POST /api/setup/request-activation/status` | Poll activation request status |
| `POST /api/setup/test-activation` | Test an activation token without saving |
| `POST /api/admin/companion/checkin` | Mobile Companion check-in (companionId, platform, appVersion) |
| `DELETE /api/admin/companion` | Clear this server's remembered mobile companion check-ins |
| `POST /api/quit` | Graceful shutdown (terminates browser proc + os._exit) |
| `WS /ws` | WebSocket push endpoint |

Public relay endpoints used by clients and the public site: `GET /v1/schedule`, `GET /v1/radar`, `GET /v1/airport-surface`, `POST /v1/reports`, `POST /v1/site/contact`, `POST /v1/site/bug-report`, `POST /v1/activate`, `GET /v1/client/status`, `POST /v1/client/checkin`, and `POST /v1/heartbeat`.

Mobile Standalone relay endpoints: `GET /v1/airports/search`, `GET /v1/airports/resolve`, `GET /v1/mobile/summary`, `GET /v1/mobile/fids`, `GET /v1/mobile/radar`, and `GET /v1/mobile/metar`. They require UUID `install_id`, valid `activation_token`, `app_version`, and `client_kind=mobile_standalone`; radar accepts only `1`, `3`, `5`, and `10` NM.

Internal relay admin JSON endpoints, Basic Auth and admin-surface gated only: `GET /admin/api/overview`, `/admin/api/usage`, `/admin/api/fleet`, `/admin/api/schedules`, `/admin/api/surfaces`, `/admin/api/activations`, `/admin/api/reports`. Read payloads must stay redacted: no raw provider keys, raw activation tokens, report contexts/log tails, or raw install IDs. Operator write endpoints live under `/admin/api/providers/*`, `/admin/api/activation/*`, `/admin/api/counters/*`, `/admin/api/install/access`, and `/admin/api/maintenance/clean-trial`; token/install actions use opaque `action_ref` values from the redacted read payloads while request actions use `request_id`, and the relay resolves private hashes/IDs server-side.

---

## Building (PyInstaller)

```bash
python build.py           # generate icons + build + zip
python build.py --clean   # wipe dist/ and build/ first
python build.py --clean --installer   # macOS signed pkg / Windows installer
```

Desktop release packaging now requires PySide6 and `LocalFlight.spec` explicitly collects PySide6 plus `localflight.native.*`, so Windows/macOS artifacts are native-GUI capable instead of depending on Chrome/Edge/Chromium.
End-user desktop launchers should not foreground a Python console: `LocalFlight.spec` keeps PyInstaller `console=False`, the macOS app bundles use a real `CFBundleExecutable=LocalFlight`, the macOS source app redirects bootstrap stdout/stderr to `~/.localflight/logs/source_app_bootstrap_*.log`, and the Windows source installer desktop shortcut targets `.venv\Scripts\pythonw.exe -m localflight` directly when available. Keep console output in the explicit dev launchers only.

Output:
- **Windows:** `dist/LocalFlight-windows.zip` + `.sha256` — unzip, double-click `LocalFlight.exe`
- **macOS:** `dist/LocalFlight.app` as the build intermediate plus `dist/LocalFlight-<version>-macos.pkg` + `.sha256` from `--installer` — upload the pkg; users double-click the installer and launch **Local Flight** from Applications

Optional code signing via env vars:
- Windows: `SIGNTOOL_CERT` (path to .pfx) + `SIGNTOOL_PASS`
- macOS app zip/dev build: `CODESIGN_IDENTITY` (Developer ID Application string) + `NOTARIZE_PROFILE` (notarytool keychain profile)
- macOS public pkg build: `CODESIGN_IDENTITY` (Developer ID Application string) + `PKG_SIGN_IDENTITY` (Developer ID Installer string) + `NOTARIZE_PROFILE` (notarytool keychain profile)

Without signing: Windows shows SmartScreen "Unknown publisher"; macOS requires right-click → Open on first launch.
The macOS `.pkg` path intentionally fails closed when signing/notarization credentials are missing so an unsigned scary installer is not published by accident.

Release build notes:
- Build Windows artifacts on Windows: `python build.py --clean` → attach `LocalFlight-windows.zip` and `LocalFlight-windows.zip.sha256`.
- Build macOS artifacts on macOS: `python build.py --clean --installer` → attach `LocalFlight-<version>-macos.pkg` and `.sha256`.
- Build the Pi source installer bundle on any machine with git available: `python scripts/package_pi_source.py` → attach `LocalFlight-pi-source-<version>.zip` and `.sha256`.
- `installers/windows/install.ps1` and `installers/macos/install.sh` are source-checkout installers with explicit display-mode choices; release users should prefer the packaged artifacts.

---

## Hardware targets

| Device | Role | Status |
|---|---|---|
| Windows PC | Dev machine | ✅ Running |
| Raspberry Pi 5 | Production server | 🔜 Installer ready, awaiting hardware |
| Pimoroni Interstate 75 W (RP2350) | LED matrix 256×64 | 🔜 MicroPython client written |
| RTL-SDR USB dongle | ADS-B receiver for Pi | 🔜 dump1090 client written |

### LED matrix client (`sources/matrix/client.py`)
- MicroPython, reads live Matrix V2 config/feed over WiFi and uses `/api/config` only for shared app/clock context
- Button A = departures, Button B = arrivals, A+B = force refresh
- RGB LED: green=ok, blue=fetching, amber=no data, red=no WiFi
- Calls `/api/matrix/v2/devices/checkin` on boot and periodically with actual/configured geometry, assigned config, and renderer revision
- Current board script marker is `matrix-display-contract-v4`; existing boards need a regenerated `main.py` after renderer/layout/clock fixes

### ADS-B on Pi
```bash
sudo apt install dump1090-fa
sudo systemctl enable dump1090-fa
```
Swap `enrich_flights_with_adsbexchange` → `enrich_flights_with_adsb` in `jobs.py`

---

## Running locally

```bash
# Windows native-first dev launcher
.\start.bat

# Windows operator Network Admin
.\start_network.bat

# macOS
./installers/macos/start.sh

# Manual (any platform)
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
cd src
python -m localflight

# Mobile app (Mac/Xcode machine)
cd mobile
npm install
npx expo install --fix
npm run ios
```

---

## Current handoff for macOS / dev machine

- **macOS handoff focus (2026-05-24 / 0.2.7):** get the Mac onto the exact same source state as this workspace before running the installer or packaging. The current source must include the Beacon Tools public site/docs refresh, mobile/support/network/privacy-choices site pages, default relay `https://relay.beacontools.cc`, mobile Standalone, Android local dev docs, Matrix integrity work, History movement hardening, AeroDataBox/AviationStack fusion, native/browser polish, macOS icon/package tooling, and the `assets/previews/` screenshot tree. If the current workspace still has uncommitted/unpushed native FIDS, radar, Matrix, Settings, installer, relay, mobile, assets, or docs changes, `git pull` on macOS will not see them. Push the branch/commit first, or transfer an explicit patch bundle; otherwise the Mac installer can rebuild an old app with missing Beacon links, wrong relay defaults, missing FIDS details, missing radar ground/context drawings, stale Matrix/settings screens, stale previews, or stale docs.
- **Stale Mac artifact warning:** do not trust an existing `~/Applications/LocalFlight.app`, old `.venv`, old `dist/LocalFlight.app`, or a previous editable install when validating current UI. If the Mac shows old FIDS behavior, no radar ground/context drawing, or old Settings layout, stop and confirm the Mac `git rev-parse --short HEAD` matches the expected Windows/current branch before debugging UI code.
- Start the Mac session with:
  ```bash
  git pull --ff-only
  git rev-parse --short HEAD
  git status --short
  rm -rf dist build ~/Applications/LocalFlight.app
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install -e ".[native]"
  python -m compileall -q src relay installers scripts tests
  python -m pytest tests -q
  ```
- Native GUI is the recommended primary desktop shell now. On macOS, test `LOCALFLIGHT_GUI_MODE=native python -m localflight` or `./installers/macos/start.sh`; browser mode remains supported for LAN/browser display validation via `LOCALFLIGHT_GUI_MODE=browser`. The native window title should be `Local Flight`, not `Local Flight Native`.
- Native first-run setup is intentionally a standalone guided window before the main Display shell. It must keep the Diagnostics step, save `diagnostics_mode` through `/api/setup/complete`, preload the hosted relay root `https://relay.beacontools.cc`, and avoid exposing `/v1/flights` to users.
- Latest native/browser/mobile polish to carry forward on Mac: setup/settings are dashboard-card based, the native shell uses the current grouped navbar/footer icon layout, FIDS displays city/country titles with passenger-friendly weather, FIDS and Radar details consume the shared current-source intelligence model, LAN radar matches the Qt layering/status behavior, LAN browser Settings matches the Qt disclosure-folder order and includes Pair Mobile QR/manual pairing, History now shares the browser/native `/api/history/summary` analytics contract for filters, KPIs, delay buckets, status mix, airline delay quotas, route/aircraft stats, daily/hourly volume, and sortable recent rows, Matrix has board-mirror preview truth, v4 renderer/geometry warnings, live settings parity, local-time clock fixes, full-width wide-board layout, stable Matrix flight labels/weather icons, split-flap/typewriter/cascade animation parity, real-only gate display, and VATSIM gate suppression, and the bundled/public docs point first to Beacon Tools. Focused verification after the Beacon relay/default/docs pass: relay/native suite `392 passed`, doc/native slice `287 passed`, compileall passed, mobile typecheck passed, and `git diff --check` passed. The Beacon mobile/trust site pass added `/local-flight/mobile/`, `/support/`, `/network/`, and `/privacy/choices/`; local/static/Cloudflare checks passed. After Matrix v4 renderer/live-settings/local-clock/web-preview hardening, focused Matrix checks passed and the full Windows/Codex suite returned `432 passed`; rerun full tests on the final release packaging source if anything behavior-facing changes.
- Native UI freshness checks on Mac after install/build:
  - FIDS must show city/country titles, passenger-friendly weather, airport-local row time labels, and the current styled/detail behavior, not the old host-clock/debug-table layout.
  - Radar must expose the current ground/context drawing path and surface-aware rendering; if the canvas lacks the current ground layer entirely, the Mac app is stale.
  - Matrix must show panel-preset choices, live preview feedback, compact weather header behavior, and real-only gate display controls; if it looks like the old long technical form, the Mac app is stale.
  - Settings must show the current dashboard-card/user-facing sections and display-mode wording; if it looks like the old crowded/dev Settings page, the Mac app is stale.
  - LAN browser Settings must show collapsed Outputs & Radar, Profiles, Pair Mobile, Advanced board timing, Maintenance, Relay details, and Diagnostics & Docs folders; Pair Mobile must expose QR/manual URL/fingerprint/copy/reset controls.
  - The macOS source installer should be run as `bash installers/macos/install.sh --display native` after the source is verified current; release users should use the signed/notarized `.pkg`, not an older source-built app in `~/Applications`.
- macOS local/dev app repack runbook:
  ```bash
  python build.py --clean
  test -d dist/LocalFlight.app
  test -f dist/LocalFlight-macos.zip
  (cd dist && shasum -a 256 -c LocalFlight-macos.zip.sha256)
  codesign --verify --deep --strict dist/LocalFlight.app
  ```
- macOS public signed `.pkg` runbook, only after Apple Developer ID credentials are installed:
  ```bash
  export CODESIGN_IDENTITY="Developer ID Application: ..."
  export PKG_SIGN_IDENTITY="Developer ID Installer: ..."
  export NOTARIZE_PROFILE="localflight-notary"
  python build.py --clean --installer
  test -d dist/LocalFlight.app
  test -f dist/LocalFlight-0.5.1-macos.pkg
  shasum -a 256 -c dist/LocalFlight-0.5.1-macos.pkg.sha256
  pkgutil --check-signature dist/LocalFlight-0.5.1-macos.pkg
  xcrun stapler validate dist/LocalFlight-0.5.1-macos.pkg
  ```
- The current Pi source release in `dist/` was rebuilt after the Beacon Tools docs/relay-default commits. The Pi bundle should continue to exclude `AGENTS.md`, `CLAUDE.md`, and `DEV_README.md` on every rebuild.
- Mobile continuation belongs on the Mac/Xcode/Android Studio machine. First run `cd mobile && npm install && npm run verify && npm run a11y && npx expo config --type public`; confirm public Expo config still shows iOS bundle ID `cc.beacontools.localflight`, iOS build number `1`, Android package `cc.beacontools.localflight`, Android version code `1`, and scheme `localflight`. Then run simulator/device smoke with `npm run ios` or `npm run ios:device`; Android local development builds are supported through `npm run android` / `npm run android:device` after Android SDK setup. Companion should prefer the desktop/Pi LAN IP or the native/browser Settings QR; `http://localflight.local:8000` is only a fallback when exactly one Local Flight server is on the LAN. Do not use phone-local `localhost`. Remote Companion smoke must pair on LAN, block LAN, verify `REMOTE` for Board/Radar/History/Control, revoke, and confirm access stops. Standalone should verify airport search, activation, FIDS, Radar, local History, Settings, and direct relay reporting without a LAN server.
- Mobile store-track continuation on macOS: create/register the Apple bundle ID and App Store Connect app for `cc.beacontools.localflight`, create the Google Play app with package `cc.beacontools.localflight`, keep both first store counters at `1`, and use Standalone as the reviewer path so review does not require a desktop/Pi host. Build/submit only after local smoke: `npx eas build -p ios --profile beta`, `npx eas submit -p ios --profile beta`, `npx eas build -p android --profile beta`, and `npx eas submit -p android --profile beta`. Keep support tips/IAP disabled in this beta pass even though dormant product IDs now use the Beacon prefix.
- Mobile real-device store smoke checklist: fresh Standalone setup, Companion manual URL and QR pairing, Remote Companion LAN-first/remote fallback/revoke proof, camera-denied path, iOS local-network-denied path, relay offline/error path, FIDS, Radar, History, Matrix where paired, Settings, manual report/support flow, large text, reduced motion, and readable contrast. Do not widen beyond TestFlight internal / Play internal testing until these pass on real devices.
- Keep public/internal separation intact during the Mac pass: public docs may describe the native privacy-first GUI, public relay behavior, mobile trust pages, and user reporting, but should not expose operator Fly secrets, `DEV_README.md`, `AGENTS.md`, raw relay admin API paths, or admin runbooks. The public `/network/` page may identify `https://network.beacontools.cc/admin` as operator-only/admin-separated.
- Active desktop/server version is `0.5.1`: `pyproject.toml`, runtime fallbacks, bundled release notes, docs, and mobile metadata should all agree unless we deliberately split mobile later.
- Preliminary `0.2.8` notes are historical and folded into `0.5.1`. Keep `docs/release-notes-0.5.1.md` as the public release summary.
- Community relay root is now `https://relay.beacontools.cc` after Beacon Tools DNS and Fly TLS verification. `network.beacontools.cc` is the operator admin host, and the Fly.io root remains accepted for existing installs. The client derives `/v1/schedule`, `/v1/radar`, `/v1/airport-surface`, `/v1/reports`, and activation routes internally; `/v1/flights` is raw-provider debug only.
- Relay admin panel: prefer Fly dashboard/CLI or `fly ssh console`. The local `start_network.bat` helper is operator-only and gitignored. Public admin access is optional and must stay password-protected; do not publish operator-only entrypoints in public docs.
- Chrome-free GUI foundation is now native-first by default: blank/invalid `LOCALFLIGHT_GUI_MODE` resolves to `native`, `platform/gui_launcher.py` verifies PySide6/Qt before native launch, display-attached Pi/Linux can use native fullscreen when installed through `--native-kiosk`, and browser/kiosk mode remains a supported LAN/browser display path for users who prefer or need it. Source installers now expose the display choice directly: Windows `install.ps1 -DisplayMode Native|Browser|Headless`, macOS `install.sh --display native|browser|headless`, and Pi `install.sh` prompts when no flag is passed while preserving `--headless`, `--native-kiosk`, and `--kiosk`. The native client now mirrors the browser/LAN UI structure with a top nav and user pages, loads the shared SVG splash/brand/preview media, embeds the public README/privacy/changelog reader inside Settings, has native setup/matrix/logs/traffic/report controls wired to declared local routes, connects to local `/ws` via QtWebSockets, and includes a required first-run Diagnostics step that saves `diagnostics_mode` through `/api/setup/complete` before the Display shell opens. Its design layer maps the same dark/light theme plus standard/technical/neon/cyan/crt skins into Qt styling and native canvas painters, so FIDS/Radar/Matrix no longer drift into a single debug palette. Native local API calls use a short TTL cache for duplicate-safe GET routes, mutate actions clear that cache, hidden canvases pause animation timers, and active-page polling is intentionally lighter than the browser UI. Network Admin remains a separate operator-only Qt shell backed by styled `/admin/api/*` relay read/action endpoints.
- Fly deployment: one warm machine in `fra`, one SQLite volume (`relay_data`), host-based public/admin gating in `relay/main.py`. Shared-schedule relay deploys must use the repo-root command `fly deploy --config relay/fly.toml --dockerfile relay/Dockerfile --remote-only -a localflight-community-relay` so the image includes `src/localflight`.
- AeroDataBox relay handoff: local code and tests now support AeroDataBox primary schedule, AviationStack sparse fill/fallback, hard upstream caps, provider source caches, stale merged cache serving, and web/Qt canonical FIDS compilation. The Fly relay was redeployed on 2026-05-22 with Beacon host config; `/health` and `/` on `https://relay.beacontools.cc` report `public_host=relay.beacontools.cc` and `admin_host=network.beacontools.cc`, and `/admin` on `https://network.beacontools.cc` returns the expected Basic Auth challenge. Before release, still smoke a fresh schedule lane and confirm it returns `provider=aerodatabox` or `aerodatabox+aviationstack` plus `meta.schedule_provider_mode=auto`.
- Mobile Expo validation after the private-beta identity pass is green on the Windows/Codex workspace: `npm run verify`, `npm run a11y`, and `npx expo config --type public` passed after adding the tracked Metro config and fixing the Windows path handling in the widget snapshot contract script. Simulator/device validation and EAS cloud builds remain pending for macOS.
- Desktop resume on Windows: run `.\start.bat`, confirm Community setup preloads the hosted relay URL, then verify FIDS/radar/admin against the live relay contract.
- Release resume: Windows and Pi artifacts have been rebuilt after the mobile Standalone relay work, Beacon Tools domain cutover, support forms, Matrix v4 polish, and docs sweep. macOS local/dev `.app` and zip were rebuilt on 2026-05-24 with checksum `23d0e8157a334187589ca8cac96715284ce1524c320e1c668d6142969a215c1e`; the public signed/notarized `.pkg` remains blocked until Apple Developer ID credentials are available.
- Cloudflare site deploy resume: `beacontools.cc` is served by the Cloudflare Worker + Assets config in `wrangler.jsonc`. A dashboard `.dev` preview can be current while production remains stale; use a real `wrangler deploy` from this repo for production updates.
- Windows/Pi release installer policy: Windows source installs are native Qt first unless `-DisplayMode Browser|Headless` is selected and always write a client-only `.env`; Pi installs default/prompt to headless, write `LOCALFLIGHT_GUI_MODE=native` only for `--native-kiosk`, and keep the backend service forced headless while the user-session Qt service uses `LOCALFLIGHT_NATIVE_FULLSCREEN=1` plus `LOCALFLIGHT_NATIVE_UI_ONLY=1`. `--kiosk` starts only the Chromium browser display service while the Python app stays headless.
- `scripts/package_pi_source.py` now excludes internal handoff-only files (`AGENTS.md`, `CLAUDE.md`, `DEV_README.md`) from the Pi source zip even if they are tracked locally, and includes non-ignored local additions so pre-release hardware bundles do not miss newly added modules before commit.
- Settings now split install/relay state, flight setup, app controls, and diagnostics/resources into clearer sections; the community relay card now reports active relay usage truthfully, and the docs buttons open bundled local files through `/docs/readme`, `/docs/install`, `/docs/display-modes`, `/docs/privacy`, and `/docs/changelog`.
- macOS packaging now has two paths: `python build.py --clean` for local/dev `.app` + zip testing, and `python build.py --clean --installer` for the public signed/notarized `.pkg`. The `.pkg` path verifies `dist/LocalFlight.app`, `dist/LocalFlight-0.5.1-macos.pkg`, and `.sha256`, then needs a native app smoke for latest History/Matrix/Settings/FIDS/Radar behavior. The `.pkg` build intentionally fails without Developer ID Application, Developer ID Installer, and notarytool credentials.
- Mobile package metadata is now aligned to the repo `0.5.1` store-proof line. Independent mobile appearance, landscape display behavior, responsive radar, and pinch zoom are implemented in code. Matrix runtime/editor code still exists for Companion but is not part of Standalone.
- Mobile IA now splits by setup mode: Companion main nav is `Board/Radar/History/Control` with Help & Reports inside Control; Standalone main nav is `Board/Radar/History/Settings`. The phone-side product goal is quick glance/control for Companion and a simplified rate-limited board for Standalone.
- Desktop flight-detail enrichment pass started first: `/api/fids/detail` now returns richer stored snapshot metadata for live track/source coverage without new external calls, and the desktop FIDS drawer renders operations/aircraft, source confidence/freshness, and position fields more clearly.
- VATSIM detail completeness pass keeps useful filed-plan fields in canonical snapshots: flight rules, planned route, cruise altitude/TAS, planned departure/arrival, enroute time, alternate, and assigned transponder. Intentionally does not store pilot names/CIDs.
- VATSIM privacy rule is explicit: use virtual-network data as flight information only. Do not store/display pilot names, controller names, CIDs/account IDs, server names, or other person-identifying VATSIM fields; callsign, aircraft, filed route/plan, airport/timing data, and aircraft position are okay.
- Desktop FIDS detail drawer now has real vs virtual modes: real flights show airport operations/aircraft/source freshness, while VATSIM flights show virtual flight plan/network/aircraft track labels and suppress real-world-only emphasis.
- Mobile detail communication is mode-specific: Companion calls the paired server's `/api/fids/detail` and never calls AviationStack, ADS-B Exchange, RapidAPI, or provider APIs directly. Remote Companion wraps the same allowlisted server calls in encrypted relay envelopes. Standalone does not have full detail parity yet; it talks to the hosted relay's mobile endpoints, not raw provider APIs.
- Mobile automatic diagnostics now includes critical detail communication failures (`5xx` or malformed JSON) through diagnostics-gated `/api/feedback/crash`; feature-specific reports keep companion identity, app version, device type, and server URL in the client context. Mobile also has its own SecureStore diagnostics choice, so auto-reporting requires both mobile and server consent.
- Linear developer reporting now goes through relay `POST /v1/reports`; no developer Linear API key/team ID is shipped in the packaged desktop or companion app. Relay secrets required: `LINEAR_REPORTER_API_KEY`, `LINEAR_TEAM_IOS_ID`, `LINEAR_TEAM_DESKTOP_ID`, `LINEAR_TEAM_SERVER_ID`, `LINEAR_TEAM_RELAY_ID`, and `LINEAR_TEAM_DEFAULT_ID`.
- Beacon Tools public contact forms now use `POST /v1/site/contact` plus relay SMTP secrets (`RELAY_CONTACT_SMTP_HOST`, `RELAY_CONTACT_SMTP_PORT`, `RELAY_CONTACT_SMTP_USERNAME`, `RELAY_CONTACT_SMTP_PASSWORD`, `RELAY_CONTACT_FROM`, `RELAY_CONTACT_TO_GENERAL`, `RELAY_CONTACT_TO_PRIVACY`) and public bug reports use `POST /v1/site/bug-report` into the existing Linear reporter secrets. Short deployed aliases (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_SECURITY`, `MAIL_FROM`, `MAIL_TO`, `PRIVACY_TO`) are accepted by the relay as compatibility fallbacks, but prefer the explicit `RELAY_CONTACT_*` names for new setup.
- Security sweep hardening is now staged in code: relay community schedule/radar access has network/global daily caps, Fly client IP handling no longer trusts spoofable `X-Forwarded-For`, admin Basic auth has failed-login throttling, local setup relay URLs are validated before server-side calls, and browser cross-origin local mutations are blocked.
- Mobile structure refactor is complete enough for handoff: `App.tsx` is a provider entrypoint, `src/app/AppShell.tsx` coordinates state/refresh, pure helpers live in `src/domain/`, stateful behavior in `src/hooks/`, and screens/sheets in `src/screens/AppScreens.tsx`.
- Mobile validation: `npm run typecheck && npm run doctor` passes on the Mac/Codex workspace after SDK 55 patch alignment (`expo ~55.0.24`, `expo-secure-store ~55.0.14`, `expo-splash-screen ~55.0.21`) and adding `expo-crypto` / `expo-sqlite`.
- Mobile resume on Mac/Xcode: run `npm run ios` or `npm run ios:device` and manually verify both first-run paths. Expo Go may reject SDK 55 depending on installed Expo Go; simulator/dev build is the safer path.
- Windows-side AviationStack reliability pass is now documented in public/internal docs. Important: the local board/filter bug is fixed, but some live airports can still show sparse future departures because AviationStack itself does not return enough near-term rows even after fair paging plus undated rescue. Current observed example: `ZRH` on `2026-05-01`.
- Sparse-board UX fallback is now active on the client: if a real-data lane has no rows inside the live window, the board shows the nearest available real flights instead of an empty departures page. Current live local check after the patch: `/api/fids?view=departures` returned `20` rows again.
- Verification after the `0.2.7` native shell/FIDS polish, AeroDataBox codeshare hardening, Matrix display-integrity merge, docs sweep, and Windows/Pi repack was green on that Windows workspace. A later Matrix v4 renderer/live-settings/local-clock/web-preview sweep superseded that full-suite count with `432 passed`; the final Windows/Codex pass rebuilt Windows and Pi again after Beacon/domain/docs/support-form changes. macOS local/dev `.app` now exists; public `.pkg` remains the missing DAU macOS artifact until Developer ID signing/notarization is available.

## What was done in the latest session (v0.2.7 — Claude UI rescue + FIDS/mobile polish)

> Dated 2026-05-16. This pass recovered UI/UX work that had landed in the
> older `/Users/philipp/Local-Flight/local-flight` checkout and safely ported it
> into the current `/Applications/local-flight` working tree. The important bit:
> do not wholesale copy the older mobile files forward, because that checkout
> predates the newer Standalone relay/client work.

- **Recovered old-path Claude work** — the current repo was clean while the older checkout had pending Qt FIDS painter, mobile launch/interactions, and macOS launcher changes. The safe patch pieces were merged into the real working tree; conflict-prone mobile files were kept on the current Standalone-aware implementation and then selectively polished.
- **Native FIDS painter polish** — `src/localflight/native/pages/fids.py` and `fids_styles.py` now make Classic/PAX/VATSIM/Nerd visibly different through row height, row gaps, font families, responsive column weights/hide thresholds, header chrome, row chrome, status chip shape, and palette overlays.
- **Mobile launch and interaction polish** — `mobile/src/components/LaunchOverlay.tsx`, `mobile/src/hooks/useLaunchOverlay.ts`, and `mobile/src/screens/AppScreens.tsx` gained the shared brand wordmark/kicker, continuous radar sweep, status text fade, breathing status dot, blinking board LED, haptics, press-scale feedback, animated weather icon swaps, and pinned-flight live glow.
- **macOS dev launcher** — root `start.command` mirrors the Windows source launcher shape for quick repo-checkout launches while keeping installer-managed launchers under `installers/macos/`.
- **Docs** — README, install guide, mobile README, release notes, changelog, and this handoff now describe the recovered visual polish without exposing secrets or operator-only relay details.
- **Validation** — final Mac/Codex validation for this merged tree is recorded in the current handoff snapshot above.

## Previous session (v0.2.7 — mobile Standalone + docs)

> Dated 2026-05-16. This pass turns the iOS-first mobile app into a two-mode
> product: Companion for paired desktop/Pi installs, and Standalone for a
> simplified relay-backed phone board. Public docs were rewritten to explain the
> split in DAU-friendly language while keeping operator-only relay details in
> handoff docs.

- **Relay Standalone support** — `relay/main.py` now supports mobile standalone activation (`requested_mode=mobile_standalone`), standalone default limits, client kind/device metadata, airport search/resolve, mobile summary/FIDS/radar/METAR endpoints, 3-hour standalone schedule policy, 5-minute standalone radar cache, and `1/3/5/10` NM radar enforcement. Cached standalone radar hits authenticate before serving.
- **Mobile Standalone client** — `mobile/src/api/standalone.ts` handles relay activation, summary, FIDS, radar, METAR, manual reports, and crash reports. `mobile/src/storage/settings.ts` persists setup mode, relay install ID, activation token, standalone airport, and diagnostics mode. `mobile/src/storage/standaloneHistory.ts` upserts standalone FIDS rows into local movement history with Expo SQLite and prunes to 30 days / 1,000 movements.
- **Mobile shell split** — `AppShell` chooses Companion or Standalone data paths by setup mode. Companion keeps WebSocket on LAN, local config/control, Matrix/admin-adjacent tools, server-mediated reports, and encrypted Remote Companion fallback when paired. Standalone hides Matrix/Admin/server controls/WebSocket, uses Board/Radar/History/Settings, enforces the mobile cadence locally, and clears standalone token/airport/history on setup reset.
- **Reporting** — Companion auto reports still require mobile + server diagnostics consent. Standalone manual/crash reports go directly to relay `/v1/reports`, and automatic reports require only mobile `auto` / `auto_logs` consent because there is no paired local server.
- **Docs** — README, install guide, display modes, Privacy, Mobile README, release notes, changelog, and `AGENTS.md` now explain Companion, Remote Companion fallback, and Standalone clearly. Public docs avoid Fly secret names and admin-only paths; operator env/endpoint details stay in `AGENTS.md`.
- **Verification** — this historical mobile Standalone pass originally ended green; the later Matrix v4 Windows release-candidate sweep supersedes its old pytest count with `.venv\Scripts\python.exe -m pytest tests -q` returning `432 passed`. `cd mobile && npm run typecheck && npm run doctor` had passed with Expo Doctor `18/18` during the mobile sweep; rerun on the Mac/Xcode machine before publishing mobile builds.
- **Known follow-up** — `npm audit --omit=dev` still reports 4 moderate advisories through Expo's Metro/PostCSS chain; the suggested fix is breaking (`npm audit fix --force` changes Expo), so defer to a dedicated dependency-security pass.

## Previous session (v0.2.7 — GUI visual refresh)

> Dated 2026-05-16. No data flow, route, or content changes — pure chrome /
> motion / iconography upgrade folded into the 0.2.7 release-candidate line.
> `pyproject.toml` and CHANGELOG.md both remain aligned on `0.2.7`.

- **Setup wizard (native first-run)** — `pages/setup.py` + new `pages/setup_widgets.py`. The numbered step buttons became an animated stepper widget (numbered circles + fill-line + pulsing current-step halo + ✓ for done). Welcome page now shows a floating logo with concentric radar rings and a tagline that fades in. Page transitions fade in ~200 ms. The thin marquee progress bar was replaced with a rotating-glyph (◐◓◑◒) spinner whose caption syncs to the live busy status. Every form field has an inline `ⓘ` info bubble. All four masked secret fields gained a 👁/🙈 eye toggle. Nav/action buttons carry emoji prefixes (🚀 Start · ▶ Next · ◀ Back · ✅ Finish · 🌐 LAN setup · 📨 Request · 🔄 Check · 🧪 Test). Finish plays a 260 ms ✅ celebration overlay before handoff.
- **Main shell — unified design language** — new `shell_widgets.py` module exposing `make_pill`, `set_pill`, `make_spinner`, `make_info_button`, `make_page_hero`, `show_toast`, `fade_swap`. The shell's `_show_page` now uses `fade_swap` so pages fade in/out instead of swapping instantly. The shared `_loading_indicator` factory returns the same rotating-glyph spinner the setup wizard uses (six pages now use it: Admin / Requests / History / Logs / Feedback / Settings / Radar / FIDS). Admin / History / Logs / Feedback / Requests adopted a unified `PageHero` band (emoji + title + subtitle + ⓘ helper + "Last refreshed HH:MM:SS" pill + status pill + action buttons). Toasts slide in bottom-right on refresh / send completions.
- **FIDS board styles** — new `pages/fids_styles.py` with four `FidsStyle` descriptors. **Classic** (default — unchanged behavior), **PAX** (big rows, friendly verbs like "Boarding now" / "Running late"), **VATSIM** (callsign-first, flight rules, phase TAXI/CLIMB/CRUISE/DESCENT, alt/GS compact field), **Nerd** (dense operator view: every column, monospace, code-style tokens BRD/DEP/LND/CXL). 4-segment selector in the FIDS header (🛬 Classic · 🧳 PAX · 🛩 VATSIM · 🤓 Nerd). Persists per-install via `QSettings("LocalFlight","Native").value("fids/style")`. `FlightBoardModel` is now style-aware: takes `columns` + `status_vocabulary` per instance, gained `set_columns()` and `set_status_vocabulary()`. `_display_value` handles new column keys (`callsign`, `flight_display`, `registration`, `altitude_ft`, `ground_speed_kt`, `alt_speed`, `squawk`, `flight_rules`, `phase`, `delay_label`, `source`). Status text routes through `translate_status` to produce friendly / phase / code variants per style.
- **Centralised emoji language** — `design.py` now owns three dicts: `NAV_GLYPHS` (page nav), `WEATHER_EMOJI` (single source replacing three duplicates across `fids.py`/`radar.py`/`_legacy_app.py`), `SECTION_EMOJI` (31 entries for section headers / status cards / FIDS row icons / setup options). Plus a `paint_emoji` helper for QPainter rendering. Result: every page nav, every weather strip, every FIDS row icon, every Settings status card, and every section header on Admin/History/Logs/Feedback/Requests now uses color emoji. Nav glyphs swapped from obscure Unicode (`◴` / `≡` / `▣` / `≋` / `⇁`) to readable emoji (📺 / 🛫 / 🛰 / 🟩 / ⚙️ / 🛠 / 📅 / 📜 / 💬 / 🔧).
- **Official brand assets** — replaced ad-hoc folder/cup icons with official SVGs from GitHub and Buy Me a Coffee. `support-repository.svg` = white GitHub Invertocat (used on dark theme), `support-repository-dark.svg` = black GitHub Invertocat (used on light theme); `_apply_design_from_config` swaps the right variant live on theme change. `support-coffee.svg` = official BMC cup logo. `support-coffee-button.svg` = official BMC button (available for any future larger CTA).
- **QSS additions in `design.py`** — `Pill[tone="*"]`, `PageHero` + `PageHeroEmoji/Title/Subtitle`, `ShellSpinner` / `SetupSpinner`, `ShellInfoButton` / `SetupInfoButton`, `SetupEyeButton`, `ShellToast[tone="*"]`, `PrimaryCTA` / `SetupPrimary`, `FidsStyleButton` (segmented), `SetupOptionCard:hover` with deeper `[selected="true"]:hover`, `SetupStepCaption`, `SetupFieldLabel`.
- **Files added** — `src/localflight/native/shell_widgets.py`, `src/localflight/native/pages/setup_widgets.py`, `src/localflight/native/pages/fids_styles.py`, plus four official brand SVGs in `src/localflight/ui/static/`.
- **Files modified** — `src/localflight/native/design.py` (emoji dicts + paint_emoji + many new QSS rules), `src/localflight/native/models.py` (FlightBoardModel column/vocabulary parameterisation), `src/localflight/native/_legacy_app.py` (`_show_page` uses fade_swap, `_loading_indicator` returns shared spinner, PageHero applied to Admin/Requests/History/Logs/Feedback, theme-aware GitHub icon, More button glyph `⋯`, brand-mark fallback `🛫`, section labels and panel titles gained emoji prefixes, duplicate weather glyph dict deleted), `src/localflight/native/pages/fids.py` (emoji `_draw_icon`, style selector, `set_fids_style`), `src/localflight/native/pages/radar.py` (uses central WEATHER_EMOJI), `src/localflight/native/pages/settings.py` (status-card icons render emoji), `src/localflight/native/pages/setup.py` (full wizard refresh), `src/localflight/ui/setup_guidance.py` (option icons → emoji).
- **Phase 4 deferred polish** (intentionally NOT in this beta — see "Pending / next up — Native GUI refresh Phase 4 (deferred polish)" below): animated KPI counters on Admin/History cards; matrix flap-board boot animation; top-nav sliding underline; per-page empty-state cards; per-column custom paint methods for the VATSIM/Nerd-only columns (currently they fall back to plain text); honoring `style.row_height` and `style.font_scale` in the delegate's `sizeHint`; broader toast coverage (theme change, save, network status).
- **Verification** — `python -m py_compile` clean across every touched file. Generated stylesheet contains all new selectors (`Pill[tone="good"]`, `PageHero`, `ShellSpinner`, `ShellInfoButton`, `ShellToast`, `PrimaryCTA`, `FidsStyleButton`, plus the setup-side `SetupSpinner` / `SetupInfoButton` / `SetupEyeButton` / `SetupPrimary` / `SetupOptionCard:hover`). FIDS style registry exposes `['classic', 'pax', 'vatsim', 'nerd']` with `classic` as default — existing users see zero behavior change unless they opt in.
- **Cross-platform handoff for this pass** — Windows workspace was the source of truth for the 0.2.7 visual-refresh diff. macOS + Pi needed fresh source pulls and fresh packaging passes; any rebuilt artifacts from before that refresh were stale. That note was specific to the GUI visual-refresh pass; the later mobile Standalone pass below supersedes the old "mobile untouched" status.
- **Re-run the pytest suite + package builds** before tagging 0.2.7 final: `.venv\Scripts\python.exe -m compileall -q src relay installers scripts tests`, `.venv\Scripts\python.exe -m pytest tests -q`, then Windows / macOS / Pi packaging runs as usual.

## What was done in the previous session (v0.2.7)

- Native shell composition was polished around grouped nav, centered UTC/LT clocks, tooltip-only sync status, icon-only support links, and a compact version/privacy footer.
- FIDS header behavior now uses city/country display names only, passenger-friendly weather, readable ARR/DEP/Refresh actions, long-label clamping, operating-first flight identity, and compact aircraft codes on the board.
- Native and browser/LAN History, Matrix, Settings, Setup, FIDS details, Radar details, and Matrix generated MicroPython paths remain the release-candidate parity areas.
- Current-source flight intelligence remains the shared detail direction for FIDS/Radar/History: current schedule, live motion, aircraft, airport ops, weather context, source evidence, and recent history are merged from existing sources without new paid calls.
- Public release notes, README, install/display-mode docs, and handoff docs were refreshed for the `0.2.7` client-polish release candidate.
- Verification from the later Windows workspace now supersedes this older checkpoint: `python -m compileall -q src relay installers scripts tests` passed and the latest full suite returned `432 passed`.
- Windows and Pi artifacts were rebuilt after the final `0.2.7` polish. This older checkpoint has been superseded for macOS: the local/dev `.app` zip was rebuilt on 2026-05-24, while the public `.pkg` still waits for Developer ID credentials.

## Archived latest-session notes from v0.2.6

- ✅ Version sweep completed to `0.2.6` across Python metadata/runtime fallbacks, PyInstaller fallback/spec docs, mobile metadata/package lock, preview/release docs, README, privacy notes, changelog, and bundled docs.
- ✅ Native and browser/LAN History now share a richer analytics contract: filters, KPIs, delay buckets, status mix, airline delay quotas, top routes/aircraft, daily/hourly volume, sortable recent rows, and cleaner detail surfaces.
- ✅ Native and browser/LAN Matrix now share panel presets, live preview overrides, friendlier setup/apply/generate feedback, compact weather header behavior, and real-source gate/stand display. VATSIM Matrix presets intentionally hide gate placeholders.
- ✅ Current-source flight intelligence is now the shared detail direction for FIDS/Radar/History: current schedule, live motion, aircraft, airport ops, weather context, source evidence, and recent history are merged from existing sources without new paid calls.
- ✅ Native and browser/LAN Settings/setup were polished around dashboard-card controls, safer theme/skin contrast, cleaner brand/icon usage, and hidden advanced sections.
- ✅ Dependency refresh completed in the Windows venv; `pip check` passed and no outdated packages remained before packaging.
- ✅ Rebuilt release artifacts from the Windows workspace at the time: `dist/LocalFlight-windows.zip` plus `.sha256`, and `dist/LocalFlight-pi-source-0.2.6.zip` plus `.sha256`. Those archived `0.2.6` artifacts are stale for the current `0.2.7` release-candidate line.

## What was done in the latest session (v0.2.5)

- ✅ Version sweep completed to `0.2.5` across Python metadata/runtime fallbacks, mobile metadata, preview badges, README, privacy notes, changelog, and tests.
- ✅ Matrix b5 work is now separated from the b4 native/relay/radar pass in the changelog. b4 remains the boundary for features that landed before the Matrix polish wave; b5 owns the Matrix updates.
- ✅ Matrix public presets are cleaned to exactly three profiles: `real_fids`, `vatsim_pilot`, and `vatsim_atc`. Legacy names remain accepted as config aliases.
- ✅ Matrix VATSIM presets are source-guarded. `vatsim_pilot` and `vatsim_atc` require app source `virtual`, do not fetch real FIDS, and do not fall back to real METAR.
- ✅ Matrix feed now carries route-safe fields, passenger-friendly airport city labels, decoded weather display fields, page-aware VATSIM ATC payloads, and a weather toggle (`options.show_metar` / `show_weather`).
- ✅ Web and native Matrix tooling now save/generate the same current MicroPython client assumptions, including the native Generate main.py button path.
- ✅ Generated `main.py` supports small-panel-safe rows, rectangular HUB75 layouts, codeshare cycling, route-code preservation, status breathing, decoded weather glyphs, VATSIM ATC page rotation, server-synced clocks, and board check-in/config assignment.

## What was done in session v0.2.5b4

- ✅ Version sweep started for `0.2.5b4` across Python metadata/runtime fallbacks, mobile metadata, setup defaults, source installers, README, changelog, dev reference, and tests.
- ✅ Community relay setup now shows the human-friendly root URL `https://localflight-community-relay.fly.dev`; the client still derives `/v1/schedule`, `/v1/radar`, `/v1/reports`, and activation routes internally.
- ✅ Relay admin can now clean setup-trial clutter without wiping provider keys, managed tokens, blocked installs, or monthly usage counters. The cleanup clears transient request logs, activation-request rows, live client lanes, shared schedule snapshots, and report event/dedupe noise.
- ✅ Relay admin live-lane crash fix remains included: snapshot stats tolerate missing counter fields and older relay DBs get migration-safe schedule snapshot counter columns.
- ✅ Fly relay redeployed on image `deployment-01KQJM7HKYXMF8EDRKFY24A7S9`; live `/health` returned ok, live admin HTML rendered with the cleanup button, and the live setup-trial cleanup was run. Transient tables now read `0` rows each; monthly usage counters were preserved (`usage` count was `30` after cleanup).
- ✅ FIDS row ordering now uses full airport-local datetimes instead of visible `HH:MM` text, so cross-midnight arrivals/departures stay in real chronological order during page rotation.
- ✅ FIDS now labels the board column as `Time (LT)` and shows a neutral schedule-fetching/relay-warmup hint when the table is empty while data may still be loading.
- ✅ Real-data radar now filters surface/ground aircraft from `/api/radar`; the radar status line reports how many ground blips were hidden. VATSIM still keeps virtual ground aircraft visible by design, but now uses exact circular range cropping.
- ✅ Tiny real-data radar views now request the shortest practical ADS-B provider radius (`5 NM`) and crop locally for 1 / 2 / 3 NM display rings, avoiding empty provider responses while keeping the visual range tight.
- ✅ VATSIM radar uses the same exact circular local range crop for 1 / 2 / 3 NM views. It still fetches the whole public VATSIM feed once and does not need a provider-radius funnel.
- ✅ Ground radar surface overlay is staged but policy-safe by default: Settings exposes `radar_surface_enabled` defaulting off, local `/api/radar/surface` can serve cached OSM-derived geometry capped to 1-5 NM, relay `/v1/airport-surface` coalesces/caches Overpass requests only when `RELAY_AIRPORT_SURFACE_ENABLED=1`, and `radar.html` draws airport boundary/runways/taxiways/aprons/terminals plus selected terminal/hangar-style building outlines with visible OpenStreetMap attribution. The browser only calls the surface endpoint when the setting is enabled, and the visible radar now offers tight 1/2/3 NM ground ranges with skin-aware overlay colors. Clean first-run installs now get a clearly labeled `localflight-estimated` fallback surface if the relay cache is disabled/empty and no stale local OSM cache exists.
- ✅ Standalone Radar now auto-fills the available viewport below the actual nav height instead of using fixed chrome math. The shared nav can horizontally scroll compact button groups on narrow screens, and the radar controls/weather strip compact for 7-10 inch Pi panels while still scaling up cleanly on wall displays.
- ✅ METAR weather decoration now stays aviation-native: `metar_client.py` still fetches AviationWeather METAR, `decode/metar.py` derives Local Flight condition/icon/tone/summary/hazards/chips, and FIDS/Radar/Admin render the additive weather mood without touching the mobile companion yet.
- ✅ `/api/metar` now uses VATSIM ATIS/METAR first when `source=virtual`, falls back to real AviationWeather METAR when unavailable, and only extracts the METAR line so controller names/CIDs are not exposed.
- ✅ FIDS weather now renders icon + temperature + decoded summary only; Radar keeps icon/category/temperature/summary plus raw METAR for the scope view.
- ✅ 1-5 NM radar views now behave as surface radar and hide airborne/overflying aircraft for both real ADS-B and VATSIM; wider real-data radar views still hide ground targets and focus airborne.
- ✅ FIDS rows now decode common airline IATA/ICAO/callsign prefixes into readable airline names, format the public flight number consistently, and preserve deduped codeshare partners as `Also ...` rows/detail metadata.
- ✅ New airline/codeshare helpers live in `src/localflight/decode/mappings/airlines.py`; the FIDS API now includes `airline_display`, `codeshare_display`, and detail-level `codeshares`.
- ✅ VATSIM privacy/display guard is now tested/documented: virtual traffic ingestion drops person-identifying feed fields such as names, CIDs/account IDs, and server names; VATSIM FIDS/detail surfaces are callsign-first and show VATSIM Summary / Filed Plan / Pilot Track / VATSIM Data / Recent Sessions instead of passenger codeshare, gate, registration, ICAO24, or delay analytics.
- ✅ Native GUI launch is now platform-layered: `gui_mode.py` parses the requested mode, `gui_launcher.py` resolves native/browser/headless from platform + display + PySide6/Qt availability, and `__main__.py` logs the resulting `GuiLaunchDecision` before dispatch.
- ✅ Windows/macOS source launchers and PyInstaller builds now install/verify PySide6/Qt for native mode, while Pi stays headless by default and adds an explicit `installers/pi/install.sh --native-kiosk` path for experimental Qt HDMI kiosk testing.
- ✅ Native Qt parity pass replaced the side-list/debug shell with a browser-like top nav, Display-first split/FIDS/Radar views, native setup wizard, Matrix canvas/runtime/script tooling, Logs file selector/live tail, traffic log tool, sectioned Settings/Admin/History/Feedback pages, shared native design tokens, and a route registry that validates every client/operator button path in tests. FIDS/Radar refreshes now run off the Qt UI thread so slow local API/provider calls do not freeze the native shell. Native Radar projects API `center` + `lat/lon` blips like the browser canvas and has a sweep animation; native Settings/Setup use `/api/airports/search` for the airport picker and fill IATA/ICAO/timezone instead of asking for manual entry. Native Qt uses PySide6 QtWebSockets for the same `/ws` live-push contract as the browser/LAN UI. The latest UI/UX parity refinement maps browser theme/skin choices into Qt, reloads styling from `/api/config`, applies skin palettes to FIDS/Radar/Matrix renderers, gives the top nav horizontal compact scrolling for small Pi-sized displays, caches duplicate-safe native GET calls briefly, dedupes repeated airport searches, pauses hidden Radar/Matrix animation timers, backs active refresh polling off to 30 seconds, and makes first-run diagnostics/reporting consent a saved setup step instead of a loose later prompt.
- ✅ Native GUI polish for Mac handoff: main window title now reads `Local Flight`; the setup wizard has centered, narrower, branded pages instead of huge fullscreen-dependent fields; FIDS labels/updates airport-local time; FIDS columns adapt better to window width; Client Admin removed the crowded Quick Tools block and keeps the support link in a quiet footer; History now combines filters, callsign lookup, statistics, and capped recent rows in one user-facing view; Logs now highlights retained log-file browsing plus live-tail state.
- ✅ Native History stats no longer clears the live period selector during refreshes, fixing a Qt lifecycle crash risk. Native `/api/logs` metadata now lets the Logs page match the web log selector without scraping HTML.
- ✅ Linear/reporting pass confirmed no new GUI/kiosk/headless route families are needed. Native Qt manual reports now post to local `/api/feedback` with richer `native/gui` context, `_NativeCrashReporter` sends diagnostics-gated Qt/Python UI exceptions through local `/api/feedback/crash`, and both `bug_reporter.py` plus relay `main.py` normalize `native/gui` into the desktop/user report bucket. Live relay smoke on 2026-05-02 created `LOC-45` in `Local Flight Reports` and the repeat returned `deduped=true`.

## What was done in session v0.2.5b3

- ✅ AviationStack fairness work now applies across all paths: shared date-aware fetch planning, airport-local date windows, `100`-row pages, per-date pagination, and configurable board display windows.
- ✅ Community and managed relay-backed installs now use a shared airport snapshot service instead of raw per-install upstream pass-through. Relay clients receive canonical Local Flight schedule records from `/v1/schedule`, while BYOK and direct local key paths stay unchanged.
- ✅ Relay accounting now separates per-install relay accesses from shared upstream AviationStack pulls, and admin/settings surfaces expose shared snapshot stats, cache-hit rate, and estimated savings.
- ✅ Web and matrix overflow handling now rotate local pages instead of clipping to a single fixed slice, with new config fields for grace window, horizon, web row limit, and web rotation timing.
- ✅ Added `scripts/audit_aviationstack.py` plus regression coverage for request planning, relay coalescing, stale fallback, and direct-vs-relay normalization parity.
- ✅ Version sweep completed to `0.2.5b3` across Python runtime fallbacks, mobile metadata, preview badges, tests, and public docs.
- ✅ Bug reporting now attaches truthful schedule-mode context (BYOK, local community key, managed/community shared relay), includes board-window details for triage, and scopes automatic crash dedupe by context as well as message.
- ✅ Live Fly relay was redeployed after the shared-snapshot rollout, and the relay image now bundles `src/localflight` so `/v1/schedule` works in production instead of crashing with `ModuleNotFoundError: localflight`.
- ✅ FIDS filtering now uses the snapshot timestamp as its reference clock, so valid saved rows do not disappear just because the wall clock moved past the snapshot.
- ✅ AviationStack fetchers now keep paging past the initial production slice when the visible board has not been reached yet, and both the local client and the hosted relay can attempt an undated rescue pass before surfacing an empty real-data board.
- ✅ Relay planner/version was pushed live through `fair-v3`, and relay-backed schedule fetch timeout was raised to `60s` to tolerate heavier cold shared-snapshot rebuilds.
- ✅ Relay admin was updated and redeployed from Windows so the operator page now shows `/v1/reports` gateway health, 24h report filed/deduped counts, recent report events, and report dedupe groups. Fly deploy succeeded on image `deployment-01KQJF7D3NH7CTWQQWYKHBN8FM`; `/health` returned ok and public `/v1/flights` still returns `404`.
- ✅ Relay admin live-lane crash fixed and redeployed after Pi clean-install testing exposed a no-snapshot lane: `_snapshot_shared_stats()` now tolerates missing snapshot counters, `schedule_snapshots` counter columns are migration-safe, and auto-activation network burst caps can be tuned through Fly secrets (`RELAY_AUTO_ACTIVATION_NETWORK_DAILY_LIMIT`, `RELAY_AUTO_ACTIVATION_NETWORK_INSTALLS_DAILY_LIMIT`). Fly deploy succeeded on image `deployment-01KQJK5R9JZDY7W6Q125F9GPZ3`; `/health` returned ok and live admin HTML rendered against the production volume.
- ✅ Reality check after the fix: the Local Flight fetch/filter bugs were corrected, but live `ZRH` departures on `2026-05-01` still remained sparse after the stronger fetch strategy. That remaining gap is currently documented as upstream AviationStack coverage behavior, not a known unresolved client filter bug.
- ✅ Client FIDS now falls back to the nearest available real rows when a sparse provider window would otherwise render `0` departures or arrivals, so the board stays useful even when AviationStack only returns older rows for that lane.
- ✅ Security/privacy abuse sweep pass: relay community traffic now has daily network/global caps in addition to install quotas; relay admin login attempts are throttled; setup-provided relay URLs are restricted to official/default roots unless custom/private dev flags are set; local browser cross-origin mutations are rejected; report routing now honors explicit platform origins before iOS inference; diagnostics wording now describes the hosted relay reporting gateway.
- ✅ macOS release packaging for `0.2.5b3` is complete on the Mac side: clean PyInstaller build, checksum verification, `Info.plist` version check, ARM64 executable check, on-disk codesign verification, and macOS installer script syntax checks passed.
- ✅ Pi source package for `0.2.5b3` is complete on the Mac side and no longer includes internal handoff files in the generated release zip.
- ✅ Windows release EXE silent-start failure fixed: PyInstaller windowed builds now bootstrap writable stdio to a local `~/.localflight/logs/bootstrap_<pid>.log`, preventing uvicorn/logging startup from failing before `/health` and the browser window come up. Fresh ZIP smoke test passed.

## What was done in session v0.2.5b2

- ✅ macOS-side mobile companion pass landed on `main`: updated Expo metadata, device identity reporting, crash reporter polish, README notes, and the iOS shell refinements from the Xcode machine work.
- ✅ Mobile review cleanup on Windows: companion version reporting now derives from Expo metadata instead of a duplicated string, and the mobile API config typing now includes the newer board-window fields from the desktop server.

## What was done in session v0.2.5b1

- ✅ Version sweep completed to `0.2.5b1` across Python runtime fallbacks, PyInstaller metadata, mobile metadata, docs, and preview assets.
- ✅ Community relay default centralized to `https://localflight-community-relay.fly.dev/v1/flights`; setup, installers, and client code now point at the same source of truth.
- ✅ Added route-contract regression coverage for core UI/API surfaces and relay public/admin surfaces; current Windows verification passed with `34` tests.
- ✅ Diagnostics/privacy reporting adapted: first-run diagnostics choice, settings control, truthful `/feedback` wording, and crash auto-report gating through `diagnostics_mode`.
- ✅ Mobile crash reporter now respects the server diagnostics setting before auto-sending.
- ✅ Matrix/I75W path hardened: `/api/matrix/config` repaired, `/api/matrix/script` added, browser helper blocks `localhost`, and board-side config intake is sanitized.
- ✅ README / privacy / mobile docs updated to match the current community / BYOK / VATSIM setup and hosted relay story.
- ✅ Settings IA cleaned up: install/relay state is separated from app controls and diagnostics/resources, community relay wording is now accurate, and README/privacy/changelog open inside the app instead of dead external placeholders.
- ✅ PyInstaller/macOS build now bundles the local docs into the app and uses a more reliable `.icns` generation path; `dist/LocalFlight-macos.zip` and `.sha256` were rebuilt successfully on this workspace.
- ✅ Mobile companion now has an independent appearance system (dark/light + 5 skins), a server-backed Matrix runtime editor, and auto landscape split display with responsive pinch-zoom radar. `npm install` and `npm run typecheck` passed on the Mac workspace; simulator/device validation still remains.
- ✅ Mobile companion structure refactor split the former single-file app into provider entrypoint, `AppShell`, domain helpers, state hooks, extracted chrome components, and `AppScreens`. `npm run typecheck` passes; `npm run doctor` is blocked only by local Xcode compatibility.
- ✅ Mobile companion UX polish: longer animated launch overlay, simplified main nav, sectioned Settings, in-app Markdown docs, compact theme-aware pinned-flight island with pin/unpin, richer detail sheet fields, explicit scheduler restart after mobile airport/profile changes, smoother screen transitions, and safer landscape split sizing.
- ✅ Desktop flight detail now exposes and renders richer stored enrichment data: source/enrichment confidence, snapshot age, last contact, geometric/barometric altitude, ICAO24, squawk, coordinates, speed, heading, vertical rate, and surface state. No new RapidAPI/OpenSky/VATSIM calls were added.
- ✅ Detail data model now preserves DAU-important aircraft/plan fields without overdoing it: aircraft registration for ADS-B/AviationStack when available, plus VATSIM filed flight rules, route, cruise altitude/TAS, planned times, enroute duration, alternate, and transponder.
- ✅ `/api/fids/detail` includes `detail_mode` (`real` / `virtual`) plus origin/destination ICAO codes, allowing desktop and companion to render source-specific detail layouts.
- ✅ Mobile detail sheet is aligned with the new server detail contract and guarded auto-reporting now catches critical detail endpoint failures without reporting normal offline/4xx cases.
- ✅ `DEV_README.md` is present again as the private operator/dev reference; keep it aligned with `AGENTS.md` and `CLAUDE.md` for AI handoff context. Pi source releases still use `python scripts/package_pi_source.py` and exclude internal handoff docs.

## What was done in session v0.2.3b2

- ✅ Hosted relay defaults centralized in `relay_defaults.py` and wired through the desktop clients, setup flow, and installers.
- ✅ `relay/main.py` hardened for Fly.io: port `8080`, FastAPI lifespan startup, `/health`, host-based public/admin gating, and reduced relay-side metadata writes.
- ✅ `relay/fly.toml` updated for explicit `relay/` deployment, one warm `fra` machine, and a public/operator hostname split.
- ✅ Privacy and handoff docs rewritten for the hosted relay model and install-scoped identifiers.
- ✅ `private_keys.py` — dev-only community key lookup from `dev/private/community_keys.json` (gitignored)
- ✅ `install.py` — `get_activation_token()` / `set_activation_token()` for managed install tokens
- ✅ `aviationstack_client.py` — explicit BYOK vs relay split; 30-day rolling community window; activation token forwarding; BYOK default 90/month; community cap 50/month
- ✅ `adsbexchange_client.py` — relay radar proxy path
- ✅ `request_log.py` — `client_type`, `client_id`, `platform` columns + schema migration; companion tracking
- ✅ `api.py` — `POST /api/admin/companion/checkin` endpoint with `CompanionCheckinIn`
- ✅ `server.py` — 6 new relay setup endpoints: client-info, activate, client-status, request-activation, request-activation/status, test-activation
- ✅ `relay/main.py` — full network admin console: provider key storage, token lifecycle/revocation, install access control, API counters, traffic stats, anonymous activation tags
- ✅ `setup.html` — three explicit paths (community / BYOK / VATSIM); managed activation flow; machine identity shown
- ✅ `admin.html` — community vs BYOK budget mode separated
- ✅ `settings.html` — read-only client link card (fingerprint, relay URL, token presence)
- ✅ `mobile/src/device/identity.ts` — companion identity (UUID, platform, deviceType, appVersion)
- ✅ `mobile/src/storage/settings.ts` — companionId persisted in Expo SecureStore
- ✅ `tests/test_relay_admin.py` — relay admin regression tests
- ✅ Version bumped to `0.2.3b2`; CHANGELOG, CLAUDE.md, AGENTS.md updated

## What was done in the macOS app session

- ✅ macOS `.app` bundle — `install.sh` now builds `~/Applications/LocalFlight.app` instead of a `.command` symlink; `scripts/make_app_bundle.py` handles SVG→icns (cairosvg → pre-rendered PNG → PIL fallback) + `Info.plist` + compiled Mach-O stub + baked shell launcher
- ✅ Mach-O stub — macOS Launch Services silently rejects shell scripts as `CFBundleExecutable`; stub is a tiny C program compiled with `cc` at install time that exec's `/bin/bash launcher.sh` in the same `MacOS/` directory
- ✅ `assets/icon_circle.png` — 1024×1024 pre-rendered from SVG and committed; `.gitignore` updated with `!assets/icon_circle.png` exception so the pre-render survives without `cairosvg`
- ✅ `LocalFlight.command` — fixed symlink `$0` resolution bug: when launched via Finder the symlink path was used as `$0`, causing `ROOT` to resolve to `~/..` instead of the project root; fixed with `readlink`
- ✅ `installers/macos/install.sh` — replaced `.command` symlink step with `make_app_bundle.py` call; `.command` file stays as shell-only fallback

## What was done in previous sessions

- ✅ `start.bat` — fixed UTF-8 box-drawing chars in `::` comments causing cmd.exe byte-eating bug on `chcp 65001`; replaced all 7 comment lines with ASCII; added error pause
- ✅ `linear_client.py` — added `test_connection()` with real GraphQL `viewer` query to validate key (not just env var presence); returns specific 401 message
- ✅ `bug_reporter.py` — originally added as the local feedback reporter; current implementation sanitizes locally and forwards developer/user reports through relay `/v1/reports`
- ✅ `feedback.html` — new `/feedback` page with title+description form, system info preview, success/error state
- ✅ `/api/feedback` endpoint — `POST`, `FeedbackIn` Pydantic model, calls `bug_reporter.submit_report()`
- ✅ `/feedback` route in `server.py`
- ✅ ðŸ› Report nav item added to `_nav.html` management group
- ✅ Admin hub Linear Issues card **removed** — replaced by dedicated `/feedback` page (no duplicate reporting)
- ✅ README rewritten from end-user perspective — install-first flow, removed dev-cycle / awaiting-hardware language
- ✅ File consistency sweep — LINEAR vars removed from all 3 installer `.env` templates; `pyproject.toml` Issues URL → GitHub; `CHANGELOG.md` updated; `AGENTS.md` updated
- ✅ Setup wizard — added ADS-B Exchange test endpoint + "Test connection" button for panel 3; POST body is now the preferred path and GET remains only as compatibility fallback
- ✅ Setup wizard — fixed RapidAPI signup URL (`adsbexchange` → `adsbx` provider slug in RapidAPI path); fixed OpenSky registration URL (old Joomla path → `/login?view=registration`)
- ✅ Admin hub — added Buy Me a Coffee strip at bottom (`buymeacoffee.com/localflight`); subtle ghost opacity, not a card
- ✅ Runtime snapshots — moved canonical JSON storage to `~/.localflight/storage/data/<IATA>/snapshots`; legacy source-tree snapshots remain readable
- ✅ Scheduler/runtime — pruning now runs inside snapshot jobs; failed cycles preserve the previous `last_success_utc`
- ✅ Installer/docs sweep — Windows/macOS/Pi source installers clarified; Pi helper path fixed; `.env.example` no longer includes operator Linear vars
- ✅ Desktop beta release prep — `psutil`/`packaging` required; Windows build writes a SHA256 checksum

- ✅ Mobile Phase 1 — created `mobile/` React Native / Expo scaffold with SecureStore settings, API client, WebSocket listener, responsive layout helpers, and iOS-first shell
- ✅ Mobile visual pass — base app followed the supplied airport-board mockup with status bar/dynamic-island-style treatment, airport/METAR header, FIDS tabs, pinned flight card, compact rows, admin/settings screens, and bottom nav
- ✅ Version bump — project moved to `0.2.2b1`; mobile npm metadata used `0.2.2-b1`; Expo metadata carried `extra.localFlightVersion = "0.2.2b1"`

## Pending / next up

- [ ] Rebuild the Windows artifact on the Windows dev machine from the current commit: `python build.py --clean`, verify `dist/LocalFlight-windows.zip.sha256`, and confirm the zip carries `localflight-0.5.1.dist-info`.
- [ ] Rebuild the Pi source artifact from the current commit: `python scripts/package_pi_source.py`, verify `dist/LocalFlight-pi-source-0.5.1.zip.sha256`, and confirm internal handoff docs are excluded.
- [x] Repack the local/dev macOS `.app` from this commit: `.venv/bin/python build.py --clean`, verify `dist/LocalFlight.app`, `dist/LocalFlight-macos.zip`, and `dist/LocalFlight-macos.zip.sha256`. Current dev zip SHA256: `23d0e8157a334187589ca8cac96715284ce1524c320e1c668d6142969a215c1e`.
- [ ] After Apple Developer ID credentials are installed, build the public macOS `.pkg`: `python build.py --clean --installer`, verify signing/notarization, then create the GitHub release `v0.5.1` and attach Windows, macOS pkg, and Pi artifacts plus all matching `.sha256` files.
- [x] Deploy the Beacon Tools Cloudflare Worker + Assets site from `site/`, add the mobile/support/network/privacy-choices trust pages, wire `relay.beacontools.cc` and `network.beacontools.cc` DNS/TLS to Fly, and flip client relay defaults from the Fly root to `https://relay.beacontools.cc`.
- [x] Refresh public and dev-facing docs for Beacon Tools, current relay defaults, mobile Companion/Remote Companion/Standalone, Android local dev, Matrix, History, VATSIM privacy, and AeroDataBox/AviationStack relay behavior.
- [ ] End-to-end community client activation test against live relay.
- [ ] Fresh live schedule smoke against `https://relay.beacontools.cc/v1/schedule` on an uncached lane to confirm `provider=aerodatabox` or `aerodatabox+aviationstack` plus `meta.schedule_provider_mode=auto`.
- [x] Sparse AviationStack airport next step is implemented as the AeroDataBox/fusion/cache-hardening path: AeroDataBox is primary when configured, AviationStack is sparse fill/fallback, and stale merged cache can serve instead of replacing a healthy board with suspiciously thin data.
- [ ] Mobile — run `npm run ios` or `npm run ios:device` on the Mac/Xcode machine after the docs/standalone commit lands.
- [ ] Mobile Android — run `npm run android` or `npm run android:device` after Android Studio/SDK setup for the local development path.
- [ ] Validate Companion runtime flows on-device/simulator: setup, Board/Radar/History/Control, Help & Reports inside Control, Remote Companion LAN-first/remote fallback/revoke proof, appearance persistence, airport/source config sheet, scheduler restart, feedback, crash gating, WebSocket refresh or remote polling fallback, landscape display, and radar pinch zoom.
- [ ] Validate Standalone runtime flows on-device/simulator: airport search, relay activation, Board, Radar 1/3/5/10 NM, local History persistence, Settings reset, direct relay report, diagnostics gating, and no Matrix/Admin/server-control surfaces.
- [ ] Notification system (Pushover/Telegram) — ~50 lines, hooks into scheduler after `_broadcast_update()`
- [ ] Pi hardware on hand — run systemd services + kiosk validation on the real unit
- [ ] RTL-SDR dongle — test dump1090 integration
- [ ] Interstate 75 W — flash client.py, test WiFi polling
- [ ] Code signing certificates — Developer ID (macOS) + EV cert (Windows SmartScreen)
- [ ] Mobile v2 — per-device auth tokens before exposing broader admin mutating controls; QR pairing itself is now IP-first and fingerprint-bound.

## Afternoon handoff (2026-04-30)

- ✅ `AGENTS.md` is the working memory file again for current-state handoff notes.
- ✅ `.gitignore` covers local assistant / dev context files including `.claude/`, `CLAUDE.md`, `DEV_README.md`, and `AGENTS.md`. Important: `AGENTS.md` is still tracked by git right now, so the ignore rule only protects future untracked state.
- ✅ Windows side is currently verified for the hosted-relay desktop app: `build.py --clean`, `compileall`, `py_compile`, and `pytest tests` passed in the latest release sweep.
- ✅ Pi / I75W prep is staged in code: Pi installer plus `lf` helper are ready, matrix preview is safer for DAU use, and the board download path rejects `localhost` in favor of LAN-safe server targets.
- ✅ Mobile companion remains version-synced but still WIP; runtime validation still belongs on the Mac/Xcode side after dependency install.
- 🔜 Next physical test focus: Raspberry Pi service / kiosk pass, Interstate 75 W flash plus matrix polling check, and later the macOS PyInstaller validation for the release app.

---

## Code style / conventions

- Python 3.11+, type hints throughout, `from __future__ import annotations`
- FastAPI for the web layer, Jinja2 for templates
- No module-level env var reads — always read lazily inside functions
- Non-fatal pattern: wrap risky operations in try/except, log warning, continue
- History writes, enrichment failures, WS broadcasts, Linear calls are all non-fatal
- `os._exit(0)` for hard shutdown (bypasses uvicorn's signal handling)
- Jinja2 templates use `{% from "_nav.html" import topnav %}` for consistent nav
- Nav active state passed as `active="pagename"` string parameter
- `app_version` available in all templates as a Jinja2 global (injected in `server.py`)
- Separation-of-power rule: keep internal/operator references out of public docs and UI copy. Public-facing surfaces such as `README.md`, `PRIVACY.md`, `CHANGELOG.md`, release text, and user-visible templates should not mention `DEV_README.md`, `AGENTS.md`, relay admin hostnames, or other operator-only paths unless there is a real end-user need.

## Pending / next up — Native GUI refresh Phase 4 (deferred polish)

Phases 1–3 of the Qt main-shell visual refresh shipped on 2026-05-16:
- Phase 1: shell_widgets.py (Pill, Spinner, InfoButton, PageHero, Toast, fade_swap) + design.py QSS
- Phase 2: PageHero/Pill/Toast applied to Admin / History / Logs / Feedback / Requests
- Phase 3: fids_styles.py with CLASSIC / PAX / VATSIM / NERD descriptors, style-aware FlightBoardModel, 4-segment selector in FIDS header, persistence via `QSettings("display/fids_style")`. Default = CLASSIC.
- Plus: official GitHub Invertocat + Buy Me a Coffee SVGs swapped in for the footer icons (with theme-aware switching between black/white invertocat).

Phase 4 (NOT yet implemented — pick up later):
1. **Animated KPI counters** on Admin + History KPI cards — tween the numeric value when it changes (QPropertyAnimation on a custom `value` property of a small QLabel subclass).
2. **Matrix flap-board boot animation** — stagger each character on first paint, then settle to live data.
3. **Top nav sliding underline** — paint-only animated underline that glides between active nav buttons on `_show_page`.
4. **Empty-state cards** — when a page returns no data, show a big emoji + guidance text + "Refresh" button (e.g. FIDS "no departures in the window", Logs "no log files retained").
5. **Per-column paint methods in `_FidsBoardDelegate`** for the new VATSIM/Nerd columns (callsign, registration, alt_speed, phase, squawk, delay_label, source). Currently those columns fall back to `_paint_plain` which draws DisplayRole text — functional but not styled per-column. Adding `_paint_callsign`, `_paint_alt_speed`, `_paint_phase` etc. would give NERD/VATSIM the same level of polish CLASSIC already has.
6. **Honor `style.row_height` and `style.font_scale` in the delegate sizeHint** — currently `sizeHint` returns a fixed 48/62/70 height. Reading from the active style would make NERD truly dense and PAX truly chunky.
7. **Toast notifications on more events** — saved settings, theme change, network status changes. Right now toasts only fire for history/logs/feedback/requests/admin refresh.

Files involved (for orientation):
- `src/localflight/native/shell_widgets.py` — shared visual primitives
- `src/localflight/native/pages/fids_styles.py` — FIDS style descriptors
- `src/localflight/native/pages/fids.py` — board page, has the style selector + `set_fids_style()` method
- `src/localflight/native/models.py` — FlightBoardModel: now takes `columns` + `status_vocabulary` per-instance, gained `set_columns()` / `set_status_vocabulary()`
- `src/localflight/native/design.py` — QSS for Pill / PageHero / ShellSpinner / ShellInfoButton / ShellToast / PrimaryCTA / FidsStyleButton
- `src/localflight/native/_legacy_app.py` — `_show_page` uses fade_swap, `_loading_indicator` returns the new spinner, footer GitHub icon picks theme-aware variant
