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
export type MobileSkin = "standard" | "technical" | "neon" | "cyan" | "crt" | "high_contrast";
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
  brand: string;
  ui: string;
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

/** Local Flight-authored content follows the Qt/LAN typography contract. */
export const UI_FONT_FAMILY = "DM Sans";
export const BOARD_FONT_FAMILY = "Space Mono";
export const BOARD_BOLD_FONT_FAMILY = "Space Mono Bold";
export const BRAND_FONT_FAMILY = "Audiowide";
/** UIKit/Android-owned navigation and form controls keep the platform face. */
export const NATIVE_FONT_FAMILY = "System";
export const MIN_TOUCH_TARGET = 44;
export const MIN_TEXT_SIZE = 11;

export const MOBILE_THEME_OPTIONS: Array<{ id: MobileThemeMode; label: string }> = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" }
];

export const MOBILE_SKIN_OPTIONS: Array<{ id: MobileSkin; label: string }> = [
  { id: "standard", label: "Signature" },
  { id: "high_contrast", label: "High contrast" }
];

/**
 * The V2 appearance preference is deliberately separate from the resolved
 * color scheme. `system` follows the device and resolves to light or dark at
 * runtime. Keeping this distinct avoids persisting a temporary system value as
 * an explicit user choice.
 */
export type MobileThemePreference = "system" | MobileThemeMode;
export type ThemePreference = MobileThemePreference;
export type MobileContrastPreference = "standard" | "high";
export type MobileSemanticThemeId = "warm_light" | "warm_dark" | "high_contrast_light" | "high_contrast";

export type SemanticStatusColors = {
  neutral: string;
  info: string;
  success: string;
  warning: string;
  danger: string;
};

/**
 * Role-based colors for new mobile surfaces. New UI should depend on these
 * roles rather than a visual color name so that all three palettes remain
 * interchangeable and contrast-safe.
 */
export type MobileSemanticColors = {
  background: string;
  surface: string;
  surfaceRaised: string;
  surfaceSunken: string;
  surfaceSubtle: string;
  border: string;
  borderStrong: string;
  borderSubtle: string;
  text: string;
  textSecondary: string;
  textMuted: string;
  textInverse: string;
  primary: string;
  primaryPressed: string;
  primarySoft: string;
  onPrimary: string;
  focusRing: string;
  overlay: string;
  disabled: string;
  status: SemanticStatusColors;
  flightStatus: StatusPalette;
};

export const typography = {
  family: {
    brand: BRAND_FONT_FAMILY,
    body: UI_FONT_FAMILY,
    board: BOARD_FONT_FAMILY,
    boardBold: BOARD_BOLD_FONT_FAMILY,
    native: NATIVE_FONT_FAMILY
  },
  size: {
    caption: 12,
    body: 15,
    bodyLarge: 17,
    title: 22,
    display: 30
  },
  lineHeight: {
    caption: 16,
    body: 21,
    bodyLarge: 24,
    title: 28,
    display: 36
  }
} as const;

export const sizing = {
  minimumTouchTarget: MIN_TOUCH_TARGET,
  minimumTextSize: MIN_TEXT_SIZE,
  iconSmall: 16,
  icon: 20,
  iconLarge: 24
} as const;

export type MobileSemanticTheme = {
  id: MobileSemanticThemeId;
  mode: MobileThemeMode;
  contrast: MobileContrastPreference;
  isDark: boolean;
  isHighContrast: boolean;
  colors: MobileSemanticColors;
  /** Singular alias retained for ergonomic access in style factories. */
  color: MobileSemanticColors;
  spacing: typeof spacing;
  radius: typeof radius;
  typography: typeof typography;
  sizing: typeof sizing;
};

function defineSemanticTheme(
  id: MobileSemanticThemeId,
  mode: MobileThemeMode,
  contrast: MobileContrastPreference,
  colors: MobileSemanticColors
): MobileSemanticTheme {
  return {
    id,
    mode,
    contrast,
    isDark: mode === "dark",
    isHighContrast: contrast === "high",
    colors,
    color: colors,
    spacing,
    radius,
    typography,
    sizing
  };
}

