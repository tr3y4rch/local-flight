import ExpoModulesCore
import UIKit
import WidgetKit

public final class LocalFlightWidgetBridgeModule: Module {
  public func definition() -> ModuleDefinition {
    Name("LocalFlightWidgetBridge")

    View(LocalFlightShortcutView.self) {
      ViewName("LocalFlightShortcutView")
      Events("onShortcut")
    }

    AsyncFunction("reload") { () -> [String: Any] in
      WidgetCenter.shared.reloadTimelines(ofKind: "LocalFlightWidget")
      return ["available": true]
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
