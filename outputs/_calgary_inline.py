"""Manual replay of fetch_calgary_events logic with prints."""

import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import httpx


async def main():
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=30)
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        r = await c.get(
            "https://www.eventbrite.ca/d/canada--calgary/all-events/",
            headers={"User-Agent": "Mozilla/5.0 (NCL personal-AI)"},
        )
        html = r.text
    blocks = re.findall(r'<script type="application/ld\+json">(.+?)</script>', html, re.DOTALL)
    print(f"blocks: {len(blocks)}")
    out = []
    for bi, block in enumerate(blocks):
        try:
            data = json.loads(block)
        except Exception as e:
            print(f"  block {bi} JSON parse FAIL: {e}")
            continue
        print(
            f"  block {bi}: type={type(data).__name__}, @type={data.get('@type') if isinstance(data, dict) else 'N/A'}"
        )
        if not (isinstance(data, dict) and data.get("@type") == "ItemList"):
            continue
        items = data.get("itemListElement") or []
        print(f"     items: {len(items)}")
        for ii, entry in enumerate(items):
            if not isinstance(entry, dict):
                print(f"     entry {ii}: not dict")
                continue
            item = entry.get("item") if isinstance(entry.get("item"), dict) else entry
            if not isinstance(item, dict):
                print(f"     entry {ii}: item not dict")
                continue
            title = (item.get("name") or "").strip()
            if not title:
                print(f"     entry {ii}: no title")
                continue
            raw_start = item.get("startDate", "")
            try:
                evt_date = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).date()
            except Exception:
                try:
                    evt_date = datetime.fromisoformat(raw_start[:10]).date()
                except:
                    evt_date = None
            in_window = evt_date is not None and today <= evt_date <= horizon
            print(f"     {ii}: title={title[:40]!r} date={evt_date} in_window={in_window}")
            if evt_date is not None and not in_window:
                continue
            out.append(
                {"title": title, "date": evt_date.isoformat() if evt_date else raw_start[:10]}
            )
    print(f"\nout total: {len(out)}")


asyncio.run(main())
