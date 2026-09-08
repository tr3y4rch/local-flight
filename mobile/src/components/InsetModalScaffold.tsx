import type { ReactNode } from "react";
import { Platform, StyleSheet, View } from "react-native";
import { useSafeAreaInsets, type EdgeInsets } from "react-native-safe-area-context";

export const insetModalPresentationProps = Platform.OS === "android"
  ? { statusBarTranslucent: true, navigationBarTranslucent: true }
  : {};

export function InsetModalScaffold({
  backgroundColor,
  children
}: {
  backgroundColor: string;
  children: (insets: EdgeInsets) => ReactNode;
}) {
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.frame,
        {
          backgroundColor,
          paddingTop: insets.top,
          paddingLeft: insets.left,
          paddingRight: insets.right
        }
      ]}
    >
      {children(insets)}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { flex: 1 }
});
