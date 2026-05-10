# Internal Native-First PySide6 Redesign Tracker

This is an internal engineering/handoff note, not end-user install guidance. It preserves the PySide6 native-first redesign plan so future work can keep the direction intact while the browser/LAN UI remains a supported display surface and parity reference during hardening.

For user-facing install and display-choice guidance, use:

- [Install Guide](install.md)
- [Display Modes](display-modes.md)

## Goal

Redesign the PySide6 app as the recommended primary desktop GUI while keeping the browser/LAN UI as a permanent supported access and display surface.

- Keep FastAPI as the local backend and source of truth.
- Use the browser/LAN UI as the parity checklist, not as a layout to copy.
- Keep browser pages supported for LAN access, headless installs, display kiosks, and recovery.
- Do not plan to remove human-facing browser routes; keep them aligned with the supported local API contract.
- Keep Operator Network Admin separate from the public client GUI.

## Chosen Direction

- Approach: Native Redesign Now.
- Browser/LAN role: Supported access and display surface.
- Public APIs: preserve existing local HTTP/WebSocket contracts first.
- Native implementation style: Qt-native widgets, models, canvases, dialogs, and shell behavior rather than HTML mimicry.
- Public client GUI audience: hobbyist/end-user first. The native app should explain problems in plain language, give a simple next step, and keep enough technical trace context available for support without making server internals the main visible message.

## End-User Feedback Rule

The primary native GUI is not an operator console. It can expose diagnostics and traceability, but its first visible layer should be safe, calm, and understandable for a hobbyist running Local Flight at home, on a Pi, or on a display.

Message pattern:

1. Plain state: what the user needs to know.
2. Next step: what Local Flight is doing or what the user can do.
3. Trace detail: short technical hint, route, timestamp, report id, or log link only when useful.

Examples:

- Good: `Updating arrivals. First refreshes can take a moment while airport data is prepared.`
- Good: `Connection interrupted. Keeping the board ready and trying again shortly.`
- Good: `Provider key needs attention. Open Settings to update the schedule data key.`
- Good trace detail: `Details: /api/fids at 03:41:22` or `Report ID: LF-...`
- Avoid as primary text: raw stack traces, raw HTTP exceptions, provider jargon, relay internals, SQL errors, token values, install ids, or unredacted request payloads.

Crash/server feedback rule:

- Automatic crash and server error reports remain gated by diagnostics settings.
- User-visible crash copy should say what happened and whether a report was saved/sent.
- Technical details belong behind `Details`, `Logs`, or `Report` surfaces, redacted by default.
- Every reportable issue should include a traceable local context string: screen/page, route/action, app version, platform, diagnostics mode, and timestamp.
- Never expose secrets, activation tokens, provider keys, raw install ids, or long log tails in the ordinary client UI.

## Separation Of Power And Secret Hygiene

Treat Local Flight like commercial software even while it is free. The public app must never ship developer/operator power, internal secrets, private defaults, privileged relay/admin values, or anything a determined user could extract from files, binaries, logs, templates, mobile bundles, or generated scripts.

Hard rules:

- No developer-owned API keys, Linear keys, relay admin passwords, provider keys, signing credentials, activation master tokens, private endpoint passwords, or privileged operator values in repo-tracked code, docs, templates, test fixtures, built artifacts, mobile bundles, matrix scripts, or sample config.
- No hidden "temporary" internal values in the GUI, local defaults, packaged `.env`, compiled assets, comments, screenshots, generated docs, or installer scripts.
- Public client GUI can call only local owner/client routes and public relay routes intended for clients.
- Operator Network Admin stays separate from the public client GUI and must use explicit operator-provided credentials.
- Local user-owned keys are stored locally, redacted in UI/logs/reports, and never forwarded except to the intended provider/relay endpoint.
- Diagnostics/reporting payloads must redact secrets, raw tokens, raw install IDs, provider responses that include credentials, and long logs before leaving the machine.
- Mobile and Matrix clients receive only the minimum public/local configuration required to operate.
- Tests may use fake values only, with names that cannot be mistaken for real credentials.
- Build and installer flows must fail closed or prompt the operator; they must not silently fall back to embedded private credentials.

Power boundaries:

