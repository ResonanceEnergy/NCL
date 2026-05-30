import asyncio
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence import local_sentiment as ls


async def main():
    print("=== FinBERT financial sentiment")
    for txt in [
        "Fed signals possible June rate hold; markets shrug",
        "TSLA crushes earnings, revenue up 38% YoY, raises FY guide",
        "NVDA misses on revenue, gross margins decline 200bps QoQ",
        "S&P 500 closes flat as traders await Fed minutes Wednesday",
    ]:
        r = await ls.score_financial(txt)
        print(f"  [{r['label']:9s} pol={r['polarity']:+.2f} {r['model']}] {txt[:65]}")

    print()
    print("=== Twitter-RoBERTa social sentiment")
    for txt in [
        "absolutely cooked nvda today imo",
        "bitcoin breaking out hard, momentum looks insane",
        "this market makes no sense, i'm done lol",
        "just hodling and ignoring the noise as usual",
    ]:
        r = await ls.score_social(txt)
        print(f"  [{r['label']:9s} pol={r['polarity']:+.2f} {r['model']}] {txt[:65]}")

    print()
    print("=== batch financial")
    batch = await ls.score_batch(
        [
            "Fed signals possible hold",
            "TSLA crushes earnings",
            "NVDA misses revenue",
        ],
        domain="financial",
    )
    for i, r in enumerate(batch):
        print(f"  {i}: {r['label']} pol={r['polarity']:+.2f}")


asyncio.run(main())
