import { Text } from "react-native";
import type { ComponentProps } from "react";

import { BRAND_FONT_FAMILY } from "../theme/tokens";

type RNTextProps = ComponentProps<typeof Text>;

export type BrandWordmarkProps = {
  children: string;
  color: string;
  size?: number;
  style?: RNTextProps["style"];
} & Pick<RNTextProps, "adjustsFontSizeToFit" | "minimumFontScale" | "numberOfLines" | "testID">;

export function BrandWordmark({
  children,
  color,
  size = 34,
  style,
  ...rest
}: BrandWordmarkProps) {
  return (
    <Text
      style={[
        style,
        {
          fontFamily: BRAND_FONT_FAMILY,
          color,
          fontSize: size,
          fontWeight: "400",
          letterSpacing: 1,
          includeFontPadding: false
        }
      ]}
      {...rest}
    >
      {children}
    </Text>
  );
}

export type BrandKickerProps = {
  children: string;
  color: string;
  size?: number;
  style?: RNTextProps["style"];
} & Pick<RNTextProps, "testID">;

export function BrandKicker({
  children,
  color,
  size = 10,
  style,
  ...rest
}: BrandKickerProps) {
  return (
    <Text
      style={[
        style,
        {
          fontFamily: BRAND_FONT_FAMILY,
          color,
          fontSize: size,
          fontWeight: "400",
          letterSpacing: 1,
          includeFontPadding: false
        }
      ]}
      {...rest}
    >
      {children}
    </Text>
  );
}
