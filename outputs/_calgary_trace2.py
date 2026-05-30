import asyncio
import logging
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
logging.basicConfig(level=logging.DEBUG)
from runtime.intelligence import free_sources as fs


async def main():
    fs._cache.clear()
    events = await fs.fetch_calgary_events(days_ahead=30, limit=20)
    print(f"\nFINAL got {len(events)} events")
    for e in events[:5]:
        print(f"  {e}")
    await fs.aclose()


asyncio.run(main())
