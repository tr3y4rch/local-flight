# Changelog

All notable changes to Local Flight are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.5b3] - 2026-05-01

### Added
- Shared relay schedule snapshots for community and managed installs via `GET /v1/schedule`, so the relay can fan out one upstream AviationStack refresh to many clients watching the same airport window.
- Relay-side schedule cache metadata and savings stats in admin/settings payloads, including shared access counts, upstream pull counts, cache-hit rate, and estimated savings.
- AviationStack audit script (`scripts/audit_aviationstack.py`) for comparing baseline, paginated, and fair windowed fetch strategies across a global airport sample.
- Configurable board-density controls for real-data fairness and overflow handling: `display_grace_minutes`, `display_horizon_hours`, `web_row_limit`, `web_rotation_seconds`, and matrix page rotation.

### Changed
- AviationStack schedule fetching now uses a shared date-aware planner across BYOK, direct local relay-key use, and hosted relay-backed paths: page size `100`, airport-local date windows, and per-date pagination.
- Community and managed installs no longer consume raw provider JSON from the relay. They now receive Local Flight canonical records and continue the normal local normalize, enrich, history, and FIDS pipeline.
- Community relay budget wording now reflects the actual model: `LOCALFLIGHT_RELAY_MONTHLY_LIMIT` tracks per-install relay schedule accesses, while upstream AviationStack pulls are shared and counted separately on the relay.
- Web and matrix boards now rotate overflow pages locally instead of forcing a single fixed visible slice.

### Fixed
- Matrix clients now clear stale rows when a refresh fails or returns empty data, avoiding misleading leftovers and tight retry hammering.
- Bug reports now attach truthful schedule-mode context for BYOK, direct local community-key, and shared relay snapshot paths, plus the active display window and web board density settings.
- Automatic crash deduplication is now scoped by crash context as well as message, and the mobile crash boundary copy now reflects best-effort report delivery more honestly.
- Relay production packaging now bundles the `localflight` schedule helpers inside the Fly image, so the shared `/v1/schedule` route works live instead of failing with `ModuleNotFoundError`.

---

## [0.2.5b2] - 2026-04-30

### Added
- iOS-first companion polish pass across the Expo shell, including the longer branded launch overlay, stronger crash-reporting context, and cleaner companion identity reporting.
- Mobile settings/admin support for the refined desktop relay and diagnostics surfaces, keeping the companion aligned with the latest server controls.

### Changed
- The companion now feels closer to the supplied airport-board mockup in daily use, with the updated FIDS shell, launch flow, and diagnostics-aware reporting path.
- Public mobile docs now describe the current beta scope more accurately instead of treating the companion like a bare phase-one scaffold.

### Fixed
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
- Fly.io deployment guidance and defaults for the hosted community backend, including the public relay host `relay.localflight.app` and the separate operator host `network.localflight.app`.
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
