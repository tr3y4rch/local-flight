# Local Flight — public-safe Codex context

This committed file is the cross-platform implementation context for AI agents
and contributors. It is safe for the public repository: do not add credentials,
private admin topology, personal filesystem paths, artifact hashes, private
build records, or operator-only runbooks here. Machine-specific additions belong
in ignored `AGENTS.local.md`; private service operations belong in the ignored
`operator/` directory.

## Product

Local Flight is a local-first, self-hosted Flight Information Display System
(FIDS) for Windows, macOS, Linux, Raspberry Pi, LAN browsers, iOS/Android, HDMI kiosk
screens, and HUB75 LED matrices. It uses Python 3.11+, FastAPI, SQLite,
WebSocket, Jinja2, PIL, and PySide6/Qt. Mobile uses React Native and Expo.

Public links:

- Product: https://beacontools.cc/local-flight
- Mobile: https://beacontools.cc/local-flight/mobile
- Support: https://beacontools.cc/support
- Network/relay explanation: https://beacontools.cc/network
- Privacy: https://beacontools.cc/privacy
- Privacy choices: https://beacontools.cc/privacy/choices
- Source: https://github.com/tr3y4rch/local-flight

## Current release line

- `pyproject.toml` is the version source of truth. The active desktop,
  Linux server, Raspberry Pi, relay-compatibility, and mobile testing line is
  `0.5.2`.
- Windows, separate Apple silicon/Intel macOS packages, x86-64/ARM64 Linux
  AppImages, Ubuntu/Debian desktop and headless packages, and Raspberry Pi are
  public package targets. Mobile is in TestFlight/Google Play testing and uses
  the permanent application identifier `cc.beacontools.localflight`.
- `0.5.2` is the platform-wide Windows, macOS, Linux, Raspberry Pi, LAN, relay,
  and mobile-testing release line. Native artifacts are built on matching
  architecture runners and uploaded with matching checksums. macOS artifacts
  additionally require Developer ID signing, notarization, and stapling.
- Current public release copy lives in `docs/release-notes-0.5.2.md` and the
  public `CHANGELOG.md`. Detailed implementation history belongs in
  `docs/engineering-changelog.md` and is not bundled as end-user help.
- Public-safe build, validation, and publication gates live in
  `docs/release-process.md`; credentials and private recovery steps do not.
- Both macOS direct-download builds are Developer ID signed and notarized
  architecture-specific `.pkg` files. Keep the signing, notarization, stapling,
  architecture, deployment-target, and checksum gates intact; never recommend
  disabling Gatekeeper.
- Rebuild every affected release artifact after included source, public docs, or
  assets change.

## Repository map

- `src/localflight/__main__.py`: platform-aware startup and crash hooks.
- `src/localflight/platform/`: platform detection, GUI decision, browser, tray.
- `src/localflight/native/`: Qt bootstrap, shell, pages, canvases, services.
- `src/localflight/native/status_tray.py`: Qt-native Windows status-area and
  macOS menu-bar/Dock actions; keep callbacks on the Qt event loop.
- `src/localflight/core/`: shared models/config and user-notice contracts.
- `src/localflight/sources/`: schedule, radar, weather, relay, Matrix clients.
- `src/localflight/storage/`: config, identity, snapshots, history, logs, usage.
- `src/localflight/ui/`: FastAPI routes, APIs, templates, static assets.
- `relay/`: hosted public relay and separately authenticated operator surface.
- `mobile/`: Expo app, native widget templates, mobile contracts.
- `site/` and `workers/`: Beacon Tools public site and release manifest Worker.
- `installers/`: Windows, macOS, Linux desktop/server, and Raspberry Pi
  installers/services.
- `scripts/`: packaging, checks, brand synchronization, and developer helpers.
- `tests/`: desktop, relay, privacy, Matrix, radar, and compatibility coverage.

## Platform model

