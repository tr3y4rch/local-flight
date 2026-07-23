import ActivityKit
import Foundation

private enum LocalFlightLiveActivityConstants {
  static let appGroupID = "group.cc.beacontools.localflight"
  static let snapshotFilename = "localflight-widget-snapshot.json"
  static let schemaVersion = 1
  static let maxSnapshotBytes = 64 * 1024
  static let statusTones: Set<String> = ["scheduled", "departed", "boarding", "delayed", "cancelled"]
}

private enum LocalFlightBridgeISO8601 {
  private static let fractional: ISO8601DateFormatter = {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return formatter
  }()

  private static let standard: ISO8601DateFormatter = {
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime]
    return formatter
  }()

  static func date(from value: String) -> Date? {
    fractional.date(from: value) ?? standard.date(from: value)
  }
}

@available(iOS 16.1, *)
public struct LocalFlightActivityAttributesV2: ActivityAttributes {
  public struct ContentState: Codable, Hashable {
    public var statusDisplay: String
    public var statusTone: String
    public var gate: String?
    public var gateLabel: String?
    public var stale: Bool
    public var lastUpdatedLabel: String
    public var appearance: String?
  }

  public let flightID: String
  public let flightDisplay: String
  public let direction: String
  public let routeName: String
  public let routeCode: String
  public let airportCode: String
  public let displayTime: String
}

private struct BridgeFlight: Decodable {
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
}

private struct BridgeAirport: Decodable {
  let code: String
}

private struct BridgeSource: Decodable {
  let lastUpdatedLabel: String
  let updatedAt: String?
}

private struct BridgePreferences: Decodable {
  let showGateTerminal: Bool?
  let liveActivityEnabled: Bool?
  let liveActivityAppearance: String?
}

private struct BridgeSmallSnapshot: Decodable {
  let source: String
  let flight: BridgeFlight?
}

private struct BridgeLiveActivitySnapshot: Decodable {
  let flight: BridgeFlight?
  let stale: Bool
}

private struct BridgeWidgetSnapshot: Decodable {
  let schemaVersion: Int
  let expiresAt: String
  let stale: Bool
  let airport: BridgeAirport
  let source: BridgeSource
  let preferences: BridgePreferences
  let small: BridgeSmallSnapshot
  let liveActivity: BridgeLiveActivitySnapshot
}

private extension String {
  func localFlightClean(max length: Int, fallback: String = "") -> String {
    let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
    let useful = trimmed == "-" ? "" : trimmed
    let value = useful.isEmpty ? fallback : useful
    return String(value.prefix(length))
  }
}

@available(iOS 16.1, *)
private struct LocalFlightLiveActivityInput {
  let attributes: LocalFlightActivityAttributesV2
  let state: LocalFlightActivityAttributesV2.ContentState
}

private enum LocalFlightLiveActivitySnapshotStore {
  static func load() -> BridgeWidgetSnapshot? {
    guard let url = FileManager.default
      .containerURL(forSecurityApplicationGroupIdentifier: LocalFlightLiveActivityConstants.appGroupID)?
      .appendingPathComponent(LocalFlightLiveActivityConstants.snapshotFilename)
    else {
      return nil
    }

    do {
      let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
      guard values.isRegularFile == true,
            let size = values.fileSize,
            size > 0,
            size <= LocalFlightLiveActivityConstants.maxSnapshotBytes
      else {
        return nil
      }
      let snapshot = try JSONDecoder().decode(BridgeWidgetSnapshot.self, from: Data(contentsOf: url))
      guard snapshot.schemaVersion == LocalFlightLiveActivityConstants.schemaVersion else {
        return nil
      }
      return snapshot
    } catch {
      return nil
    }
  }

