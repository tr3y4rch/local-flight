import { useEffect } from "react";
import { useFonts } from "expo-font";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppShell } from "./src/app/AppShell";
import { CrashBoundary } from "./src/crash/CrashBoundary";
import { MobileThemeProvider } from "./src/theme/runtime";
import {
  BOARD_BOLD_FONT_FAMILY,
  BOARD_FONT_FAMILY,
  BRAND_FONT_FAMILY,
  UI_FONT_FAMILY
} from "./src/theme/tokens";

export default function App() {
  const [fontsLoaded, fontError] = useFonts({
    [UI_FONT_FAMILY]: require("./assets/fonts/DMSans.ttf"),
    [BRAND_FONT_FAMILY]: require("./assets/fonts/Audiowide-Regular.ttf"),
    [BOARD_FONT_FAMILY]: require("./assets/fonts/SpaceMono-Regular.ttf"),
    [BOARD_BOLD_FONT_FAMILY]: require("./assets/fonts/SpaceMono-Bold.ttf")
  });

  useEffect(() => {
    if (fontError) {
      // Keep diagnostics deliberately sanitized: the exception can contain a
      // local bundle path that does not belong in ordinary support context.
      console.warn("Local Flight bundled fonts could not register; using the system fallback.");
    }
  }, [fontError]);

  if (!fontsLoaded && !fontError) return null;

  return (
    <SafeAreaProvider>
      <MobileThemeProvider>
        <CrashBoundary>
          <AppShell />
        </CrashBoundary>
      </MobileThemeProvider>
    </SafeAreaProvider>
  );
}
