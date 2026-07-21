import { useState, type ReactNode } from "react";
import {
  Animated,
  Platform,
  Pressable as RNPressable,
  StyleSheet,
  type PressableProps as RNPressableProps,
  type StyleProp,
  type ViewStyle
} from "react-native";

import { useMobileTheme } from "../theme/runtime";
import { usePressScale } from "../utils/usePressScale";

export const V2_MOTION = {
  pressInMs: 90,
  releaseMs: 180,
  pageRevealMs: 180,
  panelMs: 220,
  reducedFadeMs: 100
} as const;

type MotionPressableProps = Omit<RNPressableProps, "children" | "style" | "onPressIn" | "onPressOut"> & {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  wrapperStyle?: StyleProp<ViewStyle>;
  interactiveStyle?: StyleProp<ViewStyle>;
  scaleTo?: number;
  liftTo?: number;
};

/**
 * Shared V2 interaction feedback. It deliberately animates only a surface the
 * user is touching or focusing; list mounts and data refreshes remain static.
 */
export function MotionPressable({
  children,
  style,
  wrapperStyle,
  interactiveStyle,
  scaleTo = 0.985,
  liftTo = -2,
  onHoverIn,
  onHoverOut,
  onFocus,
  onBlur,
  ...props
}: MotionPressableProps) {
  const { appearance } = useMobileTheme();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const { scale, lift, opacity, onPressIn, onPressOut } = usePressScale(scaleTo, 360, 24, liftTo);
  const highlighted = hovered || focused;

  return (
    <Animated.View
      style={[
        localStyles.wrapper,
        wrapperStyle,
        { opacity, transform: [{ translateY: lift }, { scale }] }
      ]}
    >
      <RNPressable
        {...props}
        style={[style, highlighted && interactiveStyle]}
        onPressIn={onPressIn}
        onPressOut={onPressOut}
        onHoverIn={(event) => {
          setHovered(true);
          onHoverIn?.(event);
        }}
        onHoverOut={(event) => {
          setHovered(false);
          onHoverOut?.(event);
        }}
        onFocus={(event) => {
          setFocused(true);
          onFocus?.(event);
        }}
        onBlur={(event) => {
          setFocused(false);
          onBlur?.(event);
        }}
        android_ripple={props.android_ripple ?? (Platform.OS === "android" ? { color: `${appearance.blue}18` } : undefined)}
      >
        {children}
      </RNPressable>
    </Animated.View>
  );
}

const localStyles = StyleSheet.create({
  wrapper: { alignSelf: "stretch" }
});
