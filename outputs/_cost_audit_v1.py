"""Aggregate actual NCL spend from the cost_ledger.jsonl over the last 14 days.

Report: per-day total, per-source totals, per-(source,model) totals, per-feature
totals. Surface the top 10 cost drivers by dollar and by call volume.
"""

import collections
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


LEDGER = Path.home() / "dev" / "NCL" / "data" / "costs" / "cost_ledger.jsonl"
if not LEDGER.exists():
    print(f"ledger missing at {LEDGER}")
    raise SystemExit
sz_mb = LEDGER.stat().st_size / 1_000_000
print(f"ledger size: {sz_mb:.2f} MB")

cutoff = datetime.now(timezone.utc) - timedelta(days=14)
by_day_total = collections.defaultdict(float)
by_source_total = collections.defaultdict(float)
by_source_model = collections.defaultdict(float)
by_source_op = collections.defaultdict(float)
by_op_calls = collections.Counter()
sample_per_source_op = {}

total_rows = 0
in_window = 0
for line in LEDGER.read_text().splitlines():
    if not line.strip():
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    total_rows += 1
    ts = d.get("timestamp") or d.get("ts") or ""
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        continue
    if dt < cutoff:
        continue
    in_window += 1
    day = dt.strftime("%Y-%m-%d")
    src = str(d.get("source") or "?")
    model = str((d.get("metadata") or {}).get("model") or "?")
    amt = float(d.get("amount_usd") or d.get("amount") or d.get("cost") or 0)
    op = str(d.get("operation") or d.get("feature") or d.get("call") or "?")
    by_day_total[day] += amt
    by_source_total[src] += amt
    by_source_model[(src, model)] += amt
    by_source_op[(src, op)] += amt
    by_op_calls[(src, op)] += 1
    key = (src, op)
    if key not in sample_per_source_op:
        sample_per_source_op[key] = d.get("description") or d.get("notes") or ""

print(f"\nrows total: {total_rows:,} | in last 14d: {in_window:,}")
print("\n=== Daily totals (last 14 days):")
for day, amt in sorted(by_day_total.items()):
    print(f"  {day}: ${amt:8.4f}")

print("\n=== Per-source 14d totals:")
for src, amt in sorted(by_source_total.items(), key=lambda x: -x[1]):
    print(f"  {src:20s} ${amt:8.4f}")

print("\n=== Top 15 (source,model) by spend (14d):")
ranked_models = sorted(by_source_model.items(), key=lambda x: -x[1])[:15]
for (src, model), amt in ranked_models:
    print(f"  ${amt:8.4f}  {src}/{model}")

print("\n=== Top 15 (source,operation) by spend (14d):")
ranked_ops = sorted(by_source_op.items(), key=lambda x: -x[1])[:15]
for (src, op), amt in ranked_ops:
    calls = by_op_calls[(src, op)]
    sample = (sample_per_source_op.get((src, op)) or "")[:60]
    print(f"  ${amt:7.4f}  {calls:6d} calls  {src}/{op}  | {sample}")

print("\n=== Top 15 (source,operation) by CALL VOLUME (14d):")
for (src, op), calls in by_op_calls.most_common(15):
    amt = by_source_op[(src, op)]
    print(f"  {calls:6d}  ${amt:7.4f}  {src}/{op}")
