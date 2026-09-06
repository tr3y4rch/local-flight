import { useCallback, useEffect, useRef, useState } from "react";
import { Animated, AppState, Easing, Linking, type AppStateStatus } from "react-native";
import * as SplashScreen from "expo-splash-screen";

import { useReducedMotionPreference } from "../accessibility/mobileA11y";
import { appVersion, getCompanionIdentity, mobileOsLabel, type CompanionIdentity } from "../device/identity";
import type { AirportResolved, AppConfig } from "../api/types";
import {
  LAUNCH_AMBIENT_BREATH_MS,
  LAUNCH_AMBIENT_SWEEP_MS,
  LAUNCH_MIN_MS,
  LAUNCH_NETWORK_CEILING_MS,
  LAUNCH_REDUCED_MOTION_MS,
  launchCanEnter,
  launchStatusPresentation,
  type LaunchDataOutcome
} from "../domain/launchPresentation";
import {
  incompleteMobileSetupState,
  type ConfigProfile,
  loadCachedLanAirport,
  loadCachedLanConfig,
  loadMobileDiagnosticsMode,
  loadMobileRelayAccessSummary,
  loadPendingRelayActivation,
  loadRelayDeviceCredential,
  loadPinnedFlightReference,
  loadProfiles,
  loadServerUrl,
  resolveMobileSetupState,
  type MobileDiagnosticsMode,
  type MobileSetupState,
  type StagedRelayActivation
} from "../storage/settings";
import type { PinnedFlightReference } from "../domain/pinnedFlight";
import type { MobileRelayAccessSummary } from "../access/paidAppAccess";

export type LaunchHydration = {
  savedUrl: string | null;
  savedPin: PinnedFlightReference | null;
  initialUrl: string | null;
  savedProfiles: ConfigProfile[];
  savedConfig: AppConfig | null;
  savedAirport: AirportResolved | null;
  identity: CompanionIdentity;
  mobileDiagnosticsMode: MobileDiagnosticsMode;
  setupState: MobileSetupState;
  relayDeviceCredential: string;
  relayAccessSummary: MobileRelayAccessSummary | null;
  pendingRelayActivation: StagedRelayActivation | null;
};

export type { LaunchDataOutcome } from "../domain/launchPresentation";

async function settledValue<T>(promise: Promise<T>, fallback: T): Promise<T> {
  try {
    return await promise;
  } catch {
    return fallback;
  }
}

