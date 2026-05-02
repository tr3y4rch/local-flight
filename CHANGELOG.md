# Changelog

All notable changes to Local Flight are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.5b4] - 2026-05-01

### Changed
- Community setup and source installers now show the hosted relay root URL (`https://localflight-community-relay.fly.dev`) instead of the legacy compatibility path ending in `/v1/flights`. The app still derives `/v1/schedule`, `/v1/radar`, `/v1/reports`, and activation routes internally.
- Relay auto-activation burst limits can now be tuned with Fly secrets for local lab reinstall testing without changing the default production safety rails.
- FIDS rows now sort by the full airport-local timestamp, not just the visible `HH:MM`, and the table labels board times as `Time (LT)`.
- Real-data radar responses now hide aircraft that are clearly on the surface, and the radar status line reports when ground blips were filtered.
- Radar responses now switch into surface mode for 1 / 2 / 3 / 5 NM ranges, showing only aircraft that appear to be on the ground and hiding airborne/overflying blips for both real ADS-B and VATSIM.
- Radar now includes tighter 1 / 2 / 3 / 5 NM ground-radar ranges for airport-surface inspection. Tiny aircraft views now reuse the shortest practical ADS-B provider fetch radius (`5 NM`) and crop locally, while the optional surface overlay itself stays capped to a 1-5 NM ground-scale request instead of following wider aircraft radar ranges.
- Radar surface styling now follows dark/light theme and the active skin palette instead of using one generic overlay color.
- Standalone Radar now fills the available viewport below the real navigation height instead of subtracting a fixed chrome value, and its controls/weather strip compact themselves for 7-10 inch Pi screens and large wall displays.
- METAR weather is now decorated by Local Flight's own semantic decoder instead of adding another weather provider. `/api/metar` still returns the raw/decoded aviation fields, plus additive `weather_*` mood, icon, tone, summary, hazards, and chip fields for richer UI.
- `/api/metar` now tries VATSIM ATIS/METAR first in virtual mode, extracts only the raw METAR line, and falls back to AviationWeather when VATSIM weather is unavailable.
- FIDS weather now shows icon, temperature, and decoded summary only, while Radar keeps icon/category/temperature/summary plus raw METAR.
- FIDS flight rows now decode common airline IATA/ICAO prefixes into readable airline names, format public flight numbers consistently, and preserve deduped codeshare partners in the row/detail metadata.
- VATSIM radar now applies the same exact circular local range crop as real-data radar, so 1 / 2 / 3 NM virtual views do not show square-corner traffic outside the selected ring.
- GUI launch now goes through a shared native-first platform decision layer. Blank or invalid `LOCALFLIGHT_GUI_MODE` values request the PySide6/Qt shell first, then fall back to browser/kiosk only when Qt or display support is unusable; display-less Pi/Linux still runs headless.
- Windows and macOS source launchers now install/verify the native PySide6 extra before native launch; release packaging also fails early if PySide6/Qt is unavailable.
- Bug reports now include requested/effective GUI shell, display availability, Qt availability, fullscreen state, and launch-decision reason so native GUI, browser kiosk, and headless service reports are distinguishable inside the same two-team Linear routing model.
- Native Qt now follows the web kiosk structure more closely: top navigation, version/clocks, Display/FIDS/Radar/Matrix/Settings/Admin/History/Logs/Report pages, responsive nav labels, and a quit confirmation replace the earlier side-nav prototype.
- Native FIDS, Radar, Display, Settings, Admin, History, Logs, Matrix, Setup, and Feedback now use the same local API contracts as the web kiosk instead of debug JSON-only placeholders.
- Native Qt now connects directly to the local `/ws` live-push endpoint and reacts to `snapshot_updated`, `config_updated`, and `scheduler_restarted` events like the web kiosk instead of relying only on fallback polling.
- Native Qt now has a browser-parity design-token layer for dark/light theme plus standard/technical/neon/cyan/crt skins. The shell reloads styling from `/api/config`, the top nav scrolls compactly on smaller displays, and FIDS/Radar/Matrix renderers use the active skin palette instead of one hardcoded cyan-dark look.
- Native Qt now reuses short-lived local GET results for high-frequency routes such as config, FIDS, radar, METAR, airport search, admin summaries, logs, and surface geometry. Mutating actions clear the cache immediately, reducing duplicate local API/database work without changing backend contracts.

