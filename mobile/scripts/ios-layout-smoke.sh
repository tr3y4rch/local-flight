#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_ROOT="${ROOT_DIR}/.layout-smoke"
DERIVED_DATA="${OUT_ROOT}/DerivedData"
BUNDLE_ID="${BUNDLE_ID:-cc.beacontools.localflight}"
BUILD_CONFIGURATION="${BUILD_CONFIGURATION:-Release}"
XCODE_WORKSPACE="${XCODE_WORKSPACE:-ios/LocalFlight.xcworkspace}"
XCODE_SCHEME="${XCODE_SCHEME:-LocalFlight}"
WAIT_SECONDS="${WAIT_SECONDS:-4}"
RUNTIME_MODE="latest"
SKIP_BUILD=0
KEEP_DEVICES=0
FRESH_DEVICES=0
ONLY_SLUG=""

usage() {
  cat <<'USAGE'
Usage: npm run layout:ios -- [options]

Deep layout QA only. This builds/installs simulator apps and is intentionally
slower than the normal `npm run verify` + interactive simulator loop.

Options:
  --runtime latest    Use the newest installed iOS runtime. Default.
  --runtime all       Run the device matrix on every installed iOS runtime.
  --skip-build        Reuse APP_PATH or the last .layout-smoke build.
  --fresh-devices     Create temporary QA simulators instead of reusing existing ones.
  --keep-devices      Leave generated "Local Flight QA" simulators installed.
  --only SLUG         Run one device slug: iphone-se, iphone-compact,
                      iphone-standard, iphone-max, ipad-mini, ipad-standard,
                      or ipad-large.
  --wait SECONDS      Seconds to wait after launch before screenshots.

Environment:
  APP_PATH            Existing .app bundle to install when --skip-build is used.
  BUILD_CONFIGURATION Xcode configuration. Defaults to Release so JS is bundled.
  XCODE_WORKSPACE      Expo workspace. Defaults to ios/LocalFlight.xcworkspace.
  XCODE_SCHEME         Shared app scheme. Defaults to LocalFlight.
  BUNDLE_ID           App bundle id. Defaults to cc.beacontools.localflight.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)
      RUNTIME_MODE="${2:-latest}"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD=1
      shift
      ;;
    --fresh-devices)
      FRESH_DEVICES=1
      shift
      ;;
    --keep-devices)
      KEEP_DEVICES=1
      shift
      ;;
    --only)
      ONLY_SLUG="${2:-}"
      shift 2
      ;;
    --wait)
      WAIT_SECONDS="${2:-4}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cd "${ROOT_DIR}"
mkdir -p "${OUT_ROOT}"
RUN_DIR="${OUT_ROOT}/$(date +%Y%m%d-%H%M%S)"
mkdir -p "${RUN_DIR}"

runtime_ids() {
  xcrun simctl list runtimes available \
    | awk '/iOS/ && /com.apple.CoreSimulator.SimRuntime.iOS/ {print $NF}'
}

runtime_label() {
  echo "$1" | sed 's/^com\.apple\.CoreSimulator\.SimRuntime\.//' | tr '.-' '__'
}

runtime_pretty() {
  echo "$1" | sed 's/^com\.apple\.CoreSimulator\.SimRuntime\.iOS-/iOS /' | tr '-' '.'
}

RUNTIMES=()
if [[ "${RUNTIME_MODE}" == "all" ]]; then
  while IFS= read -r runtime; do
    [[ -n "${runtime}" ]] && RUNTIMES+=("${runtime}")
  done < <(runtime_ids)
else
  latest_runtime="$(runtime_ids | tail -n 1)"
  [[ -n "${latest_runtime}" ]] && RUNTIMES+=("${latest_runtime}")
fi

if [[ "${#RUNTIMES[@]}" -eq 0 ]]; then
  echo "No available iOS simulator runtimes found. Install one in Xcode > Settings > Components." >&2
  exit 1
fi

