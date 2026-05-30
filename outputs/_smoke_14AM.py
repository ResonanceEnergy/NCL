import asyncio
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence import free_sources as fs


async def main():
    print("=== SEC EDGAR earnings calendar (next 14d):")
    earn = await fs.fetch_sec_earnings_calendar(days_back=30, days_ahead=14, limit_per_ticker=2)
    print(f"  got {len(earn)} rows")
    for e in earn[:5]:
        print(f"   {e['date']:10s}  {e['ticker']:6s}  {e['company'][:50]}  form={e['form']}")

    print()
    print("=== SEC Form 4 insider trades (AAPL, NVDA, TSLA last 30d):")
    insider = await fs.fetch_sec_form4_insider(
        ("AAPL", "NVDA", "TSLA"), days_back=30, limit_per_ticker=5
    )
    print(f"  got {len(insider)} rows")
    for r in insider[:6]:
        print(
            f"   {r['transaction_date']}  {r['ticker']:6s}  {r['company'][:40]}  url={r['url'][:60]}..."
        )

    print()
    print("=== GDELT events today (10 keywords):")
    gdelt = await fs.fetch_gdelt_events_today()
    print(f"  got {len(gdelt)} articles")
    by_kw = {}
    for g in gdelt:
        by_kw.setdefault(g["keyword"], 0)
        by_kw[g["keyword"]] += 1
    for kw, n in sorted(by_kw.items()):
        print(f"   {kw:25s} {n}")
    if gdelt:
        sample = gdelt[0]
        print(f"   sample: {sample['title'][:80]}")
        print(f"           {sample['domain']}  {sample['url'][:80]}")

    print()
    print("=== Tradier sandbox Greeks (TRADIER_API_KEY presence test):")
    chain = await fs.fetch_tradier_options_chain("AAPL", greeks=True)
    if not chain:
        print("  empty — TRADIER_API_KEY not in env (expected until NATRIX adds it)")
    else:
        print(f"  symbol={chain['symbol']} expiration={chain['expiration']}")
        print(f"  calls={len(chain['calls'])} puts={len(chain['puts'])}")
        if chain["calls"]:
            c0 = chain["calls"][0]
            print(
                f"  sample call: strike={c0.get('strike')} delta={c0.get('delta')} gamma={c0.get('gamma')}"
            )

    await fs.aclose()


asyncio.run(main())
