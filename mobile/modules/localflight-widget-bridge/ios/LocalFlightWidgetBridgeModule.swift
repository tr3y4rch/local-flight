import ExpoModulesCore
import Foundation
import UIKit
import WidgetKit

private enum LocalFlightWidgetProbe {
  static let appGroupID = "group.cc.beacontools.localflight"
  static let filename = "localflight-widget-snapshot.json"
  static let expectedSchema = 1
  static let maximumBytes = 64 * 1024
  static let reloadKey = "localflight.widget.lastReloadRequest"

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

  static func string(from date: Date) -> String {
    fractional.string(from: date)
  }

  static func date(from value: Any?) -> Date? {
    guard let text = value as? String else {
      return nil
    }
    return fractional.date(from: text) ?? standard.date(from: text)
  }

  static func recordReload() {
    UserDefaults(suiteName: appGroupID)?.set(string(from: Date()), forKey: reloadKey)
  }

  static func write(json: String) -> [String: Any] {
    guard let container = FileManager.default.containerURL(
      forSecurityApplicationGroupIdentifier: appGroupID
    ) else {
      return result(
        appGroupAvailable: false,
        decodeResult: "app_group_unavailable",
        lastReload: UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
      )
    }
    guard let data = json.data(using: .utf8), !data.isEmpty, data.count <= maximumBytes else {
      return result(
        appGroupAvailable: true,
        byteCount: json.utf8.count,
        decodeResult: json.utf8.count > maximumBytes ? "too_large" : "invalid_json",
        lastReload: UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
      )
    }
    do {
      guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return result(
          appGroupAvailable: true,
          byteCount: data.count,
          decodeResult: "invalid_json",
          lastReload: UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
        )
      }
      guard root["schemaVersion"] as? Int == expectedSchema else {
        return result(
          appGroupAvailable: true,
          byteCount: data.count,
          decodeResult: "schema_mismatch",
          lastReload: UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
        )
      }
      guard date(from: root["generatedAt"]) != nil, date(from: root["expiresAt"]) != nil else {
        return result(
          appGroupAvailable: true,
          byteCount: data.count,
          decodeResult: "invalid_timestamp",
          lastReload: UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
        )
      }
      try data.write(to: container.appendingPathComponent(filename), options: .atomic)
      return inspect()
    } catch {
      return result(
        appGroupAvailable: true,
        byteCount: data.count,
        decodeResult: "write_failed",
        lastReload: UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
      )
    }
  }

  static func inspect() -> [String: Any] {
    let lastReload = UserDefaults(suiteName: appGroupID)?.string(forKey: reloadKey) ?? ""
    guard let container = FileManager.default.containerURL(
      forSecurityApplicationGroupIdentifier: appGroupID
    ) else {
      return result(
        appGroupAvailable: false,
        decodeResult: "app_group_unavailable",
        lastReload: lastReload
      )
    }

    let url = container.appendingPathComponent(filename)
    guard FileManager.default.fileExists(atPath: url.path) else {
      return result(
        appGroupAvailable: true,
        decodeResult: "missing",
        lastReload: lastReload
      )
    }

    do {
      let values = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
      let byteCount = values.fileSize ?? 0
      guard values.isRegularFile == true, byteCount > 0, byteCount <= maximumBytes else {
        return result(
          appGroupAvailable: true,
          byteCount: byteCount,
          decodeResult: byteCount > maximumBytes ? "too_large" : "invalid_file",
          lastReload: lastReload
        )
      }
      let data = try Data(contentsOf: url)
      guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        return result(
          appGroupAvailable: true,
          byteCount: byteCount,
          decodeResult: "invalid_json",
          lastReload: lastReload
        )
      }
      let schema = root["schemaVersion"] as? Int
      let generatedAt = root["generatedAt"] as? String ?? ""
      let expiresAt = root["expiresAt"] as? String
      let medium = root["medium"] as? [String: Any]
      let rows = medium?["rows"] as? [Any] ?? []
      let small = root["small"] as? [String: Any]
      let pinPresent = (small?["source"] as? String) == "pinned"
        && (small?["flight"] as? [String: Any]) != nil
      let decodeResult: String
      if schema != expectedSchema {
        decodeResult = "schema_mismatch"
      } else if date(from: generatedAt) == nil || date(from: expiresAt) == nil {
        decodeResult = "invalid_timestamp"
      } else {
        decodeResult = "ok"
      }
      return result(
        appGroupAvailable: true,
        schemaVersion: schema,
        byteCount: byteCount,
        generatedAt: generatedAt,
        rowCount: rows.count,
        pinPresent: pinPresent,
        decodeResult: decodeResult,
        lastReload: lastReload
      )
    } catch {
      return result(
        appGroupAvailable: true,
        decodeResult: "read_failed",
        lastReload: lastReload
      )
    }
  }

  private static func result(
    appGroupAvailable: Bool,
    schemaVersion: Int? = nil,
    byteCount: Int = 0,
    generatedAt: String = "",
    rowCount: Int = 0,
    pinPresent: Bool = false,
    decodeResult: String,
    lastReload: String
  ) -> [String: Any] {
    [
      "appGroupAvailable": appGroupAvailable,
      "schemaVersion": schemaVersion ?? 0,
      "byteCount": byteCount,
      "generatedAt": generatedAt,
      "rowCount": rowCount,
      "pinPresent": pinPresent,
      "decodeResult": decodeResult,
      "lastReloadRequest": lastReload
    ]
  }
}

