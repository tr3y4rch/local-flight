import type { ImageSourcePropType } from "react-native";

import type { MobileThemeMode } from "./tokens";

export const LOCAL_FLIGHT_BRAND_ASSETS = {
  dark: {
    icon: require("../../assets/localflight-icon-dark.png"),
    logo: require("../../assets/localflight-logo-dark.png")
  },
  light: {
    icon: require("../../assets/localflight-icon-light.png"),
    logo: require("../../assets/localflight-logo-light.png")
  }
} as const satisfies Record<MobileThemeMode, Record<"icon" | "logo", ImageSourcePropType>>;

export function localFlightLogoForTheme(themeMode: MobileThemeMode): ImageSourcePropType {
  return LOCAL_FLIGHT_BRAND_ASSETS[themeMode].logo;
}
