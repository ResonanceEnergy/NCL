#!/usr/bin/env python3
import json
import re


# Handle concatenated JSON
raw = open("/tmp/pro_brief_s.json").read()
dec = json.JSONDecoder()
d, _ = dec.raw_decode(raw)
text = d.get("full_brief", "")
print(f"=== BRIEF SIZE: {len(text)} chars ===")
print(f"=== GENERATED_AT: {d.get('generated_at')} ===\n")

BLOCKS = [
    "PORTFOLIO",
    "AGENT",
    "ROTATION",
    "GOAT",
    "BRAVO",
    "OPTIONS",
    "CRYPTO",
    "POLYMARKET",
    "PREDICTIONS",
    "YTC",
    "CONTEXT",
    "TODO_7DAY",
]

results = []
for b in BLOCKS:
    hp = rf"── {re.escape(b)} \(as of (\S+)Z · src: (\S+)(?: · (\d+) items)?\) ──"
    m = re.search(hp, text)
    if not m:
        results.append((b, "MISSING", "", 0, ""))
        continue
    body_start = m.end()
    nb = text.find("\n── ", body_start)
    if nb < 0:
        nb = text.find("\n═══", body_start)
    body = text[body_start:nb].strip() if nb > 0 else text[body_start:].strip()
    count = int(m.group(3)) if m.group(3) else 0
    is_empty = (
        "(no data)" in body
        or "(no flow data)" in body
        or "(no scheduled" in body
        or "(no fresh scan" in body
        or not body
    )
    err = "render error" in body
    results.append((b, "✓", m.group(2), count, body[:400], is_empty, err))

print(f"{'BLOCK':12s} STATUS  COUNT  EMPTY  ERR")
print("-" * 50)
for r in results:
    if r[1] == "MISSING":
        print(f"{r[0]:12s} MISSING")
        continue
    b, _, src, count, body, empty, err = r
    print(f"{b:12s}  OK   {count:>5d}   {'Y' if empty else 'n':>4s}   {'Y' if err else 'n':>3s}")

print("\n=== BODY SAMPLES ===")
for r in results:
    if r[1] == "MISSING":
        continue
    b, _, src, count, body, empty, err = r
    flag = "EMPTY" if empty else ("ERR" if err else "OK")
    print(f"\n── {b} [{flag}] (src={src}) ──")
    for line in body.split("\n")[:8]:
        print(f"   {line}")
