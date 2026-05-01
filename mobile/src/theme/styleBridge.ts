import { DEFAULT_MOBILE_APPEARANCE, type MobileAppearance } from "./tokens";

export let palette: MobileAppearance = DEFAULT_MOBILE_APPEARANCE;
export let styles: Record<string, any> = {};

export function setStyleBridge(nextStyles: Record<string, any>, nextPalette: MobileAppearance) {
  styles = nextStyles;
  palette = nextPalette;
}
