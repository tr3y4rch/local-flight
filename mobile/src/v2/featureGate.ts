/**
 * Internal compile-time rollout gate. It is intentionally not backed by user
 * storage, remote configuration, or a public old/new UI switch.
 */
export const MOBILE_V2_ROLLOUT_ENABLED = true;
export const MOBILE_V2_PUBLIC_TOGGLE = false;

/** Internal emergency gate for the iOS 26 UIKit navigation bridge. */
export const MOBILE_V2_NATIVE_NAVIGATION_ENABLED = true;
