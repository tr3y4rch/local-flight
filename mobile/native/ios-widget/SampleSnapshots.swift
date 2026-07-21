import Foundation

enum LocalFlightWidgetSamples {
  static let pinnedFlight = LocalFlightWidgetFlight(
    id: "LX2808",
    flightDisplay: "LX 2808",
    direction: "dep",
    routeName: "Geneva",
    routeCode: "GVA",
    displayTime: "17:10",
    statusDisplay: "DELAYED",
    statusTone: "delayed",
    gate: "A62",
    terminal: "1",
    pinned: true
  )

  static let liveRow = LocalFlightWidgetFlight(
    id: "LX1724",
    flightDisplay: "LX 1724",
    direction: "dep",
    routeName: "Bordeaux",
    routeCode: "BDS",
    displayTime: "17:10",
    statusDisplay: "SCHEDULE",
    statusTone: "scheduled",
    gate: "A64",
    terminal: nil,
    pinned: false
  )

  static func snapshot(
    pinned: Bool = true,
    stale: Bool = false,
    rows: [LocalFlightWidgetFlight] = [pinnedFlight, liveRow]
  ) -> LocalFlightWidgetSnapshot {
    let now = Date()
    let formatter = ISO8601DateFormatter()
    return LocalFlightWidgetSnapshot(
      schemaVersion: 1,
      generatedAt: formatter.string(from: now),
      expiresAt: formatter.string(from: now.addingTimeInterval(stale ? -60 : 15 * 60)),
      mode: "lan_companion",
      stale: stale,
      airport: LocalFlightWidgetAirport(code: "ZRH", name: "Zurich Airport", view: "departures"),
      source: LocalFlightWidgetSource(
        label: "relay",
        lastUpdatedLabel: stale ? "Stale" : "Updated now",
        updatedAt: formatter.string(from: now)
      ),
      preferences: LocalFlightWidgetPreferences(
        mediumRowCount: 3,
        showGateTerminal: true,
        automaticRefresh: true
      ),
      small: LocalFlightSmallWidgetSnapshot(source: pinned ? "pinned" : "empty", flight: pinned ? pinnedFlight : nil),
      medium: LocalFlightMediumWidgetSnapshot(rowCount: 3, rows: rows),
      liveActivity: LocalFlightLiveActivitySnapshot(flight: pinned ? pinnedFlight : nil, stale: stale || !pinned)
    )
  }

  static let noPinned = snapshot(pinned: false, rows: [liveRow])
  static let stalePinned = snapshot(pinned: true, stale: true)
  static let emptyBoard = snapshot(pinned: false, rows: [])
}
