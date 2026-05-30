"""Train the first BERTopic theme model on the last 7d of agent_signals.jsonl."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.cross_reference.bertopic_themes import train_bertopic_themes


cutoff = datetime.now(timezone.utc) - timedelta(days=7)
texts = []
with open("data/intelligence/agent_signals.jsonl") as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = d.get("timestamp") or d.get("created_at") or ""
        try:
            t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except Exception:
            continue
        if t < cutoff:
            continue
        text = d.get("title") or d.get("content") or ""
        text = str(text).strip()
        if text:
            texts.append(text[:500])

print(f"Loaded {len(texts)} signal texts from last 7d")
# Cap to 4000 — UMAP doesn't need millions to find clusters
if len(texts) > 4000:
    print(f"  sampling 4000 of {len(texts)}")
    import random

    random.seed(42)
    texts = random.sample(texts, 4000)

result = train_bertopic_themes(texts, min_topic_size=15)
print(f"\nTrained — n_topics={result['n_topics']} elapsed={result['train_elapsed_s']}s")
print(f"Saved to: {result['saved_to']}")
print()
print("Top 15 learned topic labels:")
for tid, label in list(result["topic_labels"].items())[:15]:
    print(f"  {tid:3d}: {label}")
