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
import json
import logging
import logging.handlers
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# --- Config ---

NCL_BASE = Path.home() / "Projects" / "NCL"
INPUT_DIR = NCL_BASE / "mandate-generation" / "input"
PROCESSED_DIR = NCL_BASE / "mandate-generation" / "processed"
FAILED_DIR = NCL_BASE / "mandate-generation" / "failed"
NCL_BRAIN_URL = os.getenv("NCL_BRAIN_URL", "http://localhost:8800")
RELAY_URL = os.getenv("RELAY_URL", "https://localhost:8787")
STRIKE_AUTH_TOKEN = os.getenv("STRIKE_AUTH_TOKEN", "")
if not STRIKE_AUTH_TOKEN:
    log.warning(
        "STRIKE_AUTH_TOKEN not set — pump forwarding to brain will fail auth. "
        "Set it in .env or export it before starting the watcher."
    )
POLL_INTERVAL = int(os.getenv("PUMP_WATCHER_INTERVAL", "5"))  # seconds

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

# Track processed files to avoid re-processing
_processed_files: set[str] = set()


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
        import uuid
        payload = {
            "id": f"RSP-WATCHER-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
            "promptId": prompt_id,
            "source": source,
            "type": response_type,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": None,
        }
        async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
            await client.post(
                f"{RELAY_URL}/responses/{session_id}",
                json=payload,
            )
    except Exception as e:
        log.debug(f"Response push failed (non-critical): {e}")


def copy_pump_to_mwp(pump_file: Path, envelope: dict) -> Path | None:
    """
    Copy pump into MWP execution pipeline 01-Input/.
    Returns the destination path, or None on failure.
    """
    try:
        MWP_INPUT.mkdir(parents=True, exist_ok=True)
        dest = MWP_INPUT / pump_file.name
        shutil.copy2(str(pump_file), str(dest))
        log.info(f"MWP: Copied {pump_file.name} → 01-Input/")
        return dest
    except Exception as e:
        log.error(f"MWP copy failed for {pump_file.name}: {e}")
        return None


async def forward_pump_to_brain(pump_file: Path) -> bool:
    """
    Read pump file and forward to NCL Brain API.
    Returns True if successfully forwarded.
    """
    try:
        with open(pump_file) as f:
            envelope = json.load(f)

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
                "watcher_source": str(pump_file),
            },
            "urgency": _priority_to_urgency(prompt.get("priority", "P2")),
        }

        headers = {}
        if STRIKE_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {STRIKE_AUTH_TOKEN}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{NCL_BRAIN_URL}/pump",
                json=brain_payload,
                headers=headers,
                params={"auto_flow": True},
            )

            if resp.status_code == 200:
                # Mark as brain-acked in the envelope
                envelope["_brain_ack"] = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "brain_response": resp.json(),
                }
                with open(pump_file, "w") as f:
                    json.dump(envelope, f, indent=2)

                log.info(f"FORWARDED {pump_file.name} → NCL Brain (200 OK)")
                return True
            else:
                log.warning(f"Brain rejected {pump_file.name}: {resp.status_code}")
                return False

    except httpx.ConnectError:
        log.warning(f"NCL Brain not reachable — will retry {pump_file.name}")
        return False
    except json.JSONDecodeError:
        log.error(f"Invalid JSON in {pump_file.name}")
        return False
    except Exception as e:
        log.error(f"Error processing {pump_file.name}: {e}")
        return False


async def process_pending_pumps():
    """Scan input dir for unprocessed pump files and forward them."""
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_DIR.mkdir(parents=True, exist_ok=True)

    pump_files = sorted(INPUT_DIR.glob("pump-*.json"))

    for pump_file in pump_files:
        if pump_file.name in _processed_files:
            continue

        # Read envelope — skip file if unreadable
        try:
            with open(pump_file) as f:
                envelope = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            log.error(f"Cannot read {pump_file.name}: {e} — skipping")
            continue

        # Check if already brain-acked
        if envelope.get("_brain_ack"):
            try:
                dest = PROCESSED_DIR / pump_file.name
                shutil.move(str(pump_file), str(dest))
                _processed_files.add(pump_file.name)
                log.info(f"Moved already-processed {pump_file.name} → processed/")
            except OSError as e:
                log.warning(f"Failed to move {pump_file.name}: {e}")
            continue

        # Copy to MWP execution pipeline
        copy_pump_to_mwp(pump_file, envelope)

        # Extract session ID for response push
        session_id = envelope.get("prompt", {}).get("metadata", {}).get("session_id", "")
        prompt_id = envelope.get("prompt", {}).get("id")

        success = await forward_pump_to_brain(pump_file)

        if success:
            # Move to processed (guard against file disappearing between check and move)
            try:
                dest = PROCESSED_DIR / pump_file.name
                shutil.move(str(pump_file), str(dest))
                _processed_files.add(pump_file.name)
                log.info(f"Moved {pump_file.name} → processed/")
            except OSError as e:
                log.warning(f"Failed to move {pump_file.name} after success: {e}")
                _processed_files.add(pump_file.name)  # still mark to avoid retry loop

            # Notify iPhone
            await send_response_to_relay(
                session_id=session_id,
                response_type="processing",
                message=f"Pump {pump_file.name} ingested into MWP pipeline → council stage next",
                prompt_id=prompt_id,
                source="ncl-watcher",
            )
        else:
            # Brain offline — still notify iPhone that pump is queued in MWP
            await send_response_to_relay(
                session_id=session_id,
                response_type="status",
                message=f"Pump {pump_file.name} queued in MWP pipeline (brain offline — file-only mode)",
                prompt_id=prompt_id,
                source="ncl-watcher",
            )


async def run_watcher():
    """Main watcher loop."""
    log.info("=" * 50)
    log.info("  NCL Pump Watcher v2.0.0")
    log.info(f"  Watching: {INPUT_DIR}")
    log.info(f"  Brain URL: {NCL_BRAIN_URL}")
    log.info(f"  Relay URL: {RELAY_URL}")
    log.info(f"  MWP Pipeline: {EXEC_PIPELINE}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info("=" * 50)

    while True:
        try:
            await process_pending_pumps()
        except Exception as e:
            log.error(f"Watcher cycle error: {e}")

        await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run_watcher())
