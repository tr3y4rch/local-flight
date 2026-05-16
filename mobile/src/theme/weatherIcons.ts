// Weather glyph resolver for the mobile companion.
//
// Lives next to the icon registry on purpose: it returns a
// `LocalFlightWeatherIconName` (semantic), not a raw MaterialCommunityIcons
// glyph. The registry maps that semantic name to the actual character.
//
// AGENTS.md acceptance: missing weather must show a neutral unavailable
// glyph, never a broken icon or raw METAR fragment. That's "weather-unknown".

import type { Metar } from "../api/types";
import type { LocalFlightWeatherIconName } from "./icons";

// Look at the most semantic field first (server-decoded summary), then raw
// METAR text, then bail to "unknown". This mirrors the rule the desktop
// shells follow when picking a weather glyph.
export function weatherIconFor(metar: Metar | null | undefined): LocalFlightWeatherIconName {
  if (!metar) return "weather-unknown";

  const text = `${metar.decoded_summary || ""} ${metar.raw_text || ""}`.toLowerCase();
  if (!text.trim()) return "weather-unknown";

  if (/thunder|tsra|ts\b/.test(text)) return "weather-thunder";
  if (/snow|\bsn\b/.test(text)) return "weather-snow";
  if (/rain|showers|\bra\b|drizzle|\bdz\b/.test(text)) return "weather-rain";
  if (/fog|mist|\bfg\b|\bbr\b/.test(text)) return "weather-fog";
  if (/overcast|broken|\bovc\b|\bbkn\b/.test(text)) return "weather-cloudy";
  if (/few|scattered|\bfew\b|\bsct\b/.test(text)) return "weather-partly-cloudy";
  if (/cavok|clear|no significant/.test(text)) return "weather-clear";

  return "weather-clear";
}
