import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppShell } from "./src/app/AppShell";
import { CrashBoundary } from "./src/crash/CrashBoundary";
import { MobileThemeProvider } from "./src/theme/runtime";

export default function App() {
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
