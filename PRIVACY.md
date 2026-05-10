# Privacy

Local Flight is built around a simple rule: **stay local unless a feature genuinely needs a network hop.**

No accounts. No analytics SDKs. No ad tech. No sign-up flow.

This is a hobbyist/open-source project, not a legal document, but the app is designed to be privacy-minimal and GDPR-friendly: collect as little as possible, keep identifiers technical and install-scoped, and make diagnostics opt-in.

---

## Quick Summary

- Your config, API keys, snapshots, history, and logs stay on your own machine.
- The desktop native GUI is a real Qt shell, not a webview. The primary client does not launch Chrome, Edge, Chromium, QWebEngine, or a browser profile.
- Native mode avoids browser sync, extensions, cookies, browsing history, default-browser behavior, online fonts, and CDN assets for the main Local Flight window.
- The LAN browser UI, mobile companion, and Matrix board talk to your Local Flight server over your LAN. The mobile and Matrix clients do not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.
- Community mode can use the hosted Local Flight relay for shared schedules and relay-backed radar. Optional radar runway/surface/map/terrain layers use cached public data where available, stay opt-in/visual-only, and do not create Local Flight accounts or user profiles.
- Richer FIDS/Radar/History detail views reuse data Local Flight already fetched or stored locally. Opening a detail panel should not trigger surprise per-flight paid provider calls.
- Matrix gate/stand display uses existing real-world schedule fields when available. VATSIM Matrix presets hide gate data instead of inventing placeholders.
- Manual reports are always your choice. First-run setup asks how diagnostics should work, saves that choice locally, and defaults to manual-only reporting.
- Mobile automatic diagnostics require two yeses: the mobile app's local diagnostics choice and the connected server's diagnostics mode.
- Developer reporting credentials are kept on the hosted relay, not in the desktop package, mobile app, installers, or docs.

---

## What Stays Local

- Flight snapshots, config, history, and logs stay under `~/.localflight/`.
- Your airport settings, display preferences, and personal API keys stay in your local config and `.env`.
- The native GUI, LAN browser UI, mobile companion, and matrix board all talk to your local Local Flight server first. Native mode does not fetch online fonts, CDN assets, or a webview shell for the main UI.
- The optional local traffic log at `~/.localflight/requests.db` is visible only on your own Local Flight instance and is only enabled for explicit local network diagnostics.
- Optional radar map data is simplified and cached locally for display use. It is not stored as raw provider payloads in reports or ordinary UI surfaces.
- The Interstate 75 W board talks to your Local Flight server over your LAN. Its runtime settings live in `~/.localflight/matrix_config.json`.
- Matrix V2 device check-ins store only board identity, label, size, renderer support, assigned config, and last-seen time locally so the admin page can show whether the board is alive.
- VATSIM-specific matrix presets require source `virtual` and use VATSIM-backed rows/weather only; they do not quietly switch to real-world FIDS or real METAR data.
- Flight intelligence shown in FIDS, Radar, History, and Matrix is assembled from the current local snapshot, live radar cache, METAR/weather context, airport/surface context, and local history database. It is a display model, not a new background data-harvesting layer.

When you use the Matrix page to download a ready-to-flash `main.py`, the Wi-Fi details and server host are sent to your own Local Flight instance only long enough to render that file. They are not stored in `matrix_config.json`, the hosted relay, or crash reports.

---

## Why The Native GUI Exists

Local Flight started with a browser-based local UI because that made the project practical: one local app could run on Windows, macOS, Raspberry Pi, phones, and tablets. That browser/LAN UI remains supported. The native GUI was added because a general-purpose browser process is more machinery than a local airport board should need for everyday desktop use.

The privacy goal is data minimization and separation of purpose:

- The display shell should show Local Flight, not become another browser session.
- The app should not rely on a browser profile, browser sync, extensions, cookies, history, or default-browser integrations just to render the main UI.
- The main window should not need a webview engine or remote web assets when the backend is already local.
- Browser access remains available as a deliberate LAN access and display path. It is useful for headless installs, remote screens, tablets, browser-mode displays, and recovery.

