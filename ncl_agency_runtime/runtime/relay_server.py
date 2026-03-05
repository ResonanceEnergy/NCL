#!/usr/bin/env python3
import argparse, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from pathlib import Path
import datetime
import sys
import os

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from lib_ncl import expanduser, ensure_dirs, day_file, append_ndjson, validate_minimal

# Import memory system
try:
    from ncl_memory import store_episodic_memory, get_memory_manager
    MEMORY_ENABLED = True
except ImportError:
    print("Warning: Memory system not available, running without memory integration")
    MEMORY_ENABLED = False


def load_config():
    # local config default
    cfg = {
        "event_log_dir": "~/NCL/data/event_log",
        "quarantine_dir": "~/NCL/data/quarantine",
        "relay": {"path": "/event"}
    }
    return cfg


class Handler(BaseHTTPRequestHandler):
    server_version = "NCLRelay/1.0"

    def _send(self, code, obj):
        data = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        cfg = self.server.cfg
        want_path = cfg["relay"]["path"]
        if urlparse(self.path).path != want_path:
            return self._send(404, {"ok": False, "error": "not_found"})

        length = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(length)
        try:
            event = json.loads(raw.decode('utf-8'))
        except Exception as e:
            return self._send(400, {"ok": False, "error": "bad_json", "detail": str(e)})

        # observed_at
        event.setdefault("observed_at", datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat())

        ok, reason = validate_minimal(event)
        event_log_dir = expanduser(cfg["event_log_dir"])
        quarantine_dir = expanduser(cfg["quarantine_dir"])
        ensure_dirs(event_log_dir, quarantine_dir)

        if ok:
            path = day_file(event_log_dir, event.get("occurred_at"))
            append_ndjson(path, event)

            # Store in memory system if available
            if MEMORY_ENABLED:
                try:
                    # Extract tags and context for memory storage
                    tags = []
                    context = {
                        "event_type": event.get("event_type", "unknown"),
                        "occurred_at": event.get("occurred_at"),
                        "source": "relay_server"
                    }

                    # Add event-specific tags
                    if "event_type" in event:
                        tags.append(f"event:{event['event_type']}")

                    # Add category tags if available
                    if "category" in event:
                        tags.append(f"category:{event['category']}")

                    # Store as episodic memory
                    memory_id = store_episodic_memory(
                        content=event,
                        tags=tags,
                        context=context
                    )
                    print(f"Stored event in memory: {memory_id}")

                except Exception as e:
                    print(f"Memory storage failed: {e}")

            return self._send(200, {"ok": True, "stored": str(path), "reason": reason})
        else:
            qpath = quarantine_dir / "invalid.ndjson"
            event["_validation_error"] = reason
            append_ndjson(qpath, event)
            return self._send(422, {"ok": False, "quarantined": str(qpath), "reason": reason})

    def do_GET(self):
        cfg = self.server.cfg
        path = urlparse(self.path).path

        # Health check endpoint
        if path == "/health":
            health_status = {"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}

            # Add memory stats if available
            if MEMORY_ENABLED:
                try:
                    mm = get_memory_manager()
                    health_status["memory"] = mm.get_memory_stats()
                except Exception as e:
                    health_status["memory_error"] = str(e)

            return self._send(200, health_status)

        # Memory query endpoint
        elif path.startswith("/memory/"):
            if not MEMORY_ENABLED:
                return self._send(503, {"error": "Memory system not available"})

            try:
                mm = get_memory_manager()
                query_params = urlparse(self.path).query

                # Parse query parameters
                query = {}
                if query_params:
                    from urllib.parse import parse_qs
                    params = parse_qs(query_params)

                    if "type" in params:
                        query["memory_type"] = params["type"][0]
                    if "tag" in params:
                        query["tags"] = params["tag"]
                    if "content" in params:
                        query["content"] = params["content"][0]
                    if "limit" in params:
                        query["limit"] = int(params["limit"][0])

                limit = query.pop("limit", 50)
                memories = mm.search_memories(query, limit)

                # Convert to response format
                results = []
                for mem in memories:
                    results.append({
                        "id": mem.id,
                        "content": mem.content,
                        "type": mem.memory_type,
                        "tags": mem.tags,
                        "importance": mem.importance,
                        "timestamp": mem.timestamp.isoformat(),
                        "access_count": mem.access_count
                    })

                return self._send(200, {"memories": results, "count": len(results)})

            except Exception as e:
                return self._send(500, {"error": str(e)})

        else:
            return self._send(404, {"error": "Not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8787)
    args = ap.parse_args()

    cfg = load_config()
    httpd = HTTPServer((args.host, args.port), Handler)
    httpd.cfg = cfg
    print(f"NCL Relay listening on http://{args.host}:{args.port}{cfg['relay']['path']}")
    httpd.serve_forever()


if __name__ == '__main__':
    main()
