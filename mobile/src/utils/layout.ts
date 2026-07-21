import { useWindowDimensions } from "react-native";

export type LayoutWidthClass = "compact" | "medium" | "expanded" | "large";
export type LayoutClass = LayoutWidthClass;

/** Breakpoints follow the window width, never a device-name or platform check. */
export const LAYOUT_BREAKPOINTS = {
  compact: 0,
  medium: 600,
  expanded: 840,
  large: 1200
} as const satisfies Record<LayoutWidthClass, number>;

export const layoutBreakpoints = LAYOUT_BREAKPOINTS;

export type LayoutClassMetrics = {
  contentMaxWidth: number;
  gutter: number;
  gridGap: number;
  columns: 1 | 2 | 3;
};

export const LAYOUT_CLASS_METRICS: Record<LayoutWidthClass, LayoutClassMetrics> = {
  compact: { contentMaxWidth: 620, gutter: 16, gridGap: 12, columns: 1 },
  medium: { contentMaxWidth: 760, gutter: 24, gridGap: 16, columns: 1 },
  expanded: { contentMaxWidth: 1120, gutter: 32, gridGap: 20, columns: 2 },
  large: { contentMaxWidth: 1440, gutter: 40, gridGap: 24, columns: 3 }
};

export type ResponsiveLayout = {
  width: number;
  height: number;
  sizeClass: LayoutWidthClass;
  layoutClass: LayoutWidthClass;
  isCompact: boolean;
  isMedium: boolean;
  isExpanded: boolean;
  isLarge: boolean;
  isAtLeastMedium: boolean;
  isAtLeastExpanded: boolean;
  isLandscape: boolean;
  /** Compatibility heuristic for existing iPhone/iPad presentation copy. */
  isTablet: boolean;
  contentMaxWidth: number;
  contentWidth: number;
  contentGutter: number;
  gridGap: number;
  columns: 1 | 2 | 3;
  paneCount: 1 | 2 | 3;
};

function finiteDimension(value: number): number {
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

export function layoutClassForWidth(width: number): LayoutWidthClass {
  const normalizedWidth = finiteDimension(width);
  if (normalizedWidth >= LAYOUT_BREAKPOINTS.large) return "large";
  if (normalizedWidth >= LAYOUT_BREAKPOINTS.expanded) return "expanded";
  if (normalizedWidth >= LAYOUT_BREAKPOINTS.medium) return "medium";
  return "compact";
}

export const getLayoutClass = layoutClassForWidth;
export const getLayoutSizeClass = layoutClassForWidth;

export function resolveResponsiveLayout(width: number, height: number): ResponsiveLayout {
  const normalizedWidth = finiteDimension(width);
  const normalizedHeight = finiteDimension(height);
  const sizeClass = layoutClassForWidth(normalizedWidth);
  const metrics = LAYOUT_CLASS_METRICS[sizeClass];
  const shortest = Math.min(normalizedWidth, normalizedHeight);
  const contentWidth = Math.max(
    0,
    Math.min(metrics.contentMaxWidth, normalizedWidth - metrics.gutter * 2)
  );

  return {
    width: normalizedWidth,
    height: normalizedHeight,
    sizeClass,
    layoutClass: sizeClass,
    isCompact: sizeClass === "compact",
    isMedium: sizeClass === "medium",
    isExpanded: sizeClass === "expanded",
    isLarge: sizeClass === "large",
    isAtLeastMedium: sizeClass !== "compact",
    isAtLeastExpanded: sizeClass === "expanded" || sizeClass === "large",
    isLandscape: normalizedWidth > normalizedHeight,
    isTablet: shortest >= 744,
    contentMaxWidth: metrics.contentMaxWidth,
    contentWidth,
    contentGutter: metrics.gutter,
    gridGap: metrics.gridGap,
    columns: metrics.columns,
    paneCount: metrics.columns
  };
}

export const getResponsiveLayout = resolveResponsiveLayout;

export function useResponsiveLayout(): ResponsiveLayout {
  const { width, height } = useWindowDimensions();
  return resolveResponsiveLayout(width, height);
}