| Surface | Allowed power | Not allowed |
|---|---|---|
| Native client GUI | Local display, local settings, local feedback, local scheduler controls. | Relay admin operations, developer secrets, raw provider/admin credentials. |
| Browser/LAN UI | Same public/local client capabilities as native for LAN access, headless installs, and browser-mode displays. | Hidden privileged routes or admin-only relay controls. |
| Mobile companion | LAN client display/settings subset and diagnostics by consent. | Admin mutations beyond explicitly trusted local-owner actions. |
| Matrix client/script | Read display feed, identify device, ping/check in. | Provider keys, relay secrets, admin actions. |
| Operator Network Admin | Relay/admin inspection and actions with supplied operator credentials. | Shipping or deriving credentials from the public app. |
| Relay/server infrastructure | Owns shared secrets and privileged upstream/provider access. | Exposing private secrets to client payloads, logs, reports, or generated artifacts. |

Acceptance gate for every page/release:

- Search for secret-like values before packaging.
- Review new API payloads and report contexts for redaction.
- Confirm no UI path reveals raw tokens, keys, install IDs, private relay internals, or operator-only action refs unless explicitly on the operator admin surface.
- Confirm packaged artifacts work from user-provided config, activation, or local stored settings rather than embedded internal power.

## Architecture Target

- `NativeShell`: main window, routing, fullscreen, quit, top chrome.
- `NativePageRegistry`: page id, title, nav group, lazy factory, refresh policy, required routes, browser parity source.
- `NativeApiService`: native-facing adapters over existing local FastAPI routes.
- `NativeLiveBus`: `/ws` connection, reconnect, decoded live event dispatch.
- `NativeTheme`: existing `theme` + `skin` config mapped into Qt tokens, icons, typography, and reusable widgets.
- Reusable Qt primitives:
  - `FlightBoardModel`
  - `HistoryModel`
  - `RequestLogModel`
  - `StatusCard`
  - `WeatherStrip`
  - `DetailDrawer`
  - `AirportSearchBox`

## Page Migration Order

1. FIDS standalone page/model/function parity.
2. Radar standalone canvas/screen parity.
3. Display split view composition and fullscreen behavior.
4. Setup wizard.
5. Settings + profiles + docs.
6. Matrix V2 tooling.
7. History + Logs + Requests.
8. Admin summary + Feedback/crash diagnostics.
9. Browser/LAN parity and wording cleanup pass.

## Browser Parity Checklist Per Page

Before calling a page migrated, compare against its browser template for:

- Data loaded.
- User actions.
- Live-update behavior.
- Empty/loading/error states.
- End-user copy, safe diagnostics, and traceable support context.
- Theme/skin behavior.
- Keyboard/window behavior.
- Tests.

Every page must map errors into three layers:

- User text: short, non-alarming, action-oriented.
- Support hint: route/action/status/time, redacted.
- Developer detail: logs/report payload only in Logs, Feedback, or diagnostics surfaces.

Browser templates to treat as source specs:

- `setup.html`: first-run wizard, relay activation, BYOK/VATSIM, diagnostics.
- `display.html`: split FIDS/Radar with fullscreen and saved layout.
- `fids.html`: board rotation, detail drawer, status/weather/source rendering.
- `radar.html`: native radar canvas, surface overlay, METAR, range behavior.
- `matrix_preview.html`: Matrix V2 config/device/script workflow.
- `settings.html`: airport/search/source/theme/skin/profiles/docs/setup reset.
- `admin.html`: local user-facing admin summary.
- `requests.html`: anonymized local traffic log viewer.
- `logs.html`: retained logs and live tail.
- `history.html`: browse/search/stats/detail.
- `feedback.html`: manual report and attached native context.

## Current Status

Current beta snapshot as of 2026-05-09:

