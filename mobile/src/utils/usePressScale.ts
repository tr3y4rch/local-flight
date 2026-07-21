import { useRef } from "react";
import { Animated } from "react-native";

import { useReducedMotionPreference } from "../accessibility/mobileA11y";

export function usePressScale(toValue = 0.94, stiffness = 300, damping = 18, liftTo = 0) {
  const scale = useRef(new Animated.Value(1)).current;
  const lift = useRef(new Animated.Value(0)).current;
  const opacity = useRef(new Animated.Value(1)).current;
  const reduceMotion = useReducedMotionPreference();
  const onPressIn  = () => {
    if (reduceMotion) return;
    Animated.parallel([
      Animated.spring(scale, { toValue, stiffness, damping, useNativeDriver: true }),
      Animated.spring(lift, { toValue: liftTo, stiffness, damping, useNativeDriver: true }),
      Animated.timing(opacity, { toValue: 0.96, duration: 90, useNativeDriver: true })
    ]).start();
  };
  const onPressOut = () => {
    if (reduceMotion) return;
    Animated.parallel([
      Animated.spring(scale, { toValue: 1, stiffness, damping, useNativeDriver: true }),
      Animated.spring(lift, { toValue: 0, stiffness, damping, useNativeDriver: true }),
      Animated.timing(opacity, { toValue: 1, duration: 180, useNativeDriver: true })
    ]).start();
  };
  return { scale, lift, opacity, onPressIn, onPressOut };
}
