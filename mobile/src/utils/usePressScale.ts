import { useRef } from "react";
import { Animated } from "react-native";

import { useReducedMotionPreference } from "../accessibility/mobileA11y";

export function usePressScale(toValue = 0.94, stiffness = 300, damping = 18) {
  const scale = useRef(new Animated.Value(1)).current;
  const reduceMotion = useReducedMotionPreference();
  const onPressIn  = () => {
    if (reduceMotion) return;
    Animated.spring(scale, { toValue, stiffness, damping, useNativeDriver: true }).start();
  };
  const onPressOut = () => {
    if (reduceMotion) return;
    Animated.spring(scale, { toValue: 1, stiffness, damping, useNativeDriver: true }).start();
  };
  return { scale, onPressIn, onPressOut };
}
