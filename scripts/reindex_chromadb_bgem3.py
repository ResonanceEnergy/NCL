#!/usr/bin/env python3
"""Wave 14AX (2026-05-30) — One-shot reindex of NCL MemUnits into BGE-M3 Chroma.

Usage:
    cd ~/dev/NCL
    NCL_MEMORY_EMBED_MODEL=bge-m3 python3 scripts/reindex_chromadb_bgem3.py [--commit]

Without --commit the script reports what WOULD happen but doesn't touch the
existing chromadb directory. With --commit:
  1. Backs up the current data/memory/chromadb/ to chromadb.bge.pre-{ts}/
  2. Creates a fresh PersistentClient at the SAME path
  3. Re-creates all 7 typed + default collections with BGE-M3 embedding
  4. Reads every line of data/memory/units.jsonl, batched at 200, and
     re-embeds + adds to the appropriate typed collection.
  5. Reports progress every 1000 units.

Estimated runtime: 10-30 min on M1 Ultra MPS for the current ~14K corpus.
BGE-M3 is multilingual (8K ctx, MTEB ~62.6); matters for LatAm + YTC.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
sys.path.insert(0, str(NCL_BASE))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true", help="Actually reindex (omit for dry-run)")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Units per Chroma upsert batch (default 200)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("NCL_MEMORY_EMBED_MODEL", "bge-m3"),
        help="Short-alias or HF id of the embedding model (default bge-m3)",
    )
    args = parser.parse_args()

    units_file = NCL_BASE / "data" / "memory" / "units.jsonl"
    chromadb_dir = NCL_BASE / "data" / "memory" / "chromadb"

    if not units_file.exists():
        print(f"ERROR: units file missing: {units_file}", file=sys.stderr)
        return 1

    unit_count = sum(1 for _ in units_file.open())
    sz_mb = units_file.stat().st_size / 1_000_000
    print(f"units.jsonl: {unit_count:,} lines, {sz_mb:.1f} MB")
    print(f"chromadb_dir: {chromadb_dir} (exists={chromadb_dir.exists()})")
    print(f"target model: {args.model}")

    # Set env so the store helper resolves the chosen model.
    os.environ["NCL_MEMORY_EMBED_MODEL"] = args.model

    if not args.commit:
        print("\nDry-run only. Pass --commit to actually reindex.")
        print("Estimated time on M1 Ultra MPS: 10-30 min depending on model load.")
        return 0

    # Backup existing chromadb
    if chromadb_dir.exists():
        ts = datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = chromadb_dir.parent / f"chromadb.bge.pre-{ts}"
        print(f"backing up existing chromadb to {backup}")
        shutil.move(str(chromadb_dir), str(backup))

    # Lazy import to make the dry-run mode work without heavy deps
    from runtime.memory.store import (
        COLLECTION_MAP,
        DEFAULT_COLLECTION,
        _load_chroma_embed_fn,
    )
    import chromadb  # type: ignore

    print("loading embed function...")
    embed_fn = _load_chroma_embed_fn()
    if embed_fn is None:
        print("FATAL: embed fn failed to load. Aborting.", file=sys.stderr)
        return 1
    print(f"  loaded: {getattr(embed_fn, '_ncl_label', repr(embed_fn))}")

    client = chromadb.PersistentClient(path=str(chromadb_dir))
    collections: dict[str, object] = {}
    mk_kwargs = {"metadata": {"hnsw:space": "cosine"}, "embedding_function": embed_fn}
    for mem_type, col_name in COLLECTION_MAP.items():
        collections[mem_type] = client.get_or_create_collection(name=col_name, **mk_kwargs)
    collections["default"] = client.get_or_create_collection(
        name=DEFAULT_COLLECTION, **mk_kwargs
    )
    print(f"  created {len(collections)} collections")

    t0 = time.time()
    processed = 0
    skipped = 0
    by_type_batches: dict[str, list[tuple[str, str, dict]]] = {}

    def _flush_batches(force: bool = False) -> None:
        nonlocal processed
        for mem_type, rows in list(by_type_batches.items()):
            if not rows:
                continue
            if not force and len(rows) < args.batch_size:
                continue
            ids = [r[0] for r in rows]
            docs = [r[1] for r in rows]
            metas = [r[2] for r in rows]
            try:
                col = collections.get(mem_type) or collections["default"]
                col.add(ids=ids, documents=docs, metadatas=metas)  # type: ignore[attr-defined]
                processed += len(rows)
            except Exception as e:
                print(f"  upsert {mem_type} failed: {e}", file=sys.stderr)
            by_type_batches[mem_type] = []

    with units_file.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                u = json.loads(line)
            except Exception:
                skipped += 1
                continue
            uid = u.get("unit_id") or u.get("id")
            content = u.get("content") or ""
            if not uid or not content:
                skipped += 1
                continue
            memory_type = (u.get("memory_type") or "episodic").lower()
            meta = u.get("metadata") or {}
            # Coerce metadata values to Chroma-acceptable scalar types
            clean_meta = {}
            for k, v in meta.items():
                if isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
                elif v is None:
                    continue
                else:
                    clean_meta[k] = str(v)[:120]
            clean_meta["source"] = u.get("source", "")
            clean_meta["importance"] = float(u.get("importance", 0))
            by_type_batches.setdefault(memory_type, []).append((uid, content, clean_meta))
            _flush_batches()
            if processed and processed % 1000 == 0 and processed > 0:
                el = time.time() - t0
                print(f"  {processed:,} indexed in {el:.0f}s  ({processed/el:.0f}/s)")

    _flush_batches(force=True)
    el = time.time() - t0
    print(f"\nDONE: indexed {processed:,} units in {el:.0f}s (skipped {skipped}).")
    print(f"  rate: {processed/el:.0f}/s on {args.model}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
