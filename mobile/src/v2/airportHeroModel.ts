import type { Metar } from "../api/types";

export type AirportHeroViewModel = {
  airportName: string;
  airportCode: string;
  location: string;
  identityLine: string;
  localTime: string;
  connectionLabel: string;
  freshnessLabel: string;
  temperature: string;
  weatherSummary: string;
  weatherCategory: string;
};

function clean(value: unknown): string {
  const text = String(value ?? "").trim();
  return text && text !== "-" ? text : "";
}

export function airportHeroViewModel(input: {
  airportName: string;
  airportCode: string;
  location?: string;
  localTime: string;
  connectionLabel?: string;
  freshnessLabel: string;
  metar: Metar | null;
}): AirportHeroViewModel {
  const temperature = input.metar?.temperature_c ?? input.metar?.temp_c;
  return {
    airportName: clean(input.airportName) || clean(input.airportCode) || "Your airport",
    airportCode: clean(input.airportCode),
    location: clean(input.location),
    identityLine: [clean(input.airportCode), clean(input.location)].filter(Boolean).join(" · "),
    localTime: clean(input.localTime) || "--:--",
    connectionLabel: clean(input.connectionLabel) || "Offline",
    freshnessLabel: clean(input.freshnessLabel) || "Waiting for an update",
    temperature: typeof temperature === "number" ? `${Math.round(temperature)}°` : "--°",
    weatherSummary:
      clean(input.metar?.weather_summary) ||
      clean(input.metar?.decoded_summary) ||
      clean(input.metar?.weather_label) ||
      "Weather unavailable",
    weatherCategory:
      clean(input.metar?.flight_cat) ||
      clean(input.metar?.flight_category) ||
      clean(input.metar?.category) ||
      "--"
  };
}
