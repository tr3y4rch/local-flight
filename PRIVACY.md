# Privacy

Local Flight is built around a simple rule: **stay local unless a feature genuinely needs a network hop.**

No user accounts. No analytics SDKs. No ad tech. No sign-up flow.

---

## What stays local by default

- Flight snapshots, config, history, and logs stay on your machine under `~/.localflight/`.
- Your airport settings, display preferences, and personal API keys stay in your local config and `.env`.
- The optional local traffic log at `~/.localflight/requests.db` is visible only on your own Local Flight instance.
- The mobile companion talks to your Local Flight server over your LAN. It does not send data to a cloud account service.

---

## Crash reports

If Local Flight hits an unhandled error, it can send a crash report to the developer so the issue can be fixed.

A crash report contains:
- Local Flight version
- Operating system
- Configured airport IATA code
- Python traceback
- Last 50 lines of the application log

A crash report does **not** contain:
- API keys
- Raw IP addresses
- Stored flight history
- Account data, because there are no Local Flight accounts

Reports are deduplicated so the same install does not file the same crash repeatedly within a short window.

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

The relay does **not** store:
- raw IP addresses
- airport IATA or ICAO values in new relay activity records
- readable personal identifiers
- flight history snapshots from your local app

Those anonymous network tags are one-way derived values. They help rate-limit obvious abuse without turning the relay into a user-tracking system.

If you use **Bring your own keys**, the client talks directly to the upstream providers and the hosted community relay is not part of that schedule path.

---

## Third-party data sources

When Local Flight fetches data, it communicates with:

| Service | What is sent | Their privacy policy |
|---|---|---|
| AviationStack | API key + airport IATA code + date range | [aviationstack.com/privacy](https://aviationstack.com/privacy-policy) |
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

The closest thing to remote processing is the hosted community relay and crash reporting. Both are designed around install-level technical identifiers rather than user identity.

---

## Summary

| Data | Where it lives | Who can see it |
|---|---|---|
| Flight snapshots | Your machine | You |
| Config and personal API keys | Your machine | You |
| Local traffic log | Your machine | You |
| Flight history | Your machine | You |
| Crash reports | Developer issue inbox | Developer |
| Community relay usage metadata | Relay server | Relay operator |
