import { useEffect, useState } from "react";
import { AccessibilityInfo, type Insets, type PressableProps } from "react-native";

import { MIN_TOUCH_TARGET } from "../theme/tokens";

export const minTouchTarget = MIN_TOUCH_TARGET;
export const tapTargetHitSlop: Insets = { top: 8, right: 8, bottom: 8, left: 8 };
export const compactTapTargetHitSlop: Insets = { top: 10, right: 10, bottom: 10, left: 10 };

type AccessiblePressableOptions = {
  label: string;
  hint?: string;
  selected?: boolean;
  disabled?: boolean;
  expanded?: boolean;
  busy?: boolean;
};

export function accessibleButton({
  label,
  hint,
  selected,
  disabled,
  expanded,
  busy
}: AccessiblePressableOptions): Pick<PressableProps, "accessibilityRole" | "accessibilityLabel" | "accessibilityHint" | "accessibilityState"> {
  return {
    accessibilityRole: "button",
    accessibilityLabel: label,
    accessibilityHint: hint,
    accessibilityState: {
      selected,
      disabled,
      expanded,
      busy
    }
  };
}

export function hideFromAccessibility(): Pick<PressableProps, "accessible" | "accessibilityElementsHidden" | "importantForAccessibility"> {
  return {
    accessible: false,
    accessibilityElementsHidden: true,
    importantForAccessibility: "no-hide-descendants"
  };
}

export function useReducedMotionPreference(): boolean {
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled()
      .then((enabled) => {
        if (mounted) setReduceMotion(Boolean(enabled));
      })
      .catch(() => {
        // Keep motion enabled if the platform cannot report the preference.
      });

    const subscription = AccessibilityInfo.addEventListener("reduceMotionChanged", (enabled) => {
      setReduceMotion(Boolean(enabled));
    });

    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  return reduceMotion;
}
