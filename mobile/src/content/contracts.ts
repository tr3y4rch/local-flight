export type CopyTone = "neutral" | "info" | "success" | "warning" | "danger";

/**
 * Copy for an ordinary user-facing state. Technical details intentionally do
 * not belong here; sanitized diagnostics remain a separate Admin/Report concern.
 */
export type UserFacingStateCopy = {
  title: string;
  body: string;
  nextStep?: string;
  action?: string;
  tone?: CopyTone;
};

export type NavigationCopy = {
  board: string;
  radar: string;
  history: string;
  more: string;
};

export type EnglishCopyCatalog = {
  locale: "en";
  app: {
    name: string;
    shortDescription: string;
    informationalDisclaimer: string;
  };
  navigation: NavigationCopy;
  actions: {
    back: string;
    cancel: string;
    close: string;
    continue: string;
    done: string;
    refresh: string;
    retry: string;
    save: string;
    search: string;
    openSettings: string;
  };
  states: {
    loading: UserFacingStateCopy;
    refreshing: UserFacingStateCopy;
    offline: UserFacingStateCopy;
    unavailable: UserFacingStateCopy;
  };
  connection: {
    lan: { label: string; description: string };
    remote: { label: string; description: string };
    offline: { label: string; description: string };
    checking: { label: string; description: string };
  };
  board: {
    title: string;
    departures: string;
    arrivals: string;
    empty: UserFacingStateCopy;
    noGate: string;
    updatedNow: string;
    updatedMinutesAgo: (minutes: number) => string;
  };
  radar: {
    title: string;
    range: string;
    aircraft: string;
    empty: UserFacingStateCopy;
    mapUnavailable: UserFacingStateCopy;
  };
  history: {
    title: string;
    movements: string;
    empty: UserFacingStateCopy;
    movementCount: (count: number) => string;
  };
  setup: {
    title: string;
    companion: { label: string; description: string };
    standalone: { label: string; description: string };
    privacy: string;
  };
  standalone: {
    boardCadence: string;
    radarCadence: string;
    rowAvailability: string;
    cacheCaveat: string;
    pullToRefresh: string;
  };
  weather: {
    plainLanguage: { label: string; description: string };
    aviationDetails: { label: string; description: string };
    rawMetar: { label: string; description: string };
  };
  settings: {
    title: string;
    appearance: string;
    appearanceSystem: { label: string; description: string };
    appearanceLight: { label: string; description: string };
    appearanceDark: { label: string; description: string };
    highContrast: { label: string; description: string };
  };
  platform: {
    permissions: {
      camera: string;
      localNetwork: string;
    };
    widgets: {
      pinnedFlight: string;
      nextFlight: string;
      stale: string;
      waitingForBoard: string;
    };
    liveActivity: {
      pinAndShow: string;
      stale: string;
    };
    store: {
      airlineSchedules: string;
      vatsimTraffic: string;
    };
  };
  accessibility: {
    loading: string;
    selected: (label: string) => string;
    opensDetails: (label: string) => string;
  };
};

export type GlossaryAudience = "everyday" | "help" | "technical";

export type GlossaryEntry = {
  term: string;
  definition: string;
  audience: GlossaryAudience;
  preferredUsage: string;
  avoid?: readonly string[];
};

export type EnglishGlossaryKey =
  | "flightBoard"
  | "companion"
  | "standalone"
  | "remoteCompanion"
  | "communityRelay"
  | "supportId"
  | "movement"
  | "radar"
  | "fids"
  | "vatsim"
  | "metar"
  | "matrix";

export type EnglishGlossary = Record<EnglishGlossaryKey, GlossaryEntry>;
