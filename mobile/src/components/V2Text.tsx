import { forwardRef } from "react";
import { Text as NativeText, type TextProps } from "react-native";

import { UI_FONT_FAMILY } from "../theme/tokens";

/** Default text for Local Flight-authored V2 content. */
export const V2Text = forwardRef<NativeText, TextProps>(function V2Text(
  { style, ...props },
  ref
) {
  return <NativeText ref={ref} style={[{ fontFamily: UI_FONT_FAMILY }, style]} {...props} />;
});
