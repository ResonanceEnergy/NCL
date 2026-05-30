import asyncio

import httpx


async def main():
    async with httpx.AsyncClient(timeout=15) as c:
        for name in [
            "E-MINI S&P 500 STOCK INDEX - CHICAGO MERCANTILE EXCHANGE",
            "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE",
            "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE",
            "RUSSELL 2000 MINI INDEX FUTURE - ICE FUTURES U.S.",
            "BITCOIN - CHICAGO MERCANTILE EXCHANGE",
        ]:
            r = await c.get(
                "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
                params={
                    "$where": f"market_and_exchange_names = '{name}'",
                    "$select": "report_date_as_yyyy_mm_dd, lev_money_positions_long, lev_money_positions_short",
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                    "$limit": "2",
                },
            )
            rows = r.json() if r.status_code == 200 else []
            print(f"=== {name[:55]}")
            for row in rows:
                print(
                    f"  {row['report_date_as_yyyy_mm_dd'][:10]}  lev_long={int(row.get('lev_money_positions_long',0)):,}"
                )


asyncio.run(main())
