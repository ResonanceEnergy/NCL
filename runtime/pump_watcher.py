"""
NCL Pump Watcher — Filesystem monitor for pump prompt ingestion.

Watches NCL/mandate-generation/input/ for new pump-*.json files.
When a new pump lands (from FirstStrike relay file write), this watcher:
1. Reads the pump envelope
2. Forwards to NCL Brain API (/pump) if not already processed
3. Moves processed files to mandate-generation/processed/
4. Logs everything

This is the FALLBACK path. Primary path is relay → brain API direct.
Watcher catches pumps that arrived while brain was down, or when
the relay couldn't reach the brain API.

Part of MANDATE-2026-008: STRIKE-POINT Full Pipeline.

Usage:
    python3 -m runtime.pump_watcher
    # Or via launchd: com.resonanceenergy.ncl-watcher.plist
"""

import asyncio
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
import signal
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import httpx


# --- Time-windowed Bloom Filter for processed ID tracking (Fix #13) ---

class _TimeWindowedBloomFilter:
    """Approximate membership filter with time-based expiry.

    Prevents duplicate dispatch when the bounded OrderedDict evicts entries.
    Uses multiple hash functions over a fixed-size bit array with a sliding
    time window. Entries older than `window_seconds` are periodically purged
    by rotating the active filter.
    """

    def __init__(self, capacity: int = 100_000, window_seconds: int = 86400) -> None:
        self._capacity = capacity
        self._window_seconds = window_seconds
        self._bits_current: set[int] = set()
        self._bits_previous: set[int] = set()
        self._rotated_at: float = time.monotonic()
        self._num_hashes = 5

    def _hashes(self, key: str) -> list[int]:
        """Generate multiple hash positions for the key."""
        positions = []
        for i in range(self._num_hashes):
            h = int(hashlib.md5(f"{key}:{i}".encode()).hexdigest(), 16) % self._capacity
            positions.append(h)
        return positions

    def _maybe_rotate(self) -> None:
        """Rotate filters if the time window has elapsed."""
        elapsed = time.monotonic() - self._rotated_at
        if elapsed >= self._window_seconds:
            self._bits_previous = self._bits_current
            self._bits_current = set()
            self._rotated_at = time.monotonic()

    def add(self, key: str) -> None:
        """Mark a key as seen."""
        self._maybe_rotate()
        for h in self._hashes(key):
            self._bits_current.add(h)

    def __contains__(self, key: str) -> bool:
        """Check if key was probably seen within the time window."""
        self._maybe_rotate()
        hashes = self._hashes(key)
        # Check both current and previous windows
        if all(h in self._bits_current for h in hashes):
            return True
        if all(h in self._bits_previous for h in hashes):
            return True
        return False

# --- Config ---

# Hydrate STRIKE_AUTH_TOKEN from macOS keychain if not already in env.
# Allows the launchd plist to omit secrets entirely.
if not os.getenv("STRIKE_AUTH_TOKEN"):
    try:
        import subprocess as _sp
        _r = _sp.run(
            ["security", "find-generic-password", "-s", "ncl-strike-auth-token",
             "-a", "natrix", "-w"],
            capture_output=True, text=True, timeout=2,
        )
        if _r.returncode == 0 and _r.stdout.strip():
            os.environ["STRIKE_AUTH_TOKEN"] = _r.stdout.strip()
    except Exception:
        pass

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
INPUT_DIR = NCL_BASE / "mandate-generation" / "input"
PROCESSED_DIR = NCL_BASE / "mandate-generation" / "processed"
FAILED_DIR = NCL_BASE / "mandate-generation" / "failed"
NCL_BRAIN_URL = os.getenv("NCL_BRAIN_URL", "http://localhost:8800")
RELAY_URL = os.getenv("RELAY_URL", "https://localhost:8787")
STRIKE_AUTH_TOKEN = os.getenv("STRIKE_AUTH_TOKEN", "")
POLL_INTERVAL = int(os.getenv("PUMP_WATCHER_INTERVAL", "5"))  # seconds

