#!/bin/bash
TOKEN=$(grep STRIKE_AUTH_TOKEN /Users/natrix/dev/NCL/.env | awk -F= '{print $2}' | tr -d '"')
echo "=== GOAT ==="
curl -sS -m 90 -H "Authorization: Bearer $TOKEN" \
    http://100.72.223.123:8800/stocks/scanner/goat \
    > /tmp/goat.out 2>&1
wc -c /tmp/goat.out
head -c 400 /tmp/goat.out
echo
echo
echo "=== BRAVO ==="
curl -sS -m 90 -H "Authorization: Bearer $TOKEN" \
    http://100.72.223.123:8800/stocks/scanner/bravo \
    > /tmp/bravo.out 2>&1
wc -c /tmp/bravo.out
head -c 400 /tmp/bravo.out
touch /tmp/scanners.done
