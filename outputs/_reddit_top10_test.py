import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.intelligence.brief_prep import _collect_reddit_top10


rows = _collect_reddit_top10()
print(f"reddit top10 count: {len(rows)}")
for r in rows[:5]:
    sub = r["subreddit"][:25]
    print(f"  {r['score']:.2f}  r/{sub:25s}  {r['age_min']:>4}m  {r['title'][:60]}")
