#!/usr/bin/env python3
"""Wave 14BN — backfill metadata.model on historical cost_ledger.jsonl rows.

The spend dashboard's `by_source_model` bucket counts spend by
``metadata.model``. 13.8k of 15.7k existing rows are missing model
attribution because the Wave 14BG fix only changed the WRITE path.
This script INFERS the model from each row's existing fields:

1. category like ``llm:<model-id>`` — the suffix IS the model.
2. category matching a known feature — feature → model lookup table
   (mirrors the 14BG fix decisions).
3. tweet_search / non-LLM API calls — leave model unset.

Atomic write — original ledger is backed up to a timestamped .bak
before the rewrite.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


# Feature → model attribution. Mirrors the Wave 14BG write-path fixes
# so historical rows agree with current rows for the same feature.
FEATURE_MODEL_MAP: dict[tuple[str, str], str] = {
    # (source, category) → model
    ("anthropic", "entity_extraction"): "claude-sonnet-4-20250514",
    ("anthropic", "narrative_thread_summary"): "claude-sonnet-4-20250514",
    ("anthropic", "prediction"): "claude-sonnet-4-20250514",
    ("anthropic", "calendar_todo_generation"): "claude-sonnet-4-20250514",
    ("anthropic", "memory_scoring"): "claude-sonnet-4-20250514",
    ("anthropic", "awarebot_brief"): "claude-sonnet-4-20250514",
    ("anthropic", "ytc_per_video"): "claude-sonnet-4-20250514",
    ("anthropic", "ytc_nightshift_rollup"): "claude-sonnet-4-20250514",
    ("anthropic", "ytc_analysis"): "claude-sonnet-4-20250514",
    ("anthropic", "intel_summary"): "claude-sonnet-4-20250514",
    ("anthropic", "intel_brief"): "claude-sonnet-4-20250514",
    ("anthropic", "night_watch_memory"): "claude-sonnet-4-20250514",
    ("anthropic", "journal_reflection"): "claude-3-5-haiku-20241022",
    ("anthropic", "user_chat"): "claude-sonnet-4-20250514",
    ("anthropic", "council_run"): "claude-sonnet-4-20250514",
    ("anthropic", "council_runner"): "claude-sonnet-4-20250514",
    ("anthropic", "war_room"): "claude-sonnet-4-20250514",
    ("anthropic", "goal_synth"): "claude-sonnet-4-20250514",
    ("anthropic", "uni_gathering"): "claude-sonnet-4-20250514",
    ("anthropic", "swarm_subtask"): "claude-sonnet-4-20250514",
    ("anthropic", "swarm_synthesis"): "claude-sonnet-4-20250514",
    ("google", "night_watch_memory"): "gemini-2.5-flash",
    ("google", "entity_extraction"): "gemini-2.5-flash",
    ("openai", "vision_board"): "gpt-image-1",
    ("openai", "council_run"): "gpt-4o",
    ("xai", "lde_grok"): "grok-3",
    ("xai", "uni_synthesis"): "grok-3",
    ("xai", "uni_gathering"): "grok-3-mini",
    ("xai", "x_scan"): "grok-3",
    ("xai", "x_analysis"): "grok-3",
    ("xai", "user_chat"): "grok-3",
    ("xai", "council_runner"): "grok-3",
    ("xai", "war_room"): "grok-4",
    ("xai", "orchestrator"): "grok-3",
    ("xai", "ytc_analysis"): "grok-3",
}


def infer_model(row: dict) -> str | None:
    """Return inferred model id (or None when row is not an LLM call)."""
    src = (row.get("source") or "").strip()
    cat = (row.get("category") or "").strip()

    # x_twitter API calls aren't LLM; leave model unset.
    if src == "x_twitter":
        return None

    # category like "llm:<model>"
    if cat.startswith("llm:"):
        model = cat[len("llm:") :].strip()
        if model:
            return model

    # detail like "model=... " — sometimes the writer stuffed the model
    # name into the detail string instead of metadata.model.
    detail = (row.get("detail") or "").strip()
    if detail.startswith("model="):
        token = detail[len("model=") :].split()[0]
        if token:
            return token

    # feature lookup
    return FEATURE_MODEL_MAP.get((src, cat))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--ledger",
        default=os.environ.get(
            "NCL_COST_LEDGER",
            str(
                Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                / "data" / "costs" / "cost_ledger.jsonl"
            ),
        ),
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    ledger_path = Path(args.ledger)
    if not ledger_path.exists():
        print(f"ledger missing: {ledger_path}", file=sys.stderr)
        return 2

    backed = 0
    rewrote = 0
    untouched = 0
    no_infer = 0
    by_inferred_model: Counter = Counter()
    rows: list[dict] = []

    with ledger_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            backed += 1
            meta = row.get("metadata") or {}
            if meta.get("model"):
                untouched += 1
                rows.append(row)
                continue
            inferred = infer_model(row)
            if inferred:
                meta = dict(meta)
                meta["model"] = inferred
                meta.setdefault("backfilled_at", datetime.now(timezone.utc).isoformat())
                meta.setdefault("backfilled_by", "wave_14bn")
                row["metadata"] = meta
                rewrote += 1
                by_inferred_model[(row.get("source"), inferred)] += 1
            else:
                no_infer += 1
            rows.append(row)

    print(f"read {backed:,} rows")
    print(f"  already had model:    {untouched:,}")
    print(f"  inferred new model:   {rewrote:,}")
    print(f"  unable to infer:      {no_infer:,}")
    print()
    print("top inferred model attributions:")
    for (src, model), n in by_inferred_model.most_common(15):
        print(f"  {src:14} / {model:36} {n:,}")

    if args.dry_run:
        print("\n(dry-run; no files written)")
        return 0

    # Backup + atomic replace
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_path = ledger_path.with_suffix(f".jsonl.pre-14bn-{ts}.bak")
    shutil.copy2(ledger_path, bak_path)
    print(f"\nbackup: {bak_path}")

    tmp_path = ledger_path.with_suffix(f".jsonl.tmp-{ts}")
    with tmp_path.open("w") as out:
        for row in rows:
            out.write(json.dumps(row, default=str) + "\n")
    tmp_path.replace(ledger_path)
    print(f"rewrote: {ledger_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