### Fixed
- Relay admin no longer crashes when a live client lane exists before a shared schedule snapshot has been created.
- Schedule snapshot counter columns are now migration-safe for older relay databases.
- Arrivals and departures that cross midnight no longer rotate into a confusing order such as tomorrow's `00:08` before today's `17:45`.
- FIDS row times now use the active airport timezone passed into the board renderer instead of falling back to whatever timezone is currently stored in the global config.
- Pi source pre-release bundles now include non-ignored local file additions as well as tracked files, preventing hardware test zips from silently missing newly added modules before a commit exists.
- Radar surface overlay no longer appears broken on a clean first run when the relay surface cache is disabled or empty. If no cached OSM geometry is available yet, the radar now draws a clearly labeled local estimated airport surface instead of silently rendering nothing.
- Native History stats no longer deletes and reuses its own period selector during refreshes, avoiding a Qt lifecycle crash after interacting with the stats tab.
- Native traffic/log/report controls now have declared routes and constructor coverage so user-visible buttons are less likely to drift into no-op placeholders.
- Native first-run completion now opens the Display page and prompts for the same diagnostics/reporting choice when diagnostics mode is still unset, keeping bug reporting consent behavior aligned with the browser shell.
- Native WebSocket shutdown now tolerates Qt deleting the socket during app/test teardown, avoiding an ugly finalizer traceback after otherwise successful native constructor tests.
- Native Radar and Matrix canvases now pause their animation timers while hidden, Radar sweep runs at a lighter cadence, active page polling backs off to 30 seconds, and airport search avoids repeating the same query while typing.

### Added
- Hosted relay maintenance now has a clean setup-trial action that clears transient request logs, activation-review rows, live client lanes, shared schedule snapshots, and report-event clutter while keeping provider keys, managed tokens, blocked installs, and usage counters intact.
- FIDS now shows a neutral schedule-fetching hint while an empty board may still be waiting on the relay/shared schedule warmup.
- Radar now has a staged, opt-in airport surface overlay using relay-cached OpenStreetMap/Overpass geometry through `GET /api/radar/surface` and relay `GET /v1/airport-surface`. The overlay draws runways, taxiways, aprons, terminals, airport boundaries, selected terminal/hangar-style building outlines, and visible OSM attribution without using public raster tile servers. It is disabled by default locally and requires explicit relay operator enablement via `RELAY_AIRPORT_SURFACE_ENABLED=1`.
- FIDS, Radar, and Admin now render the METAR-derived weather mood with compact weather-app-style icons, colored tone treatments, and local summaries while preserving raw METAR visibility.
- Chrome-free native UI is now the default requested shell for desktop/source/release builds; `LOCALFLIGHT_GUI_MODE=browser` remains an explicit fallback/debug override.
- Raspberry Pi installs still run headless without a display, keep legacy Chromium kiosk available through `--kiosk`, and add a `--native-kiosk` path that installs Qt runtime packages, verifies PySide6/Qt, and starts Local Flight as a fullscreen native shell on the attached display.
- Native first-run setup now has a real wizard for airport search, community/BYOK/managed/virtual source selection, relay activation checks, API key tests, and setup completion without opening a browser.
- Native Matrix now has a LED-style canvas preview, panel/zoom/brightness/runtime controls, config save, and MicroPython script generation.
- Native Logs now has log-file selection, refresh, live tail, scroll-to-bottom, line counts, and last-update metadata. Native Admin can open the local anonymized traffic log as a user-facing tool.

## [0.2.5b3] - 2026-05-01

### Added
- Shared relay schedule snapshots for community and managed installs via `GET /v1/schedule`, so the relay can fan out one upstream AviationStack refresh to many clients watching the same airport window.
- Relay-side schedule cache metadata and savings stats in admin/settings payloads, including shared access counts, upstream pull counts, cache-hit rate, and estimated savings.
- AviationStack audit script (`scripts/audit_aviationstack.py`) for comparing baseline, paginated, and fair windowed fetch strategies across a global airport sample.
- Configurable board-density controls for real-data fairness and overflow handling: `display_grace_minutes`, `display_horizon_hours`, `web_row_limit`, `web_rotation_seconds`, and matrix page rotation.
- Relay-backed developer report gateway at `POST /v1/reports`, with Linear team routing, relay-side dedupe, rate limits, and secret redaction before Linear issue creation.
- Mobile-local diagnostics consent, stored on-device, so companion auto-reporting requires both the mobile choice and the connected server diagnostics mode to allow it.

