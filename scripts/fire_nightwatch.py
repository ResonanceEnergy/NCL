#!/usr/bin/env python3
"""Trigger Night Watch manually via the running Brain.

Hits the Brain's internal trigger endpoint OR (if no endpoint) imports the
scheduler directly. Uses Brain's autonomous scheduler via the running app.
"""
import asyncio
import os
import sys

# Add NCL to path
sys.path.insert(0, os.path.expanduser("~/dev/NCL"))

async def main():
    # We can't reach the in-process scheduler from a side-script, but we can
    # call a manual-trigger endpoint if one exists. Try a few common ones.
    import urllib.request, json

    token = ""
    for line in open(os.path.expanduser("~/dev/NCL/.env")):
        if line.startswith("STRIKE_AUTH_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
            break

    # Try a manual trigger endpoint
    for path, method in [
        ("/autonomous/night-watch/run?catchup=true", "POST"),
        ("/autonomous/night-watch/run", "POST"),
        ("/autonomous/nightwatch/trigger", "POST"),
    ]:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:8800{path}",
                method=method,
                headers={"Authorization": f"Bearer {token}"},
                data=b"",
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                body = r.read().decode()
                print(f"OK {path} ->", body[:500])
                return
        except urllib.error.HTTPError as e:
            print(f"  {path}: HTTP {e.code}")
        except Exception as e:
            print(f"  {path}: {e}")

    print("No manual trigger endpoint found. Will need to wait for next 2am ET cycle OR")
    print("the boot-time catch-up should have fired automatically — check stderr for [NIGHT-WATCH].")

if __name__ == "__main__":
    asyncio.run(main())
