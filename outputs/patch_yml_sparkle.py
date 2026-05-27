#!/usr/bin/env python3
"""Wave 14G Phase 7 — add Sparkle SPM dep + Info.plist keys + asset catalog."""

p = "/Users/natrix/Projects/FirstStrike/project.yml"
s = open(p).read()

# 1) Add packages: block above targets:
pkg_block = """packages:
  Sparkle:
    url: https://github.com/sparkle-project/Sparkle
    from: "2.6.0"

"""
if "packages:" not in s:
    s = s.replace("targets:", pkg_block + "targets:", 1)
    print("added packages: block")

# 2) Add Sparkle dependency + Info.plist keys + asset catalog to NCLDesktop
old_block = """  NCLDesktop:
    type: application
    platform: macOS
    deploymentTarget: "14.0"
    sources:
      - path: MacSources
        type: group"""
new_block = """  NCLDesktop:
    type: application
    platform: macOS
    deploymentTarget: "14.0"
    dependencies:
      - package: Sparkle
    sources:
      - path: MacSources
        type: group
      - path: MacResources/Assets.xcassets"""
if "package: Sparkle" not in s:
    s = s.replace(old_block, new_block, 1)
    print("added Sparkle dependency + asset catalog")

# 3) Inject Sparkle Info.plist keys into NCLDesktop settings.base
old_settings = '''    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.resonanceenergy.ncldesktop
        PRODUCT_NAME: "NCL Desktop"
        GENERATE_INFOPLIST_FILE: true
        SWIFT_STRICT_CONCURRENCY: minimal
        INFOPLIST_KEY_LSUIElement: "YES"
        INFOPLIST_KEY_NSAppTransportSecurity_NSAllowsArbitraryLoads: "YES"'''
new_settings = '''    settings:
      base:
        PRODUCT_BUNDLE_IDENTIFIER: com.resonanceenergy.ncldesktop
        PRODUCT_NAME: "NCL Desktop"
        GENERATE_INFOPLIST_FILE: true
        SWIFT_STRICT_CONCURRENCY: minimal
        INFOPLIST_KEY_LSUIElement: "YES"
        INFOPLIST_KEY_NSAppTransportSecurity_NSAllowsArbitraryLoads: "YES"
        ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
        INFOPLIST_KEY_SUFeedURL: "http://100.72.223.123:8800/desktop/appcast.xml"
        INFOPLIST_KEY_SUEnableAutomaticChecks: "YES"
        INFOPLIST_KEY_SUScheduledCheckInterval: "86400"'''
if "ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon" not in s:
    s = s.replace(old_settings, new_settings, 1)
    print("added Sparkle Info.plist keys + asset catalog setting")

open(p, "w").write(s)
print("DONE")
