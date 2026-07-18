const fs = require("fs");
const path = require("path");
const {
  withDangerousMod,
  withEntitlementsPlist,
  withXcodeProject,
} = require("@expo/config-plugins");

const APP_GROUP_ID = "group.cc.beacontools.localflight";
const WIDGET_TARGET = "LocalFlightWidget";
const WIDGET_BUNDLE_ID = "cc.beacontools.localflight.widget";

const widgetSwiftSources = [
  "WidgetSnapshot.swift",
  "DesignTokens.swift",
  "SmallWidgetViewV2.swift",
  "MediumWidgetViewV2.swift",
  "LocalFlightWidget.swift",
];

const widgetTemplateFiles = [
  ...widgetSwiftSources,
  "LiveActivityViewV2.swift",
  "SampleSnapshots.swift",
  "LocalFlightWidget.entitlements",
  "LocalFlightWidget-Info.plist",
];

const widgetFonts = [
  "Audiowide-Regular.ttf",
  "DMSans.ttf",
  "SpaceMono-Regular.ttf",
  "SpaceMono-Bold.ttf",
];

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function copyFileIfChanged(source, destination) {
  ensureDir(path.dirname(destination));
  const next = fs.readFileSync(source);
  if (fs.existsSync(destination)) {
    const current = fs.readFileSync(destination);
    if (Buffer.compare(current, next) === 0) {
      return;
    }
  }
  fs.writeFileSync(destination, next);
}