- Native FIDS, Radar, Settings, Setup, Matrix, History, Logs, Admin, Feedback, and Display are no longer treated as throwaway placeholders. The active direction is native-first hardening with the browser/LAN UI kept as a supported display surface and spec reference.
- FIDS has moved from a table-like visual target toward a custom passenger-board surface, with operating-flight priority, codeshare rotation, status/gate chips, loading feedback, and a restyled flight-detail drawer.
- Radar has moved through the staged runway/map/blip-state/native-polish plan. It now has a radar domain layer, `/api/radar/map`, runway/surface/map/terrain toggles, local ghost trails, conservative blip states, compact hover/click details, and contrast-safe layer drawing.
- Settings has been extracted and redesigned around primary user controls, an explicit apply action, collapsed help/diagnostics/advanced drawers, profile controls, and radar-surface feedback.
- Setup has been extracted and redesigned as a guided six-step first-run flow with Community Relay as the beginner default, BYOK/VATSIM alternatives, provider links, diagnostics choice, and clear relay/key test feedback.
- Secret hygiene remains a release gate: public GUI pages must not expose raw provider payloads, activation tokens, install IDs, pilot identities, private relay internals, or operator-only action refs.

Foundation slice has been implemented.

Added:

- `src/localflight/native/registry.py`
- `src/localflight/native/service.py`
- `src/localflight/native/live.py`
- `src/localflight/native/models.py`
- `src/localflight/native/widgets.py`

Wired:

- Current shell now consumes the page registry for page order, nav grouping, eager/lazy loading, and fallback refresh group.
- Current shell now uses `NativeLiveBus` for WebSocket connection lifecycle.
- `localflight.native.app` exports the new foundation pieces.

Verified:

- `python -m compileall -q src tests`
- `python -m pytest tests/test_gui_launcher.py -q` -> `56 passed`
- `python -m pytest tests -q` -> `194 passed`

Known note: pytest may still emit a Windows temp cleanup `PermissionError` after a successful run; the suite itself passed.

End-user feedback baseline has been added to the plan.

This is now a required rule for every native page migration:

- Public pages display simple, helpful messages first.
- Technical/server/crash context remains traceable but tucked into diagnostics, logs, report metadata, or a concise details line.
- Provider/relay/API wording should be translated into user-facing concepts unless the page is explicitly a diagnostics/admin surface.

Service-routing slice has started.

Moved active read/data-shaping paths behind `NativeApiService` while preserving the working beta web-kiosk behavior and visuals:

- Setup install info and airport search.
- FIDS board fetch, METAR companion fetch, and flight detail fetch.
- Radar payload, optional surface overlay, and METAR fetch.
- Matrix V2 state, preview feed, and V1 compatibility rows/config.
- Settings config/install reads and airport search.
- Admin summary reads, including system, budget, connections, scheduler, updates, METAR, and history stats.
- Requests, History, Logs, and Feedback context reads.

Then moved remaining native mutating actions behind `NativeApiService`:

- Setup activation/status/key tests/complete/reset.
- Matrix V2/V1 config mutations, device assignment, and script generation.
- Settings save, scheduler restart, and profile save/load/delete.
- Feedback submit and app quit.

Important: this slice intentionally keeps page layout/rendering mostly unchanged. The browser/LAN UI remains the visual and behavior checklist while the service layer becomes the shared native plumbing.

FIDS function/parity routing checkpoint:

- `fids.html` currently depends on `/api/metar`, `/api/health`, `/api/fids`, `/api/fids/detail`, and `/ws`; the native FIDS page registry now tracks those routes explicitly.
- `NativeApiService.fids_board()` now fetches scheduler health alongside config, board rows, and METAR so native FIDS can show the same scheduler/API-key error banner behavior as the browser UI.
- `LocalApiClient` now identifies native requests with local request-log headers:
  - `X-LocalFlight-Client-Type: native`
  - `X-LocalFlight-Client-Platform`
  - `X-LocalFlight-Companion-Id` populated from the local install id when available.
- Feedback/crash routing remains explicit: `/api/feedback`, `/api/feedback/crash`, `/api/admin/system`, and `/api/setup/client-info`.

FIDS extraction checkpoint:

- `FidsScreen` has moved out of the compatibility module into `src/localflight/native/pages/fids.py`.
- `localflight.native.app` exports the extracted page directly.
- The compatibility display/split view now composes FIDS via the page module boundary.
- The board is backed by `FlightBoardModel` and shown through `QTableView` instead of direct `QTableWidget` item construction.
- FIDS uses the shared `WeatherStrip` and `DetailDrawer` primitives while preserving page-specific route/status text.
- Row click detail fetch is preserved and tested against paged/rotated visible rows, so clicking a visible flight still fetches the correct `/api/fids/detail` callsign.
- Detail rendering still separates real schedule/enrichment fields from virtual/VATSIM flight-plan and network-position fields.