Native mode does not change the aviation data sources you choose. If you enable Community, BYOK, VATSIM, radar, METAR, update checks, or reports, the relevant network calls still happen as described below. The native GUI simply keeps the app window itself out of the browser-vendor data surface.

---

## Setup Paths

### Community Relay

If you choose **Community**, your install uses the hosted relay for shared AviationStack schedule snapshots and, when available, relay-backed ADS-B radar. The relay is there to protect provider keys and make the hobbyist path usable without everybody bringing paid API credentials on day one.

The relay stores the minimum metadata needed to run that shared service safely:

- random local install UUID
- hashed install fingerprint
- per-install usage counts
- last-seen timestamps
- token prefixes for relay-linked installs
- one-way anonymous network tags for abuse protection
- short-lived "current interest" rows, such as airport and display window, so shared schedule snapshots can be reused
- short-lived shared schedule snapshots containing Local Flight canonical schedule records and cache metadata
- if the operator explicitly enables the optional surface/map overlay path: short-lived airport-surface and map-geometry cache entries derived from OpenStreetMap/Overpass so many installs looking at the same airport do not repeatedly query public map infrastructure

The relay does **not** store:

- raw IP addresses
- personal API keys from your install
- readable personal identifiers
- your local flight history database
- your local app logs, unless you explicitly allow diagnostic reports with sanitized logs

Community relay traffic has per-install quotas plus network/global safety caps. Duplicate reports are deduplicated before routing, so one noisy install should not spam every triage area.

For public safety, the community relay also controls how often a shared airport snapshot can trigger a new upstream schedule fetch. If an airport/window is already cached, the relay can reuse that snapshot for about one hour even when a local display checks every 15 or 30 minutes. This keeps the public relay usable when many people watch the same busy airport at the same time.

### Bring Your Own Keys

If you choose **Bring your own keys**, your local app talks directly to the upstream providers you configured. Your provider keys stay in your local `.env` and are not sent to the Local Flight relay reporting gateway.

### VATSIM

If you choose **VATSIM**, the app uses virtual traffic data and does not need real-world schedule API keys.

Local Flight fetches the public VATSIM network feed and keeps only flight-board-relevant fields such as callsign, filed route, aircraft type, airport codes, planned times, current aircraft position, and the raw METAR line when available from ATIS/METAR text. It intentionally does not store or display VATSIM pilot names, controller names, CIDs/account IDs, server names, or other person-identifying network fields.

VATSIM Matrix views also avoid gate/stand placeholders because the current source does not provide reliable gate data. Virtual boards prioritize callsign, aircraft, route/status, flight-plan, weather/ATIS, and timing information instead.

---

## Diagnostics And Reports

Manual issue reports are always available from the in-app **Report** page. Automatic diagnostics are a separate install-level choice.

During first-run setup, Local Flight asks you to choose one of these modes and saves the choice in your local config:

- `Manual reports only`
- `Automatic crash reports`
- `Automatic crash reports + sanitized logs`

You can change that choice later from **Settings** or by re-running setup.

### Manual Reports

When you send a report yourself, Local Flight sends:

- the title and description you wrote
- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
- the reporting surface, such as native GUI, LAN browser UI, server, or mobile companion
- optional mobile companion context if the report came from the companion flow

Manual reports are sanitized locally, forwarded to the hosted relay reporting gateway, deduplicated/rate-limited there, and then filed for developer triage.

### Automatic Crash Reports

If you enable automatic diagnostics, Local Flight can send a crash report when a serious error is caught. Automatic reports use the same relay reporting gateway as manual reports.

An automatic crash report can contain:

- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
- crash context
- native GUI screen/action context, when the crash happened in the Qt shell
- traceback, when available

If you choose `Automatic crash reports + sanitized logs`, the report can also include:

- a sanitized recent log excerpt from the local app log

Automatic diagnostics do **not** intentionally contain:

- API keys
- activation tokens
- raw IP addresses
- raw screenshots or screen recordings
- stored flight history
- full local logs
- account data, because there are no Local Flight accounts