function findTarget(project, name) {
  const targets = project.pbxNativeTargetSection();
  return Object.entries(targets)
    .filter(([key]) => !key.endsWith("_comment"))
    .find(([, target]) => String(target.name || "").replace(/"/g, "") === name);
}

function findGroupUuid(project, name) {
  const groups = project.hash.project.objects.PBXGroup || {};
  return Object.entries(groups)
    .filter(([key]) => !key.endsWith("_comment"))
    .find(([, group]) => group.name === name || group.path === name)?.[0];
}

function ensureGroup(project, name, groupPath) {
  const existing = findGroupUuid(project, name);
  if (existing) {
    return existing;
  }
  const created = project.addPbxGroup([], name, groupPath);
  const mainGroup = project.getFirstProject().firstProject.mainGroup;
  project.addToPbxGroup(created.uuid, mainGroup);
  return created.uuid;
}

function ensureBuildPhase(project, targetUuid, type, comment) {
  const target = project.pbxNativeTargetSection()[targetUuid];
  if (!target.buildPhases?.some((phase) => phase.comment === comment)) {
    project.addBuildPhase([], type, comment, targetUuid);
  }
}

function hasPhaseFile(phase, comment) {
  return phase.files?.some((file) => file.comment === comment);
}

function addResourceToTarget(project, filePath, targetUuid, groupUuid) {
  const basename = path.basename(filePath);
  const resources = project.pbxResourcesBuildPhaseObj(targetUuid);
  if (hasPhaseFile(resources, `${basename} in Resources`) || hasPhaseFile(resources, basename)) {
    return;
  }

  const file = project.addFile(filePath, groupUuid, { target: targetUuid });
  if (!file) {
    return;
  }

  file.uuid = project.generateUuid();
  file.target = targetUuid;
  project.addToPbxBuildFileSection(file);
  resources.files.push({
    value: file.uuid,
    comment: `${basename} in Resources`,
  });
}

function updateBuildSettings(project, targetUuid, updates) {
  const target = project.pbxNativeTargetSection()[targetUuid];
  const configList = project.pbxXCConfigurationList()[target.buildConfigurationList];
  const configs = project.pbxXCBuildConfigurationSection();

  for (const configRef of configList.buildConfigurations || []) {
    const config = configs[configRef.value];
    if (config?.buildSettings) {
      Object.assign(config.buildSettings, updates);
    }
  }
}

function ensureTargetDependency(project, targetUuid, dependencyTargetUuid) {
  const objects = project.hash.project.objects;
  objects.PBXTargetDependency = objects.PBXTargetDependency || {};
  objects.PBXContainerItemProxy = objects.PBXContainerItemProxy || {};
  const dependencySection = objects.PBXTargetDependency;
  const target = project.pbxNativeTargetSection()[targetUuid];
  target.dependencies = target.dependencies || [];
  const alreadyLinked = target.dependencies.some((dependency) => {
    const entry = dependencySection[dependency.value];
    return entry?.target === dependencyTargetUuid;
  });
  if (!alreadyLinked) {
    project.addTargetDependency(targetUuid, [dependencyTargetUuid]);
  }
}

function ensureWidgetTarget(project, config) {
  project.hash.project.objects.PBXTargetDependency =
    project.hash.project.objects.PBXTargetDependency || {};
  project.hash.project.objects.PBXContainerItemProxy =
    project.hash.project.objects.PBXContainerItemProxy || {};
  let targetEntry = findTarget(project, WIDGET_TARGET);

  if (!targetEntry) {
    const target = project.addTarget(
      WIDGET_TARGET,
      "app_extension",
      WIDGET_TARGET,
      WIDGET_BUNDLE_ID
    );
    targetEntry = [target.uuid, target.pbxNativeTarget];

    const productRef = target.pbxNativeTarget.productReference;
    const productFile = project.pbxFileReferenceSection()[productRef];
    if (productFile) {
      productFile.path = `${WIDGET_TARGET}.appex`;
      productFile.explicitFileType = '"wrapper.app-extension"';
    }
  }

  const targetUuid = targetEntry[0];
  const groupUuid = ensureGroup(project, WIDGET_TARGET, WIDGET_TARGET);

  ensureBuildPhase(project, targetUuid, "PBXSourcesBuildPhase", "Sources");
  ensureBuildPhase(project, targetUuid, "PBXFrameworksBuildPhase", "Frameworks");
  ensureBuildPhase(project, targetUuid, "PBXResourcesBuildPhase", "Resources");

  for (const sourceFile of widgetSwiftSources) {
    project.addSourceFile(sourceFile, { target: targetUuid }, groupUuid);
  }

  for (const font of widgetFonts) {
    addResourceToTarget(project, `Fonts/${font}`, targetUuid, groupUuid);
  }

  const version = config.version || "0.5.2";
  const buildNumber = config.ios?.buildNumber || "8";
  updateBuildSettings(project, targetUuid, {
    APPLICATION_EXTENSION_API_ONLY: "YES",
    CODE_SIGN_ENTITLEMENTS: `${WIDGET_TARGET}/${WIDGET_TARGET}.entitlements`,
    CURRENT_PROJECT_VERSION: buildNumber,
    INFOPLIST_FILE: `${WIDGET_TARGET}/${WIDGET_TARGET}-Info.plist`,
    IPHONEOS_DEPLOYMENT_TARGET: "15.1",
    MARKETING_VERSION: version,
    PRODUCT_BUNDLE_IDENTIFIER: WIDGET_BUNDLE_ID,
    PRODUCT_NAME: `"${WIDGET_TARGET}"`,
    SKIP_INSTALL: "YES",
    SWIFT_VERSION: "5.0",
    TARGETED_DEVICE_FAMILY: '"1,2"',
  });

  const appTarget = project.getFirstTarget();
  ensureTargetDependency(project, appTarget.uuid, targetUuid);
  updateBuildSettings(project, appTarget.uuid, {
    PRODUCT_BUNDLE_IDENTIFIER: config.ios?.bundleIdentifier || "cc.beacontools.localflight",
  });

  return project;
}

function withLocalFlightIosWidget(config) {
  config = withEntitlementsPlist(config, (nextConfig) => {
    const entitlements = nextConfig.modResults;
    const groups = new Set(entitlements["com.apple.security.application-groups"] || []);
    groups.add(APP_GROUP_ID);
    entitlements["com.apple.security.application-groups"] = Array.from(groups);
    return nextConfig;
  });

  config = withDangerousMod(config, [
    "ios",
    async (nextConfig) => {
      const projectRoot = nextConfig.modRequest.projectRoot;
      const iosRoot = nextConfig.modRequest.platformProjectRoot;
      const sourceRoot = path.join(projectRoot, "native", "ios-widget");
      const widgetRoot = path.join(iosRoot, WIDGET_TARGET);

      ensureDir(widgetRoot);
      fs.rmSync(path.join(widgetRoot, "v2"), { recursive: true, force: true });
      fs.rmSync(path.join(widgetRoot, "README.md"), { force: true });
      fs.rmSync(path.join(widgetRoot, ".DS_Store"), { force: true });
      for (const file of widgetTemplateFiles) {
        copyFileIfChanged(path.join(sourceRoot, file), path.join(widgetRoot, file));
      }

      const fontSourceRoot = path.join(sourceRoot, "Fonts");
      const fontDestRoot = path.join(widgetRoot, "Fonts");
      ensureDir(fontDestRoot);
      for (const font of widgetFonts) {
        copyFileIfChanged(path.join(fontSourceRoot, font), path.join(fontDestRoot, font));
      }

      return nextConfig;
    },
  ]);

  config = withXcodeProject(config, (nextConfig) => {
    nextConfig.modResults = ensureWidgetTarget(nextConfig.modResults, nextConfig);
    return nextConfig;
  });

  return config;
}

module.exports = withLocalFlightIosWidget;
