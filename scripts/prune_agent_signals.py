#!/usr/bin/env python3
"""Wave 14CG — prune agent_signals.jsonl down to genuinely distinct rows.

The 30k+ line file is ~49% duplicates (same fingerprint repeating because
old fingerprint was too loose) plus ~3% hollow rows (title==content + no
url). This script:

  1. Re-fingerprints every row with the tightened Wave 14CG formula
     (source + normalized title with numbers stripped).
  2. Within a sliding 24h window per fingerprint, keeps only the
     FIRST occurrence + any later occurrence whose composite_score
     bumped by >= 0.05 (genuine update) or whose direction flipped.
  3. Drops hollow rows entirely (title==content + no url + empty content).
  4. Drops source=unknown rows (provenance lost — Wave 14CG fixes the
     leak going forward; this clears historical pollution).
  5. Atomically rewrites the file with a timestamped .bak backup.

Idempotent. Safe to re-run. Use --dry-run first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


_NUM_RX = re.compile(r"\d+(?:[.,]\d+)?")
_PUNCT_RX = re.compile(r"[^a-z0-9# ]")
_WS_RX = re.compile(r"\s+")


def tight_fingerprint(source: str, title: str) -> str:
    norm = (title or "").lower()
    norm = _NUM_RX.sub("#", norm)
    norm = _PUNCT_RX.sub(" ", norm)
    norm = _WS_RX.sub(" ", norm).strip()[:80]
    raw = f"{source}::{norm}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_hollow(row: dict) -> bool:
    title = (row.get("title") or "").strip()
    content = (row.get("content") or "").strip()
    url = (row.get("url") or "").strip()
    if not content:
        return True
    if content == title and not url:
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--path",
        default=os.environ.get(
            "NCL_AGENT_SIGNALS",
            str(
                Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
                / "data" / "intelligence" / "agent_signals.jsonl"
            ),
        ),
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="dedup window per fingerprint (default 24h)",
    )
    ap.add_argument(
        "--score-bump-threshold",
        type=float,
        default=0.05,
        help="keep a repeat row if composite_score bumped by this much",
    )
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"signals file missing: {path}", file=sys.stderr)
        return 2

    print(f"reading {path}")

    rows: list[dict] = []
    total_read = 0
    with path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            total_read += 1
            rows.append(r)

    print(f"  read {total_read:,} rows")

    # Sort rows by timestamp ASC so dedup keeps the earliest occurrence
    rows.sort(key=lambda r: r.get("timestamp", ""))

    kept: list[dict] = []
    dropped_hollow = 0
    dropped_unknown = 0
    dropped_dup = 0
    kept_score_bump = 0

    # fingerprint -> {last_ts, last_score, last_direction}
    seen: dict[str, dict] = {}

    for r in rows:
        source = (r.get("source") or "").strip()
        if source == "unknown":
            dropped_unknown += 1
            continue
        if is_hollow(r):
            dropped_hollow += 1
            continue
        fp = tight_fingerprint(source, r.get("title", ""))
        ts = r.get("timestamp", "")
        score = float(r.get("composite_score") or 0)
        direction = (r.get("direction") or "").strip()

        prev = seen.get(fp)
        if prev is None:
            seen[fp] = {"ts": ts, "score": score, "direction": direction}
            kept.append(r)
            continue

        # Within 24h window? If yes, decide whether to keep.
        try:
            prev_dt = datetime.fromisoformat(prev["ts"].replace("Z", "+00:00"))
            now_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hours_apart = (now_dt - prev_dt).total_seconds() / 3600
        except Exception:
            hours_apart = 9999

        if hours_apart >= args.window_hours:
            # Outside window — treat as a fresh observation, keep
            seen[fp] = {"ts": ts, "score": score, "direction": direction}
            kept.append(r)
            continue

        # Inside window — keep only if score bump or direction flip
        score_jumped = abs(score - prev["score"]) >= args.score_bump_threshold
        direction_flipped = direction and direction != prev["direction"]
        if score_jumped or direction_flipped:
            seen[fp] = {"ts": ts, "score": score, "direction": direction}
            kept.append(r)
            kept_score_bump += 1
        else:
            dropped_dup += 1

    print()
    print("RESULT:")
    print(f"  read:                {total_read:,}")
    print(f"  dropped hollow:      {dropped_hollow:,}")
    print(f"  dropped source=unknown: {dropped_unknown:,}")
    print(f"  dropped duplicate:   {dropped_dup:,}")
    print(f"  kept (incl. bumps):  {len(kept):,}")
    print(f"    of which score-bump keeps: {kept_score_bump:,}")
    print(f"  total removed:       {total_read - len(kept):,} ({100*(total_read-len(kept))/total_read:.1f}%)")

    if args.dry_run:
        print()
        print("(dry-run; no files written)")
        return 0

    # Atomic backup + rewrite
    ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    bak_path = path.with_suffix(f".jsonl.pre-14cg-{ts_stamp}.bak")
    shutil.copy2(path, bak_path)
    print(f"\nbackup: {bak_path}")

    tmp_path = path.with_suffix(f".jsonl.tmp-{ts_stamp}")
    with tmp_path.open("w") as fh:
        for r in kept:
            fh.write(json.dumps(r, default=str) + "\n")
    tmp_path.replace(path)
    print(f"rewrote: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
