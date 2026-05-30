import asyncio
import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence.spoken_brief import render_text_to_wav


async def main():
    sample = (
        "NCL Morning Brief, May 30, 2026. "
        "Portfolio: paper account at twenty-five thousand dollars, fourteen trades closed today. "
        "Intel: Reddit chatter dominated by NVIDIA and Tesla; cross-reference engine flagged three converging signals. "
        "Calendar: FOMC press release expected next Wednesday; UV index in Edmonton peaks at six point nine. "
        "Journal: morning quiz pending. "
        "Memory: pinned priority is ship the cost audit deliverable today."
    )
    path = await render_text_to_wav(sample)
    print("rendered to:", path)
    if path and path.exists():
        print(f"size: {path.stat().st_size} bytes")
    else:
        print("FAIL no file")


asyncio.run(main())
