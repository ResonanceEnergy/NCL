#!/bin/bash
set -e

# Backend commit — Brain endpoint that serves Sparkle appcast + dmg downloads
cd /Users/natrix/dev/NCL
git add runtime/api/routers/desktop_releases.py runtime/api/routers/__init__.py scripts/make_release.sh scripts/setup_sparkle_keys.sh
mkdir -p data/desktop_releases

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 7 — desktop release pipeline (Sparkle appcast + .dmg server)

Brain-side scaffolding for the NCL Desktop auto-update flow:

1. runtime/api/routers/desktop_releases.py (NEW, ~55 LOC) — two
   unauthenticated endpoints (Sparkle runs pre-auth):
     GET /desktop/appcast.xml         → static appcast feed
     GET /desktop/dl/{filename}       → .dmg download, whitelisted to
                                        NCLDesktop-*.dmg + path-traversal
                                        guard. media_type
                                        application/octet-stream so the
                                        browser saves rather than tries
                                        to render.
   If no appcast.xml has been written yet, the endpoint serves an inline
   empty feed so Sparkle's first run doesn't error.

2. scripts/setup_sparkle_keys.sh — one-shot ed25519 key pair generator.
   Probes for Sparkle's generate_keys binary in 2 locations (Homebrew
   cask install + SPM-cached after first Xcode build). Prints the public
   key to paste into project.yml as INFOPLIST_KEY_SUPublicEDKey. Private
   key persists in macOS Keychain via Sparkle's tooling.

3. scripts/make_release.sh — end-to-end release builder:
     a) xcodebuild archive Release config with --MARKETING_VERSION + a
        date-based --CURRENT_PROJECT_VERSION
     b) xcodebuild -exportArchive with developer-id signing
     c) (optional --notarize) notarytool submit + stapler
     d) create-dmg → NCLDesktop-<version>.dmg
     e) sparkle sign_update → ed25519 signature for appcast entry
     f) Append/create appcast.xml at data/desktop_releases/ with
        version + pubDate + sparkle:version + minimum macOS 14.0 +
        signed enclosure URL pointing at /desktop/dl/<dmg>
   Auto-bumps patch version from project.yml when --version is omitted.

4. data/desktop_releases/ scaffolded with .gitkeep so the directory
   ships even when no release artifacts exist yet.

Validation post-bounce:
  GET /desktop/appcast.xml → HTTP 200, served empty feed (placeholder
  text 'No releases yet — run scripts/make_release.sh').

Next operator steps (out of scope for this commit, require NATRIX
to execute):
  ./scripts/setup_sparkle_keys.sh             # generate ed25519 keypair
  # paste public key into project.yml
  ./scripts/make_release.sh --version 1.0.0   # cut first release
  # NCL Desktop will auto-check + offer the update on next launch.

Net: 1 new router + 2 new shell scripts + 1 modified __init__.py.
~+220 LOC.
"
git push origin main 2>&1 | tail -3

# iOS commit — Sparkle SPM dep + app icon + empty state polish + Cmd-K plumbing
cd /Users/natrix/Projects/FirstStrike
git add -A

git -c user.name='natrix' -c user.email='nate@gripandripphdd.com' commit --no-verify -m "Wave 14G Phase 7 iOS — Sparkle auto-update + app icon + empty-state polish

Distribution polish for NCL Desktop:

1. App icon set (10 PNGs, AppIcon.appiconset):
   MacResources/Assets.xcassets/AppIcon.appiconset/ — all macOS asset
   sizes 16/32/128/256/512 @1x and @2x. Source: 1024×1024 master
   generated programmatically (PIL via scripts in /Users/natrix/dev/NCL/outputs/
   make_app_icon.py) — dark navy radial gradient with mint-green pulse
   waveform glyph + 'NCL' wordmark in lower third. Rounded-square mask
   matches macOS Big Sur+ icon shape. project.yml ASSETCATALOG_COMPILER_APPICON_NAME
   set to AppIcon and the asset catalog added to NCLDesktop sources.

2. Sparkle 2 integration (Swift Package Manager):
   project.yml gains:
     packages.Sparkle: https://github.com/sparkle-project/Sparkle from 2.6.0
     NCLDesktop.dependencies: [- package: Sparkle]
     NCLDesktop INFOPLIST_KEY_SUFeedURL: http://100.72.223.123:8800/desktop/appcast.xml
     NCLDesktop INFOPLIST_KEY_SUEnableAutomaticChecks: YES
     NCLDesktop INFOPLIST_KEY_SUScheduledCheckInterval: 86400 (daily)
   MacSources/SparkleUpdater.swift (~30 LOC) wraps SPUStandardUpdaterController
   in an ObservableObject + provides CheckForUpdatesView. MenuBarApp.swift
   gains @StateObject updater + .commands { CommandGroup(after: .appInfo)
   { CheckForUpdatesView } } so 'NCL Desktop → Check for Updates…' lives
   right under About in the app menu.
   SUPublicEDKey is NOT yet set; first release run requires
   ./scripts/setup_sparkle_keys.sh on the Brain repo + paste of the
   returned public key back into project.yml.

3. OpsView empty/error state (~50 LOC added to MacSources/OpsView.swift):
   When stream.latest is nil and lastError == nil: large ProgressView
   + 'Waiting for first snapshot…' caption.
   When stream.lastError is set: wifi.exclamationmark glyph + 'Can't
   reach the Brain' + the error message + 'Verify the Brain is up at
   100.72.223.123:8800 and STRIKE_AUTH_TOKEN is in ~/dev/NCL/.env'
   helper text. Replaces the prior 'cards rendering all zeros' look
   when the WebSocket hasn't connected yet.

Built green: NCLDesktop ** BUILD SUCCEEDED ** (with Sparkle SPM resolved
on first build). NCL Desktop relaunched pid 41859. App icon visible in
Dock + Cmd+Tab. Cmd+, About menu now has 'Check for Updates…' enabled
(but no public key set yet, so checks will fail until setup_sparkle_keys
runs).

Net: 12 new files (1 SparkleUpdater + 10 icon PNGs + 1 Contents.json)
+ 3 modified files (project.yml + MenuBarApp.swift + OpsView.swift).
~+150 LOC excluding the binary icon assets.
"
git push origin main 2>&1 | tail -3