### Changed
- AviationStack schedule fetching now uses a shared date-aware planner across BYOK, direct local relay-key use, and hosted relay-backed paths: page size `100`, airport-local date windows, and per-date pagination.
- The AviationStack planner now keeps paging past the initial production slice when a busy airport has not yet reached the visible board window, and relay-backed shared snapshots now rebuild on planner version `fair-v3`.
- Community and managed installs no longer consume raw provider JSON from the relay. They now receive Local Flight canonical records and continue the normal local normalize, enrich, history, and FIDS pipeline.
- Community relay budget wording now reflects the actual model: `LOCALFLIGHT_RELAY_MONTHLY_LIMIT` tracks per-install relay schedule accesses, while upstream AviationStack pulls are shared and counted separately on the relay.
- Web and matrix boards now rotate overflow pages locally instead of forcing a single fixed visible slice.
- When a date-scoped AviationStack board would otherwise come back empty, Local Flight now tries an undated rescue pass before surfacing that sparse result.
- Developer report submission now forwards through the hosted relay instead of shipping a developer Linear credential in the desktop/mobile package.
- Relay community traffic now has network-level and global daily safety caps on top of per-install monthly quotas, reducing abuse risk from rotated install IDs.
- Setup-provided relay URLs are now validated before the local app calls them; official relay hosts work by default, while custom/private relay roots require explicit local opt-in environment flags.
- Local browser mutations now reject cross-origin POST-style requests, blocking drive-by web pages from changing settings or triggering local actions on the LAN.
- README, Privacy, and mobile docs now explain the current relay, diagnostics, LAN trust, and companion privacy model in plain end-user language.

### Fixed
- FIDS board filtering now uses the snapshot timestamp as its reference clock, so valid saved rows do not disappear just because the wall clock moved on while the snapshot stayed unchanged.
- When a real-data lane still has no rows inside the live display window, the board now falls back to the nearest available real flights instead of showing a completely empty departures/arrivals table.
- Matrix clients now clear stale rows when a refresh fails or returns empty data, avoiding misleading leftovers and tight retry hammering.
- Bug reports now attach truthful schedule-mode context for BYOK, direct local community-key, and shared relay snapshot paths, plus the active display window and web board density settings.
- Automatic crash deduplication is now scoped by crash context as well as message, and the mobile crash boundary copy now reflects best-effort report delivery more honestly.
- Relay production packaging now bundles the `localflight` schedule helpers inside the Fly image, so the shared `/v1/schedule` route works live instead of failing with `ModuleNotFoundError`.
- Relay-backed schedule fetches now allow a longer timeout on cold shared-snapshot rebuilds, reducing false client failures while the relay performs the heavier sparse-board rescue path.
- Mobile crash reports with feature-specific context now keep the standard companion identity, app version, device type, and server URL attached for triage.
- Relay report routing now respects explicit desktop/web/server origins before inferring iOS from generic OS text, keeping platform triage separated.
- Relay admin Basic auth now throttles repeated bad password attempts per network tag.
- Windows PyInstaller release EXEs now bootstrap writable stdio in windowed mode, preventing uvicorn/logging startup from failing silently before the browser window opens.

---

## [0.2.5b2] - 2026-04-30

### Added
- iOS-first companion polish pass across the Expo shell, including the longer branded launch overlay, stronger crash-reporting context, and cleaner companion identity reporting.
- Mobile companion appearance system with independent on-device `dark` / `light` theme selection and five mobile skins: `standard`, `technical`, `neon`, `cyan`, and `crt`.
- Mobile Settings **Appearance** controls with theme toggle, skin chips, and a live preview strip. Mobile appearance stays local to the device and does not sync with desktop/server skin.
- Mobile support for the existing `/api/matrix/config` runtime contract. The Matrix screen now loads server config, edits a local draft, saves explicitly, and can reset unsaved edits back to the server state.
- Mobile landscape display mode for FIDS and Radar. Rotating while on either screen opens a side-by-side display, with FIDS-primary or Radar-primary focus preserved.
- Responsive mobile radar scope with pinch-to-zoom range changes that snap across the desktop-aligned 10 / 20 / 40 / 80 NM ranges, plus compact fallback range chips.
- In-app mobile document reader for README, Privacy, and Changelog, with formatted Markdown rendering and browser fallback.
- Mobile settings/admin support for the refined desktop relay and diagnostics surfaces, keeping the companion aligned with the latest server controls.

