import type { ComponentProps } from "react";
import { Pressable, Text, View } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";

import type { Screen } from "../domain/types";
import type { MobileAppearance } from "../theme/tokens";

type MaterialIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];

type BottomNavProps = {
  active: Screen;
  onChange: (screen: Screen) => void;
  insetBottom: number;
  palette: MobileAppearance;
  styles: Record<string, any>;
};

export function BottomNav({ active, onChange, insetBottom, palette, styles }: BottomNavProps) {
  const items: Array<{ id: Screen; icon: MaterialIconName; label: string }> = [
    { id: "fids", icon: "airplane-takeoff", label: "FIDS" },
    { id: "radar", icon: "radar", label: "RADAR" },
    { id: "history", icon: "history", label: "HISTORY" },
    { id: "settings", icon: "cog-outline", label: "SETTINGS" }
  ];

  return (
    <View style={[styles.bottomNav, { paddingBottom: Math.max(insetBottom, 10) }]}>
      {items.map((item) => {
        const selected = active === item.id || ((active === "matrix" || active === "admin") && item.id === "settings");
        return (
          <Pressable key={item.id} style={styles.navItem} onPress={() => onChange(item.id)}>
            <View style={[styles.navIcon, selected && styles.navIconActive]}>
              <MaterialCommunityIcons
                name={item.icon}
                size={15}
                color={selected ? palette.blue : palette.textDim}
                style={styles.navIconGlyph}
              />
            </View>
            <Text style={[styles.navLabel, selected && styles.navLabelActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}