# TLS config: PUMP_TLS_VERIFY=false disables verification (for dev).
# PUMP_CA_CERT=/path/to/ca-bundle.pem enables a custom CA for self-signed certs.
_tls_verify_env = os.getenv("PUMP_TLS_VERIFY", "true").lower()
_PUMP_TLS_VERIFY: bool | str = True
if _tls_verify_env in ("false", "0", "no"):
    _PUMP_TLS_VERIFY = False
elif os.getenv("PUMP_CA_CERT"):
    _PUMP_TLS_VERIFY = os.getenv("PUMP_CA_CERT")  # path to CA bundle

# Processed-file tracking — bounded OrderedDict (evict oldest when full)
# Fix #13: Backed by a bloom filter so evicted IDs aren't re-dispatched
_PROCESSED_MAX = 10_000
_processed_files: OrderedDict[str, None] = OrderedDict()
_processed_bloom = _TimeWindowedBloomFilter(capacity=100_000, window_seconds=86400)

# Graceful shutdown flag
_shutdown = False

# Fix #14: Retry tracking with exponential backoff (max 5 retries)
_MAX_RETRIES = 5
_retry_counts: dict[str, int] = {}  # filename -> attempt count
_retry_backoff_until: dict[str, float] = {}  # filename -> time.monotonic() when retry allowed

# MWP Execution Pipeline directories
EXEC_PIPELINE = NCL_BASE / "workspaces" / "execution-pipeline"
MWP_INPUT = EXEC_PIPELINE / "01-Input"
MWP_PLANNING = EXEC_PIPELINE / "02-Planning"

# --- Logging ---

LOG_DIR = NCL_BASE / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "pump-watcher.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
        ),
    ],
)
log = logging.getLogger("ncl.pump-watcher")


# ── Shared HTTP Client ───────────────────────────────────────────────────
# Reuse a single httpx.AsyncClient across relay pushes and brain forwards
# to avoid connection pool exhaustion from per-request client creation.

_pw_client: httpx.AsyncClient | None = None
_pw_client_lock: asyncio.Lock | None = None


def _get_pw_lock() -> asyncio.Lock:
    global _pw_client_lock
    if _pw_client_lock is None:
        _pw_client_lock = asyncio.Lock()
    return _pw_client_lock


async def _get_pw_client() -> httpx.AsyncClient:
    """Return a shared HTTP client for pump watcher calls."""
    global _pw_client
    if _pw_client is None or _pw_client.is_closed:
        async with _get_pw_lock():
            if _pw_client is None or _pw_client.is_closed:
                _pw_client = httpx.AsyncClient(timeout=30.0, verify=_PUMP_TLS_VERIFY)
    return _pw_client


async def close_pw_client() -> None:
    """Close the shared HTTP client (call on shutdown)."""
    global _pw_client
    if _pw_client is not None:
        await _pw_client.aclose()
        _pw_client = None


def _mark_processed(filename: str) -> None:
    """Add filename to bounded processed-file tracker; evict oldest if at cap.

    Fix #13: Also add to bloom filter so evicted IDs are still recognized.
    """
    _processed_bloom.add(filename)
    if filename in _processed_files:
        _processed_files.move_to_end(filename)
        return
    _processed_files[filename] = None
    while len(_processed_files) > _PROCESSED_MAX:
        _processed_files.popitem(last=False)


if not STRIKE_AUTH_TOKEN:
    log.warning(
        "STRIKE_AUTH_TOKEN not set — pump forwarding to brain will fail auth. "
        "Set it in .env or export it before starting the watcher."
    )



def _priority_to_urgency(priority: str) -> str:
    """Map pump priority to NCL brain urgency."""
    mapping = {
        "P0": "critical", "P1": "high", "P2": "normal", "P3": "low", "P4": "low",
        "critical": "critical", "high": "high", "medium": "normal", "low": "low",
    }
    return mapping.get(priority, "normal")


