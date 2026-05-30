import asyncio
import json
import re

import httpx


async def main():
    # Clear any cached state
    import os
    import sys

    sys.path.insert(0, "/Users/natrix/dev/NCL")
    os.chdir("/Users/natrix/dev/NCL")
    from runtime.intelligence import free_sources as fs

    fs._cache.clear()

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        r = await c.get(
            "https://www.eventbrite.ca/d/canada--calgary/all-events/",
            headers={"User-Agent": "Mozilla/5.0 (NCL personal-AI)"},
        )
        print(f"status: {r.status_code}  body_len: {len(r.text)}")
        # Count JSON-LD blocks
        blocks = re.findall(
            r'<script type="application/ld\+json">(.+?)</script>', r.text, re.DOTALL
        )
        print(f"JSON-LD blocks: {len(blocks)}")
        for i, b in enumerate(blocks):
            try:
                d = json.loads(b)
                if isinstance(d, dict):
                    t = d.get("@type", "")
                    items = d.get("itemListElement") or []
                    print(f"  block {i}: @type={t!r} itemList n={len(items)}")
                    if items:
                        for it in items[:3]:
                            item = it.get("item") if isinstance(it.get("item"), dict) else it
                            print(
                                f"     - {(item.get('name','') if isinstance(item, dict) else str(it))[:50]}"
                            )
            except Exception as e:
                print(f"  block {i}: parse fail {e}")


asyncio.run(main())
