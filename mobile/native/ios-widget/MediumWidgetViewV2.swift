import SwiftUI
import WidgetKit

struct LFMediumWidgetViewV2: View {
  @Environment(\.colorScheme) private var scheme
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      header
        .padding(.horizontal, 10)
        .padding(.top, 9)
        .padding(.bottom, 6)

      divider

      columnHeaders
        .padding(.horizontal, 10)
        .padding(.top, 4)
        .padding(.bottom, 2)

      divider

      rows

      Spacer(minLength: 0)
    }
    .lfWidgetBackground(scheme)
    .overlay(alignment: .top) {
      Rectangle()
        .fill(LFWidgetDesignV2.warmAccent(scheme).opacity(0.78))
        .frame(height: 3)
    }
  }

  private var header: some View {
    HStack(spacing: 8) {
      BeaconBMarkV2(
        tint: LFWidgetDesignV2.beaconBTint(scheme),
        cutout: LFWidgetDesignV2.beaconBCutout(scheme),
        size: 25
      )
      .opacity(scheme == .dark ? 0.78 : 0.66)

      VStack(alignment: .leading, spacing: 1) {
        Text(snapshot.airport.name)
          .font(LocalFlightWidgetFont.uiBold(size: 14))
          .lineLimit(1)
          .minimumScaleFactor(0.68)
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
        HStack(spacing: 5) {
          Text(snapshot.airport.code)
          Text("·")
          Text(snapshot.airport.view == "arrivals" ? "ARRIVALS" : "DEPARTURES")
        }
        .font(LocalFlightWidgetFont.boardBold(size: 8))
        .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
      }
      .frame(maxWidth: .infinity, alignment: .leading)

      VStack(alignment: .trailing, spacing: 2) {
        Text("Local Flight")
          .font(LocalFlightWidgetFont.brand(size: 11))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .foregroundStyle(LFWidgetDesignV2.textSecondary(scheme))
        Text(snapshot.source.lastUpdatedLabel.uppercased())
          .font(LocalFlightWidgetFont.boardBold(size: 7))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
          .foregroundStyle(snapshot.stale
            ? LFWidgetDesignV2.statusColor(tone: "delayed", scheme: scheme)
            : LFWidgetDesignV2.statusColor(tone: "boarding", scheme: scheme))
      }
      .frame(width: 82, alignment: .trailing)
    }
  }

  private var columnHeaders: some View {
    HStack(spacing: 0) {
      col("TIME", width: 42)
      col("FLIGHT", width: 54)
      col(snapshot.airport.view == "arrivals" ? "FROM" : "TO", flex: true)
      col("STATUS", width: 76)
      col("INFO", width: 34, trailing: true)
    }
    .font(LocalFlightWidgetFont.boardBold(size: 7))
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
    let displayRows = snapshot.medium.rows.prefix(
      min(LocalFlightWidgetConstants.maxMediumRowsWithPinned, snapshot.preferences.mediumRowCount + 1)
    )
    if displayRows.isEmpty {
      Text("Waiting for board data")
        .font(LocalFlightWidgetFont.uiBold(size: 13))
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
          .padding(.leading, isPinned ? 7 : 10)
          .padding(.trailing, 10)
          .padding(.vertical, 3)
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
          .font(LocalFlightWidgetFont.boardBold(size: isPinned ? 12 : 11))
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
          .lineLimit(1)
          .minimumScaleFactor(0.7)
        if isPinned {
          Text("PINNED")
            .font(LocalFlightWidgetFont.boardBold(size: 6))
            .foregroundStyle(LFWidgetDesignV2.warmAccent(scheme))
        }
      }
      .frame(width: 42, alignment: .leading)

      Text(flight.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: isPinned ? 12 : 11))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(LFWidgetDesignV2.textCyan(scheme))
      .frame(width: 54, alignment: .leading)

      VStack(alignment: .leading, spacing: 1) {
        Text(flight.routeName)
          .font(isPinned
            ? LocalFlightWidgetFont.uiBold(size: 11)
            : LocalFlightWidgetFont.uiBold(size: 10))
          .foregroundStyle(LFWidgetDesignV2.textPrimary(scheme))
          .lineLimit(1)
          .minimumScaleFactor(0.72)
        if !flight.routeCode.isEmpty {
          Text(flight.routeCode)
            .font(LocalFlightWidgetFont.boardBold(size: 6))
            .foregroundStyle(LFWidgetDesignV2.textMuted(scheme))
            .lineLimit(1)
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)

      LFStatusCapsuleV2(
        label: isPinned ? "PIN · \(flight.statusDisplay)" : flight.statusDisplay,
        tone: flight.statusTone,
        scheme: scheme
      )
      .scaleEffect(0.86)
      .frame(width: 76, alignment: .center)

      let info = showGate ? (flight.gate ?? flight.terminal ?? "") : ""
      Text(info.isEmpty ? "" : info.uppercased())
        .font(LocalFlightWidgetFont.boardBold(size: 8))
        .lineLimit(1)
        .minimumScaleFactor(0.7)
        .foregroundStyle(LFWidgetDesignV2.textDim(scheme))
        .frame(width: 34, alignment: .trailing)
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
        let slot = Path(roundedRect: CGRect(
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
