#!/usr/bin/env python3
"""QA dump of GOAT/BRAVO scanner outputs.

Same audit pattern as P16 for the morning brief:
  - structural completeness
  - signal age + freshness
  - ticker concentration + ETF-vs-stock bias
  - rule violations (e.g. broken liquidity/IVR gates)
  - cross-check against external truth
"""

import collections
import json
import sys


path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/goat.json"
name = sys.argv[2] if len(sys.argv) > 2 else "GOAT"

try:
    d = json.load(open(path))
except Exception as e:
    print(f"FAIL: cannot parse {path}: {e}")
    sys.exit(1)

print("=" * 78)
print(f"{name} SCANNER QA")
print("=" * 78)
print(f"file: {path}")
print(f"top-level keys: {list(d.keys())}")
print(f"scanned: {d.get('scanned', '?')}")
print(f"count returned: {d.get('count', '?')}")
print(f"scanner: {d.get('scanner', '?')}")

meta = d.get("scan_meta") or d.get("meta") or {}
if meta:
    print(f"scan_meta: {json.dumps(meta, default=str)[:300]}")

results = d.get("results") or []
print(f"\nresults count: {len(results)}")
if not results:
    print("NO RESULTS — investigate")
    sys.exit(0)

# Inspect first result for structural fields
print("\n=== FIRST RESULT (shape audit) ===")
r0 = results[0]
for k in sorted(r0.keys()):
    v = r0[k]
    if isinstance(v, (str, int, float, bool)) or v is None:
        print(f"  {k}: {v!r}")
    else:
        print(f"  {k}: {type(v).__name__} (len {len(v) if hasattr(v,'__len__') else '?'})")

# Score distribution
score_key = f"{name.lower()}_score"
scores = [r.get(score_key) for r in results if r.get(score_key) is not None]
if scores:
    print(f"\n=== {name.upper()} SCORE distribution ===")
    print(f"  count: {len(scores)}")
    print(f"  min: {min(scores)}  max: {max(scores)}  avg: {sum(scores)/len(scores):.1f}")
    bins = collections.Counter((s // 10) * 10 for s in scores)
    for b in sorted(bins.keys()):
        print(f"  {b}-{b+9}: {bins[b]}")

# Ticker breakdown — ETF vs stock
broad_etfs = {
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
    "VTI",
    "VOO",
    "VXX",
    "TLT",
    "IEF",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLI",
    "XLP",
    "XLY",
    "XLB",
    "XLU",
    "XLC",
    "XLRE",
    "GLD",
    "SLV",
    "USO",
    "UNG",
    "ARKK",
    "SMH",
    "SOXX",
}
tickers = [r.get("ticker", "?") for r in results]
etf_count = sum(1 for t in tickers if t.lstrip("$").upper() in broad_etfs)
stock_count = len(tickers) - etf_count
print("\n=== TICKER BIAS ===")
print(f"  individual stocks: {stock_count}")
print(f"  ETFs: {etf_count}")
print(f"  ratio idx:stk = {etf_count}:{stock_count}")

# Top tickers
ctr = collections.Counter(tickers)
print("\nTop 10 by score (or order):")
for r in results[:10]:
    print(
        f"  {r.get('ticker','?'):8s} {name.lower()}_score={r.get(score_key,'?')!s:>4} "
        f"price=${r.get('price', 0):.2f} sector={r.get('sector','?')}"
    )

# Stale / freshness check — look at signal/scan timestamps
print("\n=== FRESHNESS ===")
# Look for date/timestamp field in results
ts_fields = [
    k
    for k in r0.keys()
    if any(x in k.lower() for x in ("time", "date", "as_of", "captured", "updated"))
]
print(f"  timestamp fields in result: {ts_fields}")
for f in ts_fields[:3]:
    samples = [r.get(f) for r in results[:5]]
    print(f"  {f} samples: {samples}")

# Rule-gate field presence audit
expected_gates = ["adv_20d", "mcap", "ivr", "oi_total", "earnings_within_7d"]
print("\n=== GATE FIELDS PRESENCE ===")
for g in expected_gates:
    present = sum(1 for r in results if r.get(g) is not None)
    print(f"  {g}: {present}/{len(results)} populated")

# Check for confidence / signal_strength fields
print("\n=== ENRICHMENT FIELDS ===")
for f in (
    "flow_score",
    "dark_pool",
    "support_level",
    "target_1",
    "target_2",
    "rr",
    "risk_reward",
    "volume_ratio",
):
    present = sum(1 for r in results if r.get(f) is not None)
    if present > 0:
        print(f"  {f}: {present}/{len(results)} populated")