export const WARM_LIGHT_THEME = defineSemanticTheme("warm_light", "light", "standard", {
  background: "#f5f1e8",
  surface: "#fffdf8",
  surfaceRaised: "#ffffff",
  surfaceSunken: "#e9e3d8",
  surfaceSubtle: "#f0ebe2",
  border: "#c6c1b7",
  borderStrong: "#7a8791",
  borderSubtle: "#dfdad1",
  text: "#132638",
  textSecondary: "#354b5e",
  textMuted: "#536575",
  textInverse: "#ffffff",
  primary: "#2f6f9f",
  primaryPressed: "#245979",
  primarySoft: "#dce9f2",
  onPrimary: "#ffffff",
  focusRing: "#2f6f9f",
  overlay: "rgba(19, 38, 56, 0.54)",
  disabled: "#87939c",
  status: {
    neutral: "#536575",
    info: "#2f6f9f",
    success: "#1f6f61",
    warning: "#8b5c13",
    danger: "#a8473d"
  },
  flightStatus: {
    scheduled: "#2f6f9f",
    departed: "#354b5e",
    boarding: "#1f6f61",
    delayed: "#8b5c13",
    cancelled: "#a8473d"
  }
});

export const WARM_DARK_THEME = defineSemanticTheme("warm_dark", "dark", "standard", {
  background: "#08141d",
  surface: "#102330",
  surfaceRaised: "#17303f",
  surfaceSunken: "#050d13",
  surfaceSubtle: "#152a37",
  border: "#345061",
  borderStrong: "#6f8592",
  borderSubtle: "#243c4b",
  text: "#f5f0e8",
  textSecondary: "#ccd5d9",
  textMuted: "#a4b3be",
  textInverse: "#08141d",
  primary: "#74b5de",
  primaryPressed: "#9bcae5",
  primarySoft: "#193a4d",
  onPrimary: "#08141d",
  focusRing: "#a9daf2",
  overlay: "rgba(0, 0, 0, 0.68)",
  disabled: "#728592",
  status: {
    neutral: "#a4b3be",
    info: "#74b5de",
    success: "#59c1a5",
    warning: "#e3ad58",
    danger: "#ed8b7c"
  },
  flightStatus: {
    scheduled: "#74b5de",
    departed: "#ccd5d9",
    boarding: "#59c1a5",
    delayed: "#e3ad58",
    cancelled: "#ed8b7c"
  }
});

export const HIGH_CONTRAST_LIGHT_THEME = defineSemanticTheme("high_contrast_light", "light", "high", {
  background: "#fffdf8",
  surface: "#ffffff",
  surfaceRaised: "#ffffff",
  surfaceSunken: "#eee9df",
  surfaceSubtle: "#f5f1e8",
  border: "#000000",
  borderStrong: "#000000",
  borderSubtle: "#4a4a4a",
  text: "#000000",
  textSecondary: "#111111",
  textMuted: "#3d3d3d",
  textInverse: "#ffffff",
  primary: "#004b76",
  primaryPressed: "#003552",
  primarySoft: "#d4ecf8",
  onPrimary: "#ffffff",
  focusRing: "#6b21a8",
  overlay: "rgba(0, 0, 0, 0.62)",
  disabled: "#595959",
  status: {
    neutral: "#3d3d3d",
    info: "#004b76",
    success: "#006247",
    warning: "#744600",
    danger: "#92251d"
  },
  flightStatus: {
    scheduled: "#004b76",
    departed: "#111111",
    boarding: "#006247",
    delayed: "#744600",
    cancelled: "#92251d"
  }
});

export const HIGH_CONTRAST_THEME = defineSemanticTheme("high_contrast", "dark", "high", {
  background: "#000000",
  surface: "#000000",
  surfaceRaised: "#0a0a0a",
  surfaceSunken: "#000000",
  surfaceSubtle: "#141414",
  border: "#ffffff",
  borderStrong: "#ffffff",
  borderSubtle: "#bfbfbf",
  text: "#ffffff",
  textSecondary: "#ffffff",
  textMuted: "#d6d6d6",
  textInverse: "#000000",
  primary: "#66d9ff",
  primaryPressed: "#a8ecff",
  primarySoft: "#003344",
  onPrimary: "#000000",
  focusRing: "#ffff00",
  overlay: "rgba(0, 0, 0, 0.82)",
  disabled: "#bfbfbf",
  status: {
    neutral: "#ffffff",
    info: "#66d9ff",
    success: "#5cff9d",
    warning: "#ffe45c",
    danger: "#ff7676"
  },
  flightStatus: {
    scheduled: "#66d9ff",
    departed: "#ffffff",
    boarding: "#5cff9d",
    delayed: "#ffe45c",
    cancelled: "#ff7676"
  }
});

