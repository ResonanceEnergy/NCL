import asyncio
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence import free_sources as fs


async def main():
    events = await fs.fetch_calgary_events(days_ahead=30, limit=20)
    print(f"got {len(events)} Calgary events")
    for e in events[:8]:
        print(f"  {e['date']:10s}  {e['title'][:65]:65s}  @ {e['venue'][:30]}")
    await fs.aclose()


asyncio.run(main())