export function useLaunchOverlay(
  onHydrated: (value: LaunchHydration) => void,
  dataOutcome: LaunchDataOutcome,
  appearanceReady: boolean
) {
  const [visible, setVisible] = useState(true);
  const [hydrated, setHydrated] = useState(false);
  const [sequenceComplete, setSequenceComplete] = useState(false);
  const [ready, setReady] = useState(false);
  const [networkCeilingReached, setNetworkCeilingReached] = useState(false);
  const reduceMotion = useReducedMotionPreference();
  const opacity = useRef(new Animated.Value(1)).current;
  const scale = useRef(new Animated.Value(1)).current;
  const shift = useRef(new Animated.Value(0)).current;
  const sequence = useRef(new Animated.Value(0)).current;
  const ambientSweep = useRef(new Animated.Value(0)).current;
  const logoBreath = useRef(new Animated.Value(0)).current;
  const firstFrameRef = useRef(false);
  const hydrationCompleteRef = useRef(false);
  const nativeSplashHiddenRef = useRef(false);
  const cinematicStartedRef = useRef(false);
  const sequenceCompleteRef = useRef(false);
  const enteredRef = useRef(false);
  const visibleRef = useRef(true);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);
  const sequenceAnimationRef = useRef<Animated.CompositeAnimation | null>(null);
  const ambientSweepLoopRef = useRef<Animated.CompositeAnimation | null>(null);
  const logoBreathLoopRef = useRef<Animated.CompositeAnimation | null>(null);
  const ceilingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const startFrameRef = useRef<number | null>(null);
  const bypassCinematicRef = useRef(false);

  const isDirectContentLaunch = useCallback((url: string | null) => (
    Boolean(url && /^localflight:\/\/(?:board|flight|widgets)(?:[/?#]|$)/i.test(url))
  ), []);

  const stopAmbient = useCallback(() => {
    ambientSweepLoopRef.current?.stop();
    logoBreathLoopRef.current?.stop();
    ambientSweepLoopRef.current = null;
    logoBreathLoopRef.current = null;
  }, []);

  const startAmbient = useCallback(() => {
    stopAmbient();
    if (
      reduceMotion ||
      enteredRef.current ||
      !visibleRef.current ||
      !sequenceCompleteRef.current ||
      appStateRef.current !== "active"
    ) return;

    ambientSweep.setValue(0);
    logoBreath.setValue(0);
    ambientSweepLoopRef.current = Animated.loop(
      Animated.timing(ambientSweep, {
        toValue: 1,
        duration: LAUNCH_AMBIENT_SWEEP_MS,
        easing: Easing.linear,
        useNativeDriver: true
      })
    );
    logoBreathLoopRef.current = Animated.loop(
      Animated.sequence([
        Animated.timing(logoBreath, {
          toValue: 1,
          duration: LAUNCH_AMBIENT_BREATH_MS / 2,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true
        }),
        Animated.timing(logoBreath, {
          toValue: 0,
          duration: LAUNCH_AMBIENT_BREATH_MS / 2,
          easing: Easing.inOut(Easing.sin),
          useNativeDriver: true
        })
      ])
    );
    ambientSweepLoopRef.current.start();
    logoBreathLoopRef.current.start();
  }, [ambientSweep, logoBreath, reduceMotion, stopAmbient]);

  const finishSequence = useCallback(() => {
    if (sequenceCompleteRef.current) return;
    sequenceCompleteRef.current = true;
    sequence.setValue(1);
    setSequenceComplete(true);
    startAmbient();
  }, [sequence, startAmbient]);

  const startCinematic = useCallback(() => {
    if (cinematicStartedRef.current || enteredRef.current) return;
    cinematicStartedRef.current = true;
    setNetworkCeilingReached(false);
    sequence.setValue(0);
    const duration = reduceMotion ? LAUNCH_REDUCED_MOTION_MS : LAUNCH_MIN_MS;
    sequenceAnimationRef.current = Animated.timing(sequence, {
      toValue: 1,
      duration,
      // Stage boundaries in LaunchOverlay are authored against real elapsed
      // time, so the master clock stays linear and each scene layer supplies
      // its own easing through interpolation.
      easing: reduceMotion ? Easing.out(Easing.quad) : Easing.linear,
      useNativeDriver: true
    });
    sequenceAnimationRef.current.start(({ finished }) => {
      sequenceAnimationRef.current = null;
      if (finished && !enteredRef.current) finishSequence();
    });
    ceilingTimerRef.current = setTimeout(() => {
      setNetworkCeilingReached(true);
    }, LAUNCH_NETWORK_CEILING_MS);
  }, [finishSequence, reduceMotion, sequence]);

  const hideNativeSplashWhenReady = useCallback(() => {
    if (
      nativeSplashHiddenRef.current ||
      !appearanceReady ||
      !firstFrameRef.current ||
      !hydrationCompleteRef.current
    ) return;
    nativeSplashHiddenRef.current = true;
    if (bypassCinematicRef.current) {
      enteredRef.current = true;
      visibleRef.current = false;
      sequenceCompleteRef.current = true;
      sequence.setValue(1);
      setSequenceComplete(true);
      setReady(true);
      setVisible(false);
      void SplashScreen.hideAsync().catch(() => undefined);
      return;
    }
    void SplashScreen.hideAsync()
      .catch(() => {
        // Simulator fast refresh can race an already-hidden native splash.
      })
      .finally(() => {
        startFrameRef.current = requestAnimationFrame(startCinematic);
      });
  }, [appearanceReady, sequence, startCinematic]);

  const markFirstFrameReady = useCallback(() => {
    if (firstFrameRef.current) return;
    firstFrameRef.current = true;
    hideNativeSplashWhenReady();
  }, [hideNativeSplashWhenReady]);

  const enter = useCallback(() => {
    if (enteredRef.current || !ready || !sequenceCompleteRef.current) return;
    enteredRef.current = true;
    stopAmbient();
    sequenceAnimationRef.current?.stop();
    if (ceilingTimerRef.current) {
      clearTimeout(ceilingTimerRef.current);
      ceilingTimerRef.current = null;
    }
    Animated.parallel([
      Animated.timing(opacity, {
        toValue: 0,
        duration: reduceMotion ? 120 : 260,
        useNativeDriver: true
      }),
      Animated.timing(shift, {
        toValue: reduceMotion ? 0 : -16,
        duration: reduceMotion ? 120 : 260,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true
      }),
      Animated.timing(scale, {
        toValue: reduceMotion ? 1 : 0.965,
        duration: reduceMotion ? 120 : 260,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true
      })
    ]).start(() => {
      visibleRef.current = false;
      setVisible(false);
    });
  }, [opacity, ready, reduceMotion, scale, shift, stopAmbient]);

  useEffect(() => {
    let alive = true;
    const fallbackIdentity: CompanionIdentity = {
      companionId: "",
      clientName: "Local Flight Mobile",
      appVersion: appVersion(),
      mobileOs: mobileOsLabel(),
      deviceType: "unknown"
    };

    void Promise.all([
      settledValue(loadServerUrl(), null),
      settledValue(loadPinnedFlightReference(), null),
      settledValue(loadProfiles(), []),
      settledValue(loadCachedLanConfig(), null),
      settledValue(loadCachedLanAirport(), null),
      settledValue(getCompanionIdentity(), fallbackIdentity),
      settledValue(loadMobileDiagnosticsMode(), "unset" as MobileDiagnosticsMode),
      settledValue(loadRelayDeviceCredential(), ""),
      settledValue(loadMobileRelayAccessSummary(), null),
      settledValue(loadPendingRelayActivation(), null),
      settledValue(Linking.getInitialURL(), null)
    ]).then(async ([savedUrl, savedPin, savedProfiles, savedConfig, savedAirport, identity, mobileDiagnosticsMode, relayDeviceCredential, relayAccessSummary, pendingRelayActivation, initialUrl]) => {
      const setupState = await settledValue(
        resolveMobileSetupState(savedUrl || "", mobileDiagnosticsMode),
        incompleteMobileSetupState(savedUrl || "", mobileDiagnosticsMode)
      );
      // Resolving setup can migrate an older credential embedded in setup JSON.
      // Re-read after that migration so the first upgraded launch can use it.
      const hydratedRelayDeviceCredential = relayDeviceCredential
        || await settledValue(loadRelayDeviceCredential(), "");
      if (!alive) return;
      bypassCinematicRef.current = isDirectContentLaunch(initialUrl);
      onHydrated({
        savedUrl,
        savedPin,
        savedProfiles,
        savedConfig,
        savedAirport,
        identity,
        mobileDiagnosticsMode,
        setupState,
        relayDeviceCredential: hydratedRelayDeviceCredential,
        relayAccessSummary,
        pendingRelayActivation,
        initialUrl
      });
      hydrationCompleteRef.current = true;
      setHydrated(true);
    });

    return () => {
      alive = false;
    };
  }, [isDirectContentLaunch, onHydrated]);

  useEffect(() => {
    hideNativeSplashWhenReady();
  }, [appearanceReady, hideNativeSplashWhenReady, hydrated]);

  useEffect(() => {
    if (launchCanEnter({ hydrated, sequenceComplete, dataOutcome, networkCeilingReached })) {
      setReady(true);
    }
  }, [dataOutcome, hydrated, networkCeilingReached, sequenceComplete]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (nextState) => {
      appStateRef.current = nextState;
      if (nextState !== "active") {
        stopAmbient();
        if (cinematicStartedRef.current && !sequenceCompleteRef.current) {
          sequenceAnimationRef.current?.stop();
          sequenceAnimationRef.current = null;
          finishSequence();
        }
        return;
      }
      if (sequenceCompleteRef.current) startAmbient();
    });
    return () => subscription.remove();
  }, [finishSequence, startAmbient, stopAmbient]);

  useEffect(() => () => {
    visibleRef.current = false;
    sequenceAnimationRef.current?.stop();
    stopAmbient();
    if (ceilingTimerRef.current) clearTimeout(ceilingTimerRef.current);
    if (startFrameRef.current != null) cancelAnimationFrame(startFrameRef.current);
  }, [stopAmbient]);

  const { status, qualifier } = launchStatusPresentation({
    hydrated,
    ready,
    dataOutcome,
    networkCeilingReached
  });

  return {
    visible,
    opacity,
    shift,
    scale,
    sequence,
    ambientSweep,
    logoBreath,
    sequenceComplete,
    reduceMotion,
    ready,
    enter,
    markFirstFrameReady,
    status,
    qualifier
  };
}
