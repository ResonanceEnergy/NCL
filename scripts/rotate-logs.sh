#!/usr/bin/env bash
# rotate-logs.sh — NCL log housekeeping
#
# - Truncates active *.log > 100MB to last 10MB
# - Moves *.log files > 14 days old into logs/archive/
# - gzips archive files > 30 days old
# - Deletes archive *.gz > 90 days old
#
# Usage:  ./scripts/rotate-logs.sh
# Cron:   0 4 * * 0  /Users/natrix/dev/NCL/scripts/rotate-logs.sh
set -euo pipefail

LOGS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/logs"
ARCHIVE="$LOGS_DIR/archive"
mkdir -p "$ARCHIVE"

cd "$LOGS_DIR"

# 1) Truncate huge active logs (keep last ~10MB so tail is intact)
for f in *.log; do
    [ -f "$f" ] || continue
    sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
    if [ "$sz" -gt 104857600 ]; then  # 100MB
        tail -c 10485760 "$f" > "$f.tmp" && mv "$f.tmp" "$f"
        echo "truncated $f (was $((sz/1024/1024))MB → 10MB)"
    fi
done

# 2) Archive log files older than 14 days
find . -maxdepth 1 -type f -mtime +14 \( -name "*.log" -o -name "*.log.*" \) \
    -exec mv {} "$ARCHIVE/" \; 2>/dev/null || true

# 3) gzip archive files older than 30 days (skip already-gzipped)
find "$ARCHIVE" -type f -mtime +30 ! -name "*.gz" -exec gzip {} \; 2>/dev/null || true

# 4) Delete archived gzips older than 90 days
find "$ARCHIVE" -type f -mtime +90 -name "*.gz" -delete 2>/dev/null || true

echo "rotate-logs done. logs=$(du -sh "$LOGS_DIR" | cut -f1) archive=$(du -sh "$ARCHIVE" | cut -f1)"
