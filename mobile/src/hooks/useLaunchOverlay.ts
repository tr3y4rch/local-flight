import { useEffect, useRef, useState } from "react";
import { Animated, Easing } from "react-native";
import * as SplashScreen from "expo-splash-screen";

import { getCompanionIdentity, type CompanionIdentity } from "../device/identity";
import {
  LAUNCH_ANIMATION_DELAY_MS,
  LAUNCH_MIN_MS,
  LAUNCH_NATIVE_MIN_MS,
  LAUNCH_STATUS_STEPS
} from "../domain/constants";
import {
  type ConfigProfile,
  loadMobileDiagnosticsMode,
  loadPinnedFlight,
  loadProfiles,
  loadServerUrl,
  resolveMobileSetupState,
  type MobileDiagnosticsMode,
  type MobileSetupState
} from "../storage/settings";

export type LaunchHydration = {
  savedUrl: string | null;
  savedPin: string | null;
  savedProfiles: ConfigProfile[];
  identity: CompanionIdentity;
  mobileDiagnosticsMode: MobileDiagnosticsMode;
  setupState: MobileSetupState;
};

export function useLaunchOverlay(onHydrated: (value: LaunchHydration) => void) {
  const [visible, setVisible] = useState(true);
  const [statusIndex, setStatusIndex] = useState(0);
  const opacity = useRef(new Animated.Value(1)).current;
  const scale = useRef(new Animated.Value(1)).current;
  const shift = useRef(new Animated.Value(0)).current;
  const progress = useRef(new Animated.Value(0)).current;
  const pulse = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let alive = true;
    const startedAt = Date.now();
    let nativeHideTimer: ReturnType<typeof setTimeout> | null = null;
    let hideTimer: ReturnType<typeof setTimeout> | null = null;
    let fadeTimer: ReturnType<typeof setTimeout> | null = null;
    const statusTimer = setInterval(() => {
      const elapsed = Date.now() - startedAt;
      const pct = Math.min(1, elapsed / LAUNCH_MIN_MS);
      setStatusIndex(Math.min(LAUNCH_STATUS_STEPS.length - 1, Math.floor(pct * LAUNCH_STATUS_STEPS.length)));
    }, 420);
    const pulseAnim = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, {
          toValue: 1,
          duration: 1600,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true
        }),
        Animated.timing(pulse, {
          toValue: 0,
          duration: 1600,
          easing: Easing.inOut(Easing.quad),
          useNativeDriver: true
        })
      ])
    );

    progress.setValue(0);
    pulse.setValue(0);
    Animated.timing(progress, {
      toValue: 1,
      duration: LAUNCH_MIN_MS,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: false
    }).start();
    pulseAnim.start();

    Promise.all([
      loadServerUrl(),
      loadPinnedFlight(),
      loadProfiles(),
      getCompanionIdentity(),
      loadMobileDiagnosticsMode()
    ])
      .then(async ([savedUrl, savedPin, savedProfiles, identity, mobileDiagnosticsMode]) => {
        const setupState = await resolveMobileSetupState(savedUrl, mobileDiagnosticsMode);
        if (alive) {
          onHydrated({ savedUrl, savedPin, savedProfiles, identity, mobileDiagnosticsMode, setupState });
        }
      })
      .finally(() => {
        if (!alive) return;
        const nativeRemaining = Math.max(0, LAUNCH_NATIVE_MIN_MS - (Date.now() - startedAt));
        nativeHideTimer = setTimeout(() => {
          if (!alive) return;
          void SplashScreen.hideAsync().catch(() => {
            // Ignore splash hide races during simulator reloads.
          });
        }, nativeRemaining);

        const remaining = Math.max(0, LAUNCH_MIN_MS - (Date.now() - startedAt));
        hideTimer = setTimeout(() => {
          if (!alive) return;
          setStatusIndex(LAUNCH_STATUS_STEPS.length - 1);
          fadeTimer = setTimeout(() => {
            if (!alive) return;
            Animated.parallel([
              Animated.timing(opacity, {
                toValue: 0,
                duration: 420,
                useNativeDriver: true
              }),
              Animated.timing(shift, {
                toValue: -12,
                duration: 420,
                useNativeDriver: true
              }),
              Animated.timing(scale, {
                toValue: 0.965,
                duration: 420,
                useNativeDriver: true
              })
            ]).start(({ finished }) => {
              if (finished && alive) {
                setVisible(false);
              }
            });
          }, LAUNCH_ANIMATION_DELAY_MS);
        }, remaining);
      });

    return () => {
      alive = false;
      clearInterval(statusTimer);
      pulseAnim.stop();
      progress.stopAnimation();
      if (nativeHideTimer) clearTimeout(nativeHideTimer);
      if (hideTimer) clearTimeout(hideTimer);
      if (fadeTimer) clearTimeout(fadeTimer);
    };
  }, [onHydrated, opacity, progress, pulse, scale, shift]);

  return {
    visible,
    opacity,
    shift,
    scale,
    progress,
    pulse,
    status: LAUNCH_STATUS_STEPS[statusIndex] ?? "Opening companion"
  };
}
