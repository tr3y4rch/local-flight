const fs = require("fs");
const path = require("path");
const plist = require("@expo/plist").default;
const { withDangerousMod, withInfoPlist } = require("@expo/config-plugins");

const privacyManifest = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
\t<key>NSPrivacyAccessedAPITypes</key>
\t<array>
\t\t<dict>
\t\t\t<key>NSPrivacyAccessedAPIType</key>
\t\t\t<string>NSPrivacyAccessedAPICategoryUserDefaults</string>
\t\t\t<key>NSPrivacyAccessedAPITypeReasons</key>
\t\t\t<array>
\t\t\t\t<string>CA92.1</string>
\t\t\t</array>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyAccessedAPIType</key>
\t\t\t<string>NSPrivacyAccessedAPICategoryFileTimestamp</string>
\t\t\t<key>NSPrivacyAccessedAPITypeReasons</key>
\t\t\t<array>
\t\t\t\t<string>0A2A.1</string>
\t\t\t\t<string>3B52.1</string>
\t\t\t\t<string>C617.1</string>
\t\t\t</array>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyAccessedAPIType</key>
\t\t\t<string>NSPrivacyAccessedAPICategoryDiskSpace</string>
\t\t\t<key>NSPrivacyAccessedAPITypeReasons</key>
\t\t\t<array>
\t\t\t\t<string>E174.1</string>
\t\t\t\t<string>85F4.1</string>
\t\t\t</array>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyAccessedAPIType</key>
\t\t\t<string>NSPrivacyAccessedAPICategorySystemBootTime</string>
\t\t\t<key>NSPrivacyAccessedAPITypeReasons</key>
\t\t\t<array>
\t\t\t\t<string>35F9.1</string>
\t\t\t</array>
\t\t</dict>
\t</array>
\t<key>NSPrivacyCollectedDataTypes</key>
\t<array>
\t\t<dict>
\t\t\t<key>NSPrivacyCollectedDataType</key>
\t\t\t<string>NSPrivacyCollectedDataTypeDeviceID</string>
\t\t\t<key>NSPrivacyCollectedDataTypeLinked</key>
\t\t\t<true/>
\t\t\t<key>NSPrivacyCollectedDataTypePurposes</key>
\t\t\t<array>
\t\t\t\t<string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string>
\t\t\t</array>
\t\t\t<key>NSPrivacyCollectedDataTypeTracking</key>
\t\t\t<false/>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyCollectedDataType</key>
\t\t\t<string>NSPrivacyCollectedDataTypeCrashData</string>
\t\t\t<key>NSPrivacyCollectedDataTypeLinked</key>
\t\t\t<true/>
\t\t\t<key>NSPrivacyCollectedDataTypePurposes</key>
\t\t\t<array>
\t\t\t\t<string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string>
\t\t\t</array>
\t\t\t<key>NSPrivacyCollectedDataTypeTracking</key>
\t\t\t<false/>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyCollectedDataType</key>
\t\t\t<string>NSPrivacyCollectedDataTypeOtherDiagnosticData</string>
\t\t\t<key>NSPrivacyCollectedDataTypeLinked</key>
\t\t\t<true/>
\t\t\t<key>NSPrivacyCollectedDataTypePurposes</key>
\t\t\t<array>
\t\t\t\t<string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string>
\t\t\t</array>
\t\t\t<key>NSPrivacyCollectedDataTypeTracking</key>
\t\t\t<false/>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyCollectedDataType</key>
\t\t\t<string>NSPrivacyCollectedDataTypeProductInteraction</string>
\t\t\t<key>NSPrivacyCollectedDataTypeLinked</key>
\t\t\t<true/>
\t\t\t<key>NSPrivacyCollectedDataTypePurposes</key>
\t\t\t<array>
\t\t\t\t<string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string>
\t\t\t</array>
\t\t\t<key>NSPrivacyCollectedDataTypeTracking</key>
\t\t\t<false/>
\t\t</dict>
\t\t<dict>
\t\t\t<key>NSPrivacyCollectedDataType</key>
\t\t\t<string>NSPrivacyCollectedDataTypeOtherUserContent</string>
\t\t\t<key>NSPrivacyCollectedDataTypeLinked</key>
\t\t\t<true/>
\t\t\t<key>NSPrivacyCollectedDataTypePurposes</key>
\t\t\t<array>
\t\t\t\t<string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string>
\t\t\t</array>
\t\t\t<key>NSPrivacyCollectedDataTypeTracking</key>
\t\t\t<false/>
\t\t</dict>
\t</array>
\t<key>NSPrivacyTracking</key>
\t<false/>
</dict>
</plist>
`;

function removeUnusedGeneratedUsageDescriptions(infoPlist) {
  // These can be introduced by native dependencies, but Local Flight does not
  // request microphone or Face ID access in the submitted mobile app.
  delete infoPlist.NSFaceIDUsageDescription;
  delete infoPlist.NSMicrophoneUsageDescription;
  delete infoPlist.NSSupportsLiveActivities;

  if (Array.isArray(infoPlist.CFBundleURLTypes)) {
    infoPlist.CFBundleURLTypes = infoPlist.CFBundleURLTypes
      .map((urlType) => {
        if (!Array.isArray(urlType.CFBundleURLSchemes)) {
          return urlType;
        }
        return {
          ...urlType,
          CFBundleURLSchemes: urlType.CFBundleURLSchemes.filter(
            (scheme) => scheme !== "com.localflight.companion"
          ),
        };
      })
      .filter((urlType) => !Array.isArray(urlType.CFBundleURLSchemes) || urlType.CFBundleURLSchemes.length > 0);
  }
}

function withLocalFlightPrivacyManifest(config) {
  config = withInfoPlist(config, (nextConfig) => {
    removeUnusedGeneratedUsageDescriptions(nextConfig.modResults);
    return nextConfig;
  });

  return withDangerousMod(config, [
    "ios",
    async (nextConfig) => {
      const projectName = nextConfig.modRequest.projectName || "LocalFlightCompanion";
      const manifestPath = path.join(nextConfig.modRequest.platformProjectRoot, projectName, "PrivacyInfo.xcprivacy");
      fs.mkdirSync(path.dirname(manifestPath), { recursive: true });
      fs.writeFileSync(manifestPath, privacyManifest);

      const infoPlistPath = path.join(nextConfig.modRequest.platformProjectRoot, projectName, "Info.plist");
      if (fs.existsSync(infoPlistPath)) {
        const infoPlist = plist.parse(fs.readFileSync(infoPlistPath, "utf8"));
        removeUnusedGeneratedUsageDescriptions(infoPlist);
        fs.writeFileSync(infoPlistPath, plist.build(infoPlist));
      }

      return nextConfig;
    }
  ]);
}

module.exports = withLocalFlightPrivacyManifest;
