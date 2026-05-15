#!/bin/bash
# launchd wrapper for pump_watcher: sources project .env so API keys are available.
set -euo pipefail
cd /Users/natrix/dev/NCL
[ -f .env ] && set -a && source .env && set +a
exec /opt/homebrew/bin/python3 -m runtime.pump_watcher
