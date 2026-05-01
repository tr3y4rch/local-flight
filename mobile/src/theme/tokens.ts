export const spacing = {
  xs: 6,
  sm: 10,
  md: 16,
  lg: 22,
  xl: 30
};

export const radius = {
  sm: 10,
  md: 16,
  lg: 24
};

export type MobileThemeMode = "dark" | "light";
export type MobileSkin = "standard" | "technical" | "neon" | "cyan" | "crt";
export type StatusPalette = {
  scheduled: string;
  departed: string;
  boarding: string;
  delayed: string;
  cancelled: string;
};

export type MobileAppearance = {
  key: string;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  mono: string;
  bg: string;
  shell: string;
  header: string;
  line: string;
  lineSoft: string;
  row: string;
  rowAlt: string;
  text: string;
  textMuted: string;
  textDim: string;
  blue: string;
  blue2: string;
  green: string;
  amber: string;
  red: string;
  status: StatusPalette;
};

const MONO = "Menlo";

function defineAppearance(
  themeMode: MobileThemeMode,
  skin: MobileSkin,
  values: Omit<MobileAppearance, "key" | "themeMode" | "skin" | "mono">
): MobileAppearance {
  return {
    key: `${themeMode}:${skin}`,
    themeMode,
    skin,
    mono: MONO,
    ...values
  };
}

const MOBILE_APPEARANCES: Record<string, MobileAppearance> = {
  "dark:standard": defineAppearance("dark", "standard", {
    bg: "#0a1118",
    shell: "#101927",
    header: "#0c1624",
    line: "#203651",
    lineSoft: "rgba(232, 240, 254, 0.08)",
    row: "rgba(255,255,255,0.03)",
    rowAlt: "rgba(255,255,255,0.05)",
    text: "#ecf4ff",
    textMuted: "#6c94c0",
    textDim: "#436789",
    blue: "#6faad9",
    blue2: "#9cc7ea",
    green: "#29e287",
    amber: "#f0b429",
    red: "#ff6b6b",
    status: {
      scheduled: "#6faad9",
      departed: "#9cc7ea",
      boarding: "#29e287",
      delayed: "#f0b429",
      cancelled: "#ff6b6b"
    }
  }),
  "light:standard": defineAppearance("light", "standard", {
    bg: "#eef4fb",
    shell: "#f8fbff",
    header: "#e8f0f8",
    line: "#c5d7ea",
    lineSoft: "rgba(22, 50, 78, 0.10)",
    row: "rgba(255,255,255,0.82)",
    rowAlt: "rgba(245,249,255,0.92)",
    text: "#17314d",
    textMuted: "#466b90",
    textDim: "#7b9abb",
    blue: "#2d6fa5",
    blue2: "#4b87b8",
    green: "#138e52",
    amber: "#b98514",
    red: "#c34f4f",
    status: {
      scheduled: "#2d6fa5",
      departed: "#4b87b8",
      boarding: "#138e52",
      delayed: "#b98514",
      cancelled: "#c34f4f"
    }
  }),
  "dark:technical": defineAppearance("dark", "technical", {
    bg: "#080c12",
    shell: "#0d1520",
    header: "#0a1220",
    line: "#1e3a5a",
    lineSoft: "rgba(255,255,255,0.05)",
    row: "rgba(255,255,255,0.022)",
    rowAlt: "rgba(255,255,255,0.03)",
    text: "#e8f0fe",
    textMuted: "#4a7aaa",
    textDim: "#2a5a8a",
    blue: "#4a9eda",
    blue2: "#7ab0d8",
    green: "#00c040",
    amber: "#f0b429",
    red: "#ff6b6b",
    status: {
      scheduled: "#4a9eda",
      departed: "#7ab0d8",
      boarding: "#00c040",
      delayed: "#f0b429",
      cancelled: "#ff6b6b"
    }
  }),
  "light:technical": defineAppearance("light", "technical", {
    bg: "#eef3f9",
    shell: "#f7fbff",
    header: "#ebf2fb",
    line: "#c3d2e3",
    lineSoft: "rgba(16, 42, 68, 0.10)",
    row: "rgba(255,255,255,0.82)",
    rowAlt: "rgba(240,246,252,0.94)",
    text: "#18324c",
    textMuted: "#5a7a9a",
    textDim: "#7b94af",
    blue: "#3f7fb9",
    blue2: "#5a97ca",
    green: "#2f7e5a",
    amber: "#c08a1e",
    red: "#ba5858",
    status: {
      scheduled: "#3f7fb9",
      departed: "#5a97ca",
      boarding: "#2f7e5a",
      delayed: "#c08a1e",
      cancelled: "#ba5858"
    }
  }),
  "dark:neon": defineAppearance("dark", "neon", {
    bg: "#000c05",
    shell: "#03140b",
    header: "#010f07",
    line: "#0f5228",
    lineSoft: "rgba(0, 255, 80, 0.10)",
    row: "rgba(0,255,80,0.05)",
    rowAlt: "rgba(0,255,80,0.08)",
    text: "#c9ffd9",
    textMuted: "#4eb876",
    textDim: "#2a7d45",
    blue: "#00ff50",
    blue2: "#8dffb8",
    green: "#00ff50",
    amber: "#baff00",
    red: "#ff4c6a",
    status: {
      scheduled: "#00ff50",
      departed: "#8dffb8",
      boarding: "#00ff50",
      delayed: "#baff00",
      cancelled: "#ff4c6a"
    }
  }),
  "light:neon": defineAppearance("light", "neon", {
    bg: "#eefcf0",
    shell: "#f8fff8",
    header: "#ebfbea",
    line: "#a6d3ae",
    lineSoft: "rgba(0, 102, 32, 0.10)",
    row: "rgba(255,255,255,0.86)",
    rowAlt: "rgba(240,255,242,0.95)",
    text: "#134022",
    textMuted: "#418455",
    textDim: "#70a37b",
    blue: "#0d9f4a",
    blue2: "#3fbc72",
    green: "#0d9f4a",
    amber: "#8ca800",
    red: "#cf4b63",
    status: {
      scheduled: "#0d9f4a",
      departed: "#3fbc72",
      boarding: "#0d9f4a",
      delayed: "#8ca800",
      cancelled: "#cf4b63"
    }
  }),
  "dark:cyan": defineAppearance("dark", "cyan", {
    bg: "#041018",
    shell: "#071823",
    header: "#05131d",
    line: "#0e5063",
    lineSoft: "rgba(0,204,255,0.10)",
    row: "rgba(0,204,255,0.045)",
    rowAlt: "rgba(0,204,255,0.07)",
    text: "#d8fbff",
    textMuted: "#4ea7b6",
    textDim: "#2f6e82",
    blue: "#00ccff",
    blue2: "#7ce8ff",
    green: "#00ffcc",
    amber: "#ffd24a",
    red: "#ff5e7e",
    status: {
      scheduled: "#00ccff",
      departed: "#7ce8ff",
      boarding: "#00ffcc",
      delayed: "#ffd24a",
      cancelled: "#ff5e7e"
    }
  }),
  "light:cyan": defineAppearance("light", "cyan", {
    bg: "#eefcff",
    shell: "#f7feff",
    header: "#eafbff",
    line: "#a8d5df",
    lineSoft: "rgba(0, 110, 132, 0.10)",
    row: "rgba(255,255,255,0.86)",
    rowAlt: "rgba(240,252,255,0.96)",
    text: "#13414c",
    textMuted: "#46808c",
    textDim: "#72a0a7",
    blue: "#0d8fb0",
    blue2: "#4cb6cc",
    green: "#0aa889",
    amber: "#b98712",
    red: "#cd4f6a",
    status: {
      scheduled: "#0d8fb0",
      departed: "#4cb6cc",
      boarding: "#0aa889",
      delayed: "#b98712",
      cancelled: "#cd4f6a"
    }
  }),
  "dark:crt": defineAppearance("dark", "crt", {
    bg: "#120b02",
    shell: "#1a1005",
    header: "#150d03",
    line: "#62451a",
    lineSoft: "rgba(255,170,0,0.10)",
    row: "rgba(255,170,0,0.045)",
    rowAlt: "rgba(255,170,0,0.07)",
    text: "#ffe4a0",
    textMuted: "#d19c45",
    textDim: "#8f6220",
    blue: "#ffaa00",
    blue2: "#ffcc44",
    green: "#ffaa00",
    amber: "#ffdd00",
    red: "#ff5a2f",
    status: {
      scheduled: "#ffaa00",
      departed: "#ffcc44",
      boarding: "#ffaa00",
      delayed: "#ffdd00",
      cancelled: "#ff5a2f"
    }
  }),
  "light:crt": defineAppearance("light", "crt", {
    bg: "#fff7eb",
    shell: "#fffcf4",
    header: "#fff4df",
    line: "#d7bf95",
    lineSoft: "rgba(122, 80, 0, 0.10)",
    row: "rgba(255,255,255,0.88)",
    rowAlt: "rgba(255,248,233,0.96)",
    text: "#4d3510",
    textMuted: "#8d6b2e",
    textDim: "#b19156",
    blue: "#bf7f12",
    blue2: "#d89c2a",
    green: "#bf7f12",
    amber: "#d9ad00",
    red: "#d25c35",
    status: {
      scheduled: "#bf7f12",
      departed: "#d89c2a",
      boarding: "#bf7f12",
      delayed: "#d9ad00",
      cancelled: "#d25c35"
    }
  })
};

