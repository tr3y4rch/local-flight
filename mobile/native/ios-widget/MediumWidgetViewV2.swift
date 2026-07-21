import SwiftUI
import WidgetKit

struct LFMediumWidgetViewV2: View {
  @Environment(\.colorScheme) private var scheme
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
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
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .lfWidgetBackground(scheme)
    .overlay(alignment: .topLeading) {
      Capsule()
        .fill(LFWidgetDesignV2.warmAccent(scheme).opacity(0.82))
        .frame(width: 54, height: 3)
        .padding(.leading, 12)
        .padding(.top, 5)
    }
  }

  private var header: some View {
    HStack(alignment: .center, spacing: 10) {
      VStack(alignment: .leading, spacing: 1) {
        Text(snapshot.airport.name)
          .font(LocalFlightWidgetFont.uiBold(size: 15))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        HStack(spacing: 5) {
          Text(snapshot.airport.code)
            .font(LocalFlightWidgetFont.boardBold(size: 9))
          Text(snapshot.airport.view == "arrivals" ? "Arrivals" : "Departures")
            .font(LocalFlightWidgetFont.ui(size: 10))
        }
        .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
      }
      Spacer(minLength: 8)
      VStack(alignment: .trailing, spacing: 1) {
        Text("Local Flight")
          .font(LocalFlightWidgetFont.brand(size: 10))
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        Text(snapshot.stale ? "Cached · \(snapshot.source.lastUpdatedLabel)" : snapshot.source.lastUpdatedLabel)
          .font(LocalFlightWidgetFont.ui(size: 9))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .foregroundStyle(snapshot.stale
            ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: scheme)
            : LFWidgetDesignV2.textMuted(scheme))
      }
    }
  }

  private var emptyState: some View {
    HStack(spacing: 10) {
      Image(systemName: "clock.arrow.circlepath")
        .font(.system(size: 18, weight: .medium))
        .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
      VStack(alignment: .leading, spacing: 2) {
        Text("Waiting for Board")
          .font(LocalFlightWidgetFont.uiBold(size: 14))
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        Text("Open Local Flight to prepare the latest snapshot.")
          .font(LocalFlightWidgetFont.ui(size: 10))
          .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
      }
      Spacer()
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .padding(.horizontal, 10)
    .background(LFWidgetDesignV2.separator(scheme).opacity(0.12), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
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
    HStack(spacing: 9) {
      if isPinned {
        Capsule()
          .fill(LFWidgetDesignV2.warmAccent(scheme))
          .frame(width: 3, height: 30)
      }

      Text(flight.displayTime)
        .font(LocalFlightWidgetFont.boardBold(size: 12))
        .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        .frame(width: 43, alignment: .leading)

      VStack(alignment: .leading, spacing: 1) {
        HStack(spacing: 5) {
          Text(flight.flightDisplay)
            .font(LocalFlightWidgetFont.boardBold(size: 12))
            .foregroundStyle(LFWidgetDesignV2.textCyan(scheme))
          if isPinned {
            Image(systemName: "pin.fill")
              .font(.system(size: 7, weight: .bold))
              .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
          }
        }
        Text([flight.routeName, flight.routeCode].filter { !$0.isEmpty }.joined(separator: " · "))
          .font(LocalFlightWidgetFont.ui(size: 10))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
      }
      .frame(maxWidth: .infinity, alignment: .leading)

      VStack(alignment: .trailing, spacing: 2) {
        Text(flight.statusDisplay.capitalized)
          .font(LocalFlightWidgetFont.uiBold(size: 10))
          .lineLimit(1)
          .minimumScaleFactor(0.68)
          .foregroundStyle(LFWidgetDesignV2.statusColor(tone: flight.statusTone, scheme: scheme))
        if !info.isEmpty {
          Text(info)
            .font(LocalFlightWidgetFont.boardBold(size: 9))
            .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
        }
      }
      .frame(width: 76, alignment: .trailing)
    }
    .padding(.horizontal, 10)
    .padding(.vertical, 6)
    .background(
      isPinned ? LFWidgetDesignV2.warmAccent(scheme).opacity(0.10) : LFWidgetDesignV2.separator(scheme).opacity(0.08),
      in: RoundedRectangle(cornerRadius: 14, style: .continuous)
    )
  }
}
