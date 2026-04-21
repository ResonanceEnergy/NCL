"""
E2E Pipeline Test — STRIKE-POINT → NCL Brain Cortex

Tests the full pump prompt pipeline:
1. Send pump to FirstStrike relay (port 8787)
2. Verify file lands in NCL/mandate-generation/input/
3. Verify NCL brain receives the forward (port 8800)
4. Verify relay stats update

Run:
    python3 tests/test_e2e_pipeline.py
    # Or: pytest tests/test_e2e_pipeline.py -v
"""

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Config
RELAY_URL = os.getenv("RELAY_URL", "https://localhost:8787")
BRAIN_URL = os.getenv("BRAIN_URL", "http://localhost:8800")
NCL_INPUT_DIR = Path.home() / "Projects" / "NCL" / "mandate-generation" / "input"
NCL_PROCESSED_DIR = Path.home() / "Projects" / "NCL" / "mandate-generation" / "processed"

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
NC = "\033[0m"


def ok(msg: str):
    print(f"  {GREEN}✓{NC} {msg}")


def fail(msg: str):
    print(f"  {RED}✗{NC} {msg}")


def warn(msg: str):
    print(f"  {YELLOW}⚠{NC} {msg}")


def test_relay_health():
    """Test 1: Relay server is up and healthy."""
    print(f"\n{CYAN}[Test 1] Relay Health Check{NC}")
    try:
        resp = httpx.get(f"{RELAY_URL}/health", verify=False, timeout=5.0)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert data["status"] in ("ok", "degraded"), f"Bad status: {data['status']}"
        ok(f"Relay is {data['status']} on port {data.get('port', 8787)}")

        ts_ip = data.get("tailscale_ip", "not_connected")
        if ts_ip != "not_connected":
            ok(f"Tailscale IP: {ts_ip}")
        else:
            warn("Tailscale not connected")

        ok(f"NCL dir writable: {data.get('ncl_dir_writable', False)}")
        return True
    except Exception as e:
        fail(f"Relay not reachable: {e}")
        return False


def test_brain_health():
    """Test 2: NCL Brain service is up."""
    print(f"\n{CYAN}[Test 2] NCL Brain Health Check{NC}")
    try:
        resp = httpx.get(f"{BRAIN_URL}/health", timeout=5.0)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        ok(f"NCL Brain is running on {BRAIN_URL}")
        return True
    except httpx.ConnectError:
        warn(f"NCL Brain not reachable at {BRAIN_URL} — relay will operate in file-only mode")
        return False
    except Exception as e:
        fail(f"NCL Brain error: {e}")
        return False


