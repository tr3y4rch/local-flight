import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const packagePath = path.join(root, "node_modules", "react-native-screens", "package.json");
const expectedVersion = "4.23.0";
const pkg = JSON.parse(fs.readFileSync(packagePath, "utf8"));
if (pkg.version !== expectedVersion) {
  throw new Error(`Local Flight native-tab patch expects react-native-screens ${expectedVersion}; found ${pkg.version}. Review the UIKit scroll contract before updating.`);
}

const sourcePath = path.join(
  root,
  "node_modules",
  "react-native-screens",
  "ios",
  "bottom-tabs",
  "screen",
  "RNSTabsScreenViewController.mm"
);
const marker = "LOCAL_FLIGHT_CONTENT_SCROLL_VIEW_PATCH_V1";
let source = fs.readFileSync(sourcePath, "utf8");
if (!source.includes(marker)) {
  const insertionPoint = "\n#if !TARGET_OS_TV\n";
  if (!source.includes(insertionPoint)) {
    throw new Error("react-native-screens UIKit source changed; Local Flight native-tab patch was not applied.");
  }
  const patch = `

// ${marker}
// UIKit tracks this exact scroll view for Liquid Glass edge material, inset
// updates and iOS 26 tab-bar minimize-on-scroll behavior. React Native views
// can place a content wrapper above their FlatList, so make ownership explicit.
- (nullable UIScrollView *)contentScrollViewForEdge:(NSDirectionalRectEdge)edge
{
  UIScrollView *scrollView =
      [RNSScrollViewFinder findScrollViewInFirstDescendantChainFrom:[self tabScreenComponentView]];
  return scrollView != nil ? scrollView : [super contentScrollViewForEdge:edge];
}
`;
  source = source.replace(insertionPoint, `${patch}${insertionPoint}`);
  fs.writeFileSync(sourcePath, source);
}

console.log(`react-native-screens ${expectedVersion} native-tab scroll ownership patch is active.`);
