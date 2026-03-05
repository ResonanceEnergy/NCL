#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LA_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LA_DIR"

sed "s|__ROOT__|$ROOT_DIR|g" "$ROOT_DIR/launchd/ncl.relay.plist" > "$LA_DIR/ncl.relay.plist"
sed "s|__ROOT__|$ROOT_DIR|g" "$ROOT_DIR/launchd/ncl.nightly.plist" > "$LA_DIR/ncl.nightly.plist"

echo "Installed: $LA_DIR/ncl.relay.plist"
echo "Installed: $LA_DIR/ncl.nightly.plist"

echo "Load with:"
echo "  launchctl load -w $LA_DIR/ncl.relay.plist"
echo "  launchctl load -w $LA_DIR/ncl.nightly.plist"
