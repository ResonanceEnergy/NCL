"""
Unit tests for runtime/pump_watcher.py

Tests pump file detection, envelope parsing, brain forwarding logic, and
the MWP pipeline copy — all without touching the filesystem or network.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    pump_id: str = "pump-001",
    intent: str = "Test intent",
    priority: str = "P2",
    session_id: str = "sess-abc",
    brain_ack: bool = False,
) -> dict:
    """Return a minimal pump envelope dict."""
    env = {
        "pump_id": pump_id,
        "relay_id": "RLY-TEST",
        "prompt": {
            "id": pump_id,
            "rawIntent": intent,
            "formattedPrompt": f"Formatted: {intent}",
            "targetPillar": "NCL",
            "priority": priority,
            "metadata": {"source": "test", "session_id": session_id},
        },
    }
    if brain_ack:
        env["_brain_ack"] = {"timestamp": "2026-01-01T00:00:00Z", "brain_response": {}}
    return env


# ---------------------------------------------------------------------------
# _priority_to_urgency
# ---------------------------------------------------------------------------

class TestPriorityToUrgency:
    def test_p0_is_critical(self):
        from runtime.pump_watcher import _priority_to_urgency
        assert _priority_to_urgency("P0") == "critical"

    def test_p1_is_high(self):
        from runtime.pump_watcher import _priority_to_urgency
        assert _priority_to_urgency("P1") == "high"

    def test_p2_is_normal(self):
        from runtime.pump_watcher import _priority_to_urgency
        assert _priority_to_urgency("P2") == "normal"

    def test_p3_is_low(self):
        from runtime.pump_watcher import _priority_to_urgency
        assert _priority_to_urgency("P3") == "low"

    def test_unknown_defaults_to_normal(self):
        from runtime.pump_watcher import _priority_to_urgency
        assert _priority_to_urgency("UNKNOWN") == "normal"

    def test_string_critical(self):
        from runtime.pump_watcher import _priority_to_urgency
        assert _priority_to_urgency("critical") == "critical"


# ---------------------------------------------------------------------------
# _mark_processed
# ---------------------------------------------------------------------------

class TestMarkProcessed:
    def test_adds_filename(self):
        from runtime import pump_watcher
        pump_watcher._processed_files.clear()
        pump_watcher._mark_processed("pump-001.json")
        assert "pump-001.json" in pump_watcher._processed_files

    def test_idempotent(self):
        from runtime import pump_watcher
        pump_watcher._processed_files.clear()
        pump_watcher._mark_processed("pump-001.json")
        pump_watcher._mark_processed("pump-001.json")
        assert len(pump_watcher._processed_files) == 1

    def test_evicts_oldest_at_cap(self):
        from runtime import pump_watcher
        pump_watcher._processed_files.clear()
        original_max = pump_watcher._PROCESSED_MAX
        pump_watcher._PROCESSED_MAX = 3
        try:
            for i in range(4):
                pump_watcher._mark_processed(f"pump-{i:03d}.json")
            # First entry should have been evicted
            assert "pump-000.json" not in pump_watcher._processed_files
            assert len(pump_watcher._processed_files) == 3
        finally:
            pump_watcher._PROCESSED_MAX = original_max
            pump_watcher._processed_files.clear()


# ---------------------------------------------------------------------------
# forward_pump_to_brain — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forward_pump_brain_success(tmp_path):
    """forward_pump_to_brain returns True when brain responds 200."""
    envelope = _make_envelope()
    pump_file = tmp_path / "pump-001.json"
    pump_file.write_text(json.dumps(envelope))

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"pump_id": "P-001", "status": "accepted"}

    with patch("runtime.pump_watcher.STRIKE_AUTH_TOKEN", "test-token"), \
         patch("runtime.pump_watcher.NCL_BRAIN_URL", "http://localhost:8800"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from runtime.pump_watcher import forward_pump_to_brain
        result = await forward_pump_to_brain(pump_file)

    assert result is True


# ---------------------------------------------------------------------------
# forward_pump_to_brain — brain offline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forward_pump_brain_connect_error(tmp_path):
    """forward_pump_to_brain returns False when brain is unreachable."""
    import httpx as _httpx
    envelope = _make_envelope()
    pump_file = tmp_path / "pump-002.json"
    pump_file.write_text(json.dumps(envelope))

    with patch("runtime.pump_watcher.STRIKE_AUTH_TOKEN", "test-token"), \
         patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client_cls.return_value = mock_client

        from runtime.pump_watcher import forward_pump_to_brain
        result = await forward_pump_to_brain(pump_file)

    assert result is False


# ---------------------------------------------------------------------------
# forward_pump_to_brain — already acked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forward_pump_skips_already_acked(tmp_path):
    """forward_pump_to_brain returns True immediately for acked envelopes."""
    envelope = _make_envelope(brain_ack=True)
    pump_file = tmp_path / "pump-003.json"
    pump_file.write_text(json.dumps(envelope))

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client_cls.return_value = AsyncMock()
        from runtime.pump_watcher import forward_pump_to_brain
        result = await forward_pump_to_brain(pump_file)

    assert result is True
    # HTTP client should NOT have been called
    mock_client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# forward_pump_to_brain — invalid JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forward_pump_invalid_json(tmp_path):
    """forward_pump_to_brain returns False for corrupt files."""
    pump_file = tmp_path / "pump-bad.json"
    pump_file.write_text("{ not valid json }")

    from runtime.pump_watcher import forward_pump_to_brain
    result = await forward_pump_to_brain(pump_file)

    assert result is False


# ---------------------------------------------------------------------------
# forward_pump_to_brain — brain returns non-200
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_forward_pump_brain_rejects(tmp_path):
    """forward_pump_to_brain returns False when brain returns 401/403/500."""
    envelope = _make_envelope()
    pump_file = tmp_path / "pump-004.json"
    pump_file.write_text(json.dumps(envelope))

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.text = "Forbidden"

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from runtime.pump_watcher import forward_pump_to_brain
        result = await forward_pump_to_brain(pump_file)

    assert result is False


# ---------------------------------------------------------------------------
# copy_pump_to_mwp
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_pump_to_mwp_creates_file(tmp_path):
    """copy_pump_to_mwp places a copy of the pump file in the MWP 01-Input dir."""
    envelope = _make_envelope()
    pump_file = tmp_path / "pump-005.json"
    pump_file.write_text(json.dumps(envelope))

    mwp_input = tmp_path / "01-Input"

    with patch("runtime.pump_watcher.MWP_INPUT", mwp_input):
        from runtime.pump_watcher import copy_pump_to_mwp
        dest = await copy_pump_to_mwp(pump_file, envelope)

    assert dest is not None
    assert dest.exists()
    assert dest.name == pump_file.name


# ---------------------------------------------------------------------------
# process_pending_pumps — integration-style with real temp dirs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_pending_pumps_moves_file_on_success(tmp_path):
    """process_pending_pumps moves a successfully forwarded pump to processed/."""
    input_dir = tmp_path / "input"
    processed_dir = tmp_path / "processed"
    failed_dir = tmp_path / "failed"
    input_dir.mkdir()
    processed_dir.mkdir()
    failed_dir.mkdir()

    envelope = _make_envelope(pump_id="pump-test-move")
    pump_file = input_dir / "pump-test-move.json"
    pump_file.write_text(json.dumps(envelope))

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"pump_id": "pump-test-move"}

    with patch("runtime.pump_watcher.INPUT_DIR", input_dir), \
         patch("runtime.pump_watcher.PROCESSED_DIR", processed_dir), \
         patch("runtime.pump_watcher.FAILED_DIR", failed_dir), \
         patch("runtime.pump_watcher.MWP_INPUT", tmp_path / "01-Input"), \
         patch("runtime.pump_watcher.STRIKE_AUTH_TOKEN", "tok"), \
         patch("runtime.pump_watcher._processed_files", {}), \
         patch("httpx.AsyncClient") as mock_client_cls, \
         patch("runtime.pump_watcher.send_response_to_relay", new_callable=AsyncMock):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from runtime.pump_watcher import process_pending_pumps
        await process_pending_pumps()

    # File should have moved to processed/
    assert not pump_file.exists()
    assert (processed_dir / "pump-test-move.json").exists()
