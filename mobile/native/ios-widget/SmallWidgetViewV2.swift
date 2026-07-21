import SwiftUI
import WidgetKit

struct LFSmallWidgetViewV2: View {
  @Environment(\.colorScheme) private var scheme
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    ZStack(alignment: .leading) {
      background
      content
        .padding(.horizontal, 13)
        .padding(.vertical, 12)
    }
    .lfWidgetBackground(scheme)
  }

  private var background: some View {
    ZStack(alignment: .bottomTrailing) {
      scheme == .dark ? LFWidgetDesignV2.darkWidgetBg : LFWidgetDesignV2.lightWidgetBg

      Circle()
        .fill(LFWidgetDesignV2.warmAccent(scheme).opacity(scheme == .dark ? 0.13 : 0.11))
        .frame(width: 112, height: 112)
        .offset(x: 45, y: 47)

      ForEach([72, 98] as [CGFloat], id: \.self) { diameter in
        Circle()
          .stroke(LFWidgetDesignV2.warmAccent(scheme).opacity(0.12), lineWidth: 1)
          .frame(width: diameter, height: diameter)
          .offset(x: 32, y: 32)
      }

      Rectangle()
        .fill(LFWidgetDesignV2.warmAccent(scheme).opacity(0.72))
        .frame(width: 42, height: 3)
        .clipShape(Capsule())
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(.leading, 13)
        .padding(.top, 7)
    }
    .allowsHitTesting(false)
  }

  private var content: some View {
    VStack(alignment: .leading, spacing: 0) {
      header
      divider.padding(.vertical, 6)
      flightBody
      Spacer(minLength: 4)
      footer
    }
  }

  private var header: some View {
    HStack(alignment: .firstTextBaseline, spacing: 6) {
      Text(snapshot.airport.code)
        .font(LocalFlightWidgetFont.boardBold(size: 12))
        .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
      Text(snapshot.airport.view == "arrivals" ? "ARRIVALS" : "DEPARTURES")
        .font(LocalFlightWidgetFont.uiBold(size: 8))
        .lineLimit(1)
        .minimumScaleFactor(0.75)
        .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
      Spacer(minLength: 2)
      Circle()
        .fill(snapshot.stale
          ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: scheme)
          : LFWidgetDesignV2.statusColor(tone: "boarding", scheme: scheme))
        .frame(width: 5, height: 5)
      Text(snapshot.stale ? "Cached" : "Updated")
        .font(LocalFlightWidgetFont.uiBold(size: 8))
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
    }
  }

  @ViewBuilder
  private var flightBody: some View {
    if let flight = snapshot.small.flight {
      HStack(spacing: 5) {
        Image(systemName: "pin.fill")
          .font(.system(size: 7, weight: .bold))
        Text("Pinned flight")
          .font(LocalFlightWidgetFont.uiBold(size: 9))
        Spacer(minLength: 4)
        LFStatusCapsuleV2(
          label: flight.statusDisplay,
          tone: flight.statusTone,
          scheme: scheme
        )
      }
      .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))

      Text(flight.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: 31))
        .minimumScaleFactor(0.62)
        .lineLimit(1)
        .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        .padding(.top, 2)

      Text(flight.routeName)
        .font(LocalFlightWidgetFont.uiBold(size: 15))
        .minimumScaleFactor(0.72)
        .lineLimit(1)
        .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))

      HStack(spacing: 4) {
        Text(snapshot.airport.code)
        Image(systemName: flight.direction == "arr" ? "arrow.left" : "arrow.right")
          .font(.system(size: 8, weight: .bold))
        if !flight.routeCode.isEmpty {
          Text(flight.routeCode)
        }
        Text("·")
        Text(flight.displayTime)
      }
      .font(LocalFlightWidgetFont.boardBold(size: 9))
      .lineLimit(1)
      .minimumScaleFactor(0.72)
      .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
      .padding(.top, 2)
    } else {
      Spacer(minLength: 3)
      Image(systemName: "pin.slash")
        .font(.system(size: 17, weight: .medium))
        .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
      Text("Pin a flight")
        .font(LocalFlightWidgetFont.uiBold(size: 17))
        .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        .padding(.top, 5)
      Text("Open Local Flight to choose one")
        .font(LocalFlightWidgetFont.ui(size: 10))
        .lineLimit(2)
        .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
      Spacer(minLength: 3)
    }
  }

  private var footer: some View {
    HStack(spacing: 5) {
      if snapshot.preferences.showGateTerminal,
         let flight = snapshot.small.flight,
         let info = flight.gate ?? flight.terminal,
         !info.isEmpty {
        Text(flight.gate == nil ? "TERM" : "GATE")
          .font(LocalFlightWidgetFont.boardBold(size: 7))
          .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
        Text(info.uppercased())
          .font(LocalFlightWidgetFont.boardBold(size: 11))
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
      }
      Spacer(minLength: 4)
      Text(snapshot.stale ? "Cached · \(snapshot.source.lastUpdatedLabel)" : snapshot.source.lastUpdatedLabel)
        .font(LocalFlightWidgetFont.ui(size: 8))
        .lineLimit(1)
        .minimumScaleFactor(0.68)
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
    }
  }

  private var divider: some View {
    Rectangle()
      .fill(LFWidgetDesignV2.separator(scheme).opacity(0.72))
      .frame(height: 1)
  }
}
