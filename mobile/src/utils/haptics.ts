import * as Haptics from "expo-haptics";

export const hapticSelection = () => void Haptics.selectionAsync();
export const hapticLight     = () => void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
export const hapticMedium    = () => void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
export const hapticSuccess   = () => void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
export const hapticWarning   = () => void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning);
