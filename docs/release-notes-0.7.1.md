# Local Flight 0.7.1

Local Flight 0.7.1 is a desktop, Linux server, and Raspberry Pi update focused
on the first-launch setup. Relay Access, pricing, founder access, and the free
routes are unchanged from 0.7.0. Mobile 0.7.1 continues TestFlight and Play
internal testing.

## Setup wizard

- Both setup wizards, the desktop window and the browser page, now share one
  set of step names, headings, card text, buttons, and icons, so they read and
  look the same.
- Six clearer steps: Welcome, Airport, Flight data, Provider keys, Problem
  reports, and Review and open. Provider keys are grouped into Schedules and
  Radar, and the step is only shown for Bring Your Own Keys.
- Emoji icons are replaced by a small set of line icons drawn the same way on
  Windows, macOS, Linux, and in the browser.
- Gentle motion: pages slide in, a chosen card pulses once, completed steps tick,
  and the finish screen fades out before Local Flight opens. A new **Reduce
  motion** setting in Settings turns this off; the browser also follows the
  system reduce-motion preference.
- The browser setup page follows the app theme and skin.

## Windows fixes

- Setup text on Windows was hard to read and looked different from macOS. The
  desktop app now ships static weights of its DM Sans font, which Windows
  renders cleanly, instead of one variable font file.
- The setup window sizes itself from the window it actually gets rather than
  the raw screen, so 150% scaled laptops and ultrawide monitors no longer see
  cramped three-column layouts. It stays a normal window and re-flows when
  resized.

## Other fixes

- A few interface strings and one board placeholder showed mangled characters
  instead of a dash. They are fixed.

## Availability

0.7.1 keeps the 0.7.0 package matrix: Windows x64, macOS Apple silicon and
Intel, Linux AppImage and Ubuntu/Debian desktop and server packages, and the
Raspberry Pi source bundle. Mobile testing builds keep their existing store
counters until a new upload requires a change.

Local Flight is an informational display. Its flight, weather, radar, map, and
relay data may be delayed, incomplete, cached, unavailable, or wrong. Do not
use it for navigation, dispatch, operational control, or safety decisions.
