import type { EnglishCopyCatalog } from "./contracts";

function safeCount(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.round(value)) : 0;
}

export const englishCopy = {
  locale: "en",
  app: {
    name: "Local Flight",
    shortDescription: "A clear, local-first view of the flights that matter to you.",
    informationalDisclaimer: "Flight information can change. Do not use Local Flight for navigation or operational decisions."
  },
  navigation: {
    board: "Board",
    radar: "Radar",
    history: "History",
    more: "More"
  },
  actions: {
    back: "Back",
    cancel: "Cancel",
    close: "Close",
    continue: "Continue",
    done: "Done",
    refresh: "Refresh",
    retry: "Try again",
    save: "Save",
    search: "Search",
    openSettings: "Open settings"
  },
  states: {
    loading: {
      title: "Loading flight information",
      body: "Local Flight is reading the latest saved board."
    },
    refreshing: {
      title: "Refreshing flight information",
      body: "The current board stays visible while Local Flight checks for an update."
    },
    offline: {
      title: "You’re offline",
      body: "Saved flight information remains available.",
      nextStep: "Local Flight will reconnect when a network is available.",
      tone: "warning"
    },
    unavailable: {
      title: "Flight information isn’t available",
      body: "Local Flight could not load a usable board.",
      nextStep: "Check the connection and try again.",
      action: "Try again",
      tone: "danger"
    }
  },
  connection: {
    lan: {
      label: "Connected nearby",
      description: "Connected directly to your Local Flight host."
    },
    remote: {
      label: "Connected remotely",
      description: "Connected through the encrypted Remote Companion fallback."
    },
    offline: {
      label: "Offline",
      description: "The host is not reachable. Saved information may still be available."
    },
    checking: {
      label: "Checking connection",
      description: "Looking for your Local Flight host on the local network first."
    }
  },
  board: {
    title: "Board",
    departures: "Departures",
    arrivals: "Arrivals",
    empty: {
      title: "No flights to show",
      body: "There are no matching flights in the current board window.",
      nextStep: "Change the board view or refresh later."
    },
    noGate: "Gate not available",
    updatedNow: "Updated now",
    updatedMinutesAgo: (minutes) => {
      const count = safeCount(minutes);
      return `Updated ${count} ${count === 1 ? "minute" : "minutes"} ago`;
    }
  },
  radar: {
    title: "Radar",
    range: "Range",
    aircraft: "Aircraft",
    empty: {
      title: "No aircraft in range",
      body: "No current tracks match this radar view.",
      nextStep: "Change the range or refresh later."
    },
    mapUnavailable: {
      title: "Ground map isn’t available",
      body: "Live aircraft can still appear without the airport ground layer.",
      nextStep: "Local Flight will try the map again later.",
      tone: "warning"
    }
  },
  history: {
    title: "History",
    movements: "Movements",
    empty: {
      title: "No movement history yet",
      body: "History appears after Local Flight records arrivals or departures.",
      nextStep: "Keep the app connected and check again later."
    },
    movementCount: (count) => {
      const total = safeCount(count);
      return `${total} ${total === 1 ? "movement" : "movements"}`;
    }
  },
  setup: {
    title: "Set up Local Flight",
    companion: {
      label: "Connect to a Local Flight host",
      description: "Connect to your Local Flight host. This phone follows that host and does not use the Relay Access included with the app.",
      androidDescription: "Connect to your Local Flight host. Companion is free and does not require Relay Access."
    },
    standalone: {
      label: "Use without a Local Flight host",
      description: (storeName) => `Use this phone on its own. We’ll check your ${storeName} purchase and use the included Relay Access here.`
    },
    relayAccess: {
      includedHeading: "Beacon Relay Access included",
      includedBody: "There is no subscription or extra purchase. Relay Access can be active on one phone in Standalone mode or one Local Flight desktop.",
      companionReview: "This paid app includes Beacon Relay Access. Companion uses your desktop host, so the included access remains available for another main device.",
      androidCompanionReview: "Companion is free and follows your desktop host. It does not require or purchase Relay Access.",
      standaloneReview: (storeName) => `We’ll verify your ${storeName} purchase and activate the included Relay Access on this phone.`,
      androidStandaloneReview: "Real-flight Standalone uses the one-time Relay Access product from Google Play. There is no subscription.",
      vatsimReview: "VATSIM Standalone is free. It does not buy, verify, activate, or occupy Relay Access.",
      verifyAndOpenBoard: (storeName) => `Verify ${storeName} purchase & open Board`,
      getOrRestoreAndOpenBoard: "Get or restore Relay Access & open Board"
    },
    privacy: "Your setup choice is stored on this device. You can change it later in More."
  },
  standalone: {
    boardCadence: "Airline schedules usually refresh about once an hour.",
    radarCadence: "Nearby traffic can refresh about every 3 minutes while Radar is open.",
    rowAvailability: "Shows up to 50 current departures and 50 arrivals when supplied.",
    cacheCaveat: "Shared information may still be cached or delayed.",
    pullToRefresh: "Check the latest shared information."
  },
  weather: {
    plainLanguage: {
      label: "Plain language",
      description: "Show a short, everyday summary of airport weather."
    },
    aviationDetails: {
      label: "Aviation details",
      description: "Show decoded aviation weather fields and units."
    },
    rawMetar: {
      label: "Raw METAR",
      description: "Show the original coded airport observation."
    }
  },
  settings: {
    title: "Settings",
    appearance: "Appearance",
    appearanceSystem: {
      label: "Use device setting",
      description: "Follow this device’s light or dark appearance."
    },
    appearanceLight: {
      label: "Light",
      description: "Always use the warm cloud appearance."
    },
    appearanceDark: {
      label: "Dark",
      description: "Always use the midnight appearance."
    },
    highContrast: {
      label: "High contrast",
      description: "Use stronger separators and maximum text contrast."
    }
  },
  platform: {
    permissions: {
      camera: "Local Flight scans pairing QR codes shown by your Local Flight host.",
      localNetwork: "Local Flight connects to a Local Flight host on the same Wi-Fi."
    },
    widgets: {
      pinnedFlight: "Pinned flight",
      nextFlight: "Next flight",
      stale: "Stale",
      waitingForBoard: "Waiting for board data"
    },
    liveActivity: {
      pinAndShow: "Pin & show on Lock Screen",
      stale: "Pinned flight information is stale"
    },
    store: {
      airlineSchedules: "Airline schedules",
      vatsimTraffic: "VATSIM traffic"
    }
  },
  accessibility: {
    loading: "Loading",
    selected: (label) => `${label}, selected`,
    opensDetails: (label) => `${label}. Opens details.`
  }
} as const satisfies EnglishCopyCatalog;

export const copy = englishCopy;
export const en = englishCopy;
export const ENGLISH_COPY = englishCopy;
