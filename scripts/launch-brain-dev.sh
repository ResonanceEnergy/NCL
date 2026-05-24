#!/usr/bin/env bash
# launch-brain-dev.sh — DEV variant of launch-brain.sh.
#
# Binds 127.0.0.1:8801 with --reload so it never fights the production
# LaunchAgent on 100.72.223.123:8800. Source the same project .env so API
# keys / tokens work. Iterate on routes/ files; uvicorn picks up changes.
#
# Run manually:
#   ./scripts/launch-brain-dev.sh
#
# DO NOT install this as a LaunchAgent — it's a foreground dev tool.

set -euo pipefail

NCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1. Source the user-level .env if present (parity with launch-brain.sh).
if [ -f "$HOME/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$HOME/.env"
    set +a
fi

# 2. Source the project-level .env if present.
if [ -f "$NCL_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$NCL_DIR/.env"
    set +a
else
    echo "launch-brain-dev: no $NCL_DIR/.env found — relying on keychain fallback in config.py" >&2
fi

# 3. Project root on PYTHONPATH so `runtime.*` imports resolve.
export PYTHONPATH="$NCL_DIR${PYTHONPATH:+:$PYTHONPATH}"

# 4. Launch with --reload on a non-production port + loopback interface only.
cd "$NCL_DIR"
exec /opt/homebrew/bin/python3 -m uvicorn runtime.api.routes:versioned_app \
    --host 127.0.0.1 \
    --port 8801 \
    --reload \
    --log-level info