if [[ "${SKIP_BUILD}" -eq 0 ]]; then
  if [[ ! -d ios ]]; then
    echo "Generating the ignored Expo iOS project..."
    npx expo prebuild --platform ios
  fi

  if [[ ! -d "${XCODE_WORKSPACE}" ]]; then
    echo "Could not find ${XCODE_WORKSPACE}. Run Expo prebuild or set XCODE_WORKSPACE." >&2
    exit 1
  fi

  echo "Building Local Flight once for the simulator..."
  rm -rf "${DERIVED_DATA}"
  if ! xcodebuild \
    -workspace "${XCODE_WORKSPACE}" \
    -scheme "${XCODE_SCHEME}" \
    -configuration "${BUILD_CONFIGURATION}" \
    -sdk iphonesimulator \
    -derivedDataPath "${DERIVED_DATA}" \
    build >"${RUN_DIR}/xcodebuild.log" 2>&1; then
    echo "Simulator build failed. Last 200 xcodebuild log lines:" >&2
    tail -n 200 "${RUN_DIR}/xcodebuild.log" >&2 || true
    exit 1
  fi
  echo "Build log: ${RUN_DIR}/xcodebuild.log"
fi

APP_PATH="${APP_PATH:-}"
if [[ -z "${APP_PATH}" ]]; then
  APP_PATH="$(find "${DERIVED_DATA}/Build/Products/${BUILD_CONFIGURATION}-iphonesimulator" -maxdepth 1 -name "*.app" -print | head -n 1 || true)"
fi

if [[ -z "${APP_PATH}" || ! -d "${APP_PATH}" ]]; then
  echo "Could not find a simulator .app bundle. Re-run without --skip-build or set APP_PATH=/path/to/App.app." >&2
  exit 1
fi

created_devices=()
cleanup() {
  if [[ "${KEEP_DEVICES}" -eq 1 ]]; then
    return
  fi
  for udid in "${created_devices[@]:-}"; do
    xcrun simctl shutdown "${udid}" >/dev/null 2>&1 || true
    xcrun simctl delete "${udid}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

device_type_id() {
  local name="$1"
  local line
  line="$(xcrun simctl list devicetypes | grep -F "${name} (" | head -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi
  echo "${line}" | sed -E 's/.*\((com\.apple\.CoreSimulator\.SimDeviceType\.[^()]*)\).*/\1/'
}

candidates_for_slug() {
  case "$1" in
    iphone-se) printf '%s\n' "iPhone SE (3rd generation)" "iPhone 13 mini" "iPhone 16e" "iPhone 17e" ;;
    iphone-compact) printf '%s\n' "iPhone 13 mini" "iPhone SE (3rd generation)" "iPhone 16e" "iPhone 17e" ;;
    iphone-standard) printf '%s\n' "iPhone 17" "iPhone 16" "iPhone 15" ;;
    iphone-max) printf '%s\n' "iPhone 17 Pro Max" "iPhone 16 Pro Max" "iPhone 15 Pro Max" ;;
    ipad-mini) printf '%s\n' "iPad mini (A17 Pro)" "iPad mini (6th generation)" ;;
    ipad-standard) printf '%s\n' "iPad (A16)" "iPad Air 11-inch (M4)" "iPad Pro 11-inch (M5)" ;;
    ipad-large) printf '%s\n' "iPad Pro 13-inch (M5)" "iPad Air 13-inch (M4)" "iPad Pro 13-inch (M4)" ;;
  esac
}

create_device() {
  local slug="$1"
  local runtime="$2"
  local runtime_name
  runtime_name="$(runtime_label "${runtime}")"

  while IFS= read -r candidate; do
    [[ -z "${candidate}" ]] && continue
    local type_id
    type_id="$(device_type_id "${candidate}" || true)"
    [[ -z "${type_id}" ]] && continue

    local name="Local Flight QA ${slug} ${runtime_name}"
    local udid
    if udid="$(xcrun simctl create "${name}" "${type_id}" "${runtime}" 2>/dev/null)"; then
      echo "${udid}"
      return 0
    fi
  done < <(candidates_for_slug "${slug}")

  return 1
}

