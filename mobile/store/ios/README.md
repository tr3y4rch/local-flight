# Apple App Store metadata

This directory is the copy-and-paste source for the public Apple App Store
listing. Keep customer-facing English (U.S.) copy in `en-US/` and keep
technical reviewer instructions in `../../APP_STORE_REVIEW_NOTES.md`.

App Store Connect fields:

- Primary category: **Utilities**
- Secondary category: **Travel**
- Marketing URL: `https://beacontools.cc/local-flight/mobile`
- Support URL: `https://beacontools.cc/support`
- Privacy Policy URL: `https://beacontools.cc/privacy`

Before submission, run:

```bash
cd mobile
npm run appstore:contract
```

The contract checks Apple's text limits, confirms Apple-only wording, and
keeps the public safety, privacy, Companion, Standalone, widget, and optional
support-purchase claims aligned. It does not upload metadata to App Store
Connect or prove that external services and in-app purchase products are live.
