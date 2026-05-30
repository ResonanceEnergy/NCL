#!/usr/bin/env bash
# launch-brain.sh — Wrapper invoked by the launchd plist.
#
# Secret loading order (FIRST hit wins, downstream layers fill gaps):
#   1. launchd plist EnvironmentVariables (rarely used — kept empty for secrets)
#   2. ~/.env (user-level, if present)
#   3. ~/dev/NCL/.env (project-level, if present)
#   4. macOS Keychain — done inside runtime/api/config.py at startup via
#      bootstrap_env_from_keychain(). This is the canonical source now.
#
# .env files are OPTIONAL — the Brain boots fine from keychain alone. See
# docs/SECRETS.md.
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
else
    # No project .env — config.py will hydrate from macOS keychain at startup.
    # This is the post-migration steady state.
    echo "launch-brain: no $NCL_DIR/.env found — relying on macOS keychain (see docs/SECRETS.md)" >&2
fi

# 2.5 Source operator-toggleable env flags managed via POST /system/env
# (Wave 14BF). NCL_FUSION_BGE_RERANK_ENABLED, NCL_MINHASH_DEDUP_ENABLED,
# NCL_CROSS_REF_BERTOPIC_ENABLED, NCL_MEMORY_EMBED_MODEL.
if [ -f "$NCL_DIR/.env.flags" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$NCL_DIR/.env.flags"
    set +a
fi

# 3. Ensure PYTHONPATH includes the project root
export PYTHONPATH="$NCL_DIR${PYTHONPATH:+:$PYTHONPATH}"

# 4. Exec the brain server (replace this shell process so launchd tracks the right PID)
cd "$NCL_DIR"
# W8-A1 Q1 (2026-05-24): bind to Tailscale only. Port 8800 must be reachable
# from Tailscale peers (iPhone, iPad) but NOT from any LAN/coffee-shop network
# the Mac happens to be on. 100.72.223.123 is this host's stable Tailscale IP.
exec /opt/homebrew/bin/python3 -m uvicorn runtime.api.routes:versioned_app \
    --host 100.72.223.123 \
    --port 8800