async def send_response_to_relay(
    session_id: str,
    response_type: str,
    message: str,
    prompt_id: str | None = None,
    source: str = "pump-watcher",
) -> None:
    """Push a response message back to the relay for iPhone delivery."""
    if not session_id:
        return
    try:
        payload = {
            "id": f"RSP-WATCHER-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
            "promptId": prompt_id,
            "source": source,
            "type": response_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": None,
        }
        # Fix #12: Include auth header on outgoing relay pushes
        headers = {}
        if STRIKE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {STRIKE_AUTH_TOKEN}"
        client = await _get_pw_client()
        await client.post(
            f"{RELAY_URL}/responses/{session_id}",
            json=payload,
            headers=headers,
            timeout=10.0,
        )
    except Exception as e:
        log.debug(f"Response push failed (non-critical): {e}")


async def _wait_for_file_stable(path: Path, settle_time: float = 0.5) -> bool:
    """Wait until a file's size is stable (not being written to).

    Fix #11: Prevents reading a partially-written file.
    Returns True if stable, False if file vanished or didn't stabilize in 5s.
    """
    max_checks = 10
    for _ in range(max_checks):
        try:
            size1 = path.stat().st_size
        except OSError:
            return False
        await asyncio.sleep(settle_time)
        try:
            size2 = path.stat().st_size
        except OSError:
            return False
        if size1 == size2 and size1 > 0:
            return True
    return False


async def copy_pump_to_mwp(pump_file: Path, envelope: dict) -> Path | None:
    """
    Copy pump into MWP execution pipeline 01-Input/.
    Returns the destination path, or None on failure.

    Fix #11: Uses atomic rename (write to .tmp then rename) to prevent
    the downstream watcher from picking up a partially-written file.
    """
    try:
        MWP_INPUT.mkdir(parents=True, exist_ok=True)
        dest = MWP_INPUT / pump_file.name
        tmp_dest = MWP_INPUT / f".{pump_file.name}.tmp"
        await asyncio.to_thread(shutil.copy2, str(pump_file), str(tmp_dest))
        # Atomic rename — downstream sees either the old state or the complete file
        await asyncio.to_thread(tmp_dest.rename, dest)
        log.info(f"MWP: Copied {pump_file.name} → 01-Input/ (atomic)")
        return dest
    except Exception as e:
        log.error(f"MWP copy failed for {pump_file.name}: {e}")
        # Clean up temp file on failure
        try:
            tmp_dest = MWP_INPUT / f".{pump_file.name}.tmp"
            if tmp_dest.exists():
                tmp_dest.unlink()
        except Exception:
            pass
        return None


