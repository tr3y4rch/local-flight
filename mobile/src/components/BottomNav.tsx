import { useEffect, useRef, type ComponentProps } from "react";
import { Animated, Pressable, Text, View } from "react-native";
import { MaterialCommunityIcons } from "@expo/vector-icons";

import type { Screen } from "../domain/types";
import type { MobileAppearance } from "../theme/tokens";
import { hapticSelection } from "../utils/haptics";
import { usePressScale } from "../utils/usePressScale";

type MaterialIconName = ComponentProps<typeof MaterialCommunityIcons>["name"];

type BottomNavProps = {
  active: Screen;
  onChange: (screen: Screen) => void;
  insetBottom: number;
  palette: MobileAppearance;
  styles: Record<string, any>;
};

function NavItem({
  id,
  icon,
  label,
  selected,
  palette,
  styles,
  onChange
}: {
  id: Screen;
  icon: MaterialIconName;
  label: string;
  selected: boolean;
  palette: MobileAppearance;
  styles: Record<string, any>;
  onChange: (screen: Screen) => void;
}) {
  const { scale, onPressIn, onPressOut } = usePressScale(0.88, 320, 16);
  const dotOpacity = useRef(new Animated.Value(selected ? 1 : 0)).current;

  useEffect(() => {
    Animated.spring(dotOpacity, {
      toValue: selected ? 1 : 0,
      stiffness: 260,
      damping: 18,
      useNativeDriver: true
    }).start();
  }, [selected, dotOpacity]);

  const dotScale = dotOpacity.interpolate({ inputRange: [0, 1], outputRange: [0.4, 1] });

  return (
    <Pressable
      style={styles.navItem}
      onPress={() => {
        hapticSelection();
        onChange(id);
      }}
      onPressIn={onPressIn}
      onPressOut={onPressOut}
    >
      <Animated.View style={{ alignItems: "center", transform: [{ scale }] }}>
        <View style={[styles.navIcon, selected && styles.navIconActive]}>
          <MaterialCommunityIcons
            name={icon}
            size={15}
            color={selected ? palette.blue : palette.textDim}
            style={styles.navIconGlyph}
          />
        </View>
        <Text style={[styles.navLabel, selected && styles.navLabelActive]}>{label}</Text>
        <Animated.View style={[styles.navDot, { opacity: dotOpacity, transform: [{ scale: dotScale }] }]} />
      </Animated.View>
    </Pressable>
  );
}

export function BottomNav({ active, onChange, insetBottom, palette, styles }: BottomNavProps) {
  const items: Array<{ id: Screen; icon: MaterialIconName; label: string }> = [
    { id: "fids",     icon: "airplane-takeoff", label: "FIDS" },
    { id: "radar",    icon: "radar",             label: "RADAR" },
    { id: "settings", icon: "cog-outline",       label: "SETTINGS" }
  ];

  return (
    <View style={[styles.bottomNav, { paddingBottom: Math.max(insetBottom, 10) }]}>
      {items.map((item) => {
        const selected =
          active === item.id ||
          ((active === "matrix" || active === "admin" || active === "history" || active === "docs") &&
            item.id === "settings");
        return (
          <NavItem
            key={item.id}
            id={item.id}
            icon={item.icon}
            label={item.label}
            selected={selected}
            palette={palette}
            styles={styles}
            onChange={onChange}
          />
        );
      })}
    </View>
  );
}
