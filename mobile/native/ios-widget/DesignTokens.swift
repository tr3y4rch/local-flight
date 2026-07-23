import CoreText
import SwiftUI
import UIKit

enum LocalFlightWidgetFont {
  private static let registeredBundledFonts: Void = {
    for (name, postScriptName) in [
      ("DMSans", "DM Sans"),
      ("Audiowide-Regular", "Audiowide-Regular"),
      ("SpaceMono-Regular", "SpaceMono-Regular"),
      ("SpaceMono-Bold", "SpaceMono-Bold"),
    ] {
      guard UIFont(name: postScriptName, size: 12) == nil else {
        continue
      }
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
    return .custom("DM Sans", size: size, relativeTo: .body)
  }

  static func uiBold(size: CGFloat) -> Font {
    registerBundledFonts()
    return .custom("DM Sans", size: size, relativeTo: .headline).weight(.semibold)
  }
}

enum LFWidgetDesignV2 {
  // Warm glance palette anchors:
  // light #F5F1E8 / #FFFDF8 / #132638 / #536575 / #2F6F9F / #1F6F61
  // dark  #08141D / #102330 / #F5F0E8 / #A4B3BE / #74B5DE / #59C1A5
  static let darkWidgetBg = LinearGradient(
    colors: [
      Color(red: 0.063, green: 0.137, blue: 0.188),
      Color(red: 0.031, green: 0.078, blue: 0.114),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let lightWidgetBg = LinearGradient(
    colors: [
      Color(red: 1.000, green: 0.992, blue: 0.973),
      Color(red: 0.961, green: 0.945, blue: 0.910),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let darkRowBg = LinearGradient(
    colors: [
      Color(red: 0.063, green: 0.137, blue: 0.188),
      Color(red: 0.043, green: 0.110, blue: 0.153),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let lightRowBg = LinearGradient(
    colors: [
      Color(red: 1.000, green: 0.992, blue: 0.973),
      Color(red: 0.949, green: 0.929, blue: 0.894),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let darkPinnedBg = LinearGradient(
    colors: [
      Color(red: 0.259, green: 0.204, blue: 0.106),
      Color(red: 0.180, green: 0.169, blue: 0.118),
      Color(red: 0.063, green: 0.137, blue: 0.188),
    ],
    startPoint: .leading,
    endPoint: .trailing
  )

  static let lightPinnedBg = LinearGradient(
    colors: [
      Color(red: 1.000, green: 0.965, blue: 0.843),
      Color(red: 0.965, green: 0.902, blue: 0.745),
      Color(red: 0.961, green: 0.945, blue: 0.910),
    ],
    startPoint: .leading,
    endPoint: .trailing
  )

  static let amberAccentBar = LinearGradient(
    colors: [
      Color(red: 0.894, green: 0.706, blue: 0.329),
      Color(red: 0.573, green: 0.365, blue: 0.063).opacity(0.55),
    ],
    startPoint: .top,
    endPoint: .bottom
  )

  static let lightAmberAccentBar = LinearGradient(
    colors: [
      Color(red: 0.573, green: 0.365, blue: 0.063),
      Color(red: 0.776, green: 0.557, blue: 0.169).opacity(0.55),
    ],
    startPoint: .top,
    endPoint: .bottom
  )

  static func statusColor(tone: String, scheme: ColorScheme) -> Color {
    let dark = scheme == .dark
    switch tone {
    case "boarding", "departed":
      return dark ? Color(red: 0.349, green: 0.757, blue: 0.647)
                  : Color(red: 0.122, green: 0.435, blue: 0.380)
    case "delayed":
      return dark ? Color(red: 0.894, green: 0.706, blue: 0.329)
                  : Color(red: 0.573, green: 0.365, blue: 0.063)
    case "cancelled":
      return dark ? Color(red: 0.941, green: 0.486, blue: 0.384)
                  : Color(red: 0.655, green: 0.278, blue: 0.196)
    default:
      return dark ? Color(red: 0.455, green: 0.710, blue: 0.871)
                  : Color(red: 0.184, green: 0.435, blue: 0.624)
    }
  }

  static func statusBackground(tone: String, scheme: ColorScheme) -> Color {
    statusColor(tone: tone, scheme: scheme).opacity(scheme == .dark ? 0.14 : 0.04)
  }

  static func statusBorder(tone: String, scheme: ColorScheme) -> Color {
    statusColor(tone: tone, scheme: scheme).opacity(scheme == .dark ? 0.45 : 0.55)
  }

  static func textPrimary(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.961, green: 0.941, blue: 0.910)
                    : Color(red: 0.075, green: 0.149, blue: 0.220)
  }

  static func textSecondary(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.843, green: 0.886, blue: 0.910)
                    : Color(red: 0.176, green: 0.263, blue: 0.329)
  }

  static func textMuted(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.643, green: 0.702, blue: 0.745)
                    : Color(red: 0.325, green: 0.396, blue: 0.459)
  }

  static func textDim(_ scheme: ColorScheme) -> Color {
    textMuted(scheme)
  }

  static func separator(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.157, green: 0.263, blue: 0.322)
                    : Color(red: 0.843, green: 0.820, blue: 0.776)
  }

  static func textCyan(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.455, green: 0.710, blue: 0.871)
                    : Color(red: 0.184, green: 0.435, blue: 0.624)
  }

  static func pinnedBorderColor(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.894, green: 0.706, blue: 0.329)
                    : Color(red: 0.573, green: 0.365, blue: 0.063)
  }

  static func beaconBTint(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.455, green: 0.710, blue: 0.871)
                    : Color(red: 0.184, green: 0.435, blue: 0.624)
  }

  static func beaconBCutout(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.031, green: 0.078, blue: 0.114)
                    : Color(red: 0.961, green: 0.945, blue: 0.910)
  }

  static func warmAccent(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.894, green: 0.706, blue: 0.329)
                    : Color(red: 0.573, green: 0.365, blue: 0.063)
  }
}

extension LocalFlightWidgetPreferences {
  func widgetScheme(system: ColorScheme) -> ColorScheme {
    if widgetAppearance == "light" { return .light }
    if widgetAppearance == "dark" { return .dark }
    return system
  }

  func liveActivityScheme(system: ColorScheme) -> ColorScheme {
    if liveActivityAppearance == "light" { return .light }
    if liveActivityAppearance == "dark" { return .dark }
    return system
  }
}

struct LFStatusCapsuleV2: View {
  let label: String
  let tone: String
  let scheme: ColorScheme

  var body: some View {
    Text(label.uppercased())
      .font(LocalFlightWidgetFont.boardBold(size: 9))
      .lineLimit(1)
      .minimumScaleFactor(0.7)
      .foregroundStyle(LFWidgetDesignV2.statusColor(tone: tone, scheme: scheme))
      .padding(.horizontal, 7)
      .padding(.vertical, 3)
      .background(
        LFWidgetDesignV2.statusBackground(tone: tone, scheme: scheme),
        in: Capsule()
      )
      .overlay(
        Capsule().stroke(
          LFWidgetDesignV2.statusBorder(tone: tone, scheme: scheme),
          lineWidth: 1.2
        )
      )
  }
}

extension View {
  @ViewBuilder
  func lfWidgetBackground(_ scheme: ColorScheme) -> some View {
    let bg = scheme == .dark
      ? LFWidgetDesignV2.darkWidgetBg
      : LFWidgetDesignV2.lightWidgetBg
    if #available(iOSApplicationExtension 17.0, *) {
      self.containerBackground(bg, for: .widget)
    } else {
      self.background(bg)
    }
  }
}
