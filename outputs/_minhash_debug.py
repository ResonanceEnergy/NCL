import os
import sys


sys.path.insert(0, "/Users/natrix/dev/NCL")
os.chdir("/Users/natrix/dev/NCL")
from runtime.memory.minhash_dedup import MinHashDedupIndex, _shingle


# Direct shingle inspection
a = "Fed signals possible June rate hold; markets react with broad rally across sectors"
b = "Federal Reserve signals June rate pause; markets respond with sector-wide rally"
q = "Fed signals June rate pause; markets rally"

sa = _shingle(a)
sb = _shingle(b)
sq = _shingle(q)
print(f"shingle counts:  a={len(sa)} b={len(sb)} q={len(sq)}")
print(f"overlap a∩b: {len(sa & sb)} shingles")
print(f"overlap a∩q: {len(sa & sq)} shingles")
print(f"overlap b∩q: {len(sb & sq)} shingles")
print(f"sample a shingles: {list(sa)[:5]}")
print(f"sample b shingles: {list(sb)[:5]}")
print(f"sample q shingles: {list(sq)[:5]}")
jab = len(sa & sb) / max(len(sa | sb), 1)
jaq = len(sa & sq) / max(len(sa | sq), 1)
jbq = len(sb & sq) / max(len(sb | sq), 1)
print("\nactual Jaccard:")
print(f"  a vs b = {jab:.3f}")
print(f"  a vs q = {jaq:.3f}")
print(f"  b vs q = {jbq:.3f}")

# Now do MinHash Jaccard estimate
idx = MinHashDedupIndex()
ma = idx._minhash_for(a)
mb = idx._minhash_for(b)
mq = idx._minhash_for(q)
print("\nMinHash Jaccard estimate:")
print(f"  a vs b = {float(ma.jaccard(mb)):.3f}")
print(f"  a vs q = {float(ma.jaccard(mq)):.3f}")
print(f"  b vs q = {float(mb.jaccard(mq)):.3f}")
