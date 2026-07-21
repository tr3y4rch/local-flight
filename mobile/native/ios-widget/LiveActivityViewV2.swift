import ActivityKit
import SwiftUI
import WidgetKit

@available(iOS 16.1, *)
struct LocalFlightActivityAttributesV2: ActivityAttributes {
  struct ContentState: Codable, Hashable {
    var statusDisplay: String
    var statusTone: String
    var gate: String?
    var gateLabel: String?
    var stale: Bool
    var lastUpdatedLabel: String
  }

  let flightID: String
  let flightDisplay: String
  let direction: String
  let routeName: String
  let routeCode: String
  let airportCode: String
  let displayTime: String
}

private let diScheme = ColorScheme.dark

@available(iOS 16.1, *)
struct LFDICompactLeadingV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    Text(attributes.flightDisplay)
      .font(LocalFlightWidgetFont.boardBold(size: 14))
      .lineLimit(1)
      .minimumScaleFactor(0.72)
      .foregroundStyle(LFWidgetDesignV2.textPrimary(diScheme))
      .padding(.leading, 4)
  }
}

@available(iOS 16.1, *)
struct LFDICompactTrailingV2: View {
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    Text(state.stale ? "Stale" : state.statusDisplay)
      .font(LocalFlightWidgetFont.boardBold(size: 12))
      .lineLimit(1)
      .minimumScaleFactor(0.65)
      .foregroundStyle(LFWidgetDesignV2.statusColor(
        tone: state.stale ? "delayed" : state.statusTone,
        scheme: diScheme
      ))
      .padding(.trailing, 4)
  }
}

@available(iOS 16.1, *)
struct LFDIMinimalV2: View {
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    Circle()
      .fill(LFWidgetDesignV2.statusColor(
        tone: state.stale ? "delayed" : state.statusTone,
        scheme: diScheme
      ).opacity(0.88))
      .frame(width: 10, height: 10)
      .accessibilityLabel(state.stale ? "Flight information stale" : state.statusDisplay)
  }
}

// Use these three views in DynamicIslandExpandedRegion(.leading/.trailing/.bottom).
// Route/destination content intentionally lives only in the bottom region so it
// cannot compete with the TrueDepth camera area.

@available(iOS 16.1, *)
struct LFDIExpandedLeadingV2: View {
  let attributes: LocalFlightActivityAttributesV2

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      sectionLabel("Pinned flight")
      Text(attributes.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: 22))
        .lineLimit(1)
        .minimumScaleFactor(0.68)
        .foregroundStyle(LFWidgetDesignV2.textPrimary(diScheme))
    }
    .padding(.leading, 8)
  }
}

@available(iOS 16.1, *)
struct LFDIExpandedTrailingV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    VStack(alignment: .trailing, spacing: 4) {
      LFStatusCapsuleV2(
        label: state.stale ? "Stale" : state.statusDisplay,
        tone: state.stale ? "delayed" : state.statusTone,
        scheme: diScheme
      )
      Text(attributes.displayTime)
        .font(LocalFlightWidgetFont.boardBold(size: 12))
        .lineLimit(1)
        .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
    }
    .padding(.trailing, 8)
  }
}

@available(iOS 16.1, *)
struct LFDIExpandedBottomV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack(alignment: .center, spacing: 8) {
        origin
        DottedRoutePointerV2(tone: state.stale ? "delayed" : state.statusTone)
          .frame(maxWidth: .infinity)
        destination
      }
      .padding(.horizontal, 4)

      HStack(spacing: 10) {
        if let gate = state.gate, !gate.isEmpty {
        footerPair(label: state.gateLabel == "TERM" ? "Terminal" : "Gate", value: gate)
        }
        Spacer(minLength: 8)
        footerPair(label: state.stale ? "State" : "Updated", value: state.stale ? "Stale" : state.lastUpdatedLabel)
      }
      .padding(.horizontal, 4)
    }
    .padding(.horizontal, 12)
    .padding(.bottom, 4)
  }

  @ViewBuilder
  private var origin: some View {
    if attributes.direction == "arr" {
      routeEndpoint(alignment: .leading, frameAlignment: .leading)
    } else {
      airportCode(attributes.airportCode)
    }
  }

  @ViewBuilder
  private var destination: some View {
    if attributes.direction == "arr" {
      airportCode(attributes.airportCode)
    } else {
      routeEndpoint(alignment: .trailing, frameAlignment: .trailing)
    }
  }

  private func routeEndpoint(
    alignment: HorizontalAlignment,
    frameAlignment: Alignment
  ) -> some View {
    VStack(alignment: alignment, spacing: 1) {
      Text(attributes.routeName)
        .font(LocalFlightWidgetFont.uiBold(size: 14))
        .lineLimit(1)
        .minimumScaleFactor(0.62)
        .foregroundStyle(LFWidgetDesignV2.textSecondary(diScheme))
      if !attributes.routeCode.isEmpty {
        Text(attributes.routeCode)
          .font(LocalFlightWidgetFont.boardBold(size: 10))
          .lineLimit(1)
          .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
      }
    }
    .frame(maxWidth: 140, alignment: frameAlignment)
  }

  private func airportCode(_ code: String) -> some View {
    Text(code)
      .font(LocalFlightWidgetFont.boardBold(size: 12))
      .lineLimit(1)
      .minimumScaleFactor(0.75)
      .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
  }

  private func footerPair(label: String, value: String) -> some View {
    HStack(spacing: 4) {
      sectionLabel(label)
      Text(value)
        .font(LocalFlightWidgetFont.boardBold(size: 11))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(label == "State"
          ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: diScheme)
          : LFWidgetDesignV2.textPrimary(diScheme))
    }
  }
}