FIDS visual polish checkpoint:

- `FlightBoardModel` now carries native visual roles for status dots, status color, dimmed completed/cancelled rows, strong time/flight typography, strikeout cancellation, row tooltips, and accent backgrounds.
- `FidsScreen` now installs a real `QStyledItemDelegate` painter for the board, so status pills, colored dots, gate pills, left accent bars, and stacked flight/airline/codeshare rows are drawn as Qt graphics instead of depending only on text.
- The plain model fallback is also visual now: if Qt does not take the custom delegate path, delayed rows still get red foreground/background roles, clean status text, and one rotating codeshare frame in the Flight cell.
- Delayed rows now use the same red family as the browser UI, including a stronger full-row tint, a left status rail, and a painted red delay tag. Native row shaping preserves the API's `HH:MM (+N)` suffix and can derive it from `delay_minutes` when raw schedule times are present.
- Codeshare/add-on flight info now falls back across `codeshare_display`, `codeshare`, `sold_as`, and `codeshares[]`, so rows with only the raw list still show the shortened shared flight numbers.
- Operating/actually-flying airline remains the primary accented flight number. Codeshare/sold-as values are normalized to short IATA-style flight numbers (`UA 9000`, `AC 7000`) and cycle as a compact accent pill in the flight info field instead of rendering as a static prose line.
- The native board cache now keeps the configured visible row count filled from the cached payload by promoting active chronological rows ahead of completed rows. Departed/landed/cancelled flights remain in the cache, but slide behind active rows so new upcoming flights replace them on the first board page.
- The extracted page now applies table-specific `QTableView#FidsTable` styling for dark board density, hover affordance, selection, row padding, and header treatment.
- Weather strip tone is mapped from METAR mood (`good`, `caution`, `bad`) into native frame styling.
- Refreshes briefly mark rows as fresh and run a timer-driven fade pulse across the visible rows.
- FIDS loading/empty-state copy is now operator-facing rather than implementation-facing. In-flight refreshes show an indeterminate native progress bar, while quiet windows explain that Local Flight will keep checking automatically without exposing relay internals.
- Header title now carries lightweight arrival/departure direction symbols while ARR/DEP buttons remain compact.
- Offscreen render smoke check caught and fixed a bright system alternate-row fallback in `QTableView`.

Radar inventory checkpoint:

- Browser source spec: `src/localflight/ui/templates/radar.html`.
- Native page boundary is now standalone: `src/localflight/native/pages/radar.py` owns `RadarScreen`.
- Native canvas boundary is now standalone: `src/localflight/native/canvas/radar.py` owns `RadarCanvas`.
- `localflight.native.app` exports `RadarScreen` and `RadarCanvas` directly instead of forwarding those names through the compatibility module.
- Required native routes are already declared in the page registry: `/api/config`, `/api/radar`, `/api/radar/surface`, and `/api/metar`.
- `/api/radar` source behavior:
  - Real mode first tries ADS-B Exchange via direct RapidAPI or managed radar relay when available.
  - Real mode falls back to cached local snapshot positions.
  - Real mode then falls back to live OpenSky radar blips when the snapshot has no positions.
  - Virtual mode uses live VATSIM pilots only, filtered to flight plans departing from or arriving at the configured airport ICAO.
  - All modes crop/filter to the requested radius.
  - Ranges at `<=5nm` are treated as surface mode and keep ground targets while hiding airborne targets.
  - Wider ranges are airborne mode and hide ground targets.
- `/api/radar/surface` source behavior:
  - Returns disabled/empty when `radar_surface_enabled` is false.
  - Uses relay-cached OpenStreetMap airport surface when available.
  - Falls back to local stale cache when relay surface fetch fails.
  - Falls back to an estimated local surface payload when no cache is available.