public final class LocalFlightWidgetBridgeModule: Module {
  public func definition() -> ModuleDefinition {
    Name("LocalFlightWidgetBridge")

    View(LocalFlightShortcutView.self) {
      ViewName("LocalFlightShortcutView")
      Events("onShortcut")
    }

    AsyncFunction("reload") { () -> [String: Any] in
      WidgetCenter.shared.reloadTimelines(ofKind: "LocalFlightWidget")
      LocalFlightWidgetProbe.recordReload()
      return ["available": true]
    }

    AsyncFunction("probeSnapshot") { () -> [String: Any] in
      LocalFlightWidgetProbe.inspect()
    }

    AsyncFunction("writeSnapshot") { (json: String) -> [String: Any] in
      LocalFlightWidgetProbe.write(json: json)
    }

    AsyncFunction("isSupported") { () -> [String: Any] in
      LocalFlightLiveActivityBridge.isSupported()
    }

    AsyncFunction("startLiveActivity") { () async -> [String: Any] in
      await LocalFlightLiveActivityBridge.start()
    }

    AsyncFunction("updateLiveActivity") { () async -> [String: Any] in
      await LocalFlightLiveActivityBridge.update()
    }

    AsyncFunction("endLiveActivity") { () async -> [String: Any] in
      await LocalFlightLiveActivityBridge.end()
    }

    AsyncFunction("reconcileLiveActivity") { () async -> [String: Any] in
      await LocalFlightLiveActivityBridge.reconcile()
    }
  }
}

/**
 A transparent React host that participates in UIKit's responder chain and
 exposes the small, documented Local Flight keyboard-shortcut set to JS.

 Keeping the commands on a parent view means they continue to work while one
 of its controls (including a text field) is the first responder.
 */
public final class LocalFlightShortcutView: ExpoView {
  let onShortcut = EventDispatcher()

  public override var canBecomeFirstResponder: Bool {
    true
  }

  public override func didMoveToWindow() {
    super.didMoveToWindow()
    guard window != nil else {
      return
    }

    // Give the host an initial place in the responder chain. Descendant
    // controls remain free to become first responder afterwards.
    DispatchQueue.main.async { [weak self] in
      guard let self, self.window != nil, !self.hasFirstResponderDescendant else {
        return
      }
      self.becomeFirstResponder()
    }
  }

  public override var keyCommands: [UIKeyCommand]? {
    var commands: [UIKeyCommand] = []
    for modifier in [UIKeyModifierFlags.command, UIKeyModifierFlags.control] {
      commands.append(shortcutCommand(input: "1", modifiers: modifier, title: "Board"))
      commands.append(shortcutCommand(input: "2", modifiers: modifier, title: "Radar"))
      commands.append(shortcutCommand(input: "3", modifiers: modifier, title: "History"))
      commands.append(shortcutCommand(input: "4", modifiers: modifier, title: "More"))
      commands.append(shortcutCommand(input: "r", modifiers: modifier, title: "Refresh"))
      commands.append(shortcutCommand(input: "f", modifiers: modifier, title: "Search or filter"))
    }
    commands.append(shortcutCommand(input: UIKeyCommand.inputEscape, modifiers: [], title: "Close"))
    return commands
  }

  private var hasFirstResponderDescendant: Bool {
    if isFirstResponder {
      return true
    }
    return subviews.contains { view in
      view.isFirstResponder || view.subviewsContainFirstResponder
    }
  }

  private func shortcutCommand(
    input: String,
    modifiers: UIKeyModifierFlags,
    title: String
  ) -> UIKeyCommand {
    let command = UIKeyCommand(
      input: input,
      modifierFlags: modifiers,
      action: #selector(handleShortcut(_:))
    )
    command.discoverabilityTitle = title
    if #available(iOS 15.0, *) {
      command.wantsPriorityOverSystemBehavior = true
    }
    return command
  }

  @objc
  private func handleShortcut(_ command: UIKeyCommand) {
    guard let input = command.input else {
      return
    }
    let key = input == UIKeyCommand.inputEscape ? "escape" : input.lowercased()
    onShortcut(["key": key])
  }
}

private extension UIView {
  var subviewsContainFirstResponder: Bool {
    subviews.contains { view in
      view.isFirstResponder || view.subviewsContainFirstResponder
    }
  }
}
