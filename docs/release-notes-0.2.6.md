# Local Flight 0.2.6 Temporary Client Notes

`0.2.6` is a temporary client-polish target, not a final stable release label yet.

It builds on the `0.2.5` beta baseline and focuses on making the native Qt app, LAN/browser UI, Matrix tools, History, Settings, Radar, and FIDS details feel like one coherent Local Flight client.

---

## What Changed

### Native And LAN Browser Parity

The native Qt app remains the recommended desktop shell. The LAN browser UI remains supported for headless installs, remote screens, tablets, recovery, and browser-mode displays.

This pass keeps both surfaces aligned for the user-facing pages that matter most:

- FIDS
- Radar
- Matrix
- Settings
- Admin summary
- History
- Logs
- Report

The goal is not pixel-perfect duplication. The goal is that the same controls, wording, data, and privacy expectations exist in both clients.

### History Dashboard

History is now meant to feel like an airport-board analytics page instead of a debug table.

It can show:

- callsign, period, direction, and status filters
- flights tracked, departures, arrivals, on-time rate, delayed rate, and average delay
- delay buckets
- airline delay quotas
- top routes and aircraft
- sortable recent matching flights
- detail panels for recent records

### Matrix Configurator

Matrix is now a friendly board configurator for Interstate 75 W / HUB75 setups.

It includes:

- panel combination presets
- live preview updates
- startup lane selection
- brightness, zoom, row count, refresh, rotation, animation, palette, weather, and gate controls
- device status
- Wi-Fi/server guidance
- generated MicroPython `main.py`
- visible save/apply/generation feedback

Compact Matrix FIDS boards no longer waste a whole extra line on weather. Small boards keep airport, lane, UTC, local time, compact weather, and flight rows in the available space.

Real-world Matrix FIDS can show gate or stand information when the schedule source provides it. On tiny boards, Local Flight can alternate status and gate so both remain visible. VATSIM Matrix presets hide gate data because the current virtual source does not provide reliable gate information.

### Settings And Setup

Settings is now organized around user tasks instead of raw configuration density.

The main cards are:

- Airport & Source
- Appearance
- Outputs & Radar
- Profiles

Advanced/support controls are collapsed by default so the normal user path stays readable.

First-run setup keeps the standalone guided window and remains focused on:

- airport
- data source
- optional keys
- diagnostics choice
- finish summary

### FIDS And Radar Detail

FIDS click details, Radar blip details, History details, Matrix compact fields, native Qt, and LAN/browser views now share one current-source detail model.

Local Flight reuses data it already has:

- schedule rows
- radar blips
- METAR/weather context
- airport/surface context
- local history

This does not add new paid providers and does not create surprise per-row provider calls when opening a detail panel.

### Real Schedule Resilience

The real-world schedule path is being hardened so the hosted Community Relay and bring-your-own-key installs can keep boards populated without careless provider spending.

This pass adds the foundations for:

- AeroDataBox as a first-class real schedule source
- AviationStack as a compatible fill/fallback source when rows are sparse or key board fields are missing
- cache-first schedule serving from shared airport snapshots
- stale schedule serving when a provider is capped, unavailable, or slow
- one canonical FIDS row shape for native Qt, LAN/browser, Matrix, mobile, History, and local APIs

For users, the visible mode remains **Real**. Local Flight chooses the configured real schedule provider behind the scenes and keeps the board output compatible across the desktop app and browser UI.

### Privacy Notes

The privacy model stays the same:

- no Local Flight accounts
- no analytics SDKs
- no ad tech
- native desktop shell is Qt, not a browser profile or webview
- mobile and Matrix stay server-mediated through your Local Flight server
- diagnostics are consent-based
- VATSIM personal identifiers stay hidden
- maintenance/admin internals are not exposed in the normal public client

---

## Install Choices

For normal users:

- Windows: `LocalFlight-windows.zip`
- macOS: `LocalFlight-macos.zip`
- Raspberry Pi: `LocalFlight-pi-source-0.2.6.zip` once this temporary target is packaged

For source-checkout testing:

- Windows: `installers/windows/install.ps1`
- macOS: `installers/macos/install.sh`
- Pi: `installers/pi/install.sh`
- Mobile companion: `mobile/` with Expo/Xcode

Detailed instructions live in:

- [Install Guide](install.md)
- [Display Modes](display-modes.md)
- [Privacy](../PRIVACY.md)

---

## Known Beta Boundaries

`0.2.6` is still beta/stabilization work.

- macOS and Windows signing/notarization can still cause first-run trust prompts.
- Mobile companion is still developer-preview, not App Store/TestFlight.
- Provider coverage varies by airport and data source.
- Radar surface/map layers are display aids, not certified navigation tools.
- Matrix rendering is tuned for readability and available space, not for every possible custom panel geometry yet.
