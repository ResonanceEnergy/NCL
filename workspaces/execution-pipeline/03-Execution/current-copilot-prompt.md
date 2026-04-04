# Copilot Prompt — PUMP-CODING-TEST-001 (iteration 1)

```
// NARTIX EXECUTION — Iteration 1/3
// Pump: PUMP-CODING-TEST-001
// Pillar: NCC | Priority: P1

// === GOAL ===
// Build a Python health-check dashboard CLI that monitors all NARTIX services
// (relay on :8787, NCL brain on :8800, Paperclip on :3100, Ollama on :11434)
// and outputs a color-coded status table.

// === COUNCIL DECISION ===
// Single-file Python CLI using click + httpx + rich
// Async parallel checks, 5s timeout, color coded output
// --json flag for machine output

// === ACCEPTANCE CRITERIA ===
// 1. Running python3 nartix_health.py prints a table with all 4 services
// 2. Each service shows: name, URL, status (UP/DOWN/DEGRADED), response time
// 3. --json flag outputs valid JSON array
// 4. Handles connection refused, timeout, and TLS errors gracefully
// 5. Works on Mac Mini M4 Pro with Python 3.12+

// === CONSTRAINTS ===
// - Python 3.12+ with type hints
// - Include error handling and structured logging
// - Add docstrings on all public functions
// - Make it executable: if __name__ == "__main__"
```
