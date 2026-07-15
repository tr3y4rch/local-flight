import ExpoModulesCore
import WidgetKit

public final class LocalFlightWidgetBridgeModule: Module {
  public func definition() -> ModuleDefinition {
    Name("LocalFlightWidgetBridge")

    AsyncFunction("reload") { () -> [String: Any] in
      WidgetCenter.shared.reloadTimelines(ofKind: "LocalFlightWidget")
      return ["available": true]
    }
  }
}
