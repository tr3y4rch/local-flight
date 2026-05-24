# Local Flight 0.2.8 Preliminary Notes

`0.2.8` is the next polish line after the `0.2.7` release candidate. These
notes are preliminary: packaged Windows, macOS, and Raspberry Pi artifacts are
still tracked under the current `0.2.7` release-candidate line until the version
is deliberately bumped.

The theme for this pass is parity and trust: the LAN browser UI should feel like
the same product as the native Qt shell, mobile pairing should be discoverable
from either surface, and public documentation should stay current with the
actual app screens.

---

## LAN Settings Parity

- The LAN browser Settings page now follows the same calmer structure as the Qt
  Settings page.
- The main page stays focused on the high-signal cards: airport/source,
  appearance, relay status, and surface state.
- Secondary controls are now grouped into collapsed folders:
  **Outputs & Radar**, **Profiles**, **Pair Mobile**, **Advanced board timing**,
  **Maintenance**, **Relay details**, and **Diagnostics & Docs**.
- Outputs/Radar and Profiles are collapsed by default instead of competing with
  the primary setup controls.

## Mobile Pairing From The LAN Browser

- The LAN Settings page now includes the same **Pair Mobile** workflow as the
  native Qt shell.
- Companion pairing shows a reusable QR code, the preferred LAN URL, manual URL
  fallbacks, and the server fingerprint.
- Pairing actions include refreshing paired-device status, copying the pairing
  link, copying the LAN URL, and resetting paired mobile check-ins.
- The pairing link remains fingerprint-bound so a phone does not silently save a
  different Local Flight server if name resolution points somewhere unexpected.

## Documentation And Preview Assets

- Mobile preview source screenshots now live under `assets/mobile-previews/`,
  split by Android and iOS.
- Public docs and website preview work should use those real screenshots as the
  source material when possible instead of inventing mockups.
- Preview priority for future docs/site galleries is: FIDS first, then Radar,
  History, Setup, Display, and Splash.

## macOS Installer Path

- The DAU-facing macOS release path is now planned around a signed/notarized
  `LocalFlight-<version>-macos.pkg` installer instead of a zip/manual drag flow.
- The package installs only **Local Flight.app** into Applications; setup still
  happens inside the app and user data stays in the normal local profile.
- Source checkout app bundles and Terminal launchers remain documented for
  developers, not normal release users.

## Public Site Deployment Note

- The Beacon Tools public site is served from the Cloudflare Worker + Assets
  configuration in this repository.
- The Cloudflare dashboard `.dev` preview can show a current draft while the
  production custom domain is still serving the previously deployed Worker.
- Publishing the current `site/` content to `beacontools.cc` requires a real
  Worker deploy from the repository, not just a Pages preview.

## Still Expected Before 0.2.8 Final

- Decide whether `0.2.8` is a docs/site polish release or a full app version
  bump with rebuilt platform artifacts.
- Re-run the normal release validation sweep once the version is bumped.
- Refresh public screenshots from the latest native, LAN browser, Matrix, and
  mobile screens before publishing final release notes.
