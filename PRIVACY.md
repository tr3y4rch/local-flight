# Privacy

Local Flight is built around a simple rule: **stay local unless a feature genuinely needs a network hop.**

No user accounts. No analytics SDKs. No ad tech. No sign-up flow.

---

## What stays local by default

- Flight snapshots, config, history, and logs stay on your machine under `~/.localflight/`.
- Your airport settings, display preferences, and personal API keys stay in your local config and `.env`.
- The optional local traffic log at `~/.localflight/requests.db` is visible only on your own Local Flight instance.
- The mobile companion talks to your Local Flight server over your LAN. It does not send data to a cloud account service.
- The Interstate 75 W board talks to your Local Flight server over your LAN. Its runtime settings live in `~/.localflight/matrix_config.json`.

When you use the Matrix page to download a ready-to-flash `main.py`, the Wi-Fi details and server host are sent to your own Local Flight instance only long enough to render that file. They are not stored in `matrix_config.json`, the hosted relay, or crash reports.

---

## Diagnostics and reports

Manual issue reports are always available from the in-app **Report** page. Automatic diagnostics are a separate, install-level choice.

On first launch into the main app, Local Flight asks you to choose one of these modes:
- `Manual reports only`
- `Automatic crash reports`
- `Automatic crash reports + sanitized logs`

You can change that choice later from **Settings**.

### Manual reports

When you send a report yourself, Local Flight sends:
- the title and description you wrote
- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
- optional mobile companion context if the report came from the companion flow

### Automatic crash reports

If you enable automatic diagnostics, Local Flight can send a crash report to the developer issue inbox on Linear when a serious error is caught.

An automatic crash report contains:
- Local Flight version
- install fingerprint
- operating system
- Python version
- configured airport and source mode
- schedule mode, diagnostics mode, and display window settings
- crash context
- traceback, when available

If you choose `Automatic crash reports + sanitized logs`, the report also includes:
- a sanitized recent log excerpt from the local app log

Automatic diagnostics do **not** contain:
- API keys
- raw IP addresses
- stored flight history
- Local Flight account data, because there are no Local Flight accounts

Crash reports are deduplicated so the same install does not file the same crash repeatedly within a short window. The deduplication key includes the crash context as well as the error message so unrelated subsystems do not collapse into one report.

---

## Community relay

If you choose the **Community** setup path, your Local Flight install uses the hosted relay to fetch shared AviationStack schedules and relay-backed ADS-B radar data.

The relay stores only the minimum metadata needed to run that shared service safely:
- a random local install UUID
- a hashed install fingerprint
- per-install usage counts
- last-seen timestamps
- token prefixes for relay-linked installs
- anonymous network tags derived from the incoming network path for abuse protection
- short-lived install interest rows so the relay knows which airport/window an install is currently watching
- short-lived shared schedule snapshots keyed by airport and display window, containing canonical schedule records plus cache metadata

The relay does **not** store:
- raw IP addresses
- personal API keys from your install
- readable personal identifiers
- flight history snapshots from your local app

Those anonymous network tags are one-way derived values. They help rate-limit obvious abuse without turning the relay into a user-tracking system.

The important nuance is this:
- airport identifiers are no longer stored in new generic relay activity log rows
- but the relay does temporarily store the currently watched airport/window in its internal shared-cache tables, because that is how shared snapshot fan-out works

Those shared snapshots are an internal service cache, not a public export or account profile.

If you use **Bring your own keys**, the client talks directly to the upstream providers and the hosted community relay is not part of that schedule path.

---

## Third-party data sources

When Local Flight fetches data, it communicates with:

| Service | What is sent | Their privacy policy |
|---|---|---|
| AviationStack | BYOK/direct path: API key + airport IATA code + date range. Relay-backed path: the hosted relay makes that upstream request with its own provider key and shared cache. | [aviationstack.com/privacy](https://aviationstack.com/privacy-policy) |
| ADS-B Exchange via RapidAPI | API key + radar search coordinates | [rapidapi.com/privacy](https://rapidapi.com/privacy/) |
| OpenSky Network | Radar search coordinates | [opensky-network.org/about/privacy](https://opensky-network.org/about/privacy) |
| VATSIM | Airport IATA code | [vatsim.net/privacy-policy](https://vatsim.net/privacy-policy) |
| aviationweather.gov | ICAO code | Public government API |

Local Flight does not embed tracking or advertising SDKs from any of these services.

---

## Mobile companion

The mobile companion stores its server URL and companion ID locally on the device. When it connects to your Local Flight server, it reports a companion-specific ID plus a platform label so companion-originated actions can be distinguished from the desktop/server app in diagnostics.

That identity is install-scoped. It is not a login or a person profile.

---

## GDPR / personal data stance

Local Flight is designed to avoid collecting personal data in the ordinary sense:
- no accounts
- no email addresses
- no cross-device profile
- no raw IP storage in the hosted relay

The closest thing to remote processing is the hosted community relay and install-scoped diagnostics. Both are designed around technical identifiers rather than user identity.

---

## Summary

| Data | Where it lives | Who can see it |
|---|---|---|
| Flight snapshots | Your machine | You |
| Config and personal API keys | Your machine | You |
| Local traffic log | Your machine | You |
| Flight history | Your machine | You |
| Manual reports and automatic diagnostics | Developer issue inbox on Linear | Developer |
| Community relay usage metadata and short-lived shared schedule cache | Relay server | Relay operator |