### Changed
- Desktop `/api/fids/detail` now exposes richer no-extra-request live-track metadata from stored snapshots, including geometric/barometric altitude fields, ICAO24, squawk, last contact, snapshot age, enrichment source, and confidence.
- Canonical flight snapshots now preserve DAU-relevant aircraft and virtual-flight-plan fields: registration, flight rules, planned route, cruise altitude/TAS, planned departure/arrival, enroute time, alternate, and assigned transponder.
- Desktop FIDS flight detail drawer now presents operations/aircraft, data source coverage, and live-track fields more explicitly, matching the companion's expanded detail contract.
- VATSIM normalization now keeps filed plan details useful to virtual pilots while avoiding noisy personal fields such as pilot names or VATSIM IDs.
- Desktop flight detail UI now branches between real-world and VATSIM modes: real flights prioritize airport operations, registration, and real data-source freshness, while VATSIM flights prioritize filed plan, virtual network, pilot track, route, cruise, alternate, and transponder details.
- Mobile Matrix tooling is now split into **Board Runtime** controls for server-backed settings and **Panel Preview** controls for local Interstate 75 W / HUB75 sizing.
- Matrix board preview keeps the mobile app chrome on the selected mobile appearance while rendering simulated LED colors from the server-returned matrix skin.
- Mobile Expo config now allows automatic system appearance instead of forcing dark mode, while the app drives its own StatusBar styling from the selected mobile theme.
- Mobile app internals were refactored from a single large `App.tsx` into a provider entrypoint, `AppShell`, domain helpers, state hooks, extracted chrome components, and screen/sheet modules.
- Mobile main navigation is now focused on FIDS, Radar, and Settings. History, Matrix, Admin, and Docs remain available from Settings instead of crowding the bottom nav.
- Mobile Settings is now sectioned into Server, Looks, Tools, and Docs areas to reduce page density.
- Pinned-flight chrome is now a compact, theme-aware info island with direct pin/unpin and tap-for-detail behavior instead of the previous expandable dark pill.
- Mobile airport/profile changes now explicitly ask the connected server to restart the scheduler and begin a fresh fetch cycle after config save.
- Mobile flight detail sheets now consume the expanded `/api/fids/detail` contract, including real vs VATSIM detail modes, data-source freshness, aircraft registration, ICAO24/squawk, geometric/barometric altitude, and filed VATSIM plan fields when available.
- Mobile automatic diagnostics now cover critical flight-detail communication failures (`5xx` responses or malformed JSON) through the existing diagnostics-gated crash route, while normal offline, validation, and `4xx` states stay user-visible without auto-report noise.
- The companion now feels closer to the supplied airport-board mockup in daily use, with the updated FIDS shell, launch flow, and diagnostics-aware reporting path.
- Public mobile docs now describe the current beta scope more accurately instead of treating the companion like a bare phase-one scaffold.
- Expo mobile dependency alignment updated for SDK 55: `expo` now targets `~55.0.19` and `expo-font` is installed for `@expo/vector-icons`.

### Fixed
- Mobile pinned-flight island and bottom nav no longer keep hardcoded dark backgrounds in light mode.
- Mobile landscape split panes are constrained for safer scrolling/resizing after rotation.
- Companion version reporting now derives from Expo app metadata instead of a duplicated hardcoded string, reducing release drift risk.
- Mobile API typings now include the newer board-window config fields, keeping the companion aligned with the desktop server contract.

---

## [0.2.5b1] - 2026-04-29

### Added
- Pi installer (`installers/pi/install.sh`) fully rewritten: headless by default, optional `--kiosk` flag for Chromium kiosk, clean progress output (`ok`/`step`/`fail` helpers), all apt output suppressed, stale kiosk service removed on headless re-runs.
- `lf` management command installed to `/usr/local/bin/lf` during Pi setup - `lf start`, `lf stop`, `lf restart`, `lf status`, `lf logs`, `lf update` work from any directory.
- `lf.sh` rewritten: `has_kiosk()` guard makes all kiosk operations conditional on whether the kiosk service is installed; kiosk operations never run in headless mode.
- `scripts/package_pi_source.py` builds the versioned Pi source release bundle plus SHA256 so the Pi installer is reproducible from one documented command.
- `GET /api/matrix/config` and `POST /api/matrix/config` - LED matrix config (brightness, max rows, refresh interval, default view) stored server-side at `~/.localflight/matrix_config.json`; board picks up changes without reflashing.
- `POST /api/matrix/script` - generates a complete, ready-to-flash Interstate 75 W `main.py` from the canonical board client template, with LAN-host validation for the board download path.
- Matrix preview **Save Config** button: stores brightness, rows, refresh interval, and default view to the server so the board picks them up automatically.
- First-launch diagnostics choice for each install: `Manual reports only`, `Automatic crash reports`, or `Automatic crash reports + sanitized logs`.
- In-app document viewer routes (`/docs/readme`, `/docs/privacy`, `/docs/changelog`) so README, privacy, and changelog content are readable from Settings inside the desktop app.