async def forward_pump_to_brain(pump_file: Path) -> bool:
    """
    Read pump file and forward to NCL Brain API.
    Returns True if successfully forwarded.
    """
    try:
        envelope = await asyncio.to_thread(
            lambda: json.loads(pump_file.read_bytes())
        )

        prompt = envelope.get("prompt", {})
        pump_id = envelope.get("pump_id", pump_file.stem)
        relay_id = envelope.get("relay_id", "WATCHER")

        # Check if already processed by brain (has _brain_ack marker)
        if envelope.get("_brain_ack"):
            log.info(f"Skipping {pump_file.name} — already processed by brain")
            return True

        brain_payload = {
            "prompt_id": prompt.get("id", pump_id),
            "source": f"pump-watcher:{prompt.get('metadata', {}).get('source', 'file')}",
            "intent": prompt.get("raw_intent", prompt.get("rawIntent", "")),
            "context": {
                "formatted_prompt": prompt.get("formatted_prompt", prompt.get("formattedPrompt")),
                "target_pillar": prompt.get("target_pillar", prompt.get("targetPillar", "NCL")),
                "priority": prompt.get("priority", "P2"),
                "relay_id": relay_id,
                "watcher_source": pump_file.name,
            },
            "urgency": _priority_to_urgency(prompt.get("priority", "P2")),
        }

        headers = {}
        if STRIKE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {STRIKE_AUTH_TOKEN}"

        # Fix #10: Use 30s timeout so a single slow response doesn't block the
        # entire poll cycle for 3 minutes. Brain /pump should return immediately
        # with mode='background'.
        client = await _get_pw_client()
        t0 = time.monotonic()
        try:
            resp = await asyncio.wait_for(
                client.post(
                    f"{NCL_BRAIN_URL}/pump",
                    json=brain_payload,
                    headers=headers,
                    params={"auto_flow": True},
                    timeout=30.0,
                ),
                timeout=30.0,
            )
        except (asyncio.TimeoutError, httpx.ReadTimeout):
            elapsed = time.monotonic() - t0
            log.error(
                "Brain timeout after %.1fs forwarding %s "
                "(url=%s/pump?auto_flow=true, timeout=30s, prompt_id=%s) "
                "— /pump should return mode='background' immediately; "
                "check brain stderr for lifespan / scheduler errors",
                elapsed,
                pump_file.name,
                NCL_BRAIN_URL,
                brain_payload.get("prompt_id"),
            )
            return False
        except httpx.WriteTimeout:
            elapsed = time.monotonic() - t0
            log.error(
                "Brain WriteTimeout after %.1fs forwarding %s "
                "(url=%s/pump, timeout=30s, payload_bytes=%d)",
                elapsed,
                pump_file.name,
                NCL_BRAIN_URL,
                len(json.dumps(brain_payload)),
            )
            return False

        if resp.status_code == 200:
            # Brain accepted the pump and created a mandate. We MUST mark
            # the file as acked or the next watcher tick will re-pump it
            # and produce a duplicate mandate. If the ack-write fails we
            # still return True so the caller moves the file out of input/.
            try:
                envelope["_brain_ack"] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "brain_response": resp.json(),
                }
                ack_payload = json.dumps(envelope, indent=2, default=str)
                await asyncio.to_thread(pump_file.write_text, ack_payload)
            except Exception as write_exc:
                log.error(
                    f"FORWARDED {pump_file.name} but ack-write failed: "
                    f"{type(write_exc).__name__}: {write_exc!r} — file will"
                    f" still be moved out of input/ to prevent duplicates"
                )

            log.info(f"FORWARDED {pump_file.name} → NCL Brain (200 OK)")
            return True
        else:
            log.warning(
                f"Brain rejected {pump_file.name}: {resp.status_code} "
                f"body={resp.text[:200]!r}"
            )
            return False

    except httpx.ConnectError:
        log.warning(f"NCL Brain not reachable — will retry {pump_file.name}")
        return False
    except json.JSONDecodeError:
        log.error(f"Invalid JSON in {pump_file.name}")
        return False
    except Exception as e:
        log.error(
            f"Error processing {pump_file.name}: {type(e).__name__}: {e!r}"
        )
        return False


