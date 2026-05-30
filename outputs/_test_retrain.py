import asyncio
import json
import sys
sys.path.insert(0, "/Users/natrix/dev/NCL")
from runtime.cross_reference.retrain_loop import retrain_once

res = asyncio.run(
    retrain_once(days=7, min_docs_per_source=3000, min_topic_size=10)
)
out = {k: v for k, v in res.items() if k != "per_source_counts"}
print(json.dumps(out, indent=2, default=str))
