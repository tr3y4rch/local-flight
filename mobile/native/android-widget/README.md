# Local Flight Android Widget

This is the tracked source template for the Android home-screen widget. Expo
prebuild copies it into the generated `mobile/android/` project through
`plugins/with-localflight-android-widget.js`.

The widget reads only `localflight-widget-snapshot.json` from the app's private
files directory. It never opens a LAN, relay, or provider connection. Opening
the app refreshes that snapshot, and a meaningful write asks Android to redraw
installed widget instances immediately through the tracked local Expo bridge.
The widget refresh icon opens Local Flight's foreground refresh path rather than
pretending to fetch from a stale local file. Android also gets an OS-managed
background task and a 30-minute passive widget redraw, but both are inexact and
subject to battery policy. Day/night color resources follow the launcher/system
appearance without changing the independent appearance selected inside Local
Flight.

Safety rules:

- Reject missing, empty, oversized, malformed, or wrong-schema snapshots.
- Treat missing or expired timestamps as stale.
- Limit displayed text and rows before passing them to `RemoteViews`.
- Keep the receiver non-exported and use explicit immutable pending intents.
- Keep payment, account, and provider credentials out of the snapshot.

After `npx expo prebuild --platform android --clean`, verify the generated
manifest receiver, Kotlin package, XML resources, and then build with:

```bash
cd mobile/android
./gradlew :app:assembleDebug
```

Physical testing should cover compact and resizable widgets, empty/stale data,
Companion and Standalone snapshots, app tap-through, and launcher differences
on both a Pixel-style launcher and Samsung One UI.
