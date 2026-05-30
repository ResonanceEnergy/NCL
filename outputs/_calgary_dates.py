import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx


async def main():
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        r = await c.get(
            "https://www.eventbrite.ca/d/canada--calgary/all-events/",
            headers={"User-Agent": "Mozilla/5.0 (NCL personal-AI)"},
        )
        blocks = re.findall(
            r'<script type="application/ld\+json">(.+?)</script>', r.text, re.DOTALL
        )
        for block in blocks:
            try:
                d = json.loads(block)
            except:
                continue
            if not (isinstance(d, dict) and d.get("@type") == "ItemList"):
                continue
            items = d.get("itemListElement") or []
            print(f"itemListElement n={len(items)}")
            for entry in items[:5]:
                item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
                name = item.get("name", "")
                raw_start = item.get("startDate", "")
                print(f"  {name[:50]}  startDate={raw_start!r}")
                if raw_start:
                    try:
                        dt = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                        print(f"    parsed: {dt} date={dt.date()}")
                    except Exception as e:
                        print(f"    PARSE FAIL: {e}")
        # Today + horizon
        today = datetime.now(timezone.utc).date()
        horizon = today + timedelta(days=30)
        print(f"\nwindow: {today} to {horizon}")


asyncio.run(main())
