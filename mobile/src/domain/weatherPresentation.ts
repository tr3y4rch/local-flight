import type { Metar } from "../api/types";
import type { MobileWeatherDisplayMode } from "../storage/settings";

function clean(value: unknown): string {
  const text = String(value ?? "").trim();
  return text && text !== "-" ? text : "";
}

function finiteNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

export function weatherRawMetar(metar: Metar | null | undefined): string {
  return clean(metar?.raw_text) || clean(metar?.raw_ob) || clean(metar?.rawOb);
}

export function weatherCategory(metar: Metar | null | undefined): string {
  return clean(metar?.flight_cat) || clean(metar?.flight_category) || clean(metar?.category) || "--";
}

export function weatherTemperature(metar: Metar | null | undefined): string {
  const value = finiteNumber(metar?.temperature_c, metar?.temp_c);
  return value == null ? "--°" : `${Math.round(value)}°`;
}

export function weatherCondition(metar: Metar | null | undefined): string {
  const semantic = clean(metar?.weather_label)
    || clean(metar?.weather_summary)
    || clean(metar?.weather?.label)
    || clean(metar?.weather?.summary);
  if (semantic) return semantic;
  const text = `${clean(metar?.decoded_summary)} ${weatherRawMetar(metar)}`.toLowerCase();
  if (!text.trim()) return "Weather unavailable";
  if (/thunder|tsra|\bts\b/.test(text)) return "Storms nearby";
  if (/snow|\bsn\b/.test(text)) return "Snow";
  if (/rain|showers|\bra\b|drizzle|\bdz\b/.test(text)) return "Rain";
  if (/fog|mist|\bfg\b|\bbr\b/.test(text)) return "Low visibility";
  if (/overcast|broken|\bovc\b|\bbkn\b/.test(text)) return "Cloudy";
  if (/few|scattered|\bfew\b|\bsct\b/.test(text)) return "Partly cloudy";
  if (/cavok|clear|no significant/.test(text)) return "Clear";
  const category = weatherCategory(metar);
  return category === "--" ? "Current weather" : `${category} conditions`;
}

function compactWind(metar: Metar | null | undefined): string {
  const supplied = clean(metar?.wind_display) || clean(metar?.wind);
  if (supplied) return supplied;
  const speed = finiteNumber(metar?.wind_speed_kt, metar?.wind_speed, metar?.windSpeed, metar?.wspd);
  if (speed == null) return "";
  if (speed === 0) return "Calm";
  const direction = finiteNumber(metar?.wind_dir_deg, metar?.wind_dir, metar?.windDir, metar?.wdir);
  const directionText = direction == null ? "VRB" : `${Math.round(direction).toString().padStart(3, "0")}°`;
  const gust = finiteNumber(metar?.wind_gust_kt, metar?.wind_gust, metar?.windGust, metar?.wgst);
  return `${directionText} ${Math.round(speed)} kt${gust == null ? "" : ` G${Math.round(gust)}`}`;
}

export function weatherSummaryForDisplay(
  metar: Metar | null | undefined,
  mode: MobileWeatherDisplayMode
): string {
  if (!metar) return "Weather unavailable";
  if (mode === "vatsim") return weatherRawMetar(metar) || "Raw METAR unavailable";
  if (mode === "pilot") {
    const category = weatherCategory(metar);
    const wind = compactWind(metar);
    const parts = [category === "--" ? "" : category, wind].filter(Boolean);
    return parts.join(" · ") || clean(metar.decoded_summary) || weatherCondition(metar);
  }
  return weatherCondition(metar);
}

export function weatherModeContext(mode: MobileWeatherDisplayMode): string {
  if (mode === "vatsim") return "Raw METAR observation";
  if (mode === "pilot") return "Decoded aviation weather";
  return "Plain-language airport weather";
}