- Current native Radar keeps the sweep canvas, range buttons, METAR strip, surface overlay projection/cache, VATSIM-safe tooltips, hidden ground/airborne count handling, and traceable user-facing status copy.
- Radar status copy now follows the hobbyist/end-user feedback rule: visible state first, concise `/api/radar` trace context second.
- Radar API/config/live wiring checkpoint:
  - `NativeApiService.radar()` now returns the config used for the fetch along with payload, surface, weather, and redacted error hints.
  - `RadarScreen` applies config updates to the title/source context and refreshes on `config_updated`, `snapshot_updated`, and `scheduler_restarted`.
  - `RadarCanvas` emits a hover signal for the current blip, clears it when leaving or on new payloads, and keeps a small highlight ring on the hovered target.
  - `RadarScreen` shows a compact hover info panel with safe basic fields only: callsign, route, aircraft type, altitude, speed, heading, distance, source, and VATSIM flight rules/planned altitude when present. Pilot names, CIDs, install details, provider secrets, and raw payloads stay hidden.
- Radar native canvas checkpoint:
  - `RadarCanvas` now paints in explicit layers: background, optional terrain, airport surface, grid/center mark, optional procedures, sweep, aircraft, hover, footer.
  - Airport surface drawing stays intact and closer to `radar.html`: range-based surface fade, closed feature fills, runway fills, runway labels, boundary dash style, OSM/estimated attribution, and cached projection.
  - Future approach/departure recognition can feed `set_procedures()` with approach/departure/transition paths without changing the current `/api/radar` payload.
  - Future terrain or heightmap work can feed `set_terrain()` with contour/feature geometry without mixing terrain logic into the traffic or airport-surface layer.
- Radar intelligence/options checkpoint:
  - `/api/radar` now adds safe derived blip status fields (`radar_phase`, `radar_status`, `radar_status_label`) such as `Descending`, `On approach`, `On final`, `Departing`, and `On ground`.
  - `/api/radar/surface` annotates runway features with validation metadata: OSM is the runway geometry source when available, and the local OurAirports airport center is used as an internal sanity check. Estimated fallback surfaces are clearly marked as estimated.
  - Native Radar has local user toggles for `Surface`, `Status`, `Routes`, and `Relief` so the default screen stays simple and hobbyist-friendly.
  - `Routes` draws lightweight approach/departure hint lines from safe blip route data. These are not formal procedure recognition yet.
  - `Relief` draws estimated cartographic relief only. OSM building/surface data is not a real terrain heightmap, so this must remain visibly optional and eventually be replaced by a real DEM/terrain source if terrain awareness becomes a product feature.
- Radar final-form domain checkpoint:
  - `localflight.radar` now owns shared radar domain helpers for ADS-B normalization, stable display units, runway/map layer shaping, and conservative blip classification.
  - ADS-B Exchange normalization preserves useful public fields such as geometric altitude, vertical rate, nav heading/selected altitude, nav modes, emergency/squawk, aircraft category, position age, and source-quality hints without exposing raw provider payloads.
  - `/api/radar` remains backward compatible and now accepts optional traffic/altitude filters while adding `traffic_role`, phase confidence/reason, runway match hints, and ft/kt/fpm display fields.
  - `/api/radar/map` exposes the native/mobile map layer contract: runways, simplified surface features, terrain availability metadata, attribution, and source confidence.
  - Runway merging is ready for a bundled `decode/mappings/runways.csv.gz` OurAirports file when added; until then it uses OSM/cache/estimated surface features without breaking the screen.
  - Native Radar now consumes the map endpoint, draws runways separately from other surface detail, keeps compact filters, and shows confidence/reason/runway details in hover copy.
  - Verified: `python -m compileall -q src tests`, `.venv\Scripts\python.exe -m pytest tests -q` -> `216 passed` with the known Windows pytest temp cleanup warning after success.
