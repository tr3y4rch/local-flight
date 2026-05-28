import CoreText
import SwiftUI

enum LocalFlightWidgetFont {
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

enum LFWidgetDesignV2 {
  static let darkWidgetBg = LinearGradient(
    colors: [
      Color(red: 0.055, green: 0.113, blue: 0.180),
      Color(red: 0.024, green: 0.055, blue: 0.094),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let lightWidgetBg = LinearGradient(
    colors: [
      Color(red: 0.957, green: 0.969, blue: 0.988),
      Color(red: 0.922, green: 0.941, blue: 0.973),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let darkRowBg = LinearGradient(
    colors: [
      Color(red: 0.067, green: 0.125, blue: 0.188),
      Color(red: 0.043, green: 0.094, blue: 0.149),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let lightRowBg = LinearGradient(
    colors: [
      Color(red: 0.910, green: 0.929, blue: 0.965),
      Color(red: 0.871, green: 0.902, blue: 0.941),
    ],
    startPoint: .topLeading,
    endPoint: .bottomTrailing
  )

  static let darkPinnedBg = LinearGradient(
    colors: [
      Color(red: 0.125, green: 0.118, blue: 0.039),
      Color(red: 0.094, green: 0.110, blue: 0.055),
      Color(red: 0.055, green: 0.094, blue: 0.125),
    ],
    startPoint: .leading,
    endPoint: .trailing
  )

  static let lightPinnedBg = LinearGradient(
    colors: [
      Color(red: 1.000, green: 0.976, blue: 0.910),
      Color(red: 1.000, green: 0.957, blue: 0.847),
      Color(red: 0.933, green: 0.957, blue: 1.000),
    ],
    startPoint: .leading,
    endPoint: .trailing
  )

  static let amberAccentBar = LinearGradient(
    colors: [
      Color(red: 0.953, green: 0.722, blue: 0.207),
      Color(red: 0.769, green: 0.565, blue: 0.063).opacity(0.4),
    ],
    startPoint: .top,
    endPoint: .bottom
  )

  static let lightAmberAccentBar = LinearGradient(
    colors: [
      Color(red: 0.784, green: 0.565, blue: 0.000),
      Color(red: 0.627, green: 0.439, blue: 0.000).opacity(0.4),
    ],
    startPoint: .top,
    endPoint: .bottom
  )

  static func statusColor(tone: String, scheme: ColorScheme) -> Color {
    let dark = scheme == .dark
    switch tone {
    case "boarding", "departed":
      return dark ? Color(red: 0.137, green: 0.886, blue: 0.529)
                  : Color(red: 0.039, green: 0.478, blue: 0.235)
    case "delayed":
      return dark ? Color(red: 0.953, green: 0.722, blue: 0.207)
                  : Color(red: 0.541, green: 0.376, blue: 0.000)
    case "cancelled":
      return dark ? Color(red: 0.941, green: 0.349, blue: 0.298)
                  : Color(red: 0.737, green: 0.145, blue: 0.094)
    default:
      return dark ? Color(red: 0.396, green: 0.722, blue: 0.969)
                  : Color(red: 0.043, green: 0.376, blue: 0.690)
    }
  }

  static func statusBackground(tone: String, scheme: ColorScheme) -> Color {
    statusColor(tone: tone, scheme: scheme).opacity(scheme == .dark ? 0.14 : 0.12)
  }

  static func statusBorder(tone: String, scheme: ColorScheme) -> Color {
    statusColor(tone: tone, scheme: scheme).opacity(scheme == .dark ? 0.45 : 0.55)
  }

  static func textPrimary(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.929, green: 0.965, blue: 1.000)
                    : Color(red: 0.039, green: 0.078, blue: 0.125)
  }

  static func textSecondary(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.769, green: 0.851, blue: 0.933)
                    : Color(red: 0.118, green: 0.220, blue: 0.314)
  }

  static func textMuted(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.494, green: 0.651, blue: 0.800)
                    : Color(red: 0.227, green: 0.345, blue: 0.471)
  }

  static func textDim(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.239, green: 0.376, blue: 0.486)
                    : Color(red: 0.416, green: 0.557, blue: 0.659)
  }

  static func separator(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.094, green: 0.176, blue: 0.259)
                    : Color(red: 0.784, green: 0.831, blue: 0.875)
  }

  static func textCyan(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.396, green: 0.722, blue: 0.969)
                    : Color(red: 0.043, green: 0.376, blue: 0.690)
  }

  static func pinnedBorderColor(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.165, green: 0.145, blue: 0.024)
                    : Color(red: 0.831, green: 0.722, blue: 0.251)
  }

  static func beaconBTint(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.612, green: 0.780, blue: 0.918)
                    : Color(red: 0.039, green: 0.125, blue: 0.251)
  }

  static func beaconBCutout(_ scheme: ColorScheme) -> Color {
    scheme == .dark ? Color(red: 0.024, green: 0.055, blue: 0.094)
                    : Color(red: 0.922, green: 0.941, blue: 0.973)
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
      .padding(.horizontal, 9)
      .padding(.vertical, 5)
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
