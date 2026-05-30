#!/usr/bin/env python3
"""Wave 14AX (2026-05-30) — Migrate NetworkX KG into Kuzu.

Reads data/memory/knowledge_graph/ (JSONL or pickled NetworkX DiGraph)
and writes Concept nodes + RELATES_TO edges into the Kuzu DB at
data/memory/kuzu/ncl_kg.kuzu via the Wave 14AV subprocess bridge.

Usage:
    cd ~/dev/NCL
    python3 scripts/migrate_kg_to_kuzu.py [--commit] [--limit N]

Without --commit, reports what would be migrated (node + edge counts).
With --commit, runs the full insert. Idempotent — Concept name is the
primary key, so re-running doesn't duplicate. RELATES_TO is allowed to
duplicate; you can add a dedup clause later if needed.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import sys
import time
from pathlib import Path

NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
sys.path.insert(0, str(NCL_BASE))


def _load_networkx_kg():
    """Try to load the existing KG. Returns a (nodes, edges) tuple.

    nodes: list of {name, kind, importance}
    edges: list of {src, rel_type, dst, weight}
    """
    kg_dir = NCL_BASE / "data" / "memory" / "knowledge_graph"
    nodes: list[dict] = []
    edges: list[dict] = []
    if not kg_dir.exists():
        return nodes, edges

    # Try the JSONL snapshot format first
    for path in sorted(glob.glob(str(kg_dir / "*.jsonl"))):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(rec, dict):
                        continue
                    if rec.get("type") == "node" or "node" in rec:
                        nm = (rec.get("name") or rec.get("id") or "").strip()
                        if not nm:
                            continue
                        nodes.append(
                            {
                                "name": nm[:200],
                                "kind": str(rec.get("kind") or rec.get("category") or "concept")[:60],
                                "importance": int(rec.get("importance", 50) or 50),
                            }
                        )
                    elif rec.get("type") == "edge" or all(k in rec for k in ("src", "dst")):
                        edges.append(
                            {
                                "src": str(rec.get("src") or "")[:200],
                                "dst": str(rec.get("dst") or "")[:200],
                                "rel_type": str(rec.get("rel_type") or rec.get("relation") or "relates_to")[:60],
                                "weight": float(rec.get("weight", 1.0) or 1.0),
                            }
                        )
        except Exception as e:
            print(f"  warn: {path} parse failed: {e}", file=sys.stderr)

    # Fallback: try pickled NetworkX
    if not nodes and not edges:
        for path in sorted(glob.glob(str(kg_dir / "*.pkl")) + glob.glob(str(kg_dir / "*.gpickle"))):
            try:
                with open(path, "rb") as f:
                    g = pickle.load(f)
                if hasattr(g, "nodes") and hasattr(g, "edges"):
                    for n, data in g.nodes(data=True):
                        nodes.append(
                            {
                                "name": str(n)[:200],
                                "kind": str(data.get("kind") or "concept")[:60],
                                "importance": int(data.get("importance", 50) or 50),
                            }
                        )
                    for u, v, data in g.edges(data=True):
                        edges.append(
                            {
                                "src": str(u)[:200],
                                "dst": str(v)[:200],
                                "rel_type": str(data.get("rel_type") or "relates_to")[:60],
                                "weight": float(data.get("weight", 1.0) or 1.0),
                            }
                        )
                break
            except Exception as e:
                print(f"  warn: {path} pickle failed: {e}", file=sys.stderr)

    return nodes, edges


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    print("scanning data/memory/knowledge_graph/ ...")
    nodes, edges = _load_networkx_kg()
    print(f"  loaded {len(nodes):,} explicit nodes, {len(edges):,} edges")

    # Derive implicit nodes from edge endpoints when the JSONL only
    # stored edges. Every distinct src/dst becomes a Concept.
    if edges and len(nodes) < 50:
        seen = {n["name"] for n in nodes}
        for e in edges:
            for end in ("src", "dst"):
                nm = e.get(end, "").strip()
                if nm and nm not in seen:
                    seen.add(nm)
                    nodes.append({"name": nm[:200], "kind": "concept", "importance": 50})
        print(f"  derived to {len(nodes):,} nodes from edge endpoints")

    if args.limit > 0:
        nodes = nodes[: args.limit]
        edges = edges[: args.limit]
        print(f"  truncated to first {args.limit} of each")

    if not args.commit:
        print("\nDry-run. Sample:")
        for n in nodes[:3]:
            print(f"  node: {n}")
        for e in edges[:3]:
            print(f"  edge: {e}")
        print(f"\nPass --commit to actually migrate.")
        return 0

    from runtime.memory import kuzu_bridge

    if not kuzu_bridge.is_available():
        print("FATAL: kuzu venv not available. Run brew install python@3.13 first.", file=sys.stderr)
        return 1
    kuzu_bridge.ensure_db()
    if not kuzu_bridge.init_schema():
        print("FATAL: schema init failed", file=sys.stderr)
        return 1

    t0 = time.time()
    inserted_n = 0
    inserted_e = 0
    failed_n = 0
    failed_e = 0

    for n in nodes:
        # MERGE doesn't exist in Kuzu Cypher subset; use CREATE with idempotent
        # PK conflict handling (Kuzu raises on dup — we catch and continue).
        cypher = "CREATE (:Concept {name: $name, kind: $kind, importance: $imp})"
        ok = kuzu_bridge.execute(
            cypher,
            params={"name": n["name"], "kind": n["kind"], "imp": n["importance"]},
        )
        if ok:
            inserted_n += 1
        else:
            failed_n += 1
        if (inserted_n + failed_n) % 200 == 0:
            print(f"  nodes: {inserted_n:,} ok / {failed_n} fail in {time.time()-t0:.0f}s")

    print(f"node phase: {inserted_n:,} ok / {failed_n} failed")

    for e in edges:
        cypher = (
            "MATCH (a:Concept), (b:Concept) "
            "WHERE a.name = $src AND b.name = $dst "
            "CREATE (a)-[:RELATES_TO {rel_type: $rel, weight: $w}]->(b)"
        )
        ok = kuzu_bridge.execute(
            cypher,
            params={
                "src": e["src"],
                "dst": e["dst"],
                "rel": e["rel_type"],
                "w": e["weight"],
            },
        )
        if ok:
            inserted_e += 1
        else:
            failed_e += 1
        if (inserted_e + failed_e) % 500 == 0:
            print(f"  edges: {inserted_e:,} ok / {failed_e} fail in {time.time()-t0:.0f}s")

    print(f"edge phase: {inserted_e:,} ok / {failed_e} failed")
    print(f"DONE in {time.time()-t0:.0f}s. Nodes={inserted_n:,} Edges={inserted_e:,}")

    # Verification
    rows = kuzu_bridge.query("MATCH (c:Concept) RETURN count(c) AS n")
    print(f"verify: {rows}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
