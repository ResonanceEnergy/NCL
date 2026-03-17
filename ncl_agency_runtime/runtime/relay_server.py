#!/usr/bin/env python3
import argparse
import datetime
import json
import logging
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from lib_ncl import append_ndjson, day_file, ensure_dirs, expanduser, validate_minimal

logger = logging.getLogger("ncl.relay")

MAX_REQUEST_BYTES = 1_048_576  # 1 MiB

# ---- optional prometheus_client; fall back to plain counters ----
try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST as _PROM_CONTENT_TYPE,
    )
    from prometheus_client import (  # type: ignore[import]
        Counter as _PCounter,
    )
    from prometheus_client import (
        generate_latest as _prom_generate,
    )
    _prom_events_received = _PCounter("ncl_relay_events_received_total", "Events received")
    _prom_events_stored = _PCounter("ncl_relay_events_stored_total", "Events stored")
    _prom_events_quarantined = _PCounter("ncl_relay_events_quarantined_total", "Events quarantined")
    _prom_events_duplicate = _PCounter("ncl_relay_events_duplicate_total", "Duplicate events dropped")
    _prom_rate_limited = _PCounter("ncl_relay_rate_limited_total", "Rate-limited requests")
    _prom_unauthorized = _PCounter("ncl_relay_unauthorized_total", "Unauthorized requests")
    _PROMETHEUS_CLIENT = True
except ImportError:
    _PROMETHEUS_CLIENT = False

# Plain fallback counters (always maintained for /metrics text endpoint)
_METRICS: dict[str, int] = {
    "events_received_total": 0,
    "events_stored_total": 0,
    "events_quarantined_total": 0,
    "events_duplicate_total": 0,
    "rate_limited_total": 0,
    "unauthorized_total": 0,
}


def _inc(name: str) -> None:
    """Increment a metrics counter (both the fallback dict and prometheus if available)."""
    _METRICS[name] = _METRICS.get(name, 0) + 1
    if _PROMETHEUS_CLIENT:
        try:
            _prom_map = {
                "events_received_total": _prom_events_received,
                "events_stored_total": _prom_events_stored,
                "events_quarantined_total": _prom_events_quarantined,
                "events_duplicate_total": _prom_events_duplicate,
                "rate_limited_total": _prom_rate_limited,
                "unauthorized_total": _prom_unauthorized,
            }
            if name in _prom_map:
                _prom_map[name].inc()
        except Exception:
            pass


# Import memory system
try:
    from ncl_memory import get_memory_manager, store_episodic_memory
    MEMORY_ENABLED = True
except ImportError:
    logger.warning("Memory system not available — running without memory integration")
    MEMORY_ENABLED = False


class RateLimiter:
    """Token-bucket rate limiter keyed by client IP.

    Law 35 (Master the art of timing): Control the tempo of engagement.
    Art of War: 'Speed is the essence of war' — but disciplined speed.
    Habit 3 (First Things First): Throttle to protect what matters most.
    """

    def __init__(self, events_per_minute: int = 60, api_calls_per_minute: int = 30):
        self.events_per_minute = events_per_minute
        self.api_calls_per_minute = api_calls_per_minute
        self._event_buckets: dict = {}   # ip -> list of timestamps
        self._api_buckets: dict = {}     # ip -> list of timestamps

    def _check(self, buckets: dict, ip: str, limit: int) -> bool:
        import time as _t
        now = _t.time()
        window = 60.0
        stamps = buckets.get(ip, [])
        stamps = [s for s in stamps if now - s < window]
        if len(stamps) >= limit:
            buckets[ip] = stamps
            return False
        stamps.append(now)
        buckets[ip] = stamps
        return True

    def allow_event(self, ip: str) -> bool:
        return self._check(self._event_buckets, ip, self.events_per_minute)

    def allow_api(self, ip: str) -> bool:
        return self._check(self._api_buckets, ip, self.api_calls_per_minute)


class AuthManager:
    """Simple API key authentication manager.

    Law 40 (Despise the free lunch): Earned trust model — no anonymous access.
    Art of War: 'Let your plans be dark and impenetrable' — authenticate first.
    Habit 1 (Be Proactive): Enforce security before any damage can occur.
    """

    def __init__(self, keys: list | None = None, required: bool = False):
        self.required = required
        self.keys: set = set(keys or [])
        # Also load from environment
        env_key = os.environ.get("NCL_API_KEY", "")
        if env_key:
            self.keys.add(env_key)

    def authenticate(self, headers: dict) -> tuple:
        """Returns (allowed, reason)."""
        if not self.required:
            return True, "auth_not_required"

        # Check Authorization: Bearer <key>
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token in self.keys:
                return True, "authenticated"
            return False, "invalid_api_key"

        # Check X-API-Key header
        api_key = headers.get("X-API-Key", "")
        if api_key and api_key in self.keys:
            return True, "authenticated"

        if not auth_header and not api_key:
            return False, "missing_credentials"

        return False, "invalid_api_key"


