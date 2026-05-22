import { appleIapPlaceholderProvider } from "./appleSupportProvider";

// Switch this export to a platform-backed provider after adding StoreKit on iOS
// or Google Play Billing on Android. The active provider is intentionally
// non-charging for release-candidate builds.
export const supportPurchaseProvider = appleIapPlaceholderProvider;