  @available(iOS 16.1, *)
  static func input() -> LocalFlightLiveActivityInput? {
    guard let snapshot = load(),
          snapshot.preferences.liveActivityEnabled == true,
          snapshot.small.source == "pinned",
          let flight = snapshot.small.flight
    else {
      return nil
    }

    let flightID = flight.id.localFlightClean(max: 96)
    let flightDisplay = flight.flightDisplay.localFlightClean(max: 24, fallback: flightID)
    guard !flightDisplay.isEmpty else {
      return nil
    }
    let routeCode = flight.routeCode.localFlightClean(max: 8)
    let direction = flight.direction == "arr" ? "arr" : "dep"
    let statusTone = LocalFlightLiveActivityConstants.statusTones.contains(flight.statusTone)
      ? flight.statusTone
      : "scheduled"
    let expiry = LocalFlightBridgeISO8601.date(from: snapshot.expiresAt)
    let isStale = snapshot.stale
      || snapshot.liveActivity.stale
      || (expiry ?? .distantPast) <= Date()
    let terminalStatus = flight.statusDisplay.lowercased()
    let terminal = terminalStatus.contains("arriv")
      || terminalStatus.contains("departed")
      || terminalStatus.contains("cancel")
    if terminal,
       let updatedAt = snapshot.source.updatedAt.flatMap({ LocalFlightBridgeISO8601.date(from: $0) }),
       updatedAt.addingTimeInterval(2 * 60 * 60) <= Date() {
      return nil
    }
    let gate = flight.gate?.localFlightClean(max: 16)
    let terminalName = flight.terminal?.localFlightClean(max: 16)
    let visibleGate = gate?.isEmpty == false ? gate : nil
    let visibleTerminal = terminalName?.isEmpty == false ? terminalName : nil
    let showGateTerminal = snapshot.preferences.showGateTerminal != false
    let gateValue = showGateTerminal ? (visibleGate ?? visibleTerminal) : nil
    let gateLabel = showGateTerminal
      ? (visibleGate != nil ? "GATE" : (visibleTerminal != nil ? "TERM" : nil))
      : nil
    let appearance = ["light", "dark"].contains(snapshot.preferences.liveActivityAppearance ?? "")
      ? snapshot.preferences.liveActivityAppearance
      : "system"

    return LocalFlightLiveActivityInput(
      attributes: LocalFlightActivityAttributesV2(
        flightID: flightID.isEmpty ? flightDisplay : flightID,
        flightDisplay: flightDisplay,
        direction: direction,
        routeName: flight.routeName.localFlightClean(max: 64, fallback: "Flight route"),
        routeCode: routeCode,
        airportCode: snapshot.airport.code.localFlightClean(max: 8, fallback: "---"),
        displayTime: flight.displayTime.localFlightClean(max: 12, fallback: "--:--")
      ),
      state: LocalFlightActivityAttributesV2.ContentState(
        statusDisplay: flight.statusDisplay.localFlightClean(max: 20, fallback: "SCHEDULE"),
        statusTone: statusTone,
        gate: gateValue,
        gateLabel: gateLabel,
        stale: isStale,
        lastUpdatedLabel: snapshot.source.lastUpdatedLabel.localFlightClean(max: 32, fallback: "Updated"),
        appearance: appearance
      )
    )
  }
}

public enum LocalFlightLiveActivityBridge {
  public static func isSupported() -> [String: Any] {
    guard #available(iOS 16.1, *) else {
      return result(supported: false, enabled: false, active: false, action: "unsupported")
    }
    return LocalFlightLiveActivityManager.status()
  }

  public static func start() async -> [String: Any] {
    guard #available(iOS 16.1, *) else {
      return result(supported: false, enabled: false, active: false, action: "unsupported")
    }
    return await LocalFlightLiveActivityManager.start()
  }

  public static func update() async -> [String: Any] {
    guard #available(iOS 16.1, *) else {
      return result(supported: false, enabled: false, active: false, action: "unsupported")
    }
    return await LocalFlightLiveActivityManager.update()
  }

  public static func end() async -> [String: Any] {
    guard #available(iOS 16.1, *) else {
      return result(supported: false, enabled: false, active: false, action: "unsupported")
    }
    return await LocalFlightLiveActivityManager.end()
  }

  public static func reconcile() async -> [String: Any] {
    guard #available(iOS 16.1, *) else {
      return result(supported: false, enabled: false, active: false, action: "unsupported")
    }
    return await LocalFlightLiveActivityManager.reconcile()
  }

  fileprivate static func result(
    supported: Bool,
    enabled: Bool,
    active: Bool,
    action: String
  ) -> [String: Any] {
    [
      "supported": supported,
      "enabled": enabled,
      "active": active,
      "action": action,
    ]
  }
}

