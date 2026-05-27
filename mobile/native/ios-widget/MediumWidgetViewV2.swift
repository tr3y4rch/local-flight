import SwiftUI
import WidgetKit

struct LFMediumWidgetViewV2: View {
  @Environment(\.colorScheme) private var scheme
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      header
        .padding(.horizontal, 14)
        .padding(.top, 14)
        .padding(.bottom, 8)

      divider

      columnHeaders
        .padding(.horizontal, 14)
        .padding(.top, 7)
        .padding(.bottom, 3)

      divider

      rows

      Spacer(minLength: 0)
    }
    .lfWidgetBackground(scheme)
  }

  private var header: some View {
    HStack(spacing: 10) {
      BeaconBMarkV2(
        tint: LFWidgetDesignV2.beaconBTint(scheme),
        cutout: LFWidgetDesignV2.beaconBCutout(scheme),
        size: 36
      )
      .opacity(scheme == .dark ? 0.38 : 0.28)

      Spacer(minLength: 8)

      VStack(alignment: .center, spacing: 5) {
        Text(snapshot.airport.name)
          .font(LocalFlightWidgetFont.uiBold(size: 16))
          .lineLimit(1)
          .minimumScaleFactor(0.75)
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        Text(snapshot.airport.view == "arrivals" ? "ARRIVALS" : "DEPARTURES")
          .font(LocalFlightWidgetFont.boardBold(size: 9))
          .tracking(2)
          .foregroundStyle(LFWidgetDesignV2.textCyan(scheme))
          .padding(.horizontal, 14)
          .padding(.vertical, 5)
          .background(
            LFWidgetDesignV2.textCyan(scheme).opacity(scheme == .dark ? 0.10 : 0.08),
            in: Capsule()
          )
          .overlay(
            Capsule()
              .stroke(LFWidgetDesignV2.textCyan(scheme).opacity(0.35), lineWidth: 1)
          )
      }
      .frame(maxWidth: .infinity)

      Spacer(minLength: 8)

      VStack(alignment: .trailing, spacing: 5) {
        Text("Local Flight")
          .font(LocalFlightWidgetFont.brand(size: 15))
          .tracking(0.6)
          .lineLimit(1)
          .minimumScaleFactor(0.62)
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        Text(snapshot.source.lastUpdatedLabel.uppercased())
          .font(LocalFlightWidgetFont.boardBold(size: 9))
          .tracking(1.5)
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .foregroundStyle(snapshot.stale
            ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: scheme)
            : LFWidgetDesignV2.statusColor(tone: "boarding", scheme: scheme))
      }
      .frame(width: 98, alignment: .trailing)
    }
  }

  private var columnHeaders: some View {
    HStack(spacing: 0) {
      col("TIME", width: 52)
      col("FLIGHT", width: 64)
      col(snapshot.airport.view == "arrivals" ? "FROM" : "TO", flex: true)
      col("STATUS", width: 102)
      col("INFO", width: 44, trailing: true)
    }
    .font(LocalFlightWidgetFont.boardBold(size: 8))
    .tracking(2)
    .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
  }

  private func col(
    _ label: String,
    width: CGFloat? = nil,
    flex: Bool = false,
    trailing: Bool = false
  ) -> some View {
    let alignment: Alignment = trailing ? .trailing : .leading
    return Group {
      if let width {
        Text(label).frame(width: width, alignment: alignment)
      } else {
        Text(label).frame(maxWidth: .infinity, alignment: .leading)
      }
    }
  }

  @ViewBuilder
  private var rows: some View {
    let displayRows = snapshot.medium.rows.prefix(snapshot.preferences.mediumRowCount + 1)
    if displayRows.isEmpty {
      Text("Waiting for board data")
        .font(LocalFlightWidgetFont.uiBold(size: 14))
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    } else {
      ForEach(displayRows) { flight in
        LFMediumRowV2(
          flight: flight,
          showGate: snapshot.preferences.showGateTerminal,
          scheme: scheme
        )
        divider.opacity(0.55)
      }
    }
  }

  private var divider: some View {
    Rectangle()
      .fill(LFWidgetDesignV2.separator(scheme))
      .frame(height: 1)
  }
}

struct LFMediumRowV2: View {
  let flight: LocalFlightWidgetFlight
  let showGate: Bool
  let scheme: ColorScheme

  private var isPinned: Bool { flight.pinned == true }

  var body: some View {
    ZStack(alignment: .leading) {
      rowBackground

      HStack(spacing: 0) {
        if isPinned {
          Rectangle()
            .fill(scheme == .dark
              ? LFWidgetDesignV2.amberAccentBar
              : LFWidgetDesignV2.lightAmberAccentBar)
            .frame(width: 3)
        }

        content
          .padding(.leading, isPinned ? 10 : 14)
          .padding(.trailing, 14)
          .padding(.vertical, isPinned ? 8 : 5)
      }
    }
  }