### Changed
- MicroPython matrix client (`sources/matrix/client.py`) no longer has hardcoded airport or config values. Airport is read from `/api/config` on boot and every 5 minutes. Brightness, row count, refresh interval, default view, and skin are read from `/api/matrix/config`.
- Matrix board LED colors now track the app's active skin (`standard`, `technical`, `neon`, `cyan`, `crt`) - skin propagated via `/api/matrix/config` response, applied by `apply_skin()` which recreates all PicoGraphics pen objects.
- Matrix preview canvas palette is now skin-aware: initialized from `{{ cfg.skin }}` at page render, updates when skin changes.
- Matrix preview page cleaned up: aligned visual style with the rest of the app, clearer "flash once / tune here" guidance, explicit LAN host / port entry, and safer DAU-oriented hints instead of browser alerts.
- Automatic diagnostics now respect the install's chosen privacy mode across desktop, browser UI, scheduler/runtime, and mobile companion flows.
- Manual reports and automatic crash reports now describe their delivery path, source context, Python/runtime details, and whether a sanitized log excerpt was included.
- Version metadata, mobile companion metadata, runtime fallbacks, and preview badges are now aligned to `0.2.5b1`.
- Community relay defaults are now centralized on the live Fly.io endpoint so app code, setup, installers, and docs stop drifting.
- Settings now separate install/relay status, flight setup, app controls, and diagnostics/resources more clearly, and community mode now truthfully reports when the hosted relay is active.
- README now documents the Pi source release bundle and the local docs viewer routes.

### Fixed
- `.env.example` relay URL corrected from the unregistered `relay.localflight.app` to the live endpoint `https://localflight-community-relay.fly.dev/v1/flights`.
- Matrix board download no longer depends on a stale browser-only copy of the MicroPython client, no longer suggests `localhost`, and no longer ships real local SSID / IP placeholders in the canonical board file.
- Automatic crash submission now returns a clear disabled state when diagnostics are turned off instead of looking like a backend failure.
- Setup, installer, and runtime relay references now resolve to the same hosted community backend contract.
- macOS packaging now bundles `README.md`, `PRIVACY.md`, and `CHANGELOG.md` into the app and uses a more reliable `.icns` generation path before falling back to `iconutil`.

---

## [0.2.4b1] - 2026-04-28

### Changed
- Community relay URL updated to the live Fly.io endpoint (`https://localflight-community-relay.fly.dev/v1/flights`). The `relay.localflight.app` custom domain is planned once DNS is configured.
- Source installers (Windows, macOS, Pi) and `.env` defaults now point to the confirmed-working relay endpoint.
- Version bumped to `0.2.4b1` across `pyproject.toml`, runtime fallbacks, and mobile metadata.
- Removed orphaned `claude2.md` and root `package-lock.json`.

### Fixed
- `relay/main.py` used `uvicorn.run("relay.main:app", ...)` (string module import) which fails in Docker because there is no `relay` package in the container filesystem. Changed to `uvicorn.run(app, ...)`.
- Removed redundant `DB_PATH` `fly secrets set` step from deploy docs - the value is already hardcoded in `fly.toml [env]`.

---

## [0.2.3b2] - 2026-04-28

### Added
- Fly.io deployment guidance and defaults for the hosted community backend, including a public relay host and a separate operator host.
- Host-aware relay health and root responses so public clients can hit the hosted backend directly while the operator console stays on its own hostname.
- Regression coverage for public/admin hostname gating, relay privacy writes, hosted relay defaults, and the `0.2.3b2` runtime metadata sweep.

