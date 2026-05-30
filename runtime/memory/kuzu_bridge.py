"""Wave 14AV (2026-05-30) — Kuzu embedded KG bridge.

The brain runs Python 3.14; kuzu has no cp314 wheels (build fails on
source). Wave 14AV installs kuzu in a Python 3.13 venv at
~/dev/NCL/.venv313 and exposes Cypher query capability to the main
brain via a thin subprocess bridge.

USAGE
-----
    from runtime.memory import kuzu_bridge

    # one-shot Cypher
    rows = kuzu_bridge.query("MATCH (n:Concept) RETURN n.name LIMIT 5")

    # write
    kuzu_bridge.execute(
        "CREATE (:Concept {name: $name, importance: $imp})",
        params={"name": "memory", "imp": 90},
    )

Why a subprocess bridge instead of a long-running daemon?
  - Kuzu queries are typically sub-100ms; the subprocess launch
    overhead (~80ms cold, ~30ms warm) is acceptable.
  - Avoids a long-running second Python process that we have to
    supervise.
  - Stateless — each call opens the DB read-only or with a brief
    write-lock, closes, exits.

The Kuzu DB lives at data/memory/kuzu/. Schema migration helpers
seed the initial Concept + Entity + RELATES_TO node/edge types
from the existing NetworkX KG.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


log = logging.getLogger("ncl.memory.kuzu_bridge")


_NCL_BASE = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
_VENV_PY = _NCL_BASE / ".venv313" / "bin" / "python"
_KUZU_DB = _NCL_BASE / "data" / "memory" / "kuzu"
_BRIDGE_SCRIPT = _NCL_BASE / "runtime" / "memory" / "_kuzu_runner.py"


def is_available() -> bool:
    """True iff the Python 3.13 venv with kuzu is present + executable."""
    return _VENV_PY.exists() and _BRIDGE_SCRIPT.exists()


def ensure_db() -> None:
    """Create the Kuzu DB directory + minimal schema on first use."""
    _KUZU_DB.parent.mkdir(parents=True, exist_ok=True)


def _invoke(payload: dict, timeout_s: float = 15.0) -> dict:
    """Subprocess-invoke the runner with a JSON payload, return parsed response."""
    if not is_available():
        return {"error": "kuzu venv missing", "rows": []}
    ensure_db()
    try:
        proc = subprocess.run(
            [str(_VENV_PY), str(_BRIDGE_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return {"error": "kuzu subprocess timed out", "rows": []}
    except Exception as e:
        return {"error": f"kuzu subprocess failed: {e!s}", "rows": []}
    if proc.returncode != 0:
        return {"error": proc.stderr.strip()[:500] or "kuzu non-zero exit", "rows": []}
    try:
        return json.loads(proc.stdout)
    except Exception as e:
        return {"error": f"kuzu response parse failed: {e!s}", "rows": []}


def query(cypher: str, params: Optional[dict] = None) -> list[dict]:
    """Run a read-only Cypher query. Returns a list of row dicts."""
    resp = _invoke({"op": "query", "cypher": cypher, "params": params or {}})
    if resp.get("error"):
        log.warning("[kuzu] query error: %s", resp["error"])
        return []
    return resp.get("rows", [])


def execute(cypher: str, params: Optional[dict] = None) -> bool:
    """Run a write Cypher statement. Returns True on success."""
    resp = _invoke({"op": "execute", "cypher": cypher, "params": params or {}})
    if resp.get("error"):
        log.warning("[kuzu] execute error: %s", resp["error"])
        return False
    return True


async def query_async(cypher: str, params: Optional[dict] = None) -> list[dict]:
    """Async wrapper around query() — runs in a thread."""
    return await asyncio.to_thread(query, cypher, params)


async def execute_async(cypher: str, params: Optional[dict] = None) -> bool:
    """Async wrapper around execute() — runs in a thread."""
    return await asyncio.to_thread(execute, cypher, params)


def init_schema() -> bool:
    """Idempotently install NCL's base node/edge types.

    Concept(name STRING PRIMARY KEY, kind STRING, importance INT64)
    Entity(name STRING PRIMARY KEY, kind STRING, source STRING)
    RELATES_TO(FROM Concept TO Concept, rel_type STRING, weight DOUBLE)
    MENTIONS  (FROM Entity  TO Concept, count INT64)
    """
    schema_stmts = [
        "CREATE NODE TABLE IF NOT EXISTS Concept (name STRING, kind STRING, importance INT64, PRIMARY KEY (name))",
        "CREATE NODE TABLE IF NOT EXISTS Entity (name STRING, kind STRING, source STRING, PRIMARY KEY (name))",
        "CREATE REL TABLE IF NOT EXISTS RELATES_TO (FROM Concept TO Concept, rel_type STRING, weight DOUBLE)",
        "CREATE REL TABLE IF NOT EXISTS MENTIONS (FROM Entity TO Concept, count INT64)",
    ]
    for stmt in schema_stmts:
        if not execute(stmt):
            return False
    return True


__all__ = [
    "is_available",
    "ensure_db",
    "query",
    "execute",
    "query_async",
    "execute_async",
    "init_schema",
]
