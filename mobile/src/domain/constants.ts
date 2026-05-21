import type { DashboardSnapshot, MatrixAnimationMode, MatrixPaletteId, MatrixPresetId, MatrixRuntimeConfigSave } from "../api/types";
import { appVersion } from "../device/identity";
import type { HistoryWindow, RadarRadius } from "./types";

export const APP_VERSION = appVersion();
export const COMPANION_PING_MS = 10 * 60 * 1000;

export const HISTORY_WINDOWS: HistoryWindow[] = [24, 72, 168, 720, 2160];
export const RADAR_RADII: RadarRadius[] = [1, 2, 3, 5, 10, 20, 40];

export const MATRIX_ROWS = [2, 3, 4, 5, 6];
export const MATRIX_BRIGHTNESS = [0.4, 0.6, 0.8, 1];
export const MATRIX_REFRESH_SECONDS = [30, 60, 120, 300];
export const MATRIX_ROTATION_SECONDS = [5, 8, 10, 15, 30];
export const MATRIX_ANIMATION_SPEEDS = [1, 2, 3, 4, 5];

export const MATRIX_PRESETS: Array<{
  id: MatrixPresetId;
  label: string;
  meta: string;
  detail: string;
  palettes: MatrixPaletteId[];
  showGateInfo: boolean;
}> = [
  {
    id: "real_fids",
    label: "Real FIDS",
    meta: "Passenger board",
    detail: "Routes, gates, status, and compact weather for physical display.",
    palettes: ["pax_blue", "solari_amber", "ice_white", "sunset_terminal", "amber", "green", "cyan", "technical"],
    showGateInfo: true
  },
  {
    id: "vatsim_pilot",
    label: "VATSIM Pilot",
    meta: "Virtual flying",
    detail: "Callsign-focused board with quieter virtual flight context.",
    palettes: ["vatsim_scope", "tower_scope", "night_ops", "phosphor", "indigo_night", "neon"],
    showGateInfo: false
  },
  {
    id: "vatsim_atc",
    label: "VATSIM ATC",
    meta: "Controller view",
    detail: "Cycles departures, arrivals, and weather for ATC-style ops.",
    palettes: ["tower_scope", "vatsim_scope", "night_ops", "phosphor", "indigo_night"],
    showGateInfo: false
  }
];

export const MATRIX_ANIMATION_MODES: Array<{ id: MatrixAnimationMode; label: string; meta: string }> = [
  { id: "split_flap", label: "Split-flap", meta: "classic" },
  { id: "typewriter", label: "Typewriter", meta: "ticker" },
  { id: "cascade", label: "Cascade", meta: "rows" },
  { id: "slide_left", label: "Slide left", meta: "scroll" },
  { id: "slide_right", label: "Slide right", meta: "scroll" },
  { id: "static", label: "Static", meta: "calm" }
];

