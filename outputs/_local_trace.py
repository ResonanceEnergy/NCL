import asyncio
import datetime as dt
import os
import sys
import traceback


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.calendar.local_events import get_local_events


async def main():
    s = dt.date.today()
    e = s + dt.timedelta(days=14)
    try:
        ee = await get_local_events("edmonton", s, e)
        print(f"type(ee)={type(ee).__name__}  len={len(ee) if ee else 0}")
        if ee:
            edm_new = [x for x in ee if x.get("source") == "data.edmonton.ca"]
            print(f"  data.edmonton.ca={len(edm_new)}")
            for x in edm_new[:5]:
                print(f"   {x.get('date','?')} {x.get('title','?')[:60]}")
    except Exception as e:
        traceback.print_exc()


asyncio.run(main())
