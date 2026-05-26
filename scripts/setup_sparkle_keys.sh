#!/bin/bash
# Wave 14G Phase 7 — generate the Sparkle ed25519 key pair for signing
# desktop release builds. Runs ONCE. Private key persists in macOS
# Keychain (Sparkle's generate_keys tool handles this). Public key is
# echoed; paste it into project.yml under NCLDesktop settings.base as
# INFOPLIST_KEY_SUPublicEDKey: "<value>".
#
# Requires Sparkle's generate_keys tool. Path varies by install:
#   SPM cache:    ~/Library/Developer/Xcode/DerivedData/.../SourcePackages/artifacts/sparkle/...
#   Homebrew:     /opt/homebrew/Caskroom/sparkle/.../bin/generate_keys
# This script probes both.
set -e

PROBES=(
    /opt/homebrew/Caskroom/sparkle/*/bin/generate_keys
    "$HOME"/Library/Developer/Xcode/DerivedData/*/SourcePackages/artifacts/sparkle/Sparkle/bin/generate_keys
    "$HOME"/Library/Developer/Xcode/DerivedData/*/SourcePackages/checkouts/Sparkle/bin/generate_keys
)
GENKEYS=""
for p in "${PROBES[@]}"; do
    for resolved in $p; do
        if [[ -x "$resolved" ]]; then
            GENKEYS="$resolved"
            break 2
        fi
    done
done

if [[ -z "$GENKEYS" ]]; then
    echo "[setup_sparkle_keys] generate_keys not found. Build NCLDesktop once via Xcode"
    echo "  (so SPM downloads Sparkle), or 'brew install --cask sparkle'."
    exit 1
fi

echo "[setup_sparkle_keys] using $GENKEYS"
"$GENKEYS"
echo ""
echo "[setup_sparkle_keys] paste the public key above into project.yml as"
echo "  INFOPLIST_KEY_SUPublicEDKey: \"<paste-public-key-here>\""
echo "  then re-run 'xcodegen generate' and rebuild."