### Changed
- Community mode now defaults to the hosted relay URL `https://relay.localflight.app/v1/flights` across the client, setup flow, and source installers.
- The relay now runs as one Fly app with one warm machine in `fra`, one SQLite volume, and separate public/admin hostnames on top.
- Setup keeps the user-facing model to exactly three paths: Community, Bring your own keys, or VATSIM.
- Source-install templates, `.env.example`, and handoff docs now describe the hosted relay as the standard community path instead of a local-only relay experiment.
- Mobile companion metadata is version-synced to `0.2.3b2`, while the docs continue to mark mobile as WIP/beta.

### Fixed
- Fly deployment artifacts now agree on port `8080`, and the GitHub workflow explicitly deploys the `relay/` app instead of relying on repo-root defaults.
- The public relay hostname no longer exposes `/admin`, and the operator hostname no longer serves the public `/v1/*` client surface.
- Relay activity and activation records no longer persist airport-identifying fields for new writes; anonymous install fingerprints and network tags remain for abuse protection.
- Community relay setup no longer derives stored relay labels from the selected airport, keeping the privacy story consistent from the client through the hosted backend.

---

## [0.2.2b3] - 2026-04-27

### Added
- Community AviationStack relay mode for real flight schedules when no personal `AVIATIONSTACK_API_KEY` is configured.
- Personal subscription budget defaults for AviationStack and RapidAPI increased to 10,000 calls/month.
- RapidAPI / ADS-B Exchange usage tracking in Admin, including calls used, remaining quota, and monthly limit.
- Radar range controls, including URL-driven range selection for shared/bookmarked radar views.
- Airport timezone auto-detection from the server-side airport database, including region-level timezone handling for multi-timezone countries.
- Companion preview artwork in the README and local preview gallery.

### Changed
- Manual refreshes, scheduler restarts, and config changes now respect snapshot freshness before making another live schedule request.
- Manual restart now returns a rate-limited status when triggered repeatedly within a short window.
- OpenSky live radar fallback is cached briefly per airport so multiple open clients do not all trigger their own fallback fetch.
- Admin budget cards now distinguish community relay mode from personal-key mode and show separate RapidAPI usage.
- Setup now clearly presents the three main ways to use Local Flight: shared relay, your own keys, or VATSIM.
- Settings and setup now use airport-provided timezone data instead of browser-side country guesses.
- API-key test buttons now send keys in request bodies instead of putting keys in browser URLs.
- Developer reports now include a privacy-preserving install fingerprint instead of a raw relay install identifier.
- Mobile metadata, Expo metadata, runtime fallbacks, and docs now target `0.2.2b3`.
- Splash screens now stay on screen longer, show progress/status, and use richer launch animation on desktop and in the mobile companion.
- README mobile companion section now reflects the current beta feature set, setup flow, and preview graphics.
- Network/traffic diagnostics are now kept out of the standard client path and reserved for explicit local development launch.

### Fixed
- Windows taskbar/tray crash on some 64-bit systems.
- Fresh-data checks could fail because of a missing scheduler dependency import.
- Traffic Log no longer stores raw IP addresses or raw user-agent strings.
- Traffic Log rendering now escapes displayed request paths.
- Relay admin views no longer expose raw install identifiers.
- Relay admin rendering now escapes displayed table values.
- Real-mode radar now prefers ADS-B Exchange live data when a RapidAPI key is available, while caching responses so the faster radar refresh does not burn extra subscription calls.
- Radar range buttons now update the display correctly and keep mobile/desktop radar views in sync with the selected range.

---

## [0.2.2b2] - 2026-04-26

### Added
- Scheduler control API and UI controls for checking scheduler status and restarting a sleeping scheduler.
- WebSocket sync events for config changes and scheduler restarts so desktop display windows, Admin, and mobile stay in sync.
- Server crash-report endpoint for mobile/server crash submissions with duplicate suppression.
- Richer feedback context so mobile reports include client environment alongside server environment.
- macOS release zip and `.sha256` checksum generation for GitHub Releases.
- README preview gallery with sample FIDS, Radar, and Settings screenshots.

### Mobile Companion
- Matrix configurator screen with panel presets, row count, brightness, view selection, preview text, and MicroPython config output.
- Mobile airport/config sheet for searching airports, changing source, changing update interval, and managing local airport profiles.
- Animated launch overlay using the companion app icon.
- Flight Island for pinned or active flight focus.
- Long-press flight actions for pinning and details.
- In-app feedback form.
- Mobile crash reporting with client-side deduplication.
- Persistent pinned flights.
- Admin updates and connection status in the mobile API client.
- Safer layout handling for notched iPhones and iPads.

