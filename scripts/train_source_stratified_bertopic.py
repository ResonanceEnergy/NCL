#!/usr/bin/env python3
"""Wave 14BJ — bootstrap per-source BERTopic models from agent_signals.jsonl.

Reads the last N days of signals, buckets by source head (the part of
`source` before the first colon: `reddit:r/wallstreetbets` →  `reddit`),
and trains one BERTopic model per bucket that has enough docs.

Usage:
    python3 scripts/train_source_stratified_bertopic.py             [--days N]
                                                                   [--min-docs N]
                                                                   [--min-topic-size N]

Run periodically (weekly is plenty). The cross_reference engine
auto-loads models from data/cross_reference/bertopic_model/{source}/
on next brain bounce.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _load_signals(days: int) -> list[dict]:
    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    candidates = [
        base / "data" / "intelligence" / "agent_signals.jsonl",
        base / "data" / "agents" / "agent_signals.jsonl",
        base / "data" / "agent_signals.jsonl",
    ]
    sig_log = next((p for p in candidates if p.exists()), candidates[0])
    if not sig_log.exists():
        print(f"signal log not found in any of: {candidates}", file=sys.stderr)
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_iso = cutoff.isoformat()
    out: list[dict] = []
    with sig_log.open() as fh:
        for raw in fh:
            try:
                s = json.loads(raw)
            except Exception:
                continue
            ts = s.get("timestamp") or s.get("created_at") or ""
            if ts and ts < cutoff_iso:
                continue
            out.append(s)
    print(f"loaded {len(out)} signals from {sig_log}", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-docs", type=int, default=30)
    ap.add_argument("--min-topic-size", type=int, default=5)
    args = ap.parse_args()

    signals = _load_signals(args.days)
    if not signals:
        return 2

    # Bucket text by source head
    by_source: dict[str, list[str]] = defaultdict(list)
    for s in signals:
        head = (s.get("source", "") or "").split(":")[0].strip().lower()
        if not head:
            continue
        text = ((s.get("title") or "") + " " + (s.get("content") or "")).strip()
        if len(text) < 20:
            continue
        by_source[head].append(text)

    print("per-source counts:", file=sys.stderr)
    for src, texts in sorted(by_source.items(), key=lambda kv: -len(kv[1])):
        print(f"  {src}: {len(texts)}", file=sys.stderr)

    # Train
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from runtime.cross_reference.bertopic_themes import (
        train_source_stratified_bertopic,
    )

    res = train_source_stratified_bertopic(
        dict(by_source),
        min_topic_size=args.min_topic_size,
        min_docs_per_source=args.min_docs,
    )
    print(json.dumps(res, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
