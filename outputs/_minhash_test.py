import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.memory.minhash_dedup import MinHashDedupIndex


idx = MinHashDedupIndex()
docs = [
    ("u1", "Fed signals possible June rate hold; markets react with broad rally across sectors"),
    (
        "u2",
        "Federal Reserve signals June rate pause; markets respond with sector-wide rally",
    ),  # near-dup of u1
    ("u3", "TSLA earnings crush expectations, revenue up 38% YoY"),
    ("u4", "NVDA misses revenue estimates, margins decline 200bps QoQ"),
    ("u5", "Tesla earnings beat expectations significantly with revenue up 38%"),  # near-dup of u3
]
for uid, text in docs:
    idx.add(uid, text)

print(f"index size: {len(idx)}")
print()
print("--- query 'Fed signals June rate pause; markets rally':")
hits = idx.query_with_scores("Fed signals June rate pause; markets rally", top_k=5)
for uid, score in hits:
    print(f"  {uid}  J={score:.3f}")
print()
print("--- query 'TSLA crushed earnings huge revenue':")
hits = idx.query_with_scores("TSLA crushed earnings huge revenue", top_k=5)
for uid, score in hits:
    print(f"  {uid}  J={score:.3f}")
print()
print("--- query unrelated text 'crypto markets stabilize':")
hits = idx.query_with_scores("crypto markets stabilize after week of volatility", top_k=5)
print(f"  hits: {len(hits)} (expected 0)")

# Test persistence
import pathlib
import tempfile


tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="minhash-test-"))
idx.save(tmpdir)
idx2 = MinHashDedupIndex.open(tmpdir)
print(f"\nreloaded index size: {len(idx2)}")
hits2 = idx2.query_with_scores("Fed signals June rate pause", top_k=3)
print(f"reload query hits: {[f'{u}:{s:.3f}' for u,s in hits2]}")
