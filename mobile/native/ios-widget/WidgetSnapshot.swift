import Foundation

enum LocalFlightWidgetConstants {
  static let appGroupID = "group.cc.beacontools.localflight"
  static let snapshotFilename = "localflight-widget-snapshot.json"
  static let schemaVersion = 1
  static let maxSnapshotBytes = 64 * 1024
  static let maxMediumRowsWithPinned = 4
  static let statusTones: Set<String> = ["scheduled", "departed", "boarding", "delayed", "cancelled"]
}

struct LocalFlightWidgetFlight: Codable, Identifiable {
  let id: String
  let flightDisplay: String
  let direction: String
  let routeName: String
  let routeCode: String
  let displayTime: String
  let statusDisplay: String
  let statusTone: String
  let gate: String?
  let terminal: String?
  let pinned: Bool?
}

struct LocalFlightWidgetAirport: Codable {
  let code: String
  let name: String
  let view: String
}

struct LocalFlightWidgetSource: Codable {
  let label: String
  let lastUpdatedLabel: String
  let updatedAt: String?
}

struct LocalFlightWidgetPreferences: Codable {
  let mediumRowCount: Int
  let showGateTerminal: Bool
  let automaticRefresh: Bool?
}

struct LocalFlightSmallWidgetSnapshot: Codable {
  let source: String
  let flight: LocalFlightWidgetFlight?
}

struct LocalFlightMediumWidgetSnapshot: Codable {
  let rowCount: Int
  let rows: [LocalFlightWidgetFlight]
}

struct LocalFlightLiveActivitySnapshot: Codable {
  let flight: LocalFlightWidgetFlight?
  let stale: Bool
}

struct LocalFlightWidgetSnapshot: Codable {
  let schemaVersion: Int
  let generatedAt: String
  let expiresAt: String
  let mode: String
  let stale: Bool
  let airport: LocalFlightWidgetAirport
  let source: LocalFlightWidgetSource
  let preferences: LocalFlightWidgetPreferences
  let small: LocalFlightSmallWidgetSnapshot
  let medium: LocalFlightMediumWidgetSnapshot
  let liveActivity: LocalFlightLiveActivitySnapshot
}

enum LocalFlightWidgetSnapshotStore {
  static func snapshotURL() -> URL? {
    FileManager.default
      .containerURL(forSecurityApplicationGroupIdentifier: LocalFlightWidgetConstants.appGroupID)?
      .appendingPathComponent(LocalFlightWidgetConstants.snapshotFilename)
  }

  static func load() -> LocalFlightWidgetSnapshot? {
    guard let url = snapshotURL() else {
      return nil
    }
    do {
      let resourceValues = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
      guard resourceValues.isRegularFile == true,
            let fileSize = resourceValues.fileSize,
            fileSize > 0,
            fileSize <= LocalFlightWidgetConstants.maxSnapshotBytes else {
        return nil
      }
      let data = try Data(contentsOf: url)
      let snapshot = try JSONDecoder().decode(LocalFlightWidgetSnapshot.self, from: data)
      guard snapshot.schemaVersion == LocalFlightWidgetConstants.schemaVersion else {
        return nil
      }
      return snapshot.sanitized()
    } catch {
      return nil
    }
  }

  static var placeholder: LocalFlightWidgetSnapshot {
    let airport = LocalFlightWidgetAirport(code: "---", name: "Local Flight Airport", view: "departures")
    let source = LocalFlightWidgetSource(
      label: "mobile",
      lastUpdatedLabel: "Waiting",
      updatedAt: ISO8601DateFormatter().string(from: Date())
    )
    let preferences = LocalFlightWidgetPreferences(
      mediumRowCount: 3,
      showGateTerminal: true,
      automaticRefresh: true
    )
    return LocalFlightWidgetSnapshot(
      schemaVersion: 1,
      generatedAt: ISO8601DateFormatter().string(from: Date()),
      expiresAt: ISO8601DateFormatter().string(from: Date().addingTimeInterval(15 * 60)),
      mode: "lan_companion",
      stale: true,
      airport: airport,
      source: source,
      preferences: preferences,
      small: LocalFlightSmallWidgetSnapshot(source: "empty", flight: nil),
      medium: LocalFlightMediumWidgetSnapshot(rowCount: 3, rows: []),
      liveActivity: LocalFlightLiveActivitySnapshot(flight: nil, stale: true)
    )
  }
}

