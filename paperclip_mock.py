"""
Minimal Paperclip mock server for local development.

Listens on port 3100 and returns stub responses for all endpoints
so NCL Brain can start without a real Paperclip instance.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = 3100
log = logging.getLogger("paperclip-mock")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class PaperclipMockHandler(BaseHTTPRequestHandler):
    """Return minimal stub JSON for any request path."""

    def log_message(self, fmt: str, *args: object) -> None:  # suppress default access log
        log.info(fmt, *args)

    def _send_json(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/health", "/healthz", "/api/health"):
            self._send_json(200, {"status": "ok", "mock": True})
        else:
            self._send_json(200, {"mock": True, "path": self.path, "data": []})

    def do_POST(self) -> None:  # noqa: N802
        self._send_json(200, {"mock": True, "path": self.path, "accepted": True})

    def do_PUT(self) -> None:  # noqa: N802
        self._send_json(200, {"mock": True, "path": self.path, "updated": True})

    def do_DELETE(self) -> None:  # noqa: N802
        self._send_json(200, {"mock": True, "path": self.path, "deleted": True})


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), PaperclipMockHandler)
    log.info("Paperclip mock server listening on port %d", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down")
