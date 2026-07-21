import { ActivityIndicator, StyleSheet, Text, View } from "react-native";

import { accessibleButton } from "../accessibility/mobileA11y";
import { MotionPressable } from "../components/MotionPressable";
import { LocalFlightIcon } from "../theme/icons";
import { useMobileTheme } from "../theme/runtime";
import type { MobileAppearance } from "../theme/tokens";
import { hapticLight } from "../utils/haptics";
import { SUPPORT_PRODUCT_IDS } from "./products";
import type { SupportPurchaseController } from "./types";

export function SupportPurchaseContent({ controller }: { controller: SupportPurchaseController }) {
  const { appearance } = useMobileTheme();
  const styles = makeStyles(appearance);
  const catalogReady = controller.connected && controller.products.length === SUPPORT_PRODUCT_IDS.length;
  const showStoreStatus = controller.status !== "ready";
  const canRetry = controller.status === "error" || controller.status === "unavailable";

  return (
    <View style={styles.content}>
      <View style={styles.introRow}>
        <LocalFlightIcon name="heart-outline" size={19} color={appearance.textMuted} />
        <View style={styles.copy}>
          <Text style={styles.title}>Optional, one-time support</Text>
          <Text style={styles.body}>Nothing is locked or changed. Apple or Google handles the payment.</Text>
        </View>
      </View>

      {showStoreStatus ? (
        <View style={styles.statusRow} accessibilityLiveRegion="polite">
          <Text style={styles.statusLabel}>Store</Text>
          <Text style={styles.statusValue}>{controller.message}</Text>
        </View>
      ) : null}

      <View style={styles.catalog}>
        {catalogReady ? controller.products.map((product, index) => (
          <View key={product.id} style={[styles.productRow, index > 0 && styles.productDivider]}>
            <View style={styles.copy}>
              <Text style={styles.productLabel}>{product.label}</Text>
              <Text style={styles.productPrice}>{product.displayPrice}</Text>
            </View>
            <MotionPressable
              style={[styles.purchaseButton, controller.busy && styles.disabled]}
              disabled={controller.busy}
              onPress={() => {
                hapticLight();
                void controller.purchase(product.id);
              }}
              {...accessibleButton({
                label: `Support Local Flight once with ${product.label} for ${product.displayPrice}`,
                hint: "Opens the App Store or Play Store confirmation. This unlocks no features.",
                disabled: controller.busy,
                busy: controller.busy
              })}
            >
              {controller.busy ? <ActivityIndicator size="small" color={appearance.bg} /> : null}
              <Text style={styles.purchaseText}>Support once</Text>
            </MotionPressable>
          </View>
        )) : (
          <View style={styles.unavailable}>
            <Text style={styles.productLabel}>Purchases unavailable</Text>
            <Text style={styles.body}>Optional support is not available right now. Nothing in the app depends on it.</Text>
          </View>
        )}
      </View>

      {canRetry ? (
        <MotionPressable
          style={[styles.retryButton, controller.busy && styles.disabled]}
          disabled={controller.busy}
          onPress={() => void controller.refresh()}
          {...accessibleButton({ label: "Try loading support purchases again", disabled: controller.busy })}
        >
          <Text style={styles.retryText}>Try again</Text>
        </MotionPressable>
      ) : null}

      <Text style={styles.privacy}>Local Flight never receives card details.</Text>
    </View>
  );
}

function makeStyles(a: MobileAppearance) {
  return StyleSheet.create({
    content: { width: "100%", maxWidth: 720, alignSelf: "center", padding: 20, paddingBottom: 40 },
    introRow: { flexDirection: "row", alignItems: "flex-start", gap: 12 },
    copy: { flex: 1, minWidth: 0 },
    title: { color: a.text, fontSize: 18, fontWeight: "700" },
    body: { color: a.textMuted, fontSize: 14, lineHeight: 20, marginTop: 4 },
    statusRow: { borderRadius: 16, backgroundColor: a.lineSoft, padding: 14, marginTop: 18 },
    statusLabel: { color: a.text, fontSize: 13, fontWeight: "700" },
    statusValue: { color: a.textMuted, fontSize: 13, lineHeight: 18, marginTop: 3 },
    catalog: { borderRadius: 19, backgroundColor: a.shell, overflow: "hidden", marginTop: 18 },
    productRow: { minHeight: 78, flexDirection: "row", alignItems: "center", gap: 14, paddingHorizontal: 15, paddingVertical: 12 },
    productDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: a.lineSoft },
    productLabel: { color: a.text, fontSize: 15, fontWeight: "600" },
    productPrice: { color: a.textMuted, fontSize: 13, marginTop: 3 },
    purchaseButton: { minHeight: 44, minWidth: 112, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 7, borderRadius: 14, backgroundColor: a.blue, paddingHorizontal: 13 },
    purchaseText: { color: a.bg, fontSize: 13, fontWeight: "700" },
    unavailable: { padding: 16 },
    retryButton: { minHeight: 44, alignSelf: "flex-start", justifyContent: "center", paddingHorizontal: 4, marginTop: 10 },
    retryText: { color: a.blue, fontSize: 14, fontWeight: "700" },
    disabled: { opacity: 0.55 },
    privacy: { color: a.textDim, fontSize: 12, lineHeight: 18, marginTop: 16 }
  });
}
