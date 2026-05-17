// Weather glyph resolver for the mobile companion.
//
// Lives next to the icon registry on purpose: it returns a
// `LocalFlightIconName` from the central registry, not a raw ad-hoc glyph.
//
// AGENTS.md acceptance: missing weather must show a neutral unavailable
// glyph, never a broken icon or raw METAR fragment.

import type { Metar } from "../api/types";
import type { LocalFlightIconName } from "./icons";
import { weatherIconForMetar } from "./icons";

// Compatibility wrapper for older imports; the actual resolver now lives in
// the central icon registry so all weather surfaces share one mapping.
export function weatherIconFor(metar: Metar | null | undefined): LocalFlightIconName {
  return weatherIconForMetar(metar);
}
