import { useEffect } from "react";
import { Text } from "react-native";
import { useFonts } from "expo-font";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppShell } from "./src/app/AppShell";
import { CrashBoundary } from "./src/crash/CrashBoundary";
import { MobileThemeProvider } from "./src/theme/runtime";
import { BOARD_FONT_FAMILY, BRAND_FONT_FAMILY, UI_FONT_FAMILY } from "./src/theme/tokens";

let globalTextFontInstalled = false;

function installGlobalTextFont() {
  if (globalTextFontInstalled) return;
  const text = Text as unknown as { defaultProps?: { style?: unknown } };
  text.defaultProps = text.defaultProps || {};
  text.defaultProps.style = [{ fontFamily: UI_FONT_FAMILY }, text.defaultProps.style].filter(Boolean);
  globalTextFontInstalled = true;
}

export default function App() {
  const [fontsLoaded, fontError] = useFonts({
    [BRAND_FONT_FAMILY]: require("./assets/fonts/Audiowide-Regular.ttf"),
    [UI_FONT_FAMILY]: require("./assets/fonts/DMSans.ttf"),
    [BOARD_FONT_FAMILY]: require("./assets/fonts/SpaceMono-Regular.ttf"),
    "Space Mono Bold": require("./assets/fonts/SpaceMono-Bold.ttf")
  });

  useEffect(() => {
    if (fontsLoaded) installGlobalTextFont();
  }, [fontsLoaded]);

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
