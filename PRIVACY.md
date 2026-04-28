# Privacy

Local Flight is built on a simple principle: **your data stays on your machine.**

No accounts. No tracking. No analytics platform. No third-party SDKs phoning home.

---

## What stays local (everything by default)

- Flight data fetched from AviationStack, VATSIM, and ADS-B Exchange is stored in `~/.localflight/` on your own machine. It is not transmitted anywhere beyond the configured data source.
- Your airport, display preferences, and API keys live in `~/.localflight/config.json` and your local `.env` file. They are never uploaded.
- The local traffic log (`~/.localflight/requests.db`) records which endpoints your own browser and connected devices hit. It is visible only to you via `/admin/requests`, is retained for 7 days, and IPs are anonymized before storage (LAN IPs masked to `/24`, public IPs masked to `/16`). It is never sent anywhere.
- Flight history lives in a local SQLite database (`~/.localflight/history.db`). 90-day retention, pruned automatically, stays on your machine.

---

## Crash reports

If Local Flight encounters an unhandled error, it automatically files a crash report with the developer. This is the only data that leaves your machine without your explicit action.

A crash report contains:
- Local Flight version number
- Operating system (Windows / macOS / Linux)
- Configured airport IATA code (e.g. `ZRH`)
- The Python traceback
- The last 50 lines of the application log

A crash report does **not** contain:
- Your API keys
- Your IP address
- Any flight data or history
- Any personally identifiable information

Reports are deduplicated — the same error from the same install is only filed once per 6 hours. You can also submit a report manually at any time via the **🐛 Report** button in the nav bar.

---

## Community relay

If you use the community relay path (no BYOK API key), your install communicates with the relay server to fetch flight schedules. The relay logs:

- Your install's randomly generated UUID (assigned at activation, stored locally in `~/.localflight/`)
- Number of API calls made this billing month
- Timestamp of the last request

The relay does **not** log your IP address, airport, flight data, or any personal information. Your install ID is a random UUID — it is not linked to your name, email, or any personal identifier.

If you bring your own AviationStack key (BYOK), your install communicates directly with AviationStack and the relay is not involved at all.

---

## Third-party data sources

When Local Flight fetches data, it communicates with:

| Service | What is sent | Their privacy policy |
|---|---|---|
| AviationStack | Your API key + airport IATA code + date range | [aviationstack.com/privacy](https://aviationstack.com/privacy-policy) |
| ADS-B Exchange via RapidAPI | Your API key + bounding box coordinates | [rapidapi.com/privacy](https://rapidapi.com/privacy/) |
| OpenSky Network | Airport bounding box (anonymous) | [opensky-network.org/about/privacy](https://opensky-network.org/about/privacy) |
| VATSIM | Airport IATA code (anonymous) | [vatsim.net/privacy-policy](https://vatsim.net/privacy-policy) |
| aviationweather.gov | ICAO code (anonymous) | US government public API |

No tracking, analytics, or advertising SDKs from any of these services are embedded in Local Flight.

---

## Mobile companion

The Local Flight mobile companion connects directly to your Local Flight instance over your local network (LAN). It does not connect to any external server. The server URL you enter is stored in your device's secure keychain (Expo SecureStore) and never transmitted anywhere.

---

## GDPR

Local Flight does not collect, store, or process personal data as defined under GDPR. There are no user accounts, no email addresses, no cookies, and no cross-device tracking. The crash reporting described above is the closest thing to data transmission — it contains no personal identifiers.

If you deploy the community relay in the EU, the relay stores only anonymous install UUIDs and call counts. No personal data is processed relay-side.

---

## Summary

| Data | Where it lives | Who can see it |
|---|---|---|
| Flight snapshots | Your machine (`~/.localflight/`) | You |
| Config and API keys | Your machine (`~/.localflight/`) | You |
| Local traffic log | Your machine (`~/.localflight/requests.db`) | You (via `/admin/requests`) |
| Flight history | Your machine (`~/.localflight/history.db`) | You |
| Crash reports | Developer's issue tracker | Developer only |
| Relay usage counter | Relay server (anonymous UUID + count) | Relay admin (developer) |
