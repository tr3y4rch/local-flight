import CoreText
import SwiftUI
import WidgetKit

private enum LocalFlightWidgetFont {
  private static let registeredBundledFonts: Void = {
    for name in ["Audiowide-Regular", "SpaceMono-Regular", "SpaceMono-Bold", "DMSans"] {
      guard let url = Bundle.main.url(forResource: name, withExtension: "ttf", subdirectory: "Fonts")
        ?? Bundle.main.url(forResource: name, withExtension: "ttf")
      else {
        continue
      }
      _ = CTFontManagerRegisterFontsForURL(url as CFURL, .process, nil)
    }
  }()

  static func registerBundledFonts() {
    _ = registeredBundledFonts
  }

  static func brand(size: CGFloat) -> Font {
    registerBundledFonts()
    return .custom("Audiowide-Regular", size: size)
  }

  static func board(size: CGFloat) -> Font {
    registerBundledFonts()
    return .custom("SpaceMono-Regular", size: size)
  }

  static func boardBold(size: CGFloat) -> Font {
    registerBundledFonts()
    return .custom("SpaceMono-Bold", size: size)
  }

  static func ui(size: CGFloat) -> Font {
    registerBundledFonts()
    return .custom("DMSans-9ptRegular_Regular", size: size)
  }

  static func uiBold(size: CGFloat) -> Font {
    registerBundledFonts()
    return .custom("DMSans-9ptRegular_Bold", size: size)
  }
}

struct LocalFlightTimelineEntry: TimelineEntry {
  let date: Date
  let snapshot: LocalFlightWidgetSnapshot
}

struct LocalFlightWidgetProvider: TimelineProvider {
  func placeholder(in context: Context) -> LocalFlightTimelineEntry {
    LocalFlightTimelineEntry(date: Date(), snapshot: LocalFlightWidgetSnapshotStore.placeholder)
  }

  func getSnapshot(in context: Context, completion: @escaping (LocalFlightTimelineEntry) -> Void) {
    completion(LocalFlightTimelineEntry(
      date: Date(),
      snapshot: LocalFlightWidgetSnapshotStore.load() ?? LocalFlightWidgetSnapshotStore.placeholder
    ))
  }

  func getTimeline(in context: Context, completion: @escaping (Timeline<LocalFlightTimelineEntry>) -> Void) {
    let entry = LocalFlightTimelineEntry(
      date: Date(),
      snapshot: LocalFlightWidgetSnapshotStore.load() ?? LocalFlightWidgetSnapshotStore.placeholder
    )
    completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(5 * 60))))
  }
}

struct LocalFlightWidgetView: View {
  @Environment(\.widgetFamily) private var family
  let entry: LocalFlightTimelineEntry

  var body: some View {
    switch family {
    case .systemSmall:
      LocalFlightSmallWidgetView(snapshot: entry.snapshot)
    default:
      LocalFlightMediumWidgetView(snapshot: entry.snapshot)
    }
  }
}

struct LocalFlightSmallWidgetView: View {
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Text(snapshot.airport.code)
          .font(LocalFlightWidgetFont.boardBold(size: 11))
          .foregroundStyle(.cyan)
        Spacer()
        Text(snapshot.airport.view == "arrivals" ? "ARR" : "DEP")
          .font(LocalFlightWidgetFont.boardBold(size: 10))
          .foregroundStyle(.secondary)
      }
      if let flight = snapshot.small.flight {
        Text(flight.flightDisplay)
          .font(LocalFlightWidgetFont.boardBold(size: 28))
          .lineLimit(1)
          .minimumScaleFactor(0.72)
        Text("\(flight.displayTime) · \(flight.routeCode.isEmpty ? flight.routeName : flight.routeCode)")
          .font(LocalFlightWidgetFont.ui(size: 12))
          .foregroundStyle(.secondary)
          .lineLimit(1)
        LocalFlightStatusBadge(flight: flight)
      } else {
        Spacer()
        Text("Pin a flight")
          .font(LocalFlightWidgetFont.uiBold(size: 16))
        Text("in Local Flight")
          .font(LocalFlightWidgetFont.brand(size: 11))
          .foregroundStyle(.secondary)
      }
      Spacer(minLength: 0)
    }
    .padding(14)
    .localFlightWidgetBackground()
  }
}

