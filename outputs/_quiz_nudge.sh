#!/bin/bash
set -a
. /Users/natrix/dev/NCL/.env
set +a
T="$STRIKE_AUTH_TOKEN"
B="http://100.72.223.123:8800"

# 1. Check today's quiz state
echo "=== /journal/morning-quiz/today ==="
curl -sS --max-time 8 -H "Authorization: Bearer $T" "$B/journal/morning-quiz/today" | /opt/homebrew/bin/python3 -m json.tool | head -30

echo
echo "=== Manually fire morning-quiz ntfy via fixed JSON API ==="
NTFY_TOPIC="${NCL_NTFY_TOPIC:-ncl-natrix-intel-7x9k}"
/opt/homebrew/bin/python3 <<'PY'
import os, httpx, asyncio

async def push():
    topic = os.getenv("NCL_NTFY_TOPIC", "ncl-natrix-intel-7x9k")
    payload = {
        "topic": topic,
        "title": "Morning Quiz — 90s",
        "message": "Today's quiz didn't fire (06:00 nudge crashed on em-dash). Fixed now. Open FirstStrike → Journal → Quiz to set today's intention.",
        "priority": 4,
        "tags": ["sun_with_face", "books"],
        "click": "firststrike://journal/morning-quiz",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post("https://ntfy.sh/", json=payload)
        print("ntfy status:", r.status_code)
        print("ntfy body:", r.text[:200])

asyncio.run(push())
PY
echo DONE
