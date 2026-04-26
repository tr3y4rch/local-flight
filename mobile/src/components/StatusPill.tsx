import { useEffect, useRef } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme/tokens";

type Props = {
  ok: boolean;
  label?: string;
};

export function StatusPill({ ok, label }: Props) {
  const opacity = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    if (!ok) {
      opacity.setValue(1);
      return;
    }
    const anim = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, { toValue: 0.2, duration: 900, useNativeDriver: true }),
        Animated.timing(opacity, { toValue: 1, duration: 900, useNativeDriver: true }),
      ])
    );
    anim.start();
    return () => anim.stop();
  }, [ok, opacity]);

  return (
    <View style={[styles.pill, { borderColor: ok ? colors.green : colors.red }]}>
      <Animated.View
        style={[styles.dot, { backgroundColor: ok ? colors.green : colors.red, opacity }]}
      />
      <Text style={[styles.text, { color: ok ? colors.green : colors.red }]}>
        {label || (ok ? "Online" : "Offline")}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    alignSelf: "flex-start",
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    backgroundColor: "rgba(255,255,255,0.035)"
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 999
  },
  text: {
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.7,
    textTransform: "uppercase"
  }
});
