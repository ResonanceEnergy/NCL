import asyncio

import httpx


async def main():
    async with httpx.AsyncClient(timeout=15) as c:
        # Find distinct S&P / Gold / Crude markets in the current TFF dataset
        for keyword in ["S&P 500", "GOLD", "CRUDE OIL", "BITCOIN", "NASDAQ", "RUSSELL"]:
            r = await c.get(
                "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
                params={
                    "$where": f"market_and_exchange_names like '%{keyword}%'",
                    "$select": "DISTINCT market_and_exchange_names",
                    "$limit": "10",
                },
            )
            if r.status_code == 200:
                names = sorted(set(row["market_and_exchange_names"] for row in r.json()))
                print(f"=== {keyword}:")
                for n in names:
                    print(f"  {n}")


asyncio.run(main())
