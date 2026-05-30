"""Wave 14AV (2026-05-30) — Kuzu subprocess runner.

Executed by the Python 3.13 venv at ~/dev/NCL/.venv313/bin/python.
Reads a JSON payload on stdin, opens the Kuzu DB at
data/memory/kuzu/, runs the requested query/execute, writes a JSON
response to stdout.

Payload: {"op": "query"|"execute", "cypher": "...", "params": {...}}
Response: {"rows": [...], "error": null}  or  {"rows": [], "error": "..."}
"""

import json
import os
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        json.dump({"rows": [], "error": f"payload parse: {e!s}"}, sys.stdout)
        return 1

    op = payload.get("op")
    cypher = payload.get("cypher") or ""
    params = payload.get("params") or {}

    if op not in ("query", "execute"):
        json.dump({"rows": [], "error": f"unknown op: {op!r}"}, sys.stdout)
        return 1

    try:
        import kuzu  # type: ignore
    except ImportError as e:
        json.dump({"rows": [], "error": f"kuzu import failed: {e!s}"}, sys.stdout)
        return 1

    base = Path(os.environ.get("NCL_BASE", str(Path.home() / "dev" / "NCL")))
    db_dir = base / "data" / "memory" / "kuzu"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / "ncl_kg.kuzu"

    try:
        db = kuzu.Database(str(db_file))
        conn = kuzu.Connection(db)
        if params:
            result = conn.execute(cypher, parameters=params)
        else:
            result = conn.execute(cypher)
    except Exception as e:
        json.dump({"rows": [], "error": str(e)[:400]}, sys.stdout)
        return 1

    rows: list[dict] = []
    try:
        if op == "query" and result is not None:
            columns = result.get_column_names()
            while result.has_next():
                values = result.get_next()
                row = dict(zip(columns, values))
                for k, v in list(row.items()):
                    if isinstance(v, bytes):
                        row[k] = v.decode("utf-8", errors="replace")
                    elif hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                rows.append(row)
    except Exception as e:
        json.dump({"rows": rows, "error": str(e)[:400]}, sys.stdout)
        return 1

    json.dump({"rows": rows, "error": None}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
