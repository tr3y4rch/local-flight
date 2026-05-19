import { appleIapPlaceholderProvider } from "./appleSupportProvider";

// Switch this export to createAppleSupportPurchaseProvider(...) after adding
// the native IAP library/config plugin to the Expo dev build.
export const supportPurchaseProvider = appleIapPlaceholderProvider;