@available(iOS 16.1, *)
struct LFDIExpandedV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    VStack(spacing: 10) {
      HStack(alignment: .top) {
        LFDIExpandedLeadingV2(attributes: attributes)
        Spacer(minLength: 18)
        LFDIExpandedTrailingV2(attributes: attributes, state: state)
      }
      LFDIExpandedBottomV2(attributes: attributes, state: state)
    }
    .padding(.vertical, 8)
  }
}

@available(iOS 16.1, *)
struct LFLockScreenBannerV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    ZStack {
      RoundedRectangle(cornerRadius: 34, style: .continuous)
        .fill(LFWidgetDesignV2.darkWidgetBg)

      VStack(alignment: .leading, spacing: 0) {
        sectionLabel("Pinned flight")
          .padding(.top, 16)
          .padding(.horizontal, 20)

        HStack(alignment: .bottom, spacing: 16) {
          Text(attributes.flightDisplay)
            .font(LocalFlightWidgetFont.boardBold(size: 34))
            .lineLimit(1)
            .minimumScaleFactor(0.7)
            .foregroundStyle(LFWidgetDesignV2.textPrimary(diScheme))

          VStack(alignment: .leading, spacing: 2) {
            routeRow
            Text(attributes.routeName)
              .font(LocalFlightWidgetFont.uiBold(size: 15))
              .foregroundStyle(LFWidgetDesignV2.textSecondary(diScheme))
              .lineLimit(1)
              .minimumScaleFactor(0.7)
            Text(attributes.displayTime)
              .font(LocalFlightWidgetFont.board(size: 12))
              .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
          }

          Spacer()
          LFStatusCapsuleV2(
            label: state.stale ? "Stale" : state.statusDisplay,
            tone: state.stale ? "delayed" : state.statusTone,
            scheme: diScheme
          )
        }
        .padding(.horizontal, 20)
        .padding(.top, 6)

        Rectangle()
          .fill(LFWidgetDesignV2.separator(diScheme))
          .frame(height: 1)
          .padding(.horizontal, 20)
          .padding(.vertical, 8)

        HStack {
          if let gate = state.gate, !gate.isEmpty {
            HStack(spacing: 4) {
              sectionLabel(state.gateLabel == "TERM" ? "Terminal" : "Gate")
              Text(gate)
                .font(LocalFlightWidgetFont.boardBold(size: 14))
                .foregroundStyle(LFWidgetDesignV2.textPrimary(diScheme))
            }
          }
          Spacer()
          sectionLabel(state.stale ? "Stale" : state.lastUpdatedLabel)
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 16)
      }
    }
  }

  private var routeRow: some View {
    HStack(spacing: 4) {
      Text(attributes.direction == "arr" ? attributes.routeCode : attributes.airportCode)
        .font(LocalFlightWidgetFont.boardBold(size: 10))
        .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
      Image(systemName: "arrow.right")
        .font(.system(size: 9, weight: .bold))
        .foregroundStyle(LFWidgetDesignV2.textDim(diScheme))
      Text(attributes.direction == "arr" ? attributes.airportCode : attributes.routeCode)
        .font(LocalFlightWidgetFont.boardBold(size: 10))
        .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
    }
  }
}

@available(iOSApplicationExtension 16.1, *)
struct LocalFlightLiveActivityWidget: Widget {
  var body: some WidgetConfiguration {
    ActivityConfiguration(for: LocalFlightActivityAttributesV2.self) { context in
      LFLockScreenBannerV2(attributes: context.attributes, state: context.state)
        .widgetURL(URL(string: "localflight://widgets?liveActivity=1"))
        .activityBackgroundTint(Color(red: 0.031, green: 0.078, blue: 0.114))
        .activitySystemActionForegroundColor(Color(red: 0.455, green: 0.710, blue: 0.871))
    } dynamicIsland: { context in
      DynamicIsland {
        DynamicIslandExpandedRegion(.leading) {
          LFDIExpandedLeadingV2(attributes: context.attributes)
        }
        DynamicIslandExpandedRegion(.trailing) {
          LFDIExpandedTrailingV2(attributes: context.attributes, state: context.state)
        }
        DynamicIslandExpandedRegion(.bottom) {
          LFDIExpandedBottomV2(attributes: context.attributes, state: context.state)
        }
      } compactLeading: {
        LFDICompactLeadingV2(attributes: context.attributes, state: context.state)
      } compactTrailing: {
        LFDICompactTrailingV2(state: context.state)
      } minimal: {
        LFDIMinimalV2(state: context.state)
      }
      .widgetURL(URL(string: "localflight://widgets?liveActivity=1"))
      .keylineTint(LFWidgetDesignV2.statusColor(
        tone: context.state.stale ? "delayed" : context.state.statusTone,
        scheme: .dark
      ))
    }
  }
}

private struct DottedRoutePointerV2: View {
  let tone: String

  var body: some View {
    HStack(spacing: 4) {
      ForEach(0..<8, id: \.self) { index in
        Circle()
          .fill(index == 7
            ? LFWidgetDesignV2.statusColor(tone: tone, scheme: diScheme)
            : LFWidgetDesignV2.textDim(diScheme))
          .frame(width: index == 7 ? 5 : 3, height: index == 7 ? 5 : 3)
          .opacity(index == 7 ? 0.95 : 0.38)
      }
    }
    .accessibilityHidden(true)
  }
}

private func sectionLabel(_ text: String) -> some View {
  Text(text)
    .font(LocalFlightWidgetFont.uiBold(size: 11))
    .foregroundStyle(LFWidgetDesignV2.textDim(diScheme))
}
