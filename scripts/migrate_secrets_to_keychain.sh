#!/usr/bin/env bash
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  migrate_secrets_to_keychain.sh                                          ║
# ║  Moves every secret from ~/dev/NCL/.env into the macOS login keychain.   ║
# ║  Keychain naming convention: ncl-<lowercase-name-with-dashes>            ║
# ║                                                                          ║
# ║  Safe to re-run (uses `security add-generic-password -U`).               ║
# ║  Does NOT delete .env — that is a manual final step AFTER you confirm    ║
# ║  the Brain still boots from keychain alone.                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝

set -euo pipefail

NCL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${NCL_DIR}/.env"
STRIKE_TOKEN_FILE="${NCL_DIR}/.strike_token"

# ── Mapping: ENV_VAR_NAME -> keychain-service-name ────────────────────────────
# Matches runtime/api/config.py:_KEYCHAIN_ENV exactly.
declare -a KEY_MAP=(
  "ANTHROPIC_API_KEY:ncl-anthropic"
  "STRIKE_AUTH_TOKEN:ncl-strike-auth-token"
  "XAI_API_KEY:ncl-xai"
  "GOOGLE_API_KEY:ncl-google"
  "GEMINI_API_KEY:ncl-gemini"
  "OPENAI_API_KEY:ncl-openai"
  "PERPLEXITY_API_KEY:ncl-perplexity"
  "COPILOT_API_KEY:ncl-copilot"
  "X_BEARER_TOKEN:ncl-x-bearer"
  "YOUTUBE_API_KEY:ncl-youtube"
  "UNUSUAL_WHALES_API_KEY:ncl-unusual-whales"
  "UNUSUAL_WHALES_TOKEN:ncl-unusual-whales"
  "PAPERCLIP_AGENT_KEY:ncl-paperclip-agent"
  "PAPERCLIP_API_KEY:ncl-paperclip-agent"
  "PAPERCLIP_COMPANY_ID:ncl-paperclip-company"
  "REDDIT_CLIENT_ID:ncl-reddit-client-id"
  "REDDIT_CLIENT_SECRET:ncl-reddit-client-secret"
  "NTFY_TOPIC:ncl-ntfy-topic"
  "PUSHOVER_APP_TOKEN:ncl-pushover-app-token"
  "PUSHOVER_USER_KEY:ncl-pushover-user-key"
  "DISCORD_BOT_TOKEN:ncl-discord-bot"
  "SNAPTRADE_CLIENT_ID:ncl-snaptrade-client-id"
  "SNAPTRADE_CONSUMER_KEY:ncl-snaptrade-consumer-key"
  "SNAPTRADE_USER_ID:ncl-snaptrade-user-id"
  "SNAPTRADE_USER_SECRET:ncl-snaptrade-user-secret"
  "GNEWS_API_KEY:ncl-gnews"
  "NEWSAPI_KEY:ncl-newsapi"
  "TICKETMASTER_API_KEY:ncl-ticketmaster"
  "COHERE_API_KEY:ncl-cohere"
  "NDAX_API_KEY:ncl-ndax-key"
  "NDAX_API_SECRET:ncl-ndax-secret"
  "NDAX_USER_ID:ncl-ndax-user-id"
  "METAMASK_ADDRESS:ncl-metamask-address"
  "POLYMARKET_PRIVATE_KEY:ncl-polymarket-private-key"
  "POLYMARKET_FUNDER_ADDRESS:ncl-polymarket-funder-address"
)

# ── Mask helper — never echo full key values ──────────────────────────────────
mask() {
  local v="$1"
  local n=${#v}
  if [ "$n" -le 8 ]; then echo "********"; return; fi
  echo "${v:0:4}…${v: -4}"
}

# ── Read a value from .env (strips quotes + surrounding whitespace) ───────────
read_env_value() {
  local var_name="$1"
  local env_path="$2"
  [ -f "$env_path" ] || return 1
  local line
  line=$(grep -E "^[[:space:]]*${var_name}=" "$env_path" | head -n1) || return 1
  [ -z "$line" ] && return 1
  local value="${line#*=}"
  # Strip leading/trailing whitespace
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  # Strip surrounding quotes (single or double)
  if [[ "$value" =~ ^\".*\"$ ]] || [[ "$value" =~ ^\'.*\'$ ]]; then
    value="${value:1:${#value}-2}"
  fi
  printf '%s' "$value"
}

# ── Write a single secret to keychain (idempotent: -U updates if exists) ──────
write_secret() {
  local service="$1"
  local value="$2"
  security add-generic-password -U \
    -s "$service" \
    -a "$USER" \
    -w "$value" >/dev/null 2>&1
}

# ── Pre-flight ────────────────────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi

if ! command -v security >/dev/null 2>&1; then
  echo "ERROR: macOS 'security' command unavailable — this script only runs on macOS" >&2
  exit 1
fi

echo "═══════════════════════════════════════════════════════════════════════"
echo "  NCL SECRETS MIGRATION — .env → macOS Keychain"
echo "  Source: $ENV_FILE"
echo "  Keychain account: $USER"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""

migrated=0
skipped_empty=0
skipped_missing=0

for entry in "${KEY_MAP[@]}"; do
  env_name="${entry%%:*}"
  service="${entry##*:}"

  if ! value=$(read_env_value "$env_name" "$ENV_FILE"); then
    printf "  [SKIP missing] %-32s -> %s\n" "$env_name" "$service"
    skipped_missing=$((skipped_missing + 1))
    continue
  fi

  if [ -z "$value" ]; then
    printf "  [SKIP empty  ] %-32s -> %s\n" "$env_name" "$service"
    skipped_empty=$((skipped_empty + 1))
    continue
  fi

  write_secret "$service" "$value"
  printf "  [OK          ] %-32s -> %-32s (%s)\n" "$env_name" "$service" "$(mask "$value")"
  migrated=$((migrated + 1))
done

# ── Strike-Token side-channel: prefer .strike_token file if it exists ─────────
if [ -f "$STRIKE_TOKEN_FILE" ]; then
  echo ""
  echo "── .strike_token detected — migrating to ncl-strike-auth-token ──────"
  token=$(tr -d '[:space:]' < "$STRIKE_TOKEN_FILE")
  if [ -n "$token" ]; then
    write_secret "ncl-strike-auth-token" "$token"
    printf "  [OK          ] %-32s -> %-32s (%s)\n" ".strike_token" "ncl-strike-auth-token" "$(mask "$token")"
    migrated=$((migrated + 1))
  fi
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════"
echo "  SUMMARY"
echo "  Migrated:        $migrated"
echo "  Skipped (empty): $skipped_empty"
echo "  Skipped (gone):  $skipped_missing"
echo "═══════════════════════════════════════════════════════════════════════"
echo ""
echo "MIGRATION COMPLETE — next: revoke keys at provider consoles, then delete .env"
echo ""
echo "Verify a key landed in keychain:"
echo "  security find-generic-password -s ncl-anthropic -a \"\$USER\" -w | head -c 8 ; echo"
echo ""
echo "After provider key rotation + Brain restart smoke test, scrub disk version:"
echo "  cp ~/dev/NCL/.env ~/dev/NCL/.env.backup.\$(date +%Y%m%d-%H%M%S)"
echo "  rm ~/dev/NCL/.env"
echo "  [ -f ~/dev/NCL/.strike_token ] && rm ~/dev/NCL/.strike_token"
