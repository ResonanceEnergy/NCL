#!/bin/bash
set -e
cd /Users/natrix/dev/NCL

echo "=== status ==="
git status --short

echo ""
echo "=== diff stat ==="
git diff --stat

echo ""
echo "=== staging the 3 changed files ==="
git add runtime/councils/youtube/scraper.py
git add runtime/api/routes.py
git add runtime/api/routers/council.py
git status --short

echo ""
echo "=== commit ==="
git commit -m "Wave 14X-1A: YTC channel-fairness fix + silent-channel observability

- scraper: removed _strike_point_score keyword bias from selection sort
  (was implicitly favoring crypto/macro keywords, starving Stock Moe,
  Chris Williamson, Follow the Money for weeks). Now sorts by
  upload_date desc — channels compete on recency, not keywords.
  strike_score still recorded on each video as a downstream metric.

- scraper: added per-channel entry-count + silent-channel logging so
  silent failures become visible in the log stream instead of
  disappearing into the void.

- routes.py: removed hardcoded 'YouTube Council (legacy)' stub from
  the /autonomous/loops response. It was producing a phantom duplicate
  row in iOS alongside ncl-ytc-dedicated. Now: one canonical YTC row.

- routers/council.py: NEW GET /council/youtube/channels/health endpoint.
  Walks recent reports per configured channel, classifies FRESH/STALE/
  SILENT, surfaces silent_handles list. Lets us catch silent-failing
  channels in seconds instead of weeks.

Live verification (post-bounce):
  /autonomous/loops YTC entries: 2 -> 1
  /council/youtube/channels/health: 14 configured, 11 fresh, 0 stale,
    3 SILENT: ['stockmoe', 'following-the-money', 'chriswillx']

The 3 silent channels resolve fine via yt-dlp probe (all active,
posting recent videos). Either the scraper's specific options or
JS-runtime deprecation is dropping them; per-channel logs will tell
us on the next cycle. Date-sort change should also let them compete
fairly if they were just being out-scored.

Wave 14X-1A is the first slice of the broader revamp documented in
outputs/REVAMP_2026-05-29.md (NCL+FirstStrike two-camp split:
AWAREBOT/INTEL entertainment vs TRADERAGENT/PORTFOLIO trading)."

echo ""
echo "=== push ==="
git push origin HEAD 2>&1 | tail -5
