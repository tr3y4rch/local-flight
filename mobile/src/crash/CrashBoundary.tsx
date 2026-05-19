import React from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import { mono, palette } from "../theme/tokens";
import { reportMobileCrash } from "./reporter";

type Props = {
  children: React.ReactNode;
};

type State = {
  hasError: boolean;
};

export class CrashBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    void reportMobileCrash({
      message: `${error.name || "Error"}: ${error.message || "Unknown render crash"}`,
      traceback: [error.stack || "", info.componentStack || ""].filter(Boolean).join("\n\n"),
      context: "mobile/react-boundary"
    });
  }

  private retry = (): void => {
    this.setState({ hasError: false });
  };

  render(): React.ReactNode {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <View style={styles.wrap}>
        <Text style={styles.title}>Local Flight Mobile Paused</Text>
        <Text style={styles.body}>
          A critical UI error was caught. If automatic diagnostics are enabled, Local Flight will try to send a report to the developer board.
        </Text>
        <Pressable
          style={styles.button}
          onPress={this.retry}
          accessibilityRole="button"
          accessibilityLabel="Retry app"
          accessibilityHint="Attempts to restart the Local Flight mobile interface."
        >
          <Text style={styles.buttonText}>RETRY APP</Text>
        </Pressable>
      </View>
    );
  }
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
    backgroundColor: palette.bg
  },
  title: {
    fontFamily: mono,
    color: palette.red,
    fontSize: 18,
    fontWeight: "700",
    letterSpacing: 1,
    textAlign: "center"
  },
  body: {
    marginTop: 12,
    color: palette.textMuted,
    fontSize: 14,
    lineHeight: 20,
    textAlign: "center"
  },
  button: {
    marginTop: 18,
    minWidth: 160,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 10,
    backgroundColor: palette.green,
    paddingHorizontal: 16
  },
  buttonText: {
    fontFamily: mono,
    color: "#000",
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1
  }
});
