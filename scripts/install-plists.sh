#!/usr/bin/env bash
# install-plists.sh — Generate and install launchd plist files from templates.
#
# The .plist files in this repo use __HOME__ as a placeholder for the user's
# home directory. This script substitutes the real $HOME value, writes the
# expanded plists to ~/Library/LaunchAgents/, and loads them with launchctl.
#
# Usage:
#   chmod +x scripts/install-plists.sh
#   ./scripts/install-plists.sh
#
# To unload and remove:
#   launchctl bootout gui/$(id -u)/com.resonanceenergy.ncl-brain
#   rm ~/Library/LaunchAgents/com.resonanceenergy.ncl-brain.plist
set -euo pipefail

LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
NCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$LAUNCH_AGENTS"

# List of template plist files (relative to NCL_DIR)
PLISTS=(
    "com.resonanceenergy.ncl-brain.plist"
    "com.resonanceenergy.ncl-watcher.plist"
    "config/com.resonanceenergy.ncl-councils.plist"
    "config/com.resonanceenergy.ncl-orchestrator.plist"
)

for TEMPLATE in "${PLISTS[@]}"; do
    SRC="$NCL_DIR/$TEMPLATE"
    BASENAME="$(basename "$TEMPLATE")"
    DEST="$LAUNCH_AGENTS/$BASENAME"

    if [ ! -f "$SRC" ]; then
        echo "WARNING: template not found: $SRC — skipping"
        continue
    fi

    # Substitute __HOME__ with the actual $HOME value
    sed "s|__HOME__|$HOME|g" "$SRC" > "$DEST"
    echo "Installed: $DEST"

    # Bootout first in case it was already loaded (suppress error if not loaded)
    launchctl bootout "gui/$(id -u)/$(basename "$BASENAME" .plist)" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$DEST"
    echo "Loaded:    $BASENAME"
done

echo ""
echo "All plists installed and loaded."
echo "Check status: launchctl list | grep resonanceenergy"