def load_config():
    # Try to load from ncl_config.json first
    config_path = Path(__file__).parent.parent.parent / "ncl_config.json"
    cfg: dict[str, Any] = {
        "event_log_dir": "~/NCL/data/event_log",
        "quarantine_dir": "~/NCL/data/quarantine",
        "relay": {"path": "/event"},
        "access": {
            "api_keys_required": False,
            "rate_limiting": {
                "events_per_minute": 60,
                "api_calls_per_minute": 30
            }
        }
    }
    if config_path.exists():
        try:
            with open(config_path, encoding='utf-8') as f:
                file_cfg = json.load(f)
            if "network" in file_cfg:
                cfg["relay"]["port"] = file_cfg["network"].get("relay_port", 8787)
            if "access" in file_cfg:
                cfg["access"] = file_cfg["access"]
        except Exception:
            pass

    # Environment-variable overrides (always take precedence over file config)
    _ev = os.environ
    if "NCL_RELAY_PORT" in _ev:
        cfg["relay"]["port"] = int(_ev["NCL_RELAY_PORT"])
    if "NCL_RELAY_PATH" in _ev:
        cfg["relay"]["path"] = _ev["NCL_RELAY_PATH"]
    if "NCL_EVENT_LOG_DIR" in _ev:
        cfg["event_log_dir"] = _ev["NCL_EVENT_LOG_DIR"]
    if "NCL_QUARANTINE_DIR" in _ev:
        cfg["quarantine_dir"] = _ev["NCL_QUARANTINE_DIR"]
    if "NCL_API_KEYS_REQUIRED" in _ev:
        cfg["access"]["api_keys_required"] = _ev["NCL_API_KEYS_REQUIRED"].lower() in ("1", "true", "yes")
    rl = cfg["access"].setdefault("rate_limiting", {})
    if "NCL_EVENTS_PER_MINUTE" in _ev:
        rl["events_per_minute"] = int(_ev["NCL_EVENTS_PER_MINUTE"])
    if "NCL_API_CALLS_PER_MINUTE" in _ev:
        rl["api_calls_per_minute"] = int(_ev["NCL_API_CALLS_PER_MINUTE"])

    return cfg


