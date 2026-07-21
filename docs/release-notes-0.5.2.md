# Local Flight 0.5.2 — Full App Release Guide

Local Flight 0.5.2 brings the desktop, server, Raspberry Pi, LAN, Matrix, and
mobile-testing apps onto one release line. It also adds the first regular Linux
desktop and server packages, completes Intel Mac coverage, and includes the
latest security and reliability maintenance.

Local Flight is an informational display. Flight, weather, map, and status data
can be delayed, incomplete, cached, wrong, or unavailable. Never use it for
navigation, dispatch, operational control, flight planning, or safety decisions.

## Choose How You Want To Run It

- **Windows:** a normal desktop installer for 64-bit Windows.
- **Mac:** separate signed and notarized packages for Apple silicon and Intel
  Macs running macOS 12 or newer.
- **Portable Linux:** AppImages for x86-64 and ARM64 desktops. Download, allow
  the file to run, and open it without installing system-wide.
- **Ubuntu or Debian desktop:** integrated `.deb` packages with an app-menu
  entry for x86-64 and ARM64.
- **Ubuntu or Debian server:** a separate headless `.deb` package for a machine
  that serves the LAN board, mobile app, and Matrix without opening a local
  window.
- **Raspberry Pi:** the dedicated Pi OS bundle remains the preferred path for a
  headless Pi, native HDMI kiosk, Chromium kiosk, or Matrix host.
- **Phone and tablet:** the same iOS and Android app can connect to your own
  Local Flight host or run a simpler Standalone board.

Every GitHub download has a matching SHA-256 file. The Windows 0.5.2 installer
is intentionally unsigned and may appear as an unknown publisher; its checksum
confirms that the file matches the published release, but it is not a publisher
signature. macOS packages remain Developer ID signed, notarized, and stapled.

## Desktop And LAN Features

The native Windows, macOS, and Linux desktop apps include:

- A guided first launch for airport, flight source, optional provider keys,
  diagnostics choice, and final review.
- A native Qt shell with Display, FIDS, Radar, Matrix, Settings, Admin, History,
  Logs, Report, and local help pages.
- Four FIDS presentations: Classic, PAX, VATSIM, and Nerd.
- Dark and light appearances designed to keep text, status colors, menus,
  controls, and custom-painted boards readable.
- A permanent LAN browser UI at the local server address while the native app
  is running.
- Live WebSocket updates with reconnect backoff and lightweight fallback
  polling.
- Local settings, snapshots, movement history, logs, and provider-usage
  counters under the user's Local Flight data folder.

The LAN browser remains a fully supported interface for another computer,
tablet, phone, kiosk screen, or recovery session. It offers the same essential
board, radar, history, settings, setup, pairing, Matrix, and reporting actions
using controls that fit a browser.

## Flight Boards

- Real boards prefer AeroDataBox schedules when configured and can use
  AviationStack to fill sparse fields or as a fallback.
- Operating-flight identity and codeshares are combined into one useful row
  instead of inflating the board.
- Airport-local time, city and country, readable weather, status, and gate or
  stand information are shown when the underlying data actually supplies them.
- Known-good cached boards stay available during short provider or network
  interruptions.
- First-board network failures use bounded retries instead of waiting for the
  full schedule interval.
- Pinning and detail views reuse the local snapshot instead of spending an
  extra provider request for every click.

VATSIM mode is intentionally different from a passenger board. It focuses on
callsign, filed route, aircraft, altitude, speed, transponder, and freshness. It
does not invent passenger gates, codeshares, registrations, or delay analytics,
and it drops pilot and controller names, network IDs, and similar personal data.

## Radar, Maps, And Weather

- Radar can use real ADS-B data or VATSIM traffic, with OpenSky as a real-data
  fallback when configured paths are unavailable.
- Passenger board status remains separate from the live movement phase.
- Schedule intent is joined to a radar target only when the identity match is
  strong enough.
- Ground, taxi, departure, en-route, descent, approach, and final phases use
  conservative elevation-aware rules and bounded hysteresis.
- The shared presentation uses north at zero, clockwise geometry, one
  15-second sweep line, a fading trail, and no normal blip until the sweep has
  crossed its bearing.
- A selected target stays readable but always has an explicit close action.
- Optional runway, airport-surface, OpenStreetMap ground context, AWS terrain,
  and real elevation contours remain separate cached layers.
- METAR weather is decoded locally into display-friendly conditions.

## History

History counts deduplicated flight movements rather than repeated observations.
It includes filters, recent movements, delay buckets, airline and route views,
aircraft statistics, summaries, and detail panels. The raw local observations
needed for diagnostics do not inflate the movement totals shown to the user.

## Matrix And HDMI Displays

- Raspberry Pi can run headless, as a native Qt HDMI kiosk, or as a Chromium
  kiosk.
