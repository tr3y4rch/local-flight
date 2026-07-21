import SwiftUI
import WidgetKit

struct LocalFlightTimelineEntry: TimelineEntry {
  let date: Date
  let snapshot: LocalFlightWidgetSnapshot
}

struct LocalFlightWidgetProvider: TimelineProvider {
  private func nextRefresh(for snapshot: LocalFlightWidgetSnapshot) -> Date {
    let fallback = Date().addingTimeInterval(15 * 60)
    guard let expiry = ISO8601DateFormatter().date(from: snapshot.expiresAt) else {
      return fallback
    }
    return min(max(expiry, Date().addingTimeInterval(5 * 60)), Date().addingTimeInterval(30 * 60))
  }

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
    completion(Timeline(entries: [entry], policy: .after(nextRefresh(for: entry.snapshot))))
  }
}

struct LocalFlightWidgetView: View {
  @Environment(\.widgetFamily) private var family
  let entry: LocalFlightTimelineEntry

  var body: some View {
    switch family {
    case .systemSmall:
      LFSmallWidgetViewV2(snapshot: entry.snapshot)
    default:
      LFMediumWidgetViewV2(snapshot: entry.snapshot)
    }
  }
}

struct LocalFlightWidget: Widget {
  let kind = "LocalFlightWidget"

  var body: some WidgetConfiguration {
    StaticConfiguration(kind: kind, provider: LocalFlightWidgetProvider()) { entry in
      LocalFlightWidgetView(entry: entry)
        .widgetURL(URL(string: "localflight://board?source=widget"))
    }
    .configurationDisplayName("Local Flight")
    .description("Pinned flight and airport board glance.")
    .supportedFamilies([.systemSmall, .systemMedium])
    .contentMarginsDisabled()
  }
}

@main
struct LocalFlightWidgetBundle: WidgetBundle {
  @WidgetBundleBuilder
  var body: some Widget {
    LocalFlightWidget()
    if #available(iOSApplicationExtension 16.1, *) {
      LocalFlightLiveActivityWidget()
    }
  }
}
