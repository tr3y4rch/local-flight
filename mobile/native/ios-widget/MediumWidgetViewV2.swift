import SwiftUI
import WidgetKit

struct LFMediumWidgetViewV2: View {
  @Environment(\.colorScheme) private var systemScheme
  let snapshot: LocalFlightWidgetSnapshot

  private var scheme: ColorScheme {
    snapshot.preferences.widgetScheme(system: systemScheme)
  }

  var body: some View {
    ZStack(alignment: .topLeading) {
      ambientRoute
      VStack(alignment: .leading, spacing: 4) {
        header
        if snapshot.medium.rows.isEmpty {
          emptyState
        } else {
          ForEach(snapshot.medium.rows.prefix(snapshot.preferences.mediumRowCount)) { flight in
            LFMediumMovementCardV2(
              flight: flight,
              showGate: snapshot.preferences.showGateTerminal,
              scheme: scheme
            )
          }
        }
      }
      // contentMarginsDisabled lets the artwork reach the widget edge, so the
      // content itself needs an explicit rounded-corner safe region.
      .padding(.horizontal, 14)
      .padding(.top, 16)
      .padding(.bottom, 8)
    }
    .lfWidgetBackground(scheme)
  }

  private var ambientRoute: some View {
    ZStack(alignment: .topTrailing) {
      Circle()
        .stroke(LFWidgetDesignV2.textCyan(scheme).opacity(0.08), lineWidth: 1)
        .frame(width: 154, height: 154)
        .offset(x: 68, y: -82)
      Circle()
        .stroke(LFWidgetDesignV2.warmAccent(scheme).opacity(0.08), lineWidth: 1)
        .frame(width: 112, height: 112)
        .offset(x: 46, y: -60)
      Capsule()
        .fill(LFWidgetDesignV2.warmAccent(scheme).opacity(0.82))
        .frame(width: 54, height: 3)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.leading, 14)
        .padding(.top, 8)
    }
    .allowsHitTesting(false)
  }

  private var header: some View {
    HStack(alignment: .top, spacing: 9) {
      VStack(alignment: .leading, spacing: 2) {
        Text(snapshot.airport.name)
          .font(LocalFlightWidgetFont.uiBold(size: 14))
          .lineLimit(1)
          .minimumScaleFactor(0.54)
          .allowsTightening(true)
          .truncationMode(.tail)
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        HStack(spacing: 5) {
          Text(snapshot.airport.code)
            .font(LocalFlightWidgetFont.boardBold(size: 9))
          Text("·")
          Text(snapshot.airport.view == "arrivals" ? "Arrivals" : "Departures")
            .font(LocalFlightWidgetFont.uiBold(size: 10))
        }
        .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      .layoutPriority(1)
      Spacer(minLength: 8)
      VStack(alignment: .trailing, spacing: 2) {
        Text("Local Flight")
          .font(LocalFlightWidgetFont.brand(size: 9))
          .lineLimit(1)
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        Text(snapshot.stale ? "Update needed · \(snapshot.source.lastUpdatedLabel)" : snapshot.source.lastUpdatedLabel)
          .font(LocalFlightWidgetFont.ui(size: 9))
          .lineLimit(1)
          .minimumScaleFactor(0.68)
          .foregroundStyle(snapshot.stale
            ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: scheme)
            : LFWidgetDesignV2.textMuted(scheme))
      }
    }
  }

  private var emptyState: some View {
    HStack(spacing: 10) {
      Image(systemName: "clock.arrow.circlepath")
        .font(.system(size: 17, weight: .medium))
        .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
      VStack(alignment: .leading, spacing: 2) {
        Text("Waiting for Board")
          .font(LocalFlightWidgetFont.uiBold(size: 14))
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        Text("Open Local Flight to prepare current movements.")
          .font(LocalFlightWidgetFont.ui(size: 10))
          .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
      }
      Spacer()
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .padding(.horizontal, 12)
    .background(LFWidgetDesignV2.separator(scheme).opacity(0.10), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
  }
}

struct LFMediumMovementCardV2: View {
  let flight: LocalFlightWidgetFlight
  let showGate: Bool
  let scheme: ColorScheme

  private var isPinned: Bool { flight.pinned == true }
  private var info: String {
    guard showGate else { return "" }
    return flight.gate ?? flight.terminal ?? ""
  }

  var body: some View {
    HStack(spacing: 8) {
      if isPinned {
        Capsule()
          .fill(LFWidgetDesignV2.warmAccent(scheme))
          .frame(width: 3, height: 27)
      }

      Text(flight.displayTime)
        .font(LocalFlightWidgetFont.boardBold(size: 12))
        .lineLimit(1)
        .minimumScaleFactor(0.78)
        .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        .frame(width: 50, alignment: .leading)

      VStack(alignment: .leading, spacing: 0) {
        Text(flight.flightDisplay)
          .font(LocalFlightWidgetFont.boardBold(size: 12))
          .lineLimit(1)
          .foregroundStyle(LFWidgetDesignV2.textCyan(scheme))
        Text([flight.routeName, flight.routeCode].filter { !$0.isEmpty }.joined(separator: " · "))
          .font(LocalFlightWidgetFont.ui(size: 10))
          .lineLimit(1)
          .minimumScaleFactor(0.68)
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
      }
      .frame(maxWidth: .infinity, alignment: .leading)

      VStack(alignment: .trailing, spacing: 1) {
        Text(flight.statusDisplay.capitalized)
          .font(LocalFlightWidgetFont.uiBold(size: 10))
          .lineLimit(1)
          .minimumScaleFactor(0.65)
          .foregroundStyle(LFWidgetDesignV2.statusColor(tone: flight.statusTone, scheme: scheme))
        if !info.isEmpty {
          Text((flight.gate == nil ? "T " : "G ") + info)
            .font(LocalFlightWidgetFont.boardBold(size: 9))
            .lineLimit(1)
            .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
        }
      }
      .frame(width: 74, alignment: .trailing)
    }
    .padding(.horizontal, 9)
    .padding(.vertical, 4)
    .background(
      isPinned
        ? LFWidgetDesignV2.warmAccent(scheme).opacity(0.11)
        : LFWidgetDesignV2.separator(scheme).opacity(0.08),
      in: RoundedRectangle(cornerRadius: 13, style: .continuous)
    )
  }
}
