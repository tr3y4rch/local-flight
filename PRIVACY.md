# Privacy

Local Flight is built around a simple rule: **stay local unless a feature genuinely needs a network hop.**

No accounts. No analytics SDKs. No ad tech. No sign-up flow.

This is a hobbyist/open-source project, not a legal document, but the app is designed to be privacy-minimal and GDPR-friendly: collect as little as possible, keep identifiers technical and install-scoped, and make diagnostics opt-in.

---

## Quick Summary

- Your config, API keys, snapshots, history, and logs stay on your own machine.
- The mobile companion talks to your Local Flight server over your LAN. It does not call AviationStack, ADS-B Exchange, RapidAPI, OpenSky, VATSIM, or the hosted relay directly.
- Community mode can use the hosted Local Flight relay for shared schedules and relay-backed radar. That relay stores operational metadata, not accounts or user profiles.
- Manual reports are always your choice. Automatic crash diagnostics are off unless you allow them.
- Mobile automatic diagnostics require two yeses: the mobile app's local diagnostics choice and the connected server's diagnostics mode.
- Developer reporting credentials are kept on the hosted relay, not in the desktop package, mobile app, installers, or docs.

---

## What Stays Local

- Flight snapshots, config, history, and logs stay under `~/.localflight/`.
- Your airport settings, display preferences, and personal API keys stay in your local config and `.env`.
- The optional local traffic log at `~/.localflight/requests.db` is visible only on your own Local Flight instance and is only enabled for explicit local network diagnostics.
- The Interstate 75 W board talks to your Local Flight server over your LAN. Its runtime settings live in `~/.localflight/matrix_config.json`.

When you use the Matrix page to download a ready-to-flash `main.py`, the Wi-Fi details and server host are sent to your own Local Flight instance only long enough to render that file. They are not stored in `matrix_config.json`, the hosted relay, or crash reports.

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

The relay does **not** store:

- raw IP addresses
- personal API keys from your install
- readable personal identifiers
- your local flight history database
- your local app logs, unless you explicitly allow diagnostic reports with sanitized logs

Community relay traffic has per-install quotas plus network/global safety caps. Duplicate reports are deduplicated before routing, so one noisy install should not spam every triage area.

### Bring Your Own Keys

If you choose **Bring your own keys**, your local app talks directly to the upstream providers you configured. Your provider keys stay in your local `.env` and are not sent to the Local Flight relay reporting gateway.

### VATSIM

If you choose **VATSIM**, the app uses virtual traffic data and does not need real-world schedule API keys.

---

## Diagnostics And Reports

Manual issue reports are always available from the in-app **Report** page. Automatic diagnostics are a separate install-level choice.

On first launch into the main app, Local Flight asks you to choose one of these modes:

- `Manual reports only`
- `Automatic crash reports`
- `Automatic crash reports + sanitized logs`

You can change that choice later from **Settings**.

### Manual Reports

When you send a report yourself, Local Flight sends:

- the title and description you wrote
- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
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
- traceback, when available

If you choose `Automatic crash reports + sanitized logs`, the report can also include:

- a sanitized recent log excerpt from the local app log

Automatic diagnostics do **not** intentionally contain:

- API keys
- activation tokens
- raw IP addresses
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
| aviationweather.gov | ICAO code for METAR weather | Public government API |

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
| Local traffic log | Your machine | You, if network tools are enabled |
| Flight history | Your machine | You |
| Manual reports and automatic diagnostics | Hosted relay reporting gateway, then developer triage inbox | Developer |
| Community relay usage metadata and short-lived shared schedule cache | Relay server | Relay operator |