`LOCALFLIGHT_GUI_MODE=auto|native|browser|headless` is parsed centrally.
Blank/invalid desktop values resolve to native. Windows/macOS/Linux desktop
sessions prefer the Qt shell and fall back to browser only when Qt is
unavailable. Display-less Pi/Linux stays headless. Pi native kiosk uses
separate backend and user-session
display services; Chromium kiosk remains supported. The LAN UI remains
available at the local server while native mode is running.

First launch is setup-gated. Native first launch opens the standalone setup
window before the main shell; browser/LAN first launch uses `/setup`. Scheduler
startup is deferred until setup completes.

## Data paths

Real schedule flow:

1. AeroDataBox is the preferred schedule source when configured.
2. AviationStack can fill sparse fields or act as fallback.
3. Schedule fusion produces canonical Local Flight rows and source evidence.
4. ADS-B Exchange can add live position/aircraft data; OpenSky is fallback.
5. Codeshares are deduplicated, snapshots are saved, movement history is
   written, and WebSocket clients are notified.
6. Cache and provider caps fail safely so a known-good stale board can remain.

Beacon Relay setup verifies an active Relay Access credential before completion.
Licensed deployments fail closed for missing or inactive credentials, while BYOK
and VATSIM remain separate free routes. First-board network failures use bounded
retry timing instead of sleeping for the full schedule interval. The server owns upstream
freshness, so page navigation reads cached state and never bypasses provider
timers.

Virtual mode uses VATSIM public traffic. Keep it callsign/flight-plan focused and
drop pilot/controller names, CIDs, server names, and other person-identifying
fields. Do not invent passenger gates, codeshares, registrations, or delay
analytics for virtual traffic.

Mobile has two modes:

- Companion uses a Local Flight host over LAN first and can use explicitly paired,
  encrypted Remote Companion fallback while the host is online.
- Standalone uses the public relay directly with conservative board/radar
  refresh limits and keeps deduplicated movement history on the device.

Widgets read only the bounded snapshot written by the mobile app. They never
contact LAN, relay, or aviation providers themselves.

## Local storage and privacy

Runtime state lives under `~/.localflight/`; a reset-safe identity anchor may
also live at `~/.localflight_identity.json`. Packaged provider keys live in
`~/.localflight/.env`; source checkouts use the repository `.env`.

Hard rules:

- Never commit or bundle real provider keys, relay/admin credentials, signing
  material, store credentials, service-account JSON, activation tokens, or
  private endpoint passwords.
- Raw install UUIDs are server-side identifiers. Client/UI/support surfaces use
  the public install fingerprint (Support ID) only.
- Do not expose absolute local paths, raw exceptions, tokens, provider payloads,
  or long logs in ordinary UI/API responses.
- App-written secret directories use owner-only POSIX permissions where
  supported; failures remain non-fatal on Windows.
- Manual reports are user-triggered. Automatic diagnostics require the saved
  consent mode and must be sanitized before leaving the device.
- Public clients use local-owner routes and documented public relay routes only.
  Privileged operator tooling stays separate from packaged/public navigation.
- Remote Companion envelopes are end-to-end encrypted; the relay must never
  receive the shared AES secret or readable request/response contents.
- Optional mobile support purchases unlock nothing. Store evidence is verified
  by the relay and raw evidence is not retained.

## User-facing feedback contract

Primary UI text follows three layers:

1. Plain state: what the user needs to know.
2. Next step: what Local Flight is doing or what the user can do.
3. Technical context: only in local Admin diagnostics, sanitized Logs, or Report
   metadata.

Core responses may add a `notices` array with stable code, tone, safe message,
optional next step/action, and sanitized diagnostic metadata. Existing response
fields remain compatible. Never interpolate raw exceptions into notice text.

## Local API compatibility

Important local routes include `/api/config`, `/api/fids`,
`/api/fids/detail`, `/api/radar`, `/api/radar/map`, `/api/metar`,
`/api/history`, `/api/history/summary`, `/api/mobile/summary`, Matrix V2 routes,
setup routes, feedback routes, scheduler controls, `/health`, and `/ws`.