@available(iOS 16.1, *)
private enum LocalFlightLiveActivityManager {
  private typealias FlightActivity = Activity<LocalFlightActivityAttributesV2>

  static func status() -> [String: Any] {
    LocalFlightLiveActivityBridge.result(
      supported: true,
      enabled: ActivityAuthorizationInfo().areActivitiesEnabled,
      active: !FlightActivity.activities.isEmpty,
      action: "status"
    )
  }

  static func start() async -> [String: Any] {
    guard ActivityAuthorizationInfo().areActivitiesEnabled else {
      return response(action: "disabled")
    }
    guard let input = LocalFlightLiveActivitySnapshotStore.input() else {
      return response(action: "no_pinned_flight")
    }

    var keptActivity: FlightActivity?
    for activity in FlightActivity.activities {
      if keptActivity == nil && matches(activity.attributes, input.attributes) {
        keptActivity = activity
        await activity.update(using: input.state)
      } else {
        await finish(activity)
      }
    }
    if keptActivity != nil {
      return response(action: "updated")
    }

    do {
      // This activity is local-only. No push token is requested or handled.
      _ = try FlightActivity.request(
        attributes: input.attributes,
        contentState: input.state,
        pushType: nil
      )
      return response(action: "started")
    } catch {
      return response(action: "failed")
    }
  }

  static func update() async -> [String: Any] {
    guard let input = LocalFlightLiveActivitySnapshotStore.input() else {
      return response(action: "no_pinned_flight")
    }
    let matching = FlightActivity.activities.filter { matches($0.attributes, input.attributes) }
    guard !matching.isEmpty else {
      return response(action: "no_activity")
    }
    for activity in matching {
      await activity.update(using: input.state)
    }
    return response(action: "updated")
  }

  static func end() async -> [String: Any] {
    let activities = FlightActivity.activities
    for activity in activities {
      await finish(activity)
    }
    return response(action: activities.isEmpty ? "no_activity" : "ended")
  }

  static func reconcile() async -> [String: Any] {
    guard let input = LocalFlightLiveActivitySnapshotStore.input() else {
      return await end()
    }

    let hadActiveActivity = !FlightActivity.activities.isEmpty
    var matchingActivity: FlightActivity?
    for activity in FlightActivity.activities {
      if matchingActivity == nil && matches(activity.attributes, input.attributes) {
        matchingActivity = activity
        await activity.update(using: input.state)
      } else {
        await finish(activity)
      }
    }

    if matchingActivity != nil {
      return response(action: "updated")
    }
    // Replacing an existing activity after a new pin is allowed. Starting from
    // no activity is reserved for the explicit “Pin & show on Lock Screen”
    // bridge call, so a system/user dismissal is not silently resurrected by a
    // later widget snapshot write.
    return hadActiveActivity ? await start() : response(action: "no_activity")
  }

  private static func matches(
    _ lhs: LocalFlightActivityAttributesV2,
    _ rhs: LocalFlightActivityAttributesV2
  ) -> Bool {
    lhs.flightID == rhs.flightID
  }

  private static func finish(_ activity: FlightActivity) async {
    let finalState = LocalFlightActivityAttributesV2.ContentState(
      statusDisplay: "ENDED",
      statusTone: "scheduled",
      gate: nil,
      gateLabel: nil,
      stale: true,
      lastUpdatedLabel: "Ended",
      appearance: nil
    )
    await activity.end(using: finalState, dismissalPolicy: .immediate)
  }

  private static func response(action: String) -> [String: Any] {
    LocalFlightLiveActivityBridge.result(
      supported: true,
      enabled: ActivityAuthorizationInfo().areActivitiesEnabled,
      active: !FlightActivity.activities.isEmpty,
      action: action
    )
  }
}