export const MOBILE_THEME_OPTIONS: Array<{ id: MobileThemeMode; label: string }> = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" }
];

export const MOBILE_SKIN_OPTIONS: Array<{ id: MobileSkin; label: string }> = [
  { id: "standard", label: "Standard" },
  { id: "technical", label: "Technical" },
  { id: "neon", label: "Neon" },
  { id: "cyan", label: "Cyan" },
  { id: "crt", label: "CRT" }
];

export const DEFAULT_THEME_MODE: MobileThemeMode = "dark";
export const DEFAULT_SKIN: MobileSkin = "technical";
export const DEFAULT_MOBILE_APPEARANCE: MobileAppearance = MOBILE_APPEARANCES[`${DEFAULT_THEME_MODE}:${DEFAULT_SKIN}`]!;

export function getMobileAppearance(
  themeMode: MobileThemeMode,
  skin: MobileSkin
): MobileAppearance {
  return (
    MOBILE_APPEARANCES[`${themeMode}:${skin}`] ||
    DEFAULT_MOBILE_APPEARANCE
  );
}

export const mono = DEFAULT_MOBILE_APPEARANCE.mono;
export const palette = DEFAULT_MOBILE_APPEARANCE;
export const colors = {
  bg: palette.bg,
  panel: palette.row,
  panel2: palette.shell,
  border: palette.line,
  text: palette.text,
  muted: palette.textMuted,
  dim: palette.textDim,
  blue: palette.blue,
  green: palette.green,
  amber: palette.amber,
  red: palette.red
};