- The LAN layout adapts to compact 7-inch Pi screens.
- Interstate 75 W and compatible HUB75 boards use generated MicroPython that
  talks only to the Local Flight server; provider keys never go to the panel.
- Matrix preview, Qt, LAN, and generated clients share the same row, clock,
  weather, gate, VATSIM, animation, and renderer-revision rules.
- Panel presets, split-flap/typewriter/cascade motion, live settings, and board
  reflash guidance remain available.

## Linux Desktop And Server

The portable AppImage keeps its state in the current user's `~/.localflight`
folder and does not install or autostart anything. Most systems run it directly
after marking it executable. If FUSE is unavailable, use the documented
`--appimage-extract-and-run` fallback.

The desktop `.deb` installs Local Flight into `/opt/localflight`, adds an app
menu entry, and still keeps each user's data in that user's home folder.

The server `.deb` creates a locked service account and stores server state under
`/var/lib/localflight`. It starts the local web server on port 8000, waits for
setup to finish before starting scheduled provider work, and serves LAN,
mobile, Matrix, API, and WebSocket clients without a local window. Upgrades and
normal removal preserve the Local Flight data directory.

Official 0.5.2 desktop testing covers Ubuntu 22.04/24.04 and Debian 12/13 on
x86-64. ARM64 desktop packages require Ubuntu 24.04 or Debian 13. ARM64 headless
and Raspberry Pi paths retain support for the older tested operating-system
line. Alpine/musl, 32-bit Linux, RPM, Snap, and Flatpak packages are not part of
this release.

## Mobile App

Version 0.5.2 uses iOS build 11 and Android versionCode 15 for TestFlight and
Google Play internal testing.

### Companion

- Connects to a desktop, Linux server, or Raspberry Pi host over the LAN first.
- Offers Board, Radar, History, Control, pairing, profiles, appearance, and
  reporting suited to a phone or tablet.
- QR and manual pairing verify the host's public Support ID so a phone does not
  silently attach to a different Local Flight server on the same network.
- An explicitly paired phone can use encrypted Remote Companion when the LAN is
  unavailable and the host remains online.
- Remote Companion does not expose a public inbound tunnel, queue offline
  commands, or grant arbitrary administration.

### Standalone

- Connects directly to the public Local Flight service for a simpler phone-only
  board, radar, history, and settings experience.
- Uses conservative board and radar refresh timing.
- Stores deduplicated movement history on the phone.
- Does not include server-control tools because there is no paired host.

### Widgets And Optional Support

- iOS and Android widgets read only the bounded snapshot written by the mobile
  app. Widgets never contact a LAN server, relay, or aviation provider.
- Optional one-time support purchases unlock nothing, create no subscription,
  and create no durable entitlement. Store evidence is checked by the service,
  then reduced to a short non-reversible record; raw purchase evidence is not
  retained.

## Privacy And Network Choices

- No Local Flight account is required.
- Configuration, snapshots, history, and normal logs stay on the Local Flight
  device.
- The optional shared-data service reduces repeated provider calls and supports
  Standalone and encrypted Remote Companion.
- Remote Companion request and response contents are encrypted between the
  paired phone and host. The service does not receive the shared encryption
  secret or readable board data and commands.
- Manual reports are sent only when the user chooses to send them.
- Automatic diagnostics require the saved diagnostics choice and are sanitized
  before leaving the device.
- Client and support screens show a public Support ID, not the raw internal
  install identifier.
- Privacy and reset choices are available at
  [beacontools.cc/privacy/choices](https://beacontools.cc/privacy/choices).

## Security And Reliability Maintenance

0.5.2 updates the web, request, form-upload, image, and environment dependency
baseline used by the desktop and relay. Public website bug-report requests are
bounded before multipart parsing, while the existing per-file, combined-upload,
deduplication, and rate-limit protections remain in place.

The relay now has a production health check, and the release workflow runs the
full Python suite, mobile contracts and accessibility checks, dependency audits,
credential/package safety checks, relay-container smoke tests, download-manifest
contracts, and architecture-specific package verification before publication.

## Upgrading

- Close an existing desktop copy before installing the replacement package.
- macOS architecture packages share the same application identity and replace
  the previous app in `/Applications`.
- Linux desktop and server packages preserve their documented data folders.
- Raspberry Pi upgrades reuse the existing checkout and virtual environment.
- Mobile store upgrades preserve the app's local settings and history under the
  normal iOS and Android application lifecycle.

Local Flight settings, provider configuration, install identity, snapshots,
history, and logs are not intentionally removed by a normal 0.5.2 upgrade.

## Download Safety

Use only the downloads linked from
[beacontools.cc/local-flight](https://beacontools.cc/local-flight) or the official
[GitHub Releases page](https://github.com/tr3y4rch/local-flight/releases).
Confirm that the package name, version, architecture, and matching `.sha256`
file all belong to the same 0.5.2 release.