private extension String {
  func lfClean(max length: Int, fallback: String = "") -> String {
    let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
    let useful = trimmed == "-" ? "" : trimmed
    let value = useful.isEmpty ? fallback : useful
    return String(value.prefix(length))
  }
}

private extension LocalFlightWidgetFlight {
  func sanitized(pinned pinnedOverride: Bool? = nil) -> LocalFlightWidgetFlight? {
    let cleanID = id.lfClean(max: 96)
    let cleanFlight = flightDisplay.lfClean(max: 24, fallback: cleanID)
    guard !cleanFlight.isEmpty else {
      return nil
    }
    let cleanTone = LocalFlightWidgetConstants.statusTones.contains(statusTone) ? statusTone : "scheduled"
    return LocalFlightWidgetFlight(
      id: cleanID.isEmpty ? cleanFlight : cleanID,
      flightDisplay: cleanFlight,
      direction: direction == "arr" ? "arr" : "dep",
      routeName: routeName.lfClean(max: 64, fallback: "-"),
      routeCode: routeCode.lfClean(max: 8),
      displayTime: displayTime.lfClean(max: 12, fallback: "--:--"),
      statusDisplay: statusDisplay.lfClean(max: 20, fallback: "SCHEDULE"),
      statusTone: cleanTone,
      gate: gate?.lfClean(max: 16),
      terminal: terminal?.lfClean(max: 16),
      pinned: pinnedOverride ?? pinned
    )
  }
}

private extension LocalFlightWidgetSnapshot {
  var isExpired: Bool {
    guard let expires = ISO8601DateFormatter().date(from: expiresAt) else {
      return true
    }
    return expires <= Date()
  }

  func sanitized() -> LocalFlightWidgetSnapshot? {
    guard schemaVersion == LocalFlightWidgetConstants.schemaVersion,
          ISO8601DateFormatter().date(from: generatedAt) != nil else {
      return nil
    }
    let rowCount = preferences.mediumRowCount == 2 ? 2 : 3
    let pinnedFlight = small.source == "pinned" ? small.flight?.sanitized(pinned: true) : nil
    let rows = medium.rows
      .compactMap { flight in flight.sanitized(pinned: flight.pinned == true) }
      .prefix(min(LocalFlightWidgetConstants.maxMediumRowsWithPinned, rowCount + 1))
    let staleSnapshot = stale || isExpired
    let sanitizedPreferences = LocalFlightWidgetPreferences(
      mediumRowCount: rowCount,
      showGateTerminal: preferences.showGateTerminal,
      automaticRefresh: preferences.automaticRefresh ?? true
    )
    return LocalFlightWidgetSnapshot(
      schemaVersion: LocalFlightWidgetConstants.schemaVersion,
      generatedAt: generatedAt,
      expiresAt: ISO8601DateFormatter().date(from: expiresAt) == nil
        ? ISO8601DateFormatter().string(from: Date())
        : expiresAt,
      mode: mode == "standalone" ? "standalone" : "lan_companion",
      stale: staleSnapshot,
      airport: LocalFlightWidgetAirport(
        code: airport.code.lfClean(max: 8, fallback: "---"),
        name: airport.name.lfClean(max: 80, fallback: "Local Flight Airport"),
        view: airport.view == "arrivals" ? "arrivals" : "departures"
      ),
      source: LocalFlightWidgetSource(
        label: source.label.lfClean(max: 32, fallback: "mobile"),
        lastUpdatedLabel: source.lastUpdatedLabel.lfClean(max: 32, fallback: "Waiting"),
        updatedAt: source.updatedAt
      ),
      preferences: sanitizedPreferences,
      small: LocalFlightSmallWidgetSnapshot(
        source: pinnedFlight == nil ? "empty" : "pinned",
        flight: pinnedFlight
      ),
      medium: LocalFlightMediumWidgetSnapshot(
        rowCount: rowCount,
        rows: Array(rows)
      ),
      liveActivity: LocalFlightLiveActivitySnapshot(
        flight: pinnedFlight,
        stale: liveActivity.stale || staleSnapshot || pinnedFlight == nil
      )
    )
  }
}
