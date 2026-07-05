import SwiftUI
import WidgetKit

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
      LFSmallWidgetViewV2(snapshot: entry.snapshot)
    default:
      LFMediumWidgetViewV2(snapshot: entry.snapshot)
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