- Radar Stage 2 runway map checkpoint:
  - OurAirports runway handling now has a real local-first data path: bundled `decode/mappings/runways.csv(.gz)` when present, user cache at `~/.localflight/data/runways.csv.gz`, and an explicit cache refresh helper using the official public-domain OurAirports GitHub-hosted CSV.
  - `/api/radar/map` can opt into runway refresh through `refresh_runways=true`, but ordinary radar/map loads do not require network access and keep using cached, bundled, OSM, or estimated data.
  - Runway merge now matches OSM to OurAirports by label first and by heading/midpoint proximity when OSM lacks runway labels. Merged runway features carry validation metadata, heading delta, endpoint distance, length/width/surface/lighted/closed fields when available.
  - Native radar runway drawing now treats runways as their own layer: width-aware strokes, dashed estimated runways, closed-runway red styling, threshold ticks, endpoint labels, and source-confidence labels at readable ranges.
  - Surface clutter remains simplified by range: taxiways/aprons fade out on wider scopes while runway and terminal/boundary information remain the focus.
  - Verified: `python -m compileall -q src tests`, `.venv\Scripts\python.exe -m pytest tests -q` -> `219 passed` with the known Windows pytest temp cleanup warning after success.
- Radar Stage 3 blip-state checkpoint:
  - Blip classification now adds a simple `motion_trend`/`motion_label` alongside `radar_phase`, confidence, and reason so the native UI can show climb/descent/level/cruise context without becoming a controller scope.
  - Unknown-intent real traffic that is low, descending, and runway-aligned is marked as low-confidence `Approach`, not `On final`, unless route/intent data supports a stronger label.
  - Native `RadarCanvas` now keeps a very small local-only track history for visible targets. It draws subtle ghost positions and a faint trail from payloads already received, with no extra API requests.
  - Direction indicators are now light arrow ticks based on `track_deg`, `heading`, `nav_heading`, or the local ghost trail when no heading is available.
  - The feature remains intentionally restrained: no complex tags, no controller-grade detail, and no additional polling.
  - Verified: `python -m compileall -q src tests`, `.venv\Scripts\python.exe -m pytest tests -q` -> `222 passed` with the known Windows pytest temp cleanup warning after success.
- Radar Stage 4 native UI polish checkpoint:
  - The default native Radar surface is now intentionally calmer: range and refresh stay up front, while traffic filters and intelligence layers live in a small `View` drawer instead of a prominent second toolbar.
  - Runways and surface remain enabled as the useful map baseline. Status labels, route hints, and terrain stay opt-in so hobbyist users are not hit with a busy screen by default.
  - The canvas now suppresses most callsign labels at wider ranges and always restores the hovered target label, keeping broad-range views readable without hiding hover/click detail.
  - The compact source line still reports provider/range/surface context, while the small filter summary only appears when the view is actually filtered or optional layers are enabled.
  - Verified: `python -m compileall -q src tests`, `.venv\Scripts\python.exe -m pytest tests/test_gui_launcher.py -q -k "radar"` -> `11 passed`, `.venv\Scripts\python.exe -m pytest tests -q` -> `223 passed` with the known Windows pytest temp cleanup warning after success.
- Radar regression/polish checkpoint:
  - Embedded native Radar now uses a compact range selector and a smaller canvas minimum so Display split mode does not inherit the wide standalone range-button row.
  - Native `RadarCanvas` now caches static map/grid/surface/procedure layers and repaints only sweep, blips, trails, hover, and footer each animation tick.
  - Wide-range labels are quieter, runway confidence text is limited to close ranges, and the browser UI picked up only low-risk label thinning plus local ghost/direction hints.
  - Native API access now prefers `/api/radar/map` for surface/runway data and calls `/api/radar/surface` only when map loading fails. Server-side radar map building has a small internal cache reused by `/api/radar/map` and `/api/radar` classification.
  - Verified: `python -m compileall -q src tests`, `.venv\Scripts\python.exe -m pytest tests/test_gui_launcher.py -q -k "radar or native_service_prefers"` -> `15 passed`, `.venv\Scripts\python.exe -m pytest tests/test_important_regressions.py -q -k "radar_map or radar_template or api_radar"` -> `12 passed`, `.venv\Scripts\python.exe -m pytest tests -q` -> `228 passed` with the known Windows pytest temp cleanup warning after success.
