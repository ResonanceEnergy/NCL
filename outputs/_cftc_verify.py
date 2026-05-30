import asyncio
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence import free_sources as fs


async def main():
    cot = await fs.fetch_cftc_cot(markets=("ES", "NQ", "RTY", "BTC"), limit_per_market=1)
    print(f"got {len(cot)} rows")
    for r in cot:
        print(
            f"  {r['ticker']:6s} report={r['report_date']} lev_net={r['leveraged_net']:+,} am_net={r['asset_mgr_net']:+,} dl_net={r['dealer_net']:+,}"
        )
    await fs.aclose()


asyncio.run(main())
