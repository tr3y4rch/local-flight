import { useEffect, useRef } from "react";
import { Animated, Pressable, Text, View } from "react-native";

import type { Screen } from "../domain/types";
import { LocalFlightIcon, NAV_ICONS, type LocalFlightIconName } from "../theme/icons";
import type { MobileAppearance } from "../theme/tokens";
import { hapticSelection } from "../utils/haptics";
import { usePressScale } from "../utils/usePressScale";

type BottomNavProps = {
  active: Screen;
  onChange: (screen: Screen) => void;
  insetBottom: number;
  palette: MobileAppearance;
  styles: Record<string, any>;
  standalone?: boolean;
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
  icon: LocalFlightIconName;
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
          <LocalFlightIcon
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

export function BottomNav({ active, onChange, insetBottom, palette, styles, standalone = false }: BottomNavProps) {
  const items: Array<{ id: Extract<Screen, "fids" | "radar" | "history" | "control" | "settings">; icon: LocalFlightIconName; label: string }> = standalone
    ? [
        { id: "fids",     icon: NAV_ICONS.fids,     label: "BOARD" },
        { id: "radar",    icon: NAV_ICONS.radar,    label: "RADAR" },
        { id: "history",  icon: NAV_ICONS.history,  label: "HISTORY" },
        { id: "settings", icon: NAV_ICONS.settings, label: "SETTINGS" }
      ]
    : [
        { id: "fids",    icon: NAV_ICONS.fids,    label: "BOARD" },
        { id: "radar",   icon: NAV_ICONS.radar,   label: "RADAR" },
        { id: "history", icon: NAV_ICONS.history, label: "HISTORY" },
        { id: "control", icon: NAV_ICONS.control, label: "CONTROL" }
      ];

  return (
    <View style={[styles.bottomNav, { paddingBottom: Math.max(insetBottom, 10) }]}>
      {items.map((item) => {
        const selected = active === item.id;
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
