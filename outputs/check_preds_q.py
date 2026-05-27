#!/usr/bin/env python3
import json
import subprocess


H = ["-H", "Authorization: Bearer QKpHcK8lnL9s4P4mFkwzN4ugLP9sokvBWrmqNcs2ItU"]
r = subprocess.run(
    ["curl", "-sS"] + H + ["http://100.72.223.123:8800/predictions?limit=6&sort=confidence"],
    capture_output=True,
    text=True,
    timeout=15,
)
d = json.loads(r.stdout)
print("=== Wave 14Q LIST (confidence now = stated probability) ===")
for p in d.get("predictions", []):
    stated = p.get("stated_probability")
    cons = p.get("consensus_score")
    win = p.get("forecast_window_days")
    cs = p.get("cited_sources_full", [])
    cons_str = f"{cons:.2f}" if cons else "-"
    print(
        f"  conf={p.get('confidence',0):.2f}  stated={stated if stated else '-'}  "
        f"cons={cons_str}  win={win}d  "
        f"sources={len(cs)}"
    )
    print(f"    {p.get('title')[:80]}")

# Pick the BTC one (originally had win=None) to test new forecast parsing
btc = next((p for p in d.get("predictions", []) if "Bitcoin" in (p.get("title") or "")), None)
if btc:
    print("\n=== Forecast parsing verify (was None: 'through May 27') ===")
    print(f"  title: {btc.get('title')}")
    print(f"  forecast_window_days: {btc.get('forecast_window_days')}")
    print(f"  expires_at_iso: {btc.get('expires_at_iso')}")
