import { appleIapPlaceholderProvider } from "./appleSupportProvider";

// Switch this export to a platform-backed provider after adding StoreKit on iOS
// or Google Play Billing on Android. The active provider keeps the tip box
// routed through the purchase abstraction but remains intentionally no-charge.
export const supportPurchaseProvider = appleIapPlaceholderProvider;
