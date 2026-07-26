# Local Flight 0.5.2 release process

This is the public-safe contributor guide for building and publishing the
0.5.2 release. It records the release contract without credentials, private
service topology, signing material, personal paths, or operator-only recovery
details.

## Release source and supported targets

`pyproject.toml` is the version source of truth. The shared runtime helper,
installer metadata, mobile metadata, release workflow, Worker contract, and
current documentation must all agree with it. Run the version consistency test
before packaging.

The public release consists of ten packages and ten adjacent checksum files:

| Target | Package |
|---|---|
| Windows x64 | `LocalFlight-0.5.2-Setup.exe` |
| macOS Apple silicon | `LocalFlight-0.5.2-macos-arm64.pkg` |
| macOS Intel | `LocalFlight-0.5.2-macos-x86_64.pkg` |
| Linux AppImage x86-64 | `LocalFlight-0.5.2-linux-x86_64.AppImage` |
| Linux AppImage ARM64 | `LocalFlight-0.5.2-linux-aarch64.AppImage` |
| Ubuntu/Debian desktop AMD64 | `localflight-desktop_0.5.2_amd64.deb` |
| Ubuntu/Debian desktop ARM64 | `localflight-desktop_0.5.2_arm64.deb` |
| Ubuntu/Debian server AMD64 | `localflight-server_0.5.2_amd64.deb` |
| Ubuntu/Debian server ARM64 | `localflight-server_0.5.2_arm64.deb` |
| Raspberry Pi source | `LocalFlight-pi-source-0.5.2.zip` |

Do not substitute an artifact from another build. Every package must be built
on its matching operating system and CPU and must retain the filename above.

## Reproducible build boundary

- Release jobs install only the checked-in, hash-pinned Python 3.11 locks.
- Desktop builds use the native lock with `PySide6==6.8.3`.
- Raspberry Pi OS Bookworm native kiosk uses its separate
  `PySide6==6.7.3` lock; Trixie uses 6.8.3.
- The Linux server lock contains no Qt, shiboken, tray, or native-shell
  dependency.
- `build.py` rejects cross-compilation and keeps work directories separate by
  platform, architecture, and flavor.
- Package staging rejects credentials, agent/operator material, internal
  notes, caches, external symlinks, and workstation paths.
- The architecture jobs inspect the package contents and write CI-only
  attestations tied to the source commit and final package hash. Attestations
  never become public release assets.

macOS publication additionally requires Developer ID application and installer
identities, hardened-runtime signing, notarization, stapling, and package/app
verification. Both packages keep the same app and package identities so an
architecture-specific upgrade preserves Local Flight data. Windows 0.5.2 is
intentionally unsigned and must keep its clear unknown-publisher notice.

## Local validation before the release commit

Run the complete source checks from a cleanly resolved development environment:

```bash
python -m compileall -q src relay installers scripts tests
python -m pytest tests -q
python -m pip check
python -m pip_audit --strict .
python -m pip_audit --strict -r relay/requirements.txt
python scripts/security_preflight.py
git diff --check
```

Run the Beacon Tools static-site checks with the supported Node 24 line:

```bash
cd site
npm ci
npm run verify
npm audit --audit-level=high
npx playwright install chromium
npm run test:e2e
cd ..
node scripts/site_downloads_contract.mjs
```

Run the mobile checks with the supported Node 24 line:

```bash
cd mobile
npm install
npm run verify
npm run a11y
npx expo config --type public
npm audit --omit=dev --audit-level=high
```

Run a Cloudflare build preview from the repository root, but do not deploy the
0.5.2 Worker minimum while the complete public release is still missing:

```bash
npm --prefix site run build
npx wrangler deploy --dry-run
```

Before confirmation, present the integrated diff, exact artifact inventory,
validation results, known audit findings, unavailable local tooling, and the
remaining native/physical test gates. Do not tag, release, deploy, or submit a
store build at this stage.

## Publication order

1. After explicit confirmation, create one release commit directly on `main`
   and push it once to `origin main`. Do not create the release tag locally.
2. Let the gated main workflow test the source and relay image, deploy the
   relay, and verify the public `/health` response. A duplicate manual Fly
   deployment is unnecessary unless that workflow fails.
3. Dispatch `.github/workflows/release-artifacts.yml` with the exact pushed
   commit SHA. The source job requires that SHA to remain the current `main`
   commit.
4. Let the native matrix build and inspect all packages. Final assembly accepts
   only ten matching package/checksum pairs plus ten matching CI-only
   attestations. It creates the `v0.5.2` tag server-side and a draft release,
   then rechecks the draft's exact 20-file public inventory.
5. Smoke fresh installs, 0.5.1 upgrades, retained state, architecture, signing,
   LAN health, Linux desktop/server behavior, Raspberry Pi modes, and Matrix on
   the required native and physical systems. Publish the GitHub release only
   after those gates pass.
6. Build iOS `0.5.2 (11)` and Android `0.5.2 (15)`. Submit only the iOS build
   to TestFlight in this hardening pass; retain the signed Android AAB without
   uploading it to a Play track. Complete real-device checks before the public
   site describes a build as available.
7. Deploy the Cloudflare Worker and site only after the complete GitHub release
   is public. Then verify the home, product, mobile, network, privacy, privacy
   choices, and support pages; all ten manifest entries; all checksum links;
   support forms; relay health; and cache refresh behavior.

If a published release needs package-only maintenance without changing the app
version, do not move or overwrite its tag. Dispatch the same workflow with a
validated suffix such as `r1`; it creates a separate `v0.5.2-r1` draft tied to
the new source commit while retaining the `0.5.2` package filenames. Publish it
as the latest release only after the normal package inspection and smoke gates.

If a hosted gate fails, keep the release draft unpublished and fix the cause
before continuing. Do not bypass Gatekeeper, weaken package checks, publish a
partial matrix, or describe a checksum as a replacement for code signing.

## Platform smoke-test boundary

The hosted matrix proves package identity, architecture, version, checksum,
and release inventory. It does not replace native and physical validation:

- Apple silicon, Intel, and at least one macOS 12 system.
- Windows x64 fresh install and upgrade.
- Linux x86 desktop on Ubuntu 22.04/24.04 and Debian 12/13.
- Linux ARM64 desktop on Ubuntu 24.04 and Debian 13.
- ARM64 headless packages on Ubuntu 22.04 and Debian 12 as well as the newer
  line.
- AppImage on X11 and Wayland; desktop and server Debian
  install/upgrade/remove with retained state.
- Raspberry Pi headless, native kiosk, browser kiosk, and Matrix paths.
- Physical iOS and Android devices for Companion, encrypted Remote Companion,
  Standalone, widgets, and store-build identity.

Alpine/musl, 32-bit Linux, RPM, Snap, Flatpak, Windows ARM64, Universal 2, and
macOS 11 remain outside the 0.5.2 release contract.
