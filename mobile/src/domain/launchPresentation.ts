export const LAUNCH_MIN_MS = 6_000;
export const LAUNCH_REDUCED_MOTION_MS = 1_200;
export const LAUNCH_AMBIENT_SWEEP_MS = 7_200;
export const LAUNCH_AMBIENT_BREATH_MS = 3_800;
export const LAUNCH_NETWORK_CEILING_MS = 7_000;

export type LaunchDataOutcome = "pending" | "live" | "cached" | "offline" | "setup";
export type LaunchCinematicPhase = "atmosphere" | "radar_wake" | "aircraft_orbit" | "intercept" | "brand_resolve" | "ambient";

export function launchCinematicPhaseAt(elapsedMs: number, reduceMotion = false): LaunchCinematicPhase {
  const elapsed = Math.max(0, elapsedMs);
  if (reduceMotion) return elapsed < LAUNCH_REDUCED_MOTION_MS ? "brand_resolve" : "ambient";
  if (elapsed < 800) return "atmosphere";
  if (elapsed < 1_600) return "radar_wake";
  if (elapsed < 3_400) return "aircraft_orbit";
  if (elapsed < 4_600) return "intercept";
  if (elapsed < LAUNCH_MIN_MS) return "brand_resolve";
  return "ambient";
}

export function launchCanEnter(input: {
  hydrated: boolean;
  sequenceComplete: boolean;
  dataOutcome: LaunchDataOutcome;
  networkCeilingReached: boolean;
}): boolean {
  return input.hydrated &&
    input.sequenceComplete &&
    (input.dataOutcome !== "pending" || input.networkCeilingReached);
}

export function launchStatusPresentation(input: {
  hydrated: boolean;
  ready: boolean;
  dataOutcome: LaunchDataOutcome;
  networkCeilingReached: boolean;
}): { status: string; qualifier: string | null } {
  let status = "Restoring this device";
  if (input.hydrated) status = "Checking shared information";

  let qualifier: string | null = null;
  if (input.ready && input.dataOutcome === "cached") qualifier = "Cached information ready";
  else if (input.ready && (input.dataOutcome === "offline" || input.networkCeilingReached)) {
    qualifier = "Offline · cached information may be shown";
  }
  return { status, qualifier };
}
