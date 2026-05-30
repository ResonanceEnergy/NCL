"""Probe Socrata schemas to fix Wave 14AH column-name issues."""

import asyncio

import httpx


async def main():
    async with httpx.AsyncClient(timeout=15) as c:
        # 1. Edmonton events — find actual column names
        r = await c.get("https://data.edmonton.ca/resource/64u3-c7bh.json", params={"$limit": "1"})
        print("=== Edmonton events sample row keys:")
        if r.status_code == 200 and r.json():
            print(" ", sorted(r.json()[0].keys()))
        else:
            print(f"  status {r.status_code} body={r.text[:200]}")

        # 2. Calgary — try alternate dataset ids
        for ds_id in ["c2es-76ed", "kxnh-mkjf", "wrrn-gjwq"]:
            r = await c.get(
                f"https://data.calgary.ca/resource/{ds_id}.json", params={"$limit": "1"}
            )
            print(f"=== Calgary {ds_id} status={r.status_code}")
            if r.status_code == 200:
                rows = r.json()
                if rows:
                    print(" ", sorted(rows[0].keys())[:15])

        # 3. CFTC COT — find the latest dataset (the one I tried has old data)
        # Recommended: traders-in-financial-futures (TFF) Aggregated
        # current dataset id: gpe5-46if  OR  6dca-aqww (Disaggregated)
        for ds_id in ["gpe5-46if", "6dca-aqww", "jun7-fc8e", "ywwf-hesh"]:
            try:
                r = await c.get(
                    f"https://publicreporting.cftc.gov/resource/{ds_id}.json",
                    params={"$limit": "1", "$order": "report_date_as_yyyy_mm_dd DESC"},
                )
                if r.status_code != 200:
                    print(f"=== CFTC {ds_id} status={r.status_code}")
                    continue
                rows = r.json()
                if rows:
                    r0 = rows[0]
                    print(
                        f"=== CFTC {ds_id}  rows={len(rows)}  report_date={r0.get('report_date_as_yyyy_mm_dd','?')}"
                    )
                    # Print fields that look like positioning
                    keys = sorted(
                        k for k in r0.keys() if "long" in k or "short" in k or "position" in k
                    )
                    print(f"  positioning keys: {keys[:10]}")
                    print(f"  market_name sample: {r0.get('market_and_exchange_names','')}")
            except Exception as e:
                print(f"=== CFTC {ds_id} error: {e}")


asyncio.run(main())