Expo JS/React errors in the mobile companion are covered by the current crash reporter. Native iOS crashes before JavaScript starts are not covered without adding a native crash-reporting service or relying on Apple crash logs.

---

## Mobile Companion

The mobile companion stores its server URL, companion ID, appearance choice, pinned flight, local profiles, and mobile diagnostics choice locally on the device with Expo storage APIs.

When it connects to your Local Flight server, it reports a companion-specific ID plus platform/device labels so companion-originated actions can be distinguished from desktop/server actions. That ID is install-scoped. It is not a login, an account, or a person profile.

Automatic companion reports only send when:

- the mobile diagnostics mode allows automatic reports
- the connected Local Flight server diagnostics mode also allows automatic reports

If either side is set to manual or unset, automatic mobile reporting stays off.

---

## Third-Party Data Sources

When Local Flight fetches data, it may communicate with:

| Service | What is sent | Their privacy policy |
|---|---|---|
| AviationStack | BYOK/direct path: API key, airport IATA code, date/window request details. Relay-backed path: the hosted relay makes the upstream request with its own provider key and shared cache. | [aviationstack.com/privacy](https://aviationstack.com/privacy-policy) |
| ADS-B Exchange via RapidAPI | Direct path: API key and radar search coordinates. Relay-backed path: the hosted relay makes the upstream request when relay access is available. | [rapidapi.com/privacy](https://rapidapi.com/privacy/) |
| OpenSky Network | Radar search coordinates | [opensky-network.org/about/privacy](https://opensky-network.org/about/privacy) |
| VATSIM | Virtual network data for the configured airport/source mode | [vatsim.net/privacy-policy](https://vatsim.net/privacy-policy) |
| aviationweather.gov | ICAO code for METAR weather. Local Flight decodes the returned METAR locally into weather mood/icon/temperature fields; no extra weather provider is contacted for that UI. VATSIM mode can use VATSIM ATIS/METAR first and falls back here when unavailable. | Public government API |
| OurAirports | Public airport/runway CSV data may be bundled or refreshed/cached locally for runway IDs, headings, dimensions, and reference geometry. No account or user identifier is required. | [ourairports.com/data](https://ourairports.com/data/) |
| OpenStreetMap / Overpass | Only when optional radar surface/map layers are enabled or prepared: airport code/coordinates and bounded airport-area geometry requests. Local Flight stores simplified display geometry with attribution, not raw personal data. | [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright) |
| AWS Terrain Tiles | Optional radar terrain/relief layer requests public terrain tile data for the displayed airport area/range. It is cached locally and used only as a subtle visual layer. | [registry.opendata.aws/terrain-tiles](https://registry.opendata.aws/terrain-tiles/) |

Local Flight does not embed tracking or advertising SDKs from any of these services.

---

## GDPR-Friendly Stance

Local Flight is designed to avoid collecting personal data in normal use:

- no user accounts
- no email addresses
- no analytics profiles
- no ad tracking
- no raw IP storage in the hosted relay

Technical identifiers, such as install fingerprints and companion IDs, can still be personal data in some contexts. Local Flight keeps them short-lived or install-scoped where practical, uses them for rate limiting and troubleshooting, and avoids turning them into account profiles.

Your local data is under your control. To wipe local app data, stop Local Flight and remove `~/.localflight/`.

---

## Data Summary

| Data | Where it lives | Who can see it |
|---|---|---|
| Flight snapshots | Your machine | You |
| Config and personal API keys | Your machine | You |
| Native GUI state and appearance | Your machine | You |
| Local traffic log | Your machine | You, if network tools are enabled |
| Flight history | Your machine | You |
| Manual reports and automatic diagnostics | Hosted relay reporting gateway, then developer triage inbox | Developer |
| Community relay usage metadata and short-lived shared schedule cache | Relay server | Relay operator |
| Cached radar surface/map/terrain geometry | Your machine and, for relay-backed surface/map data, short-lived hosted relay cache when optional overlays are enabled | You and relay operator |
