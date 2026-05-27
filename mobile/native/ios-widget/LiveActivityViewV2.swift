import ActivityKit
import SwiftUI

struct LocalFlightActivityAttributesV2: ActivityAttributes {
  struct ContentState: Codable, Hashable {
    var statusDisplay: String
    var statusTone: String
    var gate: String?
    var stale: Bool
    var lastUpdatedLabel: String
  }

  let flightDisplay: String
  let routeName: String
  let routeCode: String
  let originCode: String
  let displayTime: String
}

private let diScheme = ColorScheme.dark

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

struct LFDICompactTrailingV2: View {
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    Text(state.statusDisplay.uppercased())
      .font(LocalFlightWidgetFont.boardBold(size: 12))
      .lineLimit(1)
      .minimumScaleFactor(0.65)
      .foregroundStyle(LFWidgetDesignV2.statusColor(tone: state.statusTone, scheme: diScheme))
      .padding(.trailing, 4)
  }
}

struct LFDIMinimalV2: View {
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    Circle()
      .fill(LFWidgetDesignV2.statusColor(tone: state.statusTone, scheme: diScheme).opacity(0.88))
      .frame(width: 10, height: 10)
  }
}

// Use these three views in DynamicIslandExpandedRegion(.leading/.trailing/.bottom).
// Route/destination content intentionally lives only in the bottom region so it
// cannot compete with the TrueDepth camera area.

struct LFDIExpandedLeadingV2: View {
  let attributes: LocalFlightActivityAttributesV2

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      sectionLabel("PINNED")
      Text(attributes.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: 22))
        .lineLimit(1)
        .minimumScaleFactor(0.68)
        .foregroundStyle(LFWidgetDesignV2.textPrimary(diScheme))
    }
    .padding(.leading, 8)
  }
}

struct LFDIExpandedTrailingV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    VStack(alignment: .trailing, spacing: 4) {
      LFStatusCapsuleV2(
        label: state.stale ? "STALE" : state.statusDisplay,
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

struct LFDIExpandedBottomV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack(alignment: .center, spacing: 8) {
        airportCode(attributes.originCode)
        DottedRoutePointerV2(tone: state.statusTone)
          .frame(maxWidth: .infinity)
        destination
      }
      .padding(.horizontal, 4)

      HStack(spacing: 10) {
        if let gate = state.gate, !gate.isEmpty {
          footerPair(label: "GATE", value: gate)
        }
        Spacer(minLength: 8)
        footerPair(label: state.stale ? "STATE" : "UPDATED", value: state.stale ? "STALE" : state.lastUpdatedLabel)
      }
      .padding(.horizontal, 4)
    }
    .padding(.horizontal, 12)
    .padding(.bottom, 4)
  }

  private var destination: some View {
    VStack(alignment: .trailing, spacing: 1) {
      Text(attributes.routeName)
        .font(LocalFlightWidgetFont.uiBold(size: 14))
        .lineLimit(1)
        .minimumScaleFactor(0.62)
        .foregroundStyle(LFWidgetDesignV2.textSecondary(diScheme))
      if !attributes.routeCode.isEmpty {
        Text(attributes.routeCode)
          .font(LocalFlightWidgetFont.boardBold(size: 10))
          .tracking(1.2)
          .lineLimit(1)
          .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
      }
    }
    .frame(maxWidth: 140, alignment: .trailing)
  }

  private func airportCode(_ code: String) -> some View {
    Text(code)
      .font(LocalFlightWidgetFont.boardBold(size: 12))
      .tracking(1.4)
      .lineLimit(1)
      .minimumScaleFactor(0.75)
      .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
  }

  private func footerPair(label: String, value: String) -> some View {
    HStack(spacing: 4) {
      sectionLabel(label)
      Text(value.uppercased())
        .font(LocalFlightWidgetFont.boardBold(size: 10))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(label == "STATE"
          ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: diScheme)
          : LFWidgetDesignV2.textPrimary(diScheme))
    }
  }
}

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

struct LFLockScreenBannerV2: View {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState

  var body: some View {
    ZStack {
      RoundedRectangle(cornerRadius: 34, style: .continuous)
        .fill(
          LinearGradient(
            colors: [
              Color(red: 0.020, green: 0.043, blue: 0.078),
              Color(red: 0.031, green: 0.067, blue: 0.118),
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
          )
        )

      VStack(alignment: .leading, spacing: 0) {
        sectionLabel("PINNED FLIGHT")
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
            label: state.stale ? "STALE" : state.statusDisplay,
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
              sectionLabel("GATE")
              Text(gate)
                .font(LocalFlightWidgetFont.boardBold(size: 14))
                .foregroundStyle(LFWidgetDesignV2.textPrimary(diScheme))
            }
          }
          Spacer()
          sectionLabel(state.stale ? "STALE" : state.lastUpdatedLabel.uppercased())
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 16)
      }
    }
  }

  private var routeRow: some View {
    HStack(spacing: 4) {
      Text(attributes.originCode)
        .font(LocalFlightWidgetFont.boardBold(size: 10))
        .tracking(1.5)
        .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
      Image(systemName: "arrow.right")
        .font(.system(size: 9, weight: .bold))
        .foregroundStyle(LFWidgetDesignV2.textDim(diScheme))
      Text(attributes.routeCode)
        .font(LocalFlightWidgetFont.boardBold(size: 10))
        .tracking(1.5)
        .foregroundStyle(LFWidgetDesignV2.textMuted(diScheme))
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
    .font(LocalFlightWidgetFont.boardBold(size: 8))
    .tracking(2)
    .foregroundStyle(LFWidgetDesignV2.textDim(diScheme))
}
