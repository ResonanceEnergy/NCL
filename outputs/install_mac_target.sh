#!/bin/bash
set -euo pipefail
FS=/Users/natrix/Projects/FirstStrike
SRC=/Users/natrix/dev/NCL/outputs

# Create Mac-only sources directory
mkdir -p "$FS/MacSources"
cp "$SRC/MenuBarApp.swift" "$FS/MacSources/MenuBarApp.swift"
echo "copied MenuBarApp.swift"

# Append the macOS target to project.yml. Use a marker so re-runs are safe.
if ! grep -q "NCLDesktop:" "$FS/project.yml"; then
cat >> "$FS/project.yml" <<'YML'

  NCLDesktop:
    type: application
    platform: macOS
    deploymentTarget: "14.0"
    sources:
      - path: MacSources
        type: group
    info:
      properties:
        LSUIElement: true  # menu-bar app — no dock icon, no main window
        NSAppTransportSecurity:
          NSAllowsArbitraryLoads: true
    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.resonanceenergy.ncldesktop
        PRODUCT_NAME: "NCL Desktop"
        GENERATE_INFOPLIST_FILE: true
        SWIFT_STRICT_CONCURRENCY: minimal
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        CODE_SIGN_ENTITLEMENTS: ""
YML
echo "appended NCLDesktop target to project.yml"
else
echo "NCLDesktop already in project.yml — skipping append"
fi

echo
echo "=== regen xcodeproj ==="
cd "$FS" && /opt/homebrew/bin/xcodegen generate --spec project.yml 2>&1 | tail -3
echo
echo "=== confirm NCLDesktop target registered ==="
xcodebuild -project FirstStrike.xcodeproj -list 2>&1 | grep -A 10 'Targets:'
echo
echo "=== build for macOS (no codesign for local run) ==="
TS=$(date +%H%M%S)
xcodebuild -project FirstStrike.xcodeproj \
  -scheme NCLDesktop \
  -destination 'platform=macOS' \
  -configuration Debug \
  -derivedDataPath build/MacDerived \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO \
  build 2>&1 | tee build/dev-logs/mac-${TS}.log | grep -E 'BUILD SUCCEEDED|BUILD FAILED|error: ' | head
