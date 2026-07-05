import SwiftUI
import WidgetKit

struct LFSmallWidgetViewV2: View {
  @Environment(\.colorScheme) private var scheme
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    ZStack(alignment: .leading) {
      background
      content
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
    }
    .lfWidgetBackground(scheme)
  }

  private var background: some View {
    ZStack {
      scheme == .dark ? LFWidgetDesignV2.darkWidgetBg : LFWidgetDesignV2.lightWidgetBg

      GeometryReader { geo in
        let cx = geo.size.width * 0.92
        let cy = geo.size.height * 0.90
        ForEach([0.42, 0.30, 0.18] as [CGFloat], id: \.self) { radius in
          Circle()
            .stroke(
              scheme == .dark
                ? Color(red: 0.170, green: 0.929, blue: 0.976)
                : Color(red: 0.102, green: 0.475, blue: 0.663),
              lineWidth: 1
            )
            .opacity(Double(scheme == .dark ? 0.04 + radius * 0.06 : 0.05 + radius * 0.05))
            .frame(width: geo.size.width * radius * 2.4)
            .position(x: cx, y: cy)
        }
      }
      .allowsHitTesting(false)
    }
  }

  private var content: some View {
    VStack(alignment: .leading, spacing: 0) {
      header
      divider.padding(.vertical, 7)
      sectionLabel("PINNED FLIGHT")
      Spacer(minLength: 4)
      flightBody
      Spacer(minLength: 8)
      divider.padding(.bottom, 7)
      footer
    }
  }

  private var header: some View {
    HStack(alignment: .center, spacing: 0) {
      Text("\(snapshot.airport.code) · \(snapshot.airport.view == "arrivals" ? "ARRIVALS" : "DEPARTURES")")
        .font(LocalFlightWidgetFont.boardBold(size: 10))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
      Spacer()
      if let flight = snapshot.small.flight {
        LFStatusCapsuleV2(
          label: flight.statusDisplay,
          tone: flight.statusTone,
          scheme: scheme
        )
      }
    }
  }

  @ViewBuilder
  private var flightBody: some View {
    if let flight = snapshot.small.flight {
      Text(flight.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: 44))
        .minimumScaleFactor(0.62)
        .lineLimit(1)
        .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))

      Text(flight.routeName)
        .font(LocalFlightWidgetFont.uiBold(size: 19))
        .minimumScaleFactor(0.75)
        .lineLimit(1)
        .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        .padding(.top, 2)

      HStack(spacing: 4) {
        Text(snapshot.airport.code)
          .font(LocalFlightWidgetFont.boardBold(size: 12))
          .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
        Image(systemName: "arrow.right")
          .font(.system(size: 9, weight: .bold))
          .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
        if !flight.routeCode.isEmpty {
          Text(flight.routeCode)
            .font(LocalFlightWidgetFont.boardBold(size: 12))
            .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
        }
        Text("· \(flight.displayTime)")
          .font(LocalFlightWidgetFont.board(size: 12))
          .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
      }
      .lineLimit(1)
      .minimumScaleFactor(0.72)
      .padding(.top, 3)
    } else {
      Spacer()
      Text("Pin a flight")
        .font(LocalFlightWidgetFont.uiBold(size: 18))
        .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
      Text("in Local Flight")
        .font(LocalFlightWidgetFont.brand(size: 13))
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
      Spacer()
    }
  }

  private var footer: some View {
    HStack {
      if let flight = snapshot.small.flight,
         let gate = flight.gate, !gate.isEmpty {
        HStack(spacing: 4) {
          sectionLabel("GATE")
          Text(gate)
            .font(LocalFlightWidgetFont.boardBold(size: 15))
            .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        }
      }
      Spacer()
      Text(snapshot.source.lastUpdatedLabel.uppercased())
        .font(LocalFlightWidgetFont.boardBold(size: 8))
        .lineLimit(1)
        .minimumScaleFactor(0.75)
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
    }
  }

  private var divider: some View {
    Rectangle()
      .fill(LFWidgetDesignV2.separator(scheme))
      .frame(height: 1)
  }

  private func sectionLabel(_ text: String) -> some View {
    Text(text)
      .font(LocalFlightWidgetFont.boardBold(size: 8))
      .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
  }
}