struct LocalFlightMediumWidgetView: View {
  let snapshot: LocalFlightWidgetSnapshot

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(alignment: .center, spacing: 10) {
        Text("B")
          .font(.system(size: 34, weight: .black, design: .rounded))
          .foregroundStyle(.cyan.opacity(0.16))
          .frame(width: 36, alignment: .leading)
        VStack(alignment: .center, spacing: 3) {
          Text(snapshot.airport.name)
            .font(LocalFlightWidgetFont.uiBold(size: 14))
            .lineLimit(1)
            .minimumScaleFactor(0.72)
          Text(snapshot.airport.view == "arrivals" ? "ARRIVALS" : "DEPARTURES")
            .font(LocalFlightWidgetFont.boardBold(size: 10))
            .foregroundStyle(.cyan)
        }
        Spacer()
        VStack(alignment: .trailing, spacing: 3) {
          Text("Local Flight")
            .font(LocalFlightWidgetFont.brand(size: 15))
            .tracking(1)
            .lineLimit(1)
            .minimumScaleFactor(0.68)
          Text(snapshot.source.lastUpdatedLabel.uppercased())
            .font(LocalFlightWidgetFont.boardBold(size: 9))
            .foregroundStyle(snapshot.stale ? .yellow : .green)
        }
      }
      Divider().overlay(.cyan.opacity(0.2))
      HStack {
        Text("TIME").frame(width: 52, alignment: .leading)
        Text("FLIGHT").frame(width: 64, alignment: .leading)
        Text(snapshot.airport.view == "arrivals" ? "FROM" : "TO").frame(maxWidth: .infinity, alignment: .leading)
        Text("STATUS").frame(width: 72, alignment: .trailing)
      }
      .font(LocalFlightWidgetFont.boardBold(size: 9))
      .foregroundStyle(.cyan.opacity(0.75))
      ForEach(snapshot.medium.rows.prefix(snapshot.preferences.mediumRowCount + 1)) { flight in
        LocalFlightMediumRow(flight: flight)
      }
      if snapshot.medium.rows.isEmpty {
        Text("Waiting for board data")
          .font(LocalFlightWidgetFont.uiBold(size: 16))
          .foregroundStyle(.secondary)
          .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
      }
      Spacer(minLength: 0)
    }
    .padding(14)
    .localFlightWidgetBackground()
  }
}

struct LocalFlightMediumRow: View {
  let flight: LocalFlightWidgetFlight

  var body: some View {
    HStack(spacing: 8) {
      Text(flight.displayTime)
        .font(LocalFlightWidgetFont.boardBold(size: flight.pinned == true ? 14 : 13))
        .frame(width: 52, alignment: .leading)
      Text(flight.flightDisplay)
        .font(LocalFlightWidgetFont.boardBold(size: flight.pinned == true ? 14 : 13))
        .frame(width: 64, alignment: .leading)
      Text(flight.routeCode.isEmpty ? flight.routeName : flight.routeCode)
        .font(LocalFlightWidgetFont.uiBold(size: flight.pinned == true ? 14 : 13))
        .frame(maxWidth: .infinity, alignment: .leading)
        .lineLimit(1)
      LocalFlightStatusBadge(flight: flight)
        .frame(width: 72, alignment: .trailing)
    }
    .padding(.vertical, flight.pinned == true ? 6 : 4)
  }
}

struct LocalFlightStatusBadge: View {
  let flight: LocalFlightWidgetFlight

  var body: some View {
    Text(flight.statusDisplay.uppercased())
      .font(LocalFlightWidgetFont.boardBold(size: 10))
      .lineLimit(1)
      .minimumScaleFactor(0.72)
      .padding(.horizontal, 7)
      .padding(.vertical, 4)
      .foregroundStyle(LocalFlightWidgetStyle.statusColor(flight.statusTone))
      .background(LocalFlightWidgetStyle.statusColor(flight.statusTone).opacity(0.16), in: Capsule())
  }
}

enum LocalFlightWidgetStyle {
  static let background = LinearGradient(
    colors: [Color(red: 0.03, green: 0.07, blue: 0.11), Color(red: 0.07, green: 0.12, blue: 0.17)],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static func statusColor(_ tone: String) -> Color {
    switch tone {
    case "departed", "boarding":
      return .green
    case "delayed":
      return .yellow
    case "cancelled":
      return .red
    default:
      return .cyan
    }
  }
}

extension View {
  @ViewBuilder
  func localFlightWidgetBackground() -> some View {
    if #available(iOSApplicationExtension 17.0, *) {
      self.containerBackground(LocalFlightWidgetStyle.background, for: .widget)
    } else {
      self.background(LocalFlightWidgetStyle.background)
    }
  }
}

@main
struct LocalFlightWidget: Widget {
  let kind = "LocalFlightWidget"

  var body: some WidgetConfiguration {
    StaticConfiguration(kind: kind, provider: LocalFlightWidgetProvider()) { entry in
      LocalFlightWidgetView(entry: entry)
    }
    .configurationDisplayName("Local Flight")
    .description("Pinned flight and airport board glance.")
    .supportedFamilies([.systemSmall, .systemMedium])
  }
}