def test_send_pump():
    """Test 3: Send a test pump prompt through the relay."""
    print(f"\n{CYAN}[Test 3] Send Test Pump Prompt{NC}")

    test_id = f"TEST-{uuid.uuid4().hex[:8].upper()}"
    pump_payload = {
        "id": test_id,
        "rawIntent": "E2E pipeline test — verify pump lands in NCL mandate-generation/input/",
        "formattedPrompt": "This is an automated E2E test pump prompt for MANDATE-2026-008 verification.",
        "targetPillar": "NCL",
        "priority": "P2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": {
            "source": "e2e-test",
            "appVersion": "test-1.0.0",
            "grokFormatted": False,
            "sessionId": f"test-session-{uuid.uuid4().hex[:6]}",
        },
    }

    try:
        resp = httpx.post(
            f"{RELAY_URL}/pump",
            json=pump_payload,
            verify=False,
            timeout=10.0,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        relay_id = data.get("relayId", "")
        ncl_file = data.get("nclFilePath", "")
        forwarded = data.get("forwardedTo", "")
        queue_pos = data.get("queuePosition", 0)

        ok(f"Relay accepted pump → {relay_id}")
        ok(f"NCL file: {ncl_file}")
        ok(f"Forwarded to: {forwarded}")
        ok(f"Queue position: {queue_pos}")

        return test_id, ncl_file, relay_id
    except Exception as e:
        fail(f"Pump send failed: {e}")
        return None, None, None


@pytest.mark.skip(reason="Requires running NCL server and ncl_file fixture")
def test_file_landed(ncl_file: str):
    """Test 4: Verify the pump file exists in NCL input dir."""
    print(f"\n{CYAN}[Test 4] Verify File in NCL Input Dir{NC}")

    if not ncl_file:
        fail("No NCL file to check (previous test failed)")
        return False

    filepath = NCL_INPUT_DIR / ncl_file

    # Check input dir first, then processed dir (watcher may have moved it)
    if filepath.exists():
        ok(f"File found: {filepath}")

        with open(filepath) as f:
            envelope = json.load(f)

        ok(f"Pump ID: {envelope.get('pump_id', 'N/A')}")
        ok(f"Relay ID: {envelope.get('relay_id', 'N/A')}")
        ok(f"Pipeline: {envelope.get('pipeline', 'N/A')}")
        ok(f"Mandate ref: {envelope.get('mandate_ref', 'N/A')}")

        # Verify envelope structure
        assert "prompt" in envelope, "Missing 'prompt' in envelope"
        assert "relay_id" in envelope, "Missing 'relay_id' in envelope"
        ok("Envelope structure valid")
        return True

    # Check processed dir
    processed_path = NCL_PROCESSED_DIR / ncl_file
    if processed_path.exists():
        ok(f"File already processed (watcher moved it): {processed_path}")
        return True

    fail(f"File not found in input/ or processed/: {ncl_file}")
    return False


def test_relay_stats():
    """Test 5: Verify relay stats updated."""
    print(f"\n{CYAN}[Test 5] Relay Stats Updated{NC}")
    try:
        resp = httpx.get(f"{RELAY_URL}/health", verify=False, timeout=5.0)
        data = resp.json()
        stats = data.get("stats", {})

        total = stats.get("total_received", 0)
        written = stats.get("total_written", 0)
        errors = stats.get("total_errors", 0)
        last = stats.get("last_pump_at", None)

        ok(f"Total received: {total}")
        ok(f"Total written: {written}")
        ok(f"Errors: {errors}")
        ok(f"Last pump at: {last}")

        assert total > 0, "No pumps received"
        assert written > 0, "No pumps written"
        return True
    except Exception as e:
        fail(f"Stats check failed: {e}")
        return False


def run_all():
    """Run full E2E pipeline test."""
    print(f"{CYAN}{'=' * 55}{NC}")
    print(f"{CYAN}  STRIKE-POINT E2E Pipeline Test{NC}")
    print(f"{CYAN}  MANDATE-2026-008{NC}")
    print(f"{CYAN}{'=' * 55}{NC}")

    results = {}

    # Test 1: Relay health
    results["relay_health"] = test_relay_health()
    if not results["relay_health"]:
        fail("Cannot continue — relay not running")
        print(f"\n{RED}FAILED — Start relay first: python3 relay-pump-endpoint.py{NC}")
        return False

    # Test 2: Brain health
    results["brain_health"] = test_brain_health()

    # Test 3: Send pump
    test_id, ncl_file, relay_id = test_send_pump()
    results["pump_sent"] = test_id is not None

    if results["pump_sent"]:
        # Brief pause for file write + potential watcher processing
        time.sleep(1)

        # Test 4: File verification
        results["file_landed"] = test_file_landed(ncl_file)

        # Test 5: Stats
        results["stats_updated"] = test_relay_stats()

    # Summary
    print(f"\n{CYAN}{'=' * 55}{NC}")
    print(f"{CYAN}  Results{NC}")
    print(f"{CYAN}{'=' * 55}{NC}")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test, result in results.items():
        status = f"{GREEN}PASS{NC}" if result else f"{RED}FAIL{NC}"
        print(f"  [{status}] {test}")

    print(f"\n  {passed}/{total} tests passed")

    if passed == total:
        print(f"\n{GREEN}  ★ PIPELINE OPERATIONAL — iPhone → Relay → NCL ★{NC}\n")
    elif results.get("pump_sent") and results.get("file_landed"):
        print(f"\n{YELLOW}  Pipeline functional (file path works, brain may need API keys){NC}\n")
    else:
        print(f"\n{RED}  Pipeline needs attention{NC}\n")

    return passed == total


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
