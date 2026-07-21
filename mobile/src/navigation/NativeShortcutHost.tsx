import { requireNativeViewManager, requireOptionalNativeModule } from "expo-modules-core";
import { useCallback, type ComponentType, type ReactNode } from "react";
import {
  Platform,
  StyleSheet,
  View,
  type NativeSyntheticEvent,
  type ViewProps
} from "react-native";

const MODULE_NAME = "LocalFlightWidgetBridge";
const VIEW_NAME = "LocalFlightShortcutView";

export type NativeShortcutKey = "1" | "2" | "3" | "4" | "r" | "f" | "escape";

export type NativeShortcutHostProps = ViewProps & {
  children?: ReactNode;
  onShortcut: (key: NativeShortcutKey) => void;
};

type ShortcutEvent = NativeSyntheticEvent<{ key?: unknown }>;
type NativeShortcutViewProps = ViewProps & {
  children?: ReactNode;
  onShortcut?: (event: ShortcutEvent) => void;
};

type ExpoRuntime = {
  getViewConfig?: (moduleName: string, viewName?: string) => unknown;
};

function loadNativeShortcutView(): ComponentType<NativeShortcutViewProps> | null {
  if (Platform.OS !== "ios" && Platform.OS !== "android") return null;
  try {
    if (!requireOptionalNativeModule(MODULE_NAME)) return null;
    const expoRuntime = (globalThis as typeof globalThis & { expo?: ExpoRuntime }).expo;
    if (!expoRuntime?.getViewConfig?.(MODULE_NAME, VIEW_NAME)) return null;
    return requireNativeViewManager<NativeShortcutViewProps>(MODULE_NAME, VIEW_NAME);
  } catch {
    // An older development build can contain the bridge module without this
    // newer view. Keep the app usable until its native binary is rebuilt.
    return null;
  }
}

const NativeShortcutView = loadNativeShortcutView();
const shortcutKeys = new Set<NativeShortcutKey>(["1", "2", "3", "4", "r", "f", "escape"]);

function isNativeShortcutKey(value: unknown): value is NativeShortcutKey {
  return typeof value === "string" && shortcutKeys.has(value as NativeShortcutKey);
}

export function NativeShortcutHost({
  children,
  onShortcut,
  style,
  ...viewProps
}: NativeShortcutHostProps) {
  const handleShortcut = useCallback((event: ShortcutEvent) => {
    const key = event.nativeEvent.key;
    if (isNativeShortcutKey(key)) onShortcut(key);
  }, [onShortcut]);

  const hostStyle = [styles.host, style];
  if (!NativeShortcutView) {
    return <View {...viewProps} style={hostStyle}>{children}</View>;
  }
  return (
    <NativeShortcutView {...viewProps} style={hostStyle} onShortcut={handleShortcut}>
      {children}
    </NativeShortcutView>
  );
}

export default NativeShortcutHost;

const styles = StyleSheet.create({
  host: {
    flex: 1
  }
});
