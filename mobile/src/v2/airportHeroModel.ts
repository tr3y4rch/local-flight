import type { Metar } from "../api/types";
import { weatherCategory, weatherSummaryForDisplay, weatherTemperature } from "../domain/weatherPresentation";
import type { MobileWeatherDisplayMode } from "../storage/settings";

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
  weatherDisplayMode: MobileWeatherDisplayMode;
}): AirportHeroViewModel {
  return {
    airportName: clean(input.airportName) || clean(input.airportCode) || "Your airport",
    airportCode: clean(input.airportCode),
    location: clean(input.location),
    identityLine: [clean(input.airportCode), clean(input.location)].filter(Boolean).join(" · "),
    localTime: clean(input.localTime) || "--:--",
    connectionLabel: clean(input.connectionLabel) || "Offline",
    freshnessLabel: clean(input.freshnessLabel) || "Waiting for an update",
    temperature: weatherTemperature(input.metar),
    weatherSummary: weatherSummaryForDisplay(input.metar, input.weatherDisplayMode),
    weatherCategory: weatherCategory(input.metar)
  };
}
