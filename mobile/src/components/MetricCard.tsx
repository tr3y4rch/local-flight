import type { ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import { colors, radius, spacing } from "../theme/tokens";

type Props = {
  label: string;
  value: string;
  tone?: "blue" | "green" | "amber" | "red";
  children?: ReactNode;
};

export function MetricCard({ label, value, tone = "blue", children }: Props) {
  return (
    <View style={styles.card}>
      <Text style={styles.label}>{label}</Text>
      <Text style={[styles.value, { color: colors[tone] }]}>{value}</Text>
      {children ? <View style={styles.extra}>{children}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flex: 1,
    minWidth: 150,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.panel
  },
  label: {
    color: colors.dim,
    fontSize: 12,
    fontWeight: "700",
    letterSpacing: 0.8,
    textTransform: "uppercase"
  },
  value: {
    marginTop: spacing.xs,
    fontSize: 20,
    fontWeight: "900"
  },
  extra: {
    marginTop: spacing.sm
  }
});
