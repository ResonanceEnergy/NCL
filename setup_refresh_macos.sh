#!/bin/bash
# Super Agency Cross-Platform Refresh Setup - macOS (Quantum Quasar)
# Installs and configures the 5-minute refresh system

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_FILE="$SCRIPT_DIR/com.superagency.crossplatformrefresh.plist"
LOG_DIR="$SCRIPT_DIR/logs"

echo "🚀 Setting up Cross-Platform Refresh on Quantum Quasar (macOS)"
echo "============================================================"

# Create log directory
mkdir -p "$LOG_DIR"

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3 first."
    exit 1
fi

# Test the refresh script
echo "🧪 Testing refresh script..."
if python3 "$SCRIPT_DIR/cross_platform_refresh.py"; then
    echo "✅ Refresh script test passed"
else
    echo "❌ Refresh script test failed"
    exit 1
fi

# Install the launchd plist
echo "📝 Installing launchd service..."
PLIST_DEST="$HOME/Library/LaunchAgents/com.superagency.crossplatformrefresh.plist"

cp "$PLIST_FILE" "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

# Load the service
echo "🔄 Loading launchd service..."
launchctl unload "$PLIST_DEST" 2>/dev/null || true  # Unload if already loaded
launchctl load "$PLIST_DEST"

# Check if service is loaded
if launchctl list | grep -q "com.superagency.crossplatformrefresh"; then
    echo "✅ Service loaded successfully"
else
    echo "❌ Failed to load service"
    exit 1
fi

echo ""
echo "🎉 Cross-Platform Refresh setup complete!"
echo "=========================================="
echo "📊 Service: com.superagency.crossplatformrefresh"
echo "⏰ Runs every: 5 minutes"
echo "📝 Logs: $LOG_DIR/"
echo "🔄 Status: $(launchctl list | grep "com.superagency.crossplatformrefresh" | awk '{print $3}')"
echo ""
echo "To check status: launchctl list | grep superagency"
echo "To stop: launchctl unload $PLIST_DEST"
echo "To start: launchctl load $PLIST_DEST"</content>
<parameter name="filePath">/Users/gripandripphdd/Library/CloudStorage/OneDrive-GripandRipp(2)/SuperAgency-Shared/setup_refresh_macos.sh