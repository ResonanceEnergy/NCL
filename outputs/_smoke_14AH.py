import asyncio
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence import free_sources as fs


async def main():
    print("=== Fed speeches")
    sp = await fs.fetch_fed_speeches(limit=3)
    print(f"  got {len(sp)}; sample={sp[0]['title'][:60] if sp else None!r}")

    print("=== Fed press releases")
    pr = await fs.fetch_fed_press_releases(limit=3)
    print(f"  got {len(pr)}; sample={pr[0]['title'][:60] if pr else None!r}")

    print("=== CCXT crypto (binance public)")
    cx = await fs.fetch_ccxt_tickers(symbols=("BTC/USDT", "ETH/USDT", "SOL/USDT"))
    print(f"  got {len(cx)}")
    for r in cx[:3]:
        print(f"  {r['symbol']:12s} ${r['last_usd']:,.2f}  24h={r['pct_change_24h']:+.2f}%")

    print("=== Open-Meteo air quality Edmonton")
    aq = await fs.fetch_open_meteo_air_quality("edmonton")
    print(
        f"  uv_now={aq.get('uv_index_now')} uv_max={aq.get('uv_index_max_today')} aqi={aq.get('aqi_us')} pm2.5={aq.get('pm2_5_now')}"
    )

    print("=== CFTC COT (ES + GC + CL)")
    cot = await fs.fetch_cftc_cot(markets=("ES", "GC", "CL"), limit_per_market=2)
    print(f"  got {len(cot)} rows")
    if cot:
        r = cot[0]
        print(
            f"  {r['ticker']} report={r['report_date'][:10]} lev_net={r['leveraged_net']:,} dl_net={r['dealer_net']:,}"
        )

    print("=== Edmonton events")
    edm = await fs.fetch_edmonton_events(days_ahead=14)
    print(f"  got {len(edm)} events")
    if edm:
        print(f"  sample: {edm[0]['title'][:60]} on {edm[0]['date'][:10]}")

    print("=== Calgary events")
    cgy = await fs.fetch_calgary_events(days_ahead=14)
    print(f"  got {len(cgy)} events")

    await fs.aclose()


asyncio.run(main())