export const MOBILE_SEMANTIC_THEMES = {
  light: WARM_LIGHT_THEME,
  dark: WARM_DARK_THEME,
  highContrastLight: HIGH_CONTRAST_LIGHT_THEME,
  highContrast: HIGH_CONTRAST_THEME
} as const;

export const semanticThemeTokens = MOBILE_SEMANTIC_THEMES;
export const warmLightTheme = WARM_LIGHT_THEME;
export const warmDarkTheme = WARM_DARK_THEME;
export const highContrastTheme = HIGH_CONTRAST_THEME;
export const highContrastLightTheme = HIGH_CONTRAST_LIGHT_THEME;

export const DEFAULT_THEME_PREFERENCE: MobileThemePreference = "system";
export const DEFAULT_CONTRAST_PREFERENCE: MobileContrastPreference = "standard";
export const MOBILE_THEME_PREFERENCES = ["system", "light", "dark"] as const satisfies readonly MobileThemePreference[];
export const MOBILE_CONTRAST_PREFERENCES = ["standard", "high"] as const satisfies readonly MobileContrastPreference[];

export function resolveMobileThemeMode(
  preference: MobileThemePreference,
  systemMode: MobileThemeMode | null | undefined
): MobileThemeMode {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  return systemMode === "light" ? "light" : "dark";
}

export function getMobileSemanticTheme(
  mode: MobileThemeMode,
  contrast: MobileContrastPreference = DEFAULT_CONTRAST_PREFERENCE
): MobileSemanticTheme {
  if (contrast === "high") {
    return mode === "light" ? HIGH_CONTRAST_LIGHT_THEME : HIGH_CONTRAST_THEME;
  }
  return mode === "light" ? WARM_LIGHT_THEME : WARM_DARK_THEME;
}

export const getMobileThemeTokens = getMobileSemanticTheme;

/**
 * Adapter for screens that still consume the flat V1 `MobileAppearance`
 * contract. It lets those screens adopt the V2 palette without a coordinated
 * rewrite and can be removed only after the compatibility exports are retired.
 */
export function mobileAppearanceFromSemanticTheme(
  theme: MobileSemanticTheme,
  skin: MobileSkin = theme.isHighContrast ? "high_contrast" : "standard"
): MobileAppearance {
  const { colors: color } = theme;
  return {
    key: `${theme.mode}:${skin}`,
    themeMode: theme.mode,
    skin,
    brand: BRAND_FONT_FAMILY,
    ui: UI_FONT_FAMILY,
    mono: BOARD_FONT_FAMILY,
    bg: color.background,
    shell: color.surface,
    header: color.surfaceRaised,
    line: color.border,
    lineSoft: color.borderSubtle,
    row: color.surface,
    rowAlt: color.surfaceSubtle,
    text: color.text,
    textMuted: color.textSecondary,
    textDim: color.textMuted,
    blue: color.primary,
    blue2: color.status.info,
    green: color.status.success,
    amber: color.status.warning,
    red: color.status.danger,
    status: color.flightStatus
  };
}

export const DEFAULT_THEME_MODE: MobileThemeMode = "dark";
export const DEFAULT_SKIN: MobileSkin = "standard";
export const DEFAULT_MOBILE_APPEARANCE: MobileAppearance = mobileAppearanceFromSemanticTheme(
  WARM_DARK_THEME,
  DEFAULT_SKIN
);

export function getMobileAppearance(
  themeMode: MobileThemeMode,
  skin: MobileSkin
): MobileAppearance {
  return mobileAppearanceFromSemanticTheme(
    getMobileSemanticTheme(themeMode, skin === "high_contrast" ? "high" : "standard"),
    skin
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
