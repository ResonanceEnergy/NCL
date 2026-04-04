# Council Output — PUMP-CODING-TEST-001

## Council Session
- **Chair:** Claude
- **Strategy:** Hierarchical Delegation (simple task, no debate needed)
- **Duration:** Immediate pass-through

## Decision
Build a single-file Python CLI (`nartix-health`) that:
1. Checks HTTP health endpoints for relay, NCL brain, Paperclip, Ollama
2. Uses `httpx` for async HTTP with TLS skip for self-signed certs
3. Outputs a rich table using `rich` library
4. Supports `--json` flag for machine-readable output
5. Color codes: green=healthy, red=down, yellow=degraded

## Implementation Plan
- Single file: `nartix_health.py`
- Use `click` for CLI, `httpx` for HTTP, `rich` for table output
- Service config as a dict of name → (url, expected_status_key)
- Async check all services in parallel with `asyncio.gather`
- Timeout per service: 5 seconds
- Exit code: 0 if all healthy, 1 if any down

## Acceptance Criteria
1. Running `python3 nartix_health.py` prints a table with all 4 services
2. Each service shows: name, URL, status (UP/DOWN/DEGRADED), response time
3. `--json` flag outputs valid JSON array
4. Handles connection refused, timeout, and TLS errors gracefully
5. Works on Mac Mini M4 Pro with Python 3.12+
