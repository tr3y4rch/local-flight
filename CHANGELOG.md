# Changelog

All notable changes to Local Flight are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.2.3b2] - 2026-04-27

### Added
- Separate community and BYOK schedule tracking in Admin, including the active runtime mode, community path, and BYOK spare-call headroom.
- Local-only private key lookup for community schedule testing via ignored `dev/private/community_keys.json`.
- Managed-install activation tokens for relay-backed deployments, including relay proxy support for both AviationStack schedules and ADS-B radar.
- A dedicated network admin console for managed relay deployments, covering provider-key storage, token reshuffling and revocation, install access control, API totals, and traffic statistics.
- A read-only client link card in Settings showing the machine fingerprint, current key family, relay URL, token presence, and managed verification state.
- Direct managed-relay activation from Setup, so a normal install can connect itself to the relay and verify the path without waiting for a manual token handoff.
- Anonymous relay network tags for activation safety checks, so the network console can flag unusual bursts without storing readable IP addresses.
- A separate mobile companion identity, plus companion OS/device reporting and server-side companion check-ins for traceable mobile diagnostics.

### Changed
- Local Flight now treats the three setup paths more explicitly: community schedules, BYOK schedules, or VATSIM virtual traffic.
- BYOK AviationStack budgeting now defaults back to 90 calls/month so free-plan users keep 10 calls in reserve.
- Community relay installs now cap AviationStack schedule usage at 50 calls/month per machine, and the relay admin shows that ceiling directly.
- Community relay installs now keep that 50-call limit in a rolling 30-day local window, even if you switch to virtual traffic and back again later.
- Setup now shows the machine identity, can connect straight to the relay, and verifies the relay communication path once the managed link is active.
- Setup can now store a managed-install activation token so deployment clients can use the hosted relay without shipping vendor secrets.
- Managed relay key changes now stay relay-side and take effect for clients on their next request instead of requiring vendor keys in the shipped app.
- The network admin console now shows anonymous activation activity and manual-review exceptions instead of a default approval queue.
- Mobile companion requests now identify themselves with a separate companion ID and platform label, and server-side connection data now distinguishes server install identity from companion identity.
- Runtime fallbacks and mobile metadata now target `0.2.3b1`.

### Fixed
- Budget reporting no longer collapses community and BYOK schedule usage into one ambiguous AviationStack mode.
- Virtual radar mode stays on the VATSIM branch and is covered by regression checks so real-data fallbacks do not creep back in.
- Managed relay installs no longer inherit stale community usage counts, and the client now verifies the correct relay-linked key family before launch.

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