- Radar map/terrain visibility checkpoint:
  - Native `RadarCanvas` now uses a contrast-safe radar palette separate from generic theme colors so runways, map context, terrain, blips, labels, and range rings remain distinguishable in dark and light modes.
  - Static layer order is explicit: background, surface, map, terrain, grid, runways, procedures, then dynamic sweep/blips/trails/hover/footer.
  - The grid painter now forces `NoBrush`, fixing the regression where filled range rings could repaint over otherwise-loaded map and terrain features.
  - OSM map points arriving as `"lat lon"` strings are parsed as well as numeric coordinate arrays, so cached map geometry can draw reliably.
  - Runway labels and confidence text are limited to close ranges to avoid runway text clutter at 5/10/20/40 NM.
  - Verified: `python -m compileall -q src/localflight/native/canvas/radar.py src/localflight/radar`, `.venv\Scripts\python.exe -m pytest tests/test_important_regressions.py -q -k "radar_map or native_service_prefers or api_radar"` -> `15 passed`, `.venv\Scripts\python.exe -m pytest tests -q` -> `271 passed`.

## What To Do Next

Continue from the current native beta state, not from the earlier shell foundation.

Recommended next slice:

1. Run visual QA for Radar overlays across at least ZRH and LAX:
   - 1/2/3/5 NM surface mode.
   - 10/20/40 NM airborne mode.
   - map on/off, terrain on/off, runways on/off, surface on/off.
   - dark/light theme contrast.
   - no OSM cache, stale cache, and estimated fallback states.
2. Tighten Display split composition now that FIDS and Radar have standalone native surfaces.
3. Continue full native extraction/polish for Matrix, History, Logs, Requests, Admin, and Feedback until each page has native tests and browser-parity checklists.
4. Keep browser/LAN parity checks running as native acceptance passes, because both surfaces remain supported.

## Page-by-Page Feedback Map

Use this when migrating or polishing each page:

| Page | User-facing message style | Traceable support context |
|---|---|---|
| FIDS | Board updating, no flights in this window, provider key needs attention, connection retrying. | `/api/fids`, `/api/fids/detail`, `/api/metar`, scheduler health state, timestamp, view, airport. |
| Radar | Radar updating, no aircraft currently visible, surface/map/terrain unavailable, range adjusted. | `/api/radar`, `/api/radar/map`, `/api/radar/surface`, `/api/metar`, radius, airport, layer toggles, surface enabled flag. |
| Display split | Screen layout saved, one side temporarily unavailable, fullscreen/window state. | composed page ids, splitter mode, active routes, refresh event. |
| Setup | Plain setup choices, key/activation tests as pass/fail with next step, diagnostics choice explained. | `/api/setup/*` action, provider test result status, diagnostics mode, no raw keys/tokens. |
| Settings | Saved, restart queued, profile loaded, setup reset confirmation. | changed config keys, scheduler restart route, profile name, timestamp. |
| Matrix | Device not seen yet, script ready, preview using current board, Wi-Fi/server URL reminder. | config id, device id/ref, `/api/matrix/*` route, feed timestamp. |
| History | No records yet, filters too narrow, detail unavailable. | `/api/history`, callsign, filter window, DB stats. |
| Logs | Friendly retained-log browser with clear privacy note. | file name, selected offset/tail time, redacted content only. |
| Requests | Local traffic summary for troubleshooting, not scary network language. | client type/id prefix only, route, status code, latency. |
| Admin summary | Health cards and clear actions, no operator-only relay internals. | `/api/admin/*` route, scheduler state, budget status, update check. |
| Feedback/crash | Report sent/saved/failed with simple retry guidance. | report route, diagnostics mode, app version, screen, generated report/ref id if returned. |

## Working Reminder For Future Page Tasks

When working on any native page:

- Open this note first.
- Identify the matching browser template.
- List the browser behaviors before editing.
- Keep the local HTTP API unchanged unless absolutely necessary.
- Prefer shared native services/models/widgets over page-local copies.
- Preserve current tests, then add focused parity tests for the page.
- Avoid browser layout mimicry when a Qt-native control is clearer.

## Browser/LAN Support Gate

Do not regress or remove browser/LAN UI support. Before release, confirm:

- Human-facing browser pages still load through the local FastAPI server.
- Native setup works first-run on Windows and macOS.
- Pi headless and Chromium kiosk paths still expose the LAN UI at `http://localflight.local:8000`.
- Mobile and Matrix clients remain unaffected.
- Local API routes still serve non-GUI clients.
- Native and browser wording presents the browser/LAN UI as a supported path.