class Handler(BaseHTTPRequestHandler):
    server_version = "NCLRelay/1.0"

    def log_message(self, fmt, *args):
        logger.info(fmt, *args)

    def _send(self, code, obj):
        data = json.dumps(obj).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _check_auth(self) -> bool:
        """Return True if request is authorised, else send 401 and return False.

        Art of War: 'All warfare is based on deception' — verify before trusting.
        Law 4: Always say less than necessary — generic 401, no internal details.
        """
        auth: AuthManager = self.server.auth  # type: ignore[attr-defined]
        ok, reason = auth.authenticate(dict(self.headers))
        if not ok:
            self._send(401, {"ok": False, "error": "unauthorized", "detail": reason})
            _inc("unauthorized_total")
            return False
        return True

    def _check_rate(self, bucket: str = "event") -> bool:
        """Return True if within rate limit, else send 429 and return False.

        Law 35: Master the art of timing — control engagement tempo.
        """
        rl: RateLimiter = self.server.rate_limiter  # type: ignore[attr-defined]
        ip = self._client_ip()
        allowed = rl.allow_event(ip) if bucket == "event" else rl.allow_api(ip)
        if not allowed:
            self._send(429, {"ok": False, "error": "rate_limited"})
            _inc("rate_limited_total")
            return False
        return True

    def _store_single_event(self, event: dict, cfg: dict) -> tuple:
        """Validate and store a single event. Returns (ok, status_code, response_body).

        Habit 2: Begin with the End in Mind — validate and route to clear outcome.
        Art of War: 'Every battle is won before it is fought' — validate inputs.
        Law 29: Plan all the way to the end — idempotency + audit trail.
        """
        event.setdefault("observed_at", datetime.datetime.now(datetime.UTC).astimezone().isoformat())

        ok, reason = validate_minimal(event)
        event_log_dir = expanduser(cfg["event_log_dir"])
        quarantine_dir = expanduser(cfg["quarantine_dir"])
        ensure_dirs(event_log_dir, quarantine_dir)

        _inc("events_received_total")
        if ok:
            # Idempotency: skip if event_id already seen
            event_id = event.get("event_id")
            seen: set = self.server.seen_event_ids  # type: ignore[attr-defined]
            if event_id and event_id in seen:
                _inc("events_duplicate_total")
                return True, 200, {"ok": True, "status": "duplicate", "event_id": event_id}
            if event_id:
                seen.add(event_id)
                # Cap set size to prevent unbounded memory growth
                if len(seen) > 100_000:
                    # Remove oldest half (set is unordered, so just discard ~half)
                    to_remove = list(seen)[:50_000]
                    for eid in to_remove:
                        seen.discard(eid)

            path = day_file(event_log_dir, event.get("occurred_at"))
            append_ndjson(path, event)

            # Store in memory system if available
            if MEMORY_ENABLED:
                self._store_in_memory(event)

            _inc("events_stored_total")
            return True, 200, {"ok": True, "stored": str(path), "reason": reason}
        else:
            qpath = quarantine_dir / "invalid.ndjson"
            event["_validation_error"] = reason
            append_ndjson(qpath, event)
            _inc("events_quarantined_total")
            return False, 422, {"ok": False, "quarantined": str(qpath), "reason": reason}

    @staticmethod
    def _store_in_memory(event: dict) -> None:
        try:
            tags = []
            context = {
                "event_type": event.get("event_type", "unknown"),
                "occurred_at": event.get("occurred_at"),
                "source": "relay_server",
            }
            if "event_type" in event:
                tags.append(f"event:{event['event_type']}")
            if "category" in event:
                tags.append(f"category:{event['category']}")
            memory_id = store_episodic_memory(content=event, tags=tags, context=context)
            logger.info("Stored event in memory: %s", memory_id)
        except Exception as e:
            logger.warning("Memory storage failed: %s", e)

    def do_POST(self):
        if not self._check_auth():
            return
        if not self._check_rate("event"):
            return

        cfg = self.server.cfg  # type: ignore[attr-defined]
        req_path = urlparse(self.path).path
        want_path = cfg["relay"]["path"]

        if req_path not in (want_path, want_path + "/batch"):
            return self._send(404, {"ok": False, "error": "not_found"})

        length = int(self.headers.get('Content-Length', '0'))
        if length > MAX_REQUEST_BYTES:
            return self._send(413, {"ok": False, "error": "payload_too_large",
                                    "max_bytes": MAX_REQUEST_BYTES})

        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode('utf-8'))
        except Exception as e:
            return self._send(400, {"ok": False, "error": "bad_json", "detail": str(e)})

        # Batch endpoint: expects {"events": [...]}
        if req_path == want_path + "/batch":
            if not isinstance(payload, dict) or "events" not in payload:
                return self._send(400, {"ok": False, "error": "batch_requires_events_array"})
            events = payload["events"]
            if not isinstance(events, list):
                return self._send(400, {"ok": False, "error": "events_must_be_array"})

            results = []
            stored = 0
            for event in events:
                ok, _code, body = self._store_single_event(event, cfg)
                results.append(body)
                if ok:
                    stored += 1
            return self._send(200, {"ok": True, "stored": stored, "total": len(events), "results": results})

        # Single event endpoint
        _ok, code, body = self._store_single_event(payload, cfg)
        return self._send(code, body)

    def do_GET(self):
        if not self._check_auth():
            return
        if not self._check_rate("api"):
            return

        path = urlparse(self.path).path

        # Health check endpoint
        if path == "/health":
            health_status: dict[str, Any] = {"status": "healthy", "timestamp": datetime.datetime.now().isoformat()}

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
                query: dict[str, Any] = {}
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

        # Prometheus-compatible metrics endpoint
        elif path == "/metrics":
            if _PROMETHEUS_CLIENT:
                body = _prom_generate()
                content_type = _PROM_CONTENT_TYPE
            else:
                lines = ["# TYPE ncl_relay_counter counter"]
                for metric, value in _METRICS.items():
                    lines.append(f"ncl_relay_{metric} {value}")
                body = ("\n".join(lines) + "\n").encode("utf-8")
                content_type = "text/plain; version=0.0.4; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body if isinstance(body, bytes) else body.encode("utf-8"))
            return

        else:
            return self._send(404, {"error": "Not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8787)
    ap.add_argument('--tls-cert', default=None, help='Path to TLS certificate PEM file')
    ap.add_argument('--tls-key', default=None, help='Path to TLS private key PEM file')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')

    cfg = load_config()

    # Build auth + rate limiter from config
    access = cfg.get("access", {})
    rl_cfg = access.get("rate_limiting", {})
    rate_limiter = RateLimiter(
        events_per_minute=rl_cfg.get("events_per_minute", 60),
        api_calls_per_minute=rl_cfg.get("api_calls_per_minute", 30),
    )
    auth = AuthManager(required=access.get("api_keys_required", False))

    httpd = HTTPServer((args.host, args.port), Handler)
    httpd.cfg = cfg  # type: ignore[attr-defined]
    httpd.rate_limiter = rate_limiter  # type: ignore[attr-defined]
    httpd.auth = auth  # type: ignore[attr-defined]
    httpd.seen_event_ids = set()  # type: ignore[attr-defined]

    # Optional TLS
    scheme = "http"
    if args.tls_cert and args.tls_key:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(args.tls_cert, args.tls_key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    logger.info("NCL Relay listening on %s://%s:%d%s", scheme, args.host, args.port, cfg['relay']['path'])
    httpd.serve_forever()


if __name__ == '__main__':
    main()