### Changed
- Scheduler-relevant config changes now wake the scheduler immediately instead of waiting for the previous sleep interval.
- Desktop display, FIDS, Radar, Admin, and mobile now refresh or reload on live sync events.
- Release docs now separate packaged release installs from source-checkout installers.
- README now presents desktop release installation before mobile developer-preview instructions.
- Mobile main navigation now contains FIDS, Radar, History, and Settings; Matrix and Admin are launched from Settings.
- Mobile header now shows airport/live status plus UTC and local time.
- Pinned flights persist locally and sort back to the top of the mobile FIDS list.
- Mobile feedback/crash submissions now share a common JSON POST helper.

### Fixed
- Mobile dependency metadata now matches `0.2.2-b2`.
- macOS code signing no longer fails when optional entitlements are absent.

---

## [0.2.2b1] - 2026-04-26

### Added
- macOS source-checkout `.app` bundle installer.
- Pre-rendered macOS app icon asset for systems without SVG conversion tools.
- Initial React Native / Expo mobile companion preview.
- Mobile FIDS shell styled after an airport-board mobile mockup.
- Mobile server URL storage.
- Mobile WebSocket listener for live updates.

### Changed
- Version metadata updated to `0.2.2b1` for Python, runtime fallbacks, PyInstaller fallback, docs, and release guidance.
- Mobile package metadata uses npm prerelease version `0.2.2-b1`.
- Mobile dependency pins updated for the current Expo SDK.

### Notes
- Mobile install/build verification should be run on the Mac/Xcode machine.

---

## [0.2.1b2] - 2026-04-26

### Added
- Versioned launch splash screen before setup/display.
- Regression coverage for key scheduler, storage, route, and runtime-state behavior.
- Windows release zip checksum output.
- Cross-platform startup model for Windows, macOS, Raspberry Pi, and Linux.
- Desktop kiosk browser launcher.
- Cross-platform tray/taskbar support.
- Raspberry Pi installer and management helper.
- Shared navigation bar across app pages.
- FIDS arrivals/departures toggle improvements.
- Flight detail drawer with times, position, operational details, and recent history.
- Settings page improvements.
- Admin hub with scheduler status, API budget, connection count, history stats, METAR, log tail, and update checks.
- SQLite flight history database and history browser.
- Five display skins: standard, technical, neon, cyan, and CRT.
- PyInstaller desktop packaging.
- Version badge in the app UI.
- API-key error banner on the FIDS board.
- Quit confirmation modal.
- User feedback/report page.
- RapidAPI key validation during setup.
- Buy Me a Coffee link in Admin.
- Per-flight detail data for desktop and mobile clients.
- Setup reset option.
- GitHub release update check.

### Changed
- Desktop launchers and Pi kiosk now open through the splash screen.
- Runtime snapshots now live in the user data directory, while legacy source-tree snapshots remain readable.
- Installer docs now distinguish source-checkout installers from packaged release artifacts.
- README rewritten from an end-user perspective.
- Installer layout reorganized by platform.
- Windows source installer clarified as source-only.
- Shutdown now exits the app more reliably after closing browser processes.

### Fixed
- Snapshot pruning now runs during snapshot jobs.
- Failed fetch cycles preserve the previous successful fetch timestamp.
- Duplicate config route registration removed.
- Local AviationStack file loading now checks current and legacy snapshot locations consistently.
- Example environment files no longer include private operator Linear variables.
- Windows source installer detects Python more reliably and supports additional install flags.
- Windows launcher UTF-8 comment issue fixed.
- RapidAPI and OpenSky signup links fixed.
- Tray quit no longer logs a false crash.
- VATSIM aircraft type extraction handles heavy-prefix formats.
- Navigation template syntax issue fixed.
- Windows console encoding issue during build fixed.

---

## [0.1.0] - 2025-03-01

### Added
- Initial release.
- FastAPI web server and browser FIDS board.
- WebSocket live push.
- AviationStack schedule data source with monthly budget guard.
- ADS-B Exchange position enrichment.
- OpenSky Network position fallback.
- VATSIM virtual traffic source.
- METAR weather display.
- Radar view with sweep animation.
- Split FIDS/Radar display.
- Matrix preview.
- MicroPython client for Pimoroni Interstate 75 W.
- First-run setup wizard.
- SQLite flight history.
- Raspberry Pi ADS-B receiver support.
