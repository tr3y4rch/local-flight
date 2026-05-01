import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { loadAppearancePrefs, saveAppearancePrefs } from "../storage/settings";
import {
  DEFAULT_MOBILE_APPEARANCE,
  DEFAULT_SKIN,
  DEFAULT_THEME_MODE,
  getMobileAppearance,
  type MobileAppearance,
  type MobileSkin,
  type MobileThemeMode
} from "./tokens";

type MobileThemeContextValue = {
  appearance: MobileAppearance;
  themeMode: MobileThemeMode;
  skin: MobileSkin;
  setThemeMode: (value: MobileThemeMode) => void;
  setSkin: (value: MobileSkin) => void;
};

const MobileThemeContext = createContext<MobileThemeContextValue | null>(null);

export function MobileThemeProvider({ children }: { children: ReactNode }) {
  const [themeMode, setThemeModeState] = useState<MobileThemeMode>(DEFAULT_THEME_MODE);
  const [skin, setSkinState] = useState<MobileSkin>(DEFAULT_SKIN);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    let alive = true;
    void loadAppearancePrefs()
      .then((prefs) => {
        if (!alive) return;
        setThemeModeState(prefs.themeMode);
        setSkinState(prefs.skin);
      })
      .finally(() => {
        if (alive) {
          setHydrated(true);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    void saveAppearancePrefs({ themeMode, skin });
  }, [hydrated, skin, themeMode]);

  const value = useMemo<MobileThemeContextValue>(
    () => ({
      appearance: getMobileAppearance(themeMode, skin),
      themeMode,
      skin,
      setThemeMode: setThemeModeState,
      setSkin: setSkinState
    }),
    [skin, themeMode]
  );

  return (
    <MobileThemeContext.Provider value={value}>
      {children}
    </MobileThemeContext.Provider>
  );
}

export function useMobileTheme(): MobileThemeContextValue {
  return useContext(MobileThemeContext) || {
    appearance: DEFAULT_MOBILE_APPEARANCE,
    themeMode: DEFAULT_THEME_MODE,
    skin: DEFAULT_SKIN,
    setThemeMode: () => {},
    setSkin: () => {}
  };
}
