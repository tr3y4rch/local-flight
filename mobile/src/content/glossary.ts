import type { EnglishGlossary } from "./contracts";

/** Preferred product language for English UI, help, and accessibility copy. */
export const englishGlossary = {
  flightBoard: {
    term: "flight board",
    definition: "The arrivals or departures list shown by Local Flight.",
    audience: "everyday",
    preferredUsage: "Use “flight board” or “board” in everyday UI.",
    avoid: ["feed", "schedule database"]
  },
  companion: {
    term: "Companion",
    definition: "Mobile mode that connects to a Local Flight host run by the user.",
    audience: "everyday",
    preferredUsage: "Capitalize Companion when naming the mode.",
    avoid: ["client mode", "slave"]
  },
  standalone: {
    term: "Standalone",
    definition: "Mobile mode that reads a conservatively refreshed public relay board without a user-run host.",
    audience: "everyday",
    preferredUsage: "Capitalize Standalone when naming the mode.",
    avoid: ["cloud mode", "account mode"]
  },
  remoteCompanion: {
    term: "Remote Companion",
    definition: "The explicitly paired, end-to-end encrypted fallback used when a Companion cannot reach its host over LAN.",
    audience: "help",
    preferredUsage: "Say “Remote Companion fallback”; never imply that the relay can read board contents.",
    avoid: ["cloud sync", "public tunnel"]
  },
  communityRelay: {
    term: "Community Relay",
    definition: "The shared Local Flight service that provides bounded public data and relay functions.",
    audience: "help",
    preferredUsage: "Use the full name on first mention, then “relay”.",
    avoid: ["Local Flight cloud", "provider proxy"]
  },
  supportId: {
    term: "Support ID",
    definition: "The public install fingerprint safe to show in support surfaces.",
    audience: "help",
    preferredUsage: "Use “Support ID” in UI; raw install identifiers are not user-facing.",
    avoid: ["install UUID", "device UUID"]
  },
  movement: {
    term: "movement",
    definition: "One deduplicated arrival or departure, not every observation of a flight.",
    audience: "everyday",
    preferredUsage: "Use movement when describing History counts.",
    avoid: ["hit", "observation count"]
  },
  radar: {
    term: "radar",
    definition: "Local Flight’s informational view of available live aircraft tracks and airport context.",
    audience: "everyday",
    preferredUsage: "Use “radar view” when a distinction from a real aviation radar system matters.",
    avoid: ["air traffic control radar", "navigation display"]
  },
  fids: {
    term: "FIDS",
    definition: "Flight Information Display System, the technical category for a flight board.",
    audience: "technical",
    preferredUsage: "Spell out on first mention in technical help; prefer “flight board” in daily UI.",
    avoid: ["FIDS board board"]
  },
  vatsim: {
    term: "VATSIM",
    definition: "The public virtual aviation network used by Local Flight’s virtual mode.",
    audience: "help",
    preferredUsage: "Keep virtual traffic callsign and flight-plan focused.",
    avoid: ["real traffic"]
  },
  metar: {
    term: "METAR",
    definition: "A coded aviation weather observation for an airport.",
    audience: "technical",
    preferredUsage: "Use “weather” in passenger copy and METAR in pilot or technical views.",
    avoid: ["forecast"]
  },
  matrix: {
    term: "Matrix",
    definition: "A Local Flight display output for supported HUB75 LED matrix hardware.",
    audience: "help",
    preferredUsage: "Capitalize Matrix when naming the Local Flight output or control surface.",
    avoid: ["sign controller"]
  }
} as const satisfies EnglishGlossary;

export const glossary = englishGlossary;
export const ENGLISH_GLOSSARY = englishGlossary;