async def process_pending_pumps():
    """Scan input dir for unprocessed pump files and forward them."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    pump_files = sorted(INPUT_DIR.glob("pump-*.json"))

    for pump_file in pump_files:
        # Fix #13: Check both the OrderedDict and bloom filter to prevent
        # duplicate dispatch after eviction
        if pump_file.name in _processed_files or pump_file.name in _processed_bloom:
            continue

        # Fix #14: Exponential backoff — skip files in cool-down period
        if pump_file.name in _retry_backoff_until:
            if time.monotonic() < _retry_backoff_until[pump_file.name]:
                continue  # still in backoff period
        if _retry_counts.get(pump_file.name, 0) >= _MAX_RETRIES:
            # Max retries exceeded — move to failed/
            log.error(f"Max retries ({_MAX_RETRIES}) exceeded for {pump_file.name} — moving to failed/")
            try:
                dest = FAILED_DIR / pump_file.name
                await asyncio.to_thread(shutil.move, str(pump_file), str(dest))
                _mark_processed(pump_file.name)
            except OSError as e:
                log.warning(f"Failed to move {pump_file.name} to failed/: {e}")
            _retry_counts.pop(pump_file.name, None)
            _retry_backoff_until.pop(pump_file.name, None)
            continue

        # Fix #11: Wait for file to stabilize before reading (partial write guard)
        if not await _wait_for_file_stable(pump_file, settle_time=0.3):
            log.warning(f"File {pump_file.name} not stable yet — skipping this cycle")
            continue

        # Read envelope — skip file if unreadable
        try:
            envelope = await asyncio.to_thread(
                lambda p=pump_file: json.loads(p.read_bytes())
            )
        except (json.JSONDecodeError, OSError) as e:
            log.error(f"Cannot read {pump_file.name}: {e} — skipping")
            continue

        # Check if already brain-acked
        if envelope.get("_brain_ack"):
            try:
                dest = PROCESSED_DIR / pump_file.name
                await asyncio.to_thread(shutil.move, str(pump_file), str(dest))
                _mark_processed(pump_file.name)
                log.info(f"Moved already-processed {pump_file.name} → processed/")
            except OSError as e:
                log.warning(f"Failed to move {pump_file.name}: {e}")
            continue

        # Copy to MWP execution pipeline
        await copy_pump_to_mwp(pump_file, envelope)

        # Extract session ID for response push
        session_id = envelope.get("prompt", {}).get("metadata", {}).get("session_id", "")
        prompt_id = envelope.get("prompt", {}).get("id")

        success = await forward_pump_to_brain(pump_file)

        if success:
            # Move to processed (guard against file disappearing between check and move)
            try:
                dest = PROCESSED_DIR / pump_file.name
                await asyncio.to_thread(shutil.move, str(pump_file), str(dest))
                _mark_processed(pump_file.name)
                log.info(f"Moved {pump_file.name} → processed/")
            except OSError as e:
                log.warning(f"Failed to move {pump_file.name} after success: {e}")
                _mark_processed(pump_file.name)  # still mark to avoid retry loop

            # Clear retry state on success
            _retry_counts.pop(pump_file.name, None)
            _retry_backoff_until.pop(pump_file.name, None)

            # Notify iPhone
            await send_response_to_relay(
                session_id=session_id,
                response_type="processing",
                message=f"Pump {pump_file.name} ingested into MWP pipeline → council stage next",
                prompt_id=prompt_id,
                source="ncl-watcher",
            )
        else:
            # Fix #14: Record failure and compute exponential backoff
            attempts = _retry_counts.get(pump_file.name, 0) + 1
            _retry_counts[pump_file.name] = attempts
            backoff_secs = min(2 ** attempts, 300)  # max 5 min backoff
            _retry_backoff_until[pump_file.name] = time.monotonic() + backoff_secs
            log.warning(
                f"Forward failed for {pump_file.name} (attempt {attempts}/{_MAX_RETRIES}) "
                f"— backing off {backoff_secs}s"
            )

            # Brain offline — still notify iPhone that pump is queued in MWP
            await send_response_to_relay(
                session_id=session_id,
                response_type="status",
                message=f"Pump {pump_file.name} queued in MWP pipeline (brain offline — file-only mode)",
                prompt_id=prompt_id,
                source="ncl-watcher",
            )


async def run_watcher():
    """Main watcher loop with graceful shutdown on SIGINT/SIGTERM."""
    global _shutdown

    loop = asyncio.get_running_loop()

    def _request_shutdown(signum, _frame) -> None:
        global _shutdown
        log.info(f"Signal {signum} received — shutting down pump watcher gracefully")
        _shutdown = True


    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown, sig, None)
        except (NotImplementedError, RuntimeError):
            # Windows / non-main-thread: fall back to signal.signal
            signal.signal(sig, _request_shutdown)

    tls_info = (
        "disabled"
        if _PUMP_TLS_VERIFY is False
        else ("custom CA" if isinstance(_PUMP_TLS_VERIFY, str) else "enabled")
    )
    log.info("=" * 50)
    log.info("  NCL Pump Watcher v2.0.0")
    log.info(f"  Watching: {INPUT_DIR}")
    log.info(f"  Brain URL: {NCL_BRAIN_URL}")
    log.info(f"  Relay URL: {RELAY_URL}")
    log.info(f"  Relay TLS verify: {tls_info}")
    log.info(f"  MWP Pipeline: {EXEC_PIPELINE}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info("=" * 50)

    while not _shutdown:
        try:
            await process_pending_pumps()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Watcher cycle error: {e}")

        try:
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            break

    log.info("Pump watcher stopped.")


if __name__ == "__main__":
    asyncio.run(run_watcher())