`/api/setup/client-info` keeps the legacy `install_id` field for compatibility,
but it must contain the public fingerprint, matching `install_fingerprint`.
Raw identity is used only inside server-to-relay operations.

WebSocket events are `snapshot_updated`, `config_updated`, and
`scheduler_restarted`. Clients reconnect with backoff and retain lightweight
fallback polling.

## Native and LAN parity

Native Qt is the primary desktop shell; LAN browser UI is permanent supported
functionality, not a deprecated fallback. Preserve equivalent user actions,
data, privacy expectations, live updates, and error/empty/loading states while
using platform-appropriate controls.

Qt appearance uses both the shared stylesheet and QApplication palette. Dark
and light themes must keep text and semantic colors contrast-safe across every
skin, including custom-painted FIDS/Radar surfaces, setup, detached menus, and
native control glyphs. Keep the primary app tile consistently branded; the
small status icon may simplify/adapt for platform legibility.

FIDS priority: operating flight identity, airport-local time, city/country
title, readable weather, status/gate when real data supplies it, and safe detail
drawers. Radar keeps passenger `board_status` separate from the live
`radar_phase`, joins schedule intent only through strong identities, and uses
elevation-aware conservative phase rules with bounded hysteresis. AWS elevation
bands/contours and OSM ground context are separate, radius-aware cached layers.
The relay can share authenticated 5/10/20 NM ground snapshots and prewarm a
hybrid 20-airport set no more than once every 30 days. Automatic warming stays
feature-flagged until a manual cache inspection succeeds, and it never includes
live aircraft, schedules, weather, or per-install history.
Radar presentation is also shared: north-zero clockwise geometry, a monotonic
15-second revolution, one leading line, a 72-degree fading trail, and no blip
before the sweep crosses its bearing. Focus/selection may keep a target visible,
but every selected-detail surface must have an explicit dismissal path and stale
detail responses must not restore a cleared selection.
History counts movements rather than raw observations. Matrix preview,
Qt, LAN, and generated MicroPython share the Matrix display contract; VATSIM
presets suppress gate placeholders.

## Security and release boundaries

- `.gitignore` is the first barrier, not the only one. Packaging scripts must
  independently reject credential-like paths and internal/operator material.
- Release packages exclude `AGENTS.md`, ignored operator files, internal review
  notes, temporary renders, generated native projects, and dependency caches.
- Public brand manifests use logical source labels and hashes, never workstation
  paths. Brand master paths come from CLI arguments or local environment.
- Public docs may explain relay behavior and privacy, but not privileged admin
  routes, credentials, secret inventories, or private operations.
- Treat Local Flight as an informational display only, never navigation,
  dispatch, operational-control, or safety software.

## Development and validation

Typical source setup:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[native]"
```

Run desktop/backend validation:

```bash
python -m compileall -q src relay installers scripts tests
python -m pytest tests -q
git diff --check
```

Run mobile validation:

```bash
cd mobile
npm install
npm run verify
npm run a11y
npx expo config --type public
```

Run public-site and packaging contracts before release, then smoke fresh install
and upgrade paths on Windows, macOS, and Raspberry Pi. Physical Matrix/i75W,
Pi kiosk/service, real-provider, relay, VATSIM, Companion, Remote Companion, and
Standalone walkthroughs remain release gates where applicable.

## Code conventions

- Python 3.11+, type hints, `from __future__ import annotations`.
- Lazy environment reads; avoid module-import-time secret/config capture.
- Risky network/history/report/broadcast operations are non-fatal unless the
  action itself cannot safely continue.
- Preserve unrelated user changes in dirty worktrees.
- Use shared native services/models/widgets rather than page-local duplicates.
- Keep browser/LAN routes and local APIs working when changing native pages.
- Tests use unmistakably fake credentials only.
