#!/usr/bin/env bash
# launch-brain.sh — Wrapper invoked by the launchd plist.
# Sources ~/.env (and the project .env) so environment variables are available
# to the Python process, then execs the brain server.
#
# launchd does not run login shells, so .bashrc / .zshrc are never sourced.
# This script fills that gap without requiring EnvironmentVariables to be
# maintained by hand in the plist.

set -euo pipefail

NCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1. Source the user-level .env if it exists (API keys, tokens, etc.)
if [ -f "$HOME/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$HOME/.env"
    set +a
fi

# 2. Source the project-level .env (overrides user-level where both define a key)
if [ -f "$NCL_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$NCL_DIR/.env"
    set +a
fi

# 3. Ensure PYTHONPATH includes the project root
export PYTHONPATH="$NCL_DIR${PYTHONPATH:+:$PYTHONPATH}"

# 4. Exec the brain server (replace this shell process so launchd tracks the right PID)
cd "$NCL_DIR"
exec /opt/homebrew/bin/python3 -m uvicorn runtime.api.routes:versioned_app \
    --host 0.0.0.0 \
    --port 8800