export const MATRIX_PALETTE_OPTIONS: Array<{
  id: MatrixPaletteId;
  label: string;
  meta: string;
  colors: {
    off: string;
    green: string;
    white: string;
    dim: string;
    amber: string;
    red: string;
    cyan: string;
  };
}> = [
  {
    id: "pax_blue",
    label: "PAX Blue",
    meta: "terminal",
    colors: { off: "#040a12", green: "#1d8cff", white: "#f6fbff", dim: "#2c5f92", amber: "#ffbd45", red: "#ff4d5f", cyan: "#65e7ff" }
  },
  {
    id: "solari_amber",
    label: "Solari Amber",
    meta: "warm",
    colors: { off: "#0b0600", green: "#ffad2f", white: "#ffe6a8", dim: "#8c5a12", amber: "#ffe15c", red: "#ff5538", cyan: "#ffd06c" }
  },
  {
    id: "tower_scope",
    label: "Tower Scope",
    meta: "ATC",
    colors: { off: "#001006", green: "#38ff75", white: "#d9ffe6", dim: "#1b7a3c", amber: "#ffd84a", red: "#ff4c4c", cyan: "#4deaff" }
  },
  {
    id: "vatsim_scope",
    label: "VATSIM Scope",
    meta: "virtual",
    colors: { off: "#031006", green: "#74ff5f", white: "#d8ffd0", dim: "#2b7a2f", amber: "#ffe066", red: "#ff5b5b", cyan: "#6bdcff" }
  },
  {
    id: "night_ops",
    label: "Night Ops",
    meta: "ramp",
    colors: { off: "#020812", green: "#4bb8ff", white: "#d8f7ff", dim: "#27506e", amber: "#f4c95d", red: "#ff5d7a", cyan: "#49f0c8" }
  },
  {
    id: "sunset_terminal",
    label: "Sunset Terminal",
    meta: "bold",
    colors: { off: "#12040b", green: "#ff7a3d", white: "#fff2e6", dim: "#8e3f55", amber: "#ffd166", red: "#ff3864", cyan: "#ff4fd8" }
  },
  {
    id: "ice_white",
    label: "Ice White",
    meta: "bright",
    colors: { off: "#060a0f", green: "#bde9ff", white: "#ffffff", dim: "#6a8195", amber: "#ffd35a", red: "#ff5252", cyan: "#66d9ff" }
  },
  {
    id: "crt",
    label: "CRT Amber",
    meta: "retro",
    colors: { off: "#060400", green: "#ffcc44", white: "#ffeeaa", dim: "#7a5000", amber: "#ffdd00", red: "#ff4020", cyan: "#ffaa00" }
  },
  {
    id: "neon",
    label: "Neon Green",
    meta: "showpiece",
    colors: { off: "#000d00", green: "#00ff50", white: "#dcffdc", dim: "#007a28", amber: "#aaff00", red: "#ff4040", cyan: "#aaff00" }
  },
  {
    id: "amber",
    label: "Amber",
    meta: "classic",
    colors: { off: "#0b0600", green: "#ffae2e", white: "#ffebb4", dim: "#7e5416", amber: "#ffdf55", red: "#ff5738", cyan: "#ffc56b" }
  },
  {
    id: "green",
    label: "Green",
    meta: "terminal",
    colors: { off: "#001006", green: "#28f76e", white: "#dcffe6", dim: "#227c3e", amber: "#ffc94a", red: "#ff4d4d", cyan: "#55e7ff" }
  },
  {
    id: "cyan",
    label: "Cyan",
    meta: "cool",
    colors: { off: "#00080f", green: "#00ccff", white: "#d7fcff", dim: "#006688", amber: "#ffcc00", red: "#ff4060", cyan: "#00ffcc" }
  },
  {
    id: "technical",
    label: "Technical",
    meta: "app",
    colors: { off: "#040608", green: "#4a9eda", white: "#d2e6f8", dim: "#507494", amber: "#d4a020", red: "#c04040", cyan: "#7ce7ff" }
  },
  {
    id: "phosphor",
    label: "Phosphor",
    meta: "mono",
    colors: { off: "#031006", green: "#39ff14", white: "#cdffc6", dim: "#3a8a18", amber: "#aaff00", red: "#ff3232", cyan: "#b4ffb4" }
  },
  {
    id: "indigo_night",
    label: "Indigo Night",
    meta: "ambient",
    colors: { off: "#06051a", green: "#8272ff", white: "#d8d4ff", dim: "#5548b8", amber: "#ffd84a", red: "#ff6b8a", cyan: "#4deaff" }
  },
  {
    id: "rose_gold",
    label: "Rose Gold",
    meta: "decor",
    colors: { off: "#170712", green: "#ff7ecb", white: "#ffd8ee", dim: "#a04878", amber: "#ffd166", red: "#ff3864", cyan: "#ffb8c8" }
  }
];

export const LAUNCH_MIN_MS = 7800;
export const LAUNCH_NATIVE_MIN_MS = 420;
export const LAUNCH_ANIMATION_DELAY_MS = 180;
export const LAUNCH_STATUS_STEPS = [
  "Starting mobile",
  "Loading saved server",
  "Checking LAN link",
  "Aligning FIDS rows",
  "Priming radar sweep",
  "Syncing local profile",
  "Opening mobile"
];

export const REFRESH_OPTIONS: Array<{ seconds: number; label: string }> = [
  { seconds: 900, label: "15 min" },
  { seconds: 1800, label: "30 min" },
  { seconds: 2700, label: "45 min" },
  { seconds: 3600, label: "1 h" },
  { seconds: 7200, label: "2 h" },
  { seconds: 14400, label: "4 h" },
  { seconds: 28800, label: "8 h" },
  { seconds: 43200, label: "12 h" },
  { seconds: 86400, label: "24 h" }
];

export const EMPTY_SNAPSHOT: DashboardSnapshot = {
  config: null,
  state: null,
  system: null,
  connections: null,
  updates: null,
  budget: null,
  scheduler: null,
  metar: null
};

export const DEFAULT_MATRIX_CONFIG: MatrixRuntimeConfigSave = {
  preset: "real_fids",
  brightness: 0.8,
  max_rows: 4,
  refresh_seconds: 60,
  default_view: "departures",
  page_rotation_seconds: 10,
  animation_enabled: true,
  animation_mode: "split_flap",
  animation_speed: 3,
  status_animation_enabled: true,
  show_gate_info: true,
  palette: "pax_blue",
  options: {
    palette: "pax_blue",
    show_metar: true,
    show_weather: true,
    show_gate_info: true,
    animation_mode: "split_flap"
  }
};
