#!/usr/bin/env python3
"""Pretty-print /autonomous/loops output for the audit verification."""
import json, sys, os, urllib.request

token = ""
for line in open(os.path.expanduser("~/dev/NCL/.env")):
    if line.startswith("STRIKE_AUTH_TOKEN="):
        token = line.split("=", 1)[1].strip().strip('"').strip("'")
        break

req = urllib.request.Request(
    "http://127.0.0.1:8800/autonomous/loops",
    headers={"Authorization": f"Bearer {token}"},
)
with urllib.request.urlopen(req, timeout=8) as r:
    d = json.load(r)

print(f"total loops: {len(d['loops'])}")
for l in d["loops"]:
    state = "ON " if l["active"] else "off"
    lr = l["last_run"] or "never"
    iv = l["interval"]
    print(f"  [{state}] {l['id']:30s} every {iv:>6}s   last_run={lr}")
