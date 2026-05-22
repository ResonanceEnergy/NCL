#!/usr/bin/env bash
# Adds TICKETMASTER_API_KEY + NEWSAPI_KEY to ~/dev/NCL/.env
# Both are FREE-TIER keys; no charges if you stay under the limits below.
#
# TICKETMASTER:  https://developer-acct.ticketmaster.com/
#   Sign up -> "My Apps" -> create app -> Consumer Key is your API key.
#   Free tier: 5,000 requests/day, 5 req/sec. Plenty for 7-city hourly scan.
#
# NEWSAPI:       https://newsapi.org/register
#   Sign up -> Account -> API Key is shown immediately.
#   Free tier: 100 req/day (Developer plan). City scanner uses ~14/day total.

set -e
ENV_FILE="$HOME/dev/NCL/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "FATAL: $ENV_FILE not found"
    exit 1
fi

echo "==========================================================="
echo "NCL Brain — Event API Key Setup"
echo "==========================================================="
echo ""
echo "Get your keys first:"
echo "  Ticketmaster:  https://developer-acct.ticketmaster.com/"
echo "  NewsAPI:       https://newsapi.org/register"
echo ""
echo "Then paste them below (press Enter to skip either):"
echo ""

read -p "TICKETMASTER_API_KEY: " TM_KEY
read -p "NEWSAPI_KEY:          " NEWS_KEY

upsert_env() {
    local key="$1"
    local val="$2"
    if [ -z "$val" ]; then
        echo "  (skipped $key - empty input)"
        return
    fi
    if grep -qE "^${key}=" "$ENV_FILE"; then
        awk -v k="$key" -v v="$val" '$0 ~ "^" k "=" {print k "=" v; next} {print}' "$ENV_FILE" > "${ENV_FILE}.tmp"
        mv "${ENV_FILE}.tmp" "$ENV_FILE"
        echo "  Updated $key"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
        echo "  Added $key"
    fi
}

upsert_env "TICKETMASTER_API_KEY" "$TM_KEY"
upsert_env "NEWSAPI_KEY"          "$NEWS_KEY"

echo ""
echo "Restart Brain to pick up new keys:"
echo "  launchctl kickstart -k gui/\$(id -u)/com.resonanceenergy.ncl-brain"
echo ""
