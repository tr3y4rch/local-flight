import { useWindowDimensions } from "react-native";

export function useResponsiveLayout() {
  const { width, height } = useWindowDimensions();
  const shortest = Math.min(width, height);
  const isTablet = shortest >= 744;
  const isLandscape = width > height;

  return {
    width,
    height,
    isTablet,
    isLandscape,
    contentMaxWidth: isTablet ? 1120 : 620,
    columns: isTablet && isLandscape ? 2 : 1
  };
}
