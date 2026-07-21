import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode
} from "react";
import { AccessibilityInfo, Appearance, Platform, useColorScheme } from "react-native";
import * as NavigationBar from "expo-navigation-bar";

import {
  loadMobileThemePreferences,
  saveMobileThemePreferences
} from "../storage/settings";
import {
  DEFAULT_CONTRAST_PREFERENCE,
  DEFAULT_THEME_MODE,
  DEFAULT_THEME_PREFERENCE,
  getMobileSemanticTheme,
  mobileAppearanceFromSemanticTheme,
  resolveMobileThemeMode,
  type MobileAppearance,
  type MobileContrastPreference,
  type MobileSemanticTheme,
  type MobileSkin,
  type MobileThemeMode,
  type MobileThemePreference
} from "./tokens";

export type MobileThemeContextValue = {
  /** V2 semantic theme used by new screens and style factories. */
  theme: MobileSemanticTheme;
  /** Alias for `theme`, useful when destructuring beside component styles. */
  tokens: MobileSemanticTheme;
  preference: MobileThemePreference;
  themePreference: MobileThemePreference;
  resolvedThemeMode: MobileThemeMode;
  contrast: MobileContrastPreference;
  isHighContrast: boolean;
  hydrated: boolean;
  setPreference: (value: MobileThemePreference) => void;
  setThemePreference: (value: MobileThemePreference) => void;
  setHighContrast: (enabled: boolean) => void;

  /** V1 compatibility fields. */
  appearance: MobileAppearance;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  setThemeMode: (value: MobileThemeMode) => void;
  setSkin: (value: MobileSkin) => void;
};

const MobileThemeContext = createContext<MobileThemeContextValue | null>(null);

function resolvedSystemThemeMode(value: ReturnType<typeof useColorScheme>): MobileThemeMode {
  return value === "light" ? "light" : "dark";
}

function useSystemHighContrast(): boolean {
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let alive = true;
    void AccessibilityInfo.isHighTextContrastEnabled()
      .then((value) => {
        if (alive) setEnabled(value);
      })
      .catch(() => {
        // High-text-contrast detection is not available on every platform.
      });
    const subscription = AccessibilityInfo.addEventListener(
      "highTextContrastChanged",
      setEnabled
    );
    return () => {
      alive = false;
      subscription.remove();
    };
  }, []);

  return enabled;
}

export function MobileThemeProvider({ children }: { children: ReactNode }) {
  const systemThemeMode = resolvedSystemThemeMode(useColorScheme());
  const systemHighContrast = useSystemHighContrast();
  const [preference, setPreference] = useState<MobileThemePreference>(DEFAULT_THEME_PREFERENCE);
  const [contrast, setContrast] = useState<MobileContrastPreference>(DEFAULT_CONTRAST_PREFERENCE);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let alive = true;
    void loadMobileThemePreferences(systemThemeMode)
      .then((prefs) => {
        if (!alive) return;
        setPreference(prefs.preference);
        setContrast(prefs.contrast);
      })
      .catch(() => {
        // The in-memory system preference remains a safe fallback.
      })
      .finally(() => {
        if (alive) setHydrated(true);
      });
    return () => {
      alive = false;
    };
    // Preference hydration is intentionally a one-time storage operation.
    // System appearance changes are resolved below without re-reading storage.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resolvedThemeMode = resolveMobileThemeMode(preference, systemThemeMode);
  const isHighContrast = contrast === "high" || systemHighContrast;
  const theme = useMemo(
    () => getMobileSemanticTheme(resolvedThemeMode, isHighContrast ? "high" : "standard"),
    [isHighContrast, resolvedThemeMode]
  );
  const skin: MobileSkin = isHighContrast ? "high_contrast" : "standard";
  const appearance = useMemo(
    () => mobileAppearanceFromSemanticTheme(theme, skin),
    [skin, theme]
  );

  useEffect(() => {
    if (!hydrated) return;
    // Keep UIKit's trait collection in lockstep with the hydrated preference.
    // Native tab/navigation material remains UIKit-owned and therefore adapts
    // its Liquid Glass contrast instead of being painted by React Native.
    Appearance.setColorScheme(preference === "system" ? "unspecified" : resolvedThemeMode);
    if (Platform.OS === "android") {
      // Android remains edge-to-edge. The React Navigation tab underlay covers
      // the gesture/three-button region while the system icons retain contrast
      // with the resolved V2 appearance.
      void NavigationBar.setButtonStyleAsync(resolvedThemeMode === "dark" ? "light" : "dark")
        .catch(() => {
          // Some vendor builds do not expose navigation-bar styling. The safe
          // area underlay still prevents content and controls from overlapping.
        });
    }
    void saveMobileThemePreferences({
      preference,
      contrast,
      resolvedThemeMode
    }).catch(() => {
      // A storage failure must not make the active appearance unusable.
    });
  }, [contrast, hydrated, preference, resolvedThemeMode]);

  const value = useMemo<MobileThemeContextValue>(
    () => ({
      theme,
      tokens: theme,
      preference,
      themePreference: preference,
      resolvedThemeMode,
      contrast,
      isHighContrast,
      hydrated,
      setPreference,
      setThemePreference: setPreference,
      setHighContrast: (enabled) => setContrast(enabled ? "high" : "standard"),
      appearance,
      themeMode: theme.mode,
      skin,
      setThemeMode: setPreference,
      setSkin: (value) => setContrast(value === "high_contrast" ? "high" : "standard")
    }),
    [appearance, contrast, hydrated, isHighContrast, preference, resolvedThemeMode, skin, theme]
  );

  return (
    <MobileThemeContext.Provider value={value}>
      {children}
    </MobileThemeContext.Provider>
  );
}

const fallbackTheme = getMobileSemanticTheme(DEFAULT_THEME_MODE);
const fallbackAppearance = mobileAppearanceFromSemanticTheme(fallbackTheme);
const noop = () => {};

export function useMobileTheme(): MobileThemeContextValue {
  return useContext(MobileThemeContext) || {
    theme: fallbackTheme,
    tokens: fallbackTheme,
    preference: DEFAULT_THEME_PREFERENCE,
    themePreference: DEFAULT_THEME_PREFERENCE,
    resolvedThemeMode: DEFAULT_THEME_MODE,
    contrast: DEFAULT_CONTRAST_PREFERENCE,
    isHighContrast: false,
    hydrated: false,
    setPreference: noop,
    setThemePreference: noop,
    setHighContrast: noop,
    appearance: fallbackAppearance,
    themeMode: DEFAULT_THEME_MODE,
    skin: "standard",
    setThemeMode: noop,
    setSkin: noop
  };
}
