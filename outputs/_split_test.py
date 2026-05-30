import asyncio
import datetime as dt
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.calendar.events import get_all_events_split


async def main():
    s = dt.date.today()
    e = s + dt.timedelta(days=14)
    split = await get_all_events_split(s, e, include_economic=False, city_id="edmonton")
    print(f"counts: {split['counts']}")
    print(f"\nFINANCIAL ({len(split['financial'])}):")
    for ev in split["financial"][:8]:
        print(f"  {ev['date']:10s} [{ev.get('category'):12s}] {ev.get('title','')[:60]}")
    print(f"\nINFOTAINMENT ({len(split['infotainment'])}):")
    for ev in split["infotainment"][:8]:
        print(f"  {ev['date']:10s} [{ev.get('category'):12s}] {ev.get('title','')[:60]}")


asyncio.run(main())