  private var rowBackground: some View {
    Group {
      if isPinned {
        (scheme == .dark ? LFWidgetDesignV2.darkPinnedBg : LFWidgetDesignV2.lightPinnedBg)
          .overlay(alignment: .top) {
            Rectangle()
              .fill(LFWidgetDesignV2.pinnedBorderColor(scheme).opacity(0.55))
              .frame(height: 1)
          }
          .overlay(alignment: .bottom) {
            Rectangle()
              .fill(LFWidgetDesignV2.pinnedBorderColor(scheme).opacity(0.55))
              .frame(height: 1)
          }
      } else {
        scheme == .dark ? LFWidgetDesignV2.darkRowBg : LFWidgetDesignV2.lightRowBg
      }
    }
  }

  private var content: some View {
    HStack(spacing: 0) {
      VStack(alignment: .leading, spacing: 1) {
        Text(flight.displayTime)
          .font(LocalFlightWidgetFont.boardBold(size: isPinned ? 15 : 14))
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
        if isPinned {
          Text("PINNED")
            .font(LocalFlightWidgetFont.boardBold(size: 7))
            .tracking(1.8)
            .foregroundStyle(scheme == .dark
              ? Color(red: 0.953, green: 0.722, blue: 0.207)
              : Color(red: 0.541, green: 0.376, blue: 0.000))
        }
      }
      .frame(width: 52, alignment: .leading)

      Text(flight.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: isPinned ? 15 : 13))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(LFWidgetDesignV2.textCyan(scheme))
        .frame(width: 64, alignment: .leading)

      VStack(alignment: .leading, spacing: 1) {
        Text(flight.routeName)
          .font(isPinned
            ? LocalFlightWidgetFont.uiBold(size: 14)
            : LocalFlightWidgetFont.uiBold(size: 13))
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
          .lineLimit(1)
          .minimumScaleFactor(0.72)
        if !flight.routeCode.isEmpty {
          Text(flight.routeCode)
            .font(LocalFlightWidgetFont.boardBold(size: 8))
            .tracking(0.5)
            .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
            .lineLimit(1)
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)

      LFStatusCapsuleV2(
        label: flight.statusDisplay,
        tone: flight.statusTone,
        scheme: scheme
      )
      .frame(width: 102, alignment: .center)

      let info = showGate ? (flight.gate ?? flight.terminal ?? "") : ""
      Text(info.isEmpty ? "" : info.uppercased())
        .font(LocalFlightWidgetFont.boardBold(size: 11))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
        .frame(width: 44, alignment: .trailing)
    }
  }
}

struct BeaconBMarkV2: View {
  let tint: Color
  let cutout: Color
  var size: CGFloat = 44

  private let origW: CGFloat = 856
  private let origH: CGFloat = 922

  var body: some View {
    Canvas { ctx, sz in
      let sx = sz.width / origW
      let sy = sz.height / origH

      func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
        CGPoint(x: (x - 84) * sx, y: (y - 52) * sy)
      }

      var spine = Path()
      spine.move(to: pt(140, 52))
      spine.addLine(to: pt(460, 52))
      spine.addLine(to: pt(460, 974))
      spine.addLine(to: pt(140, 974))
      spine.closeSubpath()
      ctx.fill(spine, with: .color(tint))

      var bowl = Path()
      bowl.move(to: pt(84, 108))
      bowl.addCurve(to: pt(772, 318), control1: pt(610, 78), control2: pt(812, 158))
      bowl.addCurve(to: pt(458, 493), control1: pt(748, 420), control2: pt(611, 486))
      bowl.addCurve(to: pt(822, 724), control1: pt(690, 505), control2: pt(856, 585))
      bowl.addCurve(to: pt(436, 974), control1: pt(774, 920), control2: pt(558, 985))
      bowl.addLine(to: pt(310, 974))
      bowl.addLine(to: pt(310, 52))
      bowl.addLine(to: pt(436, 52))
      bowl.addCurve(to: pt(84, 108), control1: pt(300, 42), control2: pt(175, 58))
      bowl.closeSubpath()
      ctx.fill(bowl, with: .color(tint))

      for y in [180, 300, 650, 770] as [CGFloat] {
        var slot = Path(roundedRect: CGRect(
          x: pt(190, y).x,
          y: pt(190, y).y,
          width: 145 * sx,
          height: 82 * sy
        ), cornerRadius: 6 * min(sx, sy))
        ctx.fill(slot, with: .color(cutout))
      }

      var cut = Path()
      cut.addEllipse(in: CGRect(
        x: pt(440, 180).x,
        y: pt(440, 180).y,
        width: 255 * sx,
        height: 255 * sy
      ))
      cut.addEllipse(in: CGRect(
        x: pt(440, 610).x,
        y: pt(440, 610).y,
        width: 295 * sx,
        height: 295 * sy
      ))
      ctx.fill(cut, with: .color(cutout))
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}