existing_device() {
  local slug="$1"
  local runtime="$2"
  local pretty
  local section
  local candidate
  local line

  pretty="$(runtime_pretty "${runtime}")"
  section="$(xcrun simctl list devices available | awk -v header="-- ${pretty} --" '
    $0 == header {capture=1; next}
    capture && /^-- / {exit}
    capture {print}
  ')"

  while IFS= read -r candidate; do
    [[ -z "${candidate}" ]] && continue
    line="$(echo "${section}" | grep -F "    ${candidate} (" | head -n 1 || true)"
    [[ -z "${line}" ]] && continue
    echo "${line}" | sed -E 's/.*\(([0-9A-Fa-f-]{36})\).*/\1/'
    return 0
  done < <(candidates_for_slug "${slug}")

  return 1
}

resolve_device() {
  local slug="$1"
  local runtime="$2"
  local udid

  if [[ "${FRESH_DEVICES}" -eq 0 ]]; then
    if udid="$(existing_device "${slug}" "${runtime}")"; then
      echo "${udid}:existing"
      return 0
    fi
  fi

  if udid="$(create_device "${slug}" "${runtime}")"; then
    echo "${udid}:created"
    return 0
  fi

  return 1
}

is_booted() {
  xcrun simctl list devices | grep -F "$1" | grep -q "(Booted)"
}

rotate_left() {
  osascript >/dev/null <<'OSA'
tell application "Simulator" to activate
delay 0.25
tell application "System Events"
  tell process "Simulator"
    click menu item "Rotate Left" of menu "Device" of menu bar 1
  end tell
end tell
OSA
}

rotate_right() {
  osascript >/dev/null <<'OSA'
tell application "Simulator" to activate
delay 0.25
tell application "System Events"
  tell process "Simulator"
    click menu item "Rotate Right" of menu "Device" of menu bar 1
  end tell
end tell
OSA
}

DEVICE_SLUGS=(iphone-se iphone-compact iphone-standard iphone-max ipad-mini ipad-standard ipad-large)
if [[ -n "${ONLY_SLUG}" ]]; then
  case "${ONLY_SLUG}" in
    iphone-se|iphone-compact|iphone-standard|iphone-max|ipad-mini|ipad-standard|ipad-large)
      DEVICE_SLUGS=("${ONLY_SLUG}")
      ;;
    *)
      echo "Unknown device slug: ${ONLY_SLUG}" >&2
      usage >&2
      exit 2
      ;;
  esac
fi

echo "Writing screenshots to ${RUN_DIR}"
echo "Using app bundle: ${APP_PATH}"

for runtime in "${RUNTIMES[@]}"; do
  runtime_name="$(runtime_label "${runtime}")"
  for slug in "${DEVICE_SLUGS[@]}"; do
    echo
    echo "== ${slug} on ${runtime_name} =="
    if ! resolved="$(resolve_device "${slug}" "${runtime}")"; then
      echo "Skipping ${slug}: no compatible device type for ${runtime_name}." | tee -a "${RUN_DIR}/warnings.log"
      continue
    fi
    udid="${resolved%%:*}"
    device_origin="${resolved##*:}"

    if [[ "${device_origin}" == "created" ]]; then
      created_devices+=("${udid}")
    fi

    was_booted=0
    if is_booted "${udid}"; then
      was_booted=1
    else
      xcrun simctl boot "${udid}" >/dev/null
    fi
    xcrun simctl bootstatus "${udid}" -b

    if [[ "${device_origin}" == "created" ]]; then
      xcrun simctl uninstall "${udid}" "${BUNDLE_ID}" >/dev/null 2>&1 || true
    fi

    xcrun simctl install "${udid}" "${APP_PATH}"
    xcrun simctl launch "${udid}" "${BUNDLE_ID}" >/dev/null
    sleep "${WAIT_SECONDS}"

    xcrun simctl io "${udid}" screenshot "${RUN_DIR}/${runtime_name}-${slug}-portrait.png" >/dev/null

    if rotate_left; then
      sleep 1.2
      xcrun simctl io "${udid}" screenshot "${RUN_DIR}/${runtime_name}-${slug}-landscape.png" >/dev/null
      rotate_right || true
    else
      echo "Landscape capture skipped for ${slug}; grant Simulator Accessibility permission if rotation is blocked." | tee -a "${RUN_DIR}/warnings.log"
    fi

    if [[ "${was_booted}" -eq 0 ]]; then
      xcrun simctl shutdown "${udid}" >/dev/null
    fi
  done
done

echo
echo "Layout smoke screenshots complete:"
echo "${RUN_DIR}"
if [[ -f "${RUN_DIR}/warnings.log" ]]; then
  echo "Warnings:"
  cat "${RUN_DIR}/warnings.log"
fi
