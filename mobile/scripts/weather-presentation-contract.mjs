#!/usr/bin/env node
import assert from "node:assert/strict";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const mobileRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const presentation = await import(pathToFileURL(path.join(mobileRoot, "src/domain/weatherPresentation.ts")).href);

const metar = {
  raw_text: "EDDH 301320Z 23016KT 9999 RA BKN025 19/17 Q1013",
  weather_summary: "Rain",
  flight_category: "MVFR",
  temperature_c: 19,
  wind_dir_deg: 230,
  wind_speed_kt: 16
};

assert.equal(presentation.weatherSummaryForDisplay(metar, "passenger"), "Rain");
assert.equal(presentation.weatherSummaryForDisplay(metar, "pilot"), "MVFR · 230° 16 kt");
assert.equal(
  presentation.weatherSummaryForDisplay(metar, "vatsim"),
  "EDDH 301320Z 23016KT 9999 RA BKN025 19/17 Q1013"
);
assert.equal(presentation.weatherModeContext("passenger"), "Plain-language airport weather");
assert.equal(presentation.weatherModeContext("pilot"), "Decoded aviation weather");
assert.equal(presentation.weatherModeContext("vatsim"), "Raw METAR observation");
assert.notEqual(
  presentation.weatherSummaryForDisplay(metar, "passenger"),
  presentation.weatherSummaryForDisplay(metar, "pilot")
);
assert.notEqual(
  presentation.weatherSummaryForDisplay(metar, "pilot"),
  presentation.weatherSummaryForDisplay(metar, "vatsim")
);

console.log("Weather presentation contract checks passed.");
