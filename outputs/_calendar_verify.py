import asyncio
import datetime as dt
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.calendar.events import get_all_events
from runtime.calendar.local_events import get_local_events


async def main():
    s = dt.date.today()
    e = s + dt.timedelta(days=14)
    print("=== events get_all (with Fed RSS):")
    evs = await get_all_events(s, e, include_economic=False)
    fed = [x for x in evs if x.get("source") == "fed_rss"]
    print(f"  total={len(evs)}  fed_rss={len(fed)}")
    for f in fed[:5]:
        print(f"   {f['date']} [{f['category']:9s}] {f['title'][:70]}")

    print("=== local_events Edmonton:")
    ee = await get_local_events("edmonton", s, e)
    edm_new = [x for x in ee if x.get("source") == "data.edmonton.ca"]
    print(f"  total={len(ee)}  data.edmonton.ca={len(edm_new)}")
    for x in edm_new[:5]:
        print(f"   {x['date']} [{x.get('category')}] {x['title'][:60]} @ {x.get('venue','')[:30]}")


asyncio.run(main())
