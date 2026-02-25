import asyncio
import pytest
from unittest.mock import AsyncMock, patch

# Assume NCC is imported from the right module where it should exist
# from ncl.core.ncc import NCC

@pytest.fixture
def mock_ncc():
    """Fixture to create a mock instance of NCC."""
    mock_instance = AsyncMock()
    mock_instance.initialize.return_value = True
    mock_instance.orchestrate_cycle.return_value = ["Insight1", "Insight2"]
    mock_instance.emergency_shutdown.return_value = None
    return mock_instance

@pytest.fixture
def start_ncl(monkeypatch, mock_ncc):
    """Fixture to patch NCC and return the main function from start_ncl.py"""
    monkeypatch.setattr("start_ncl.NCC", lambda: mock_ncc)
    from start_ncl import main
    return main

@pytest.mark.asyncio
async def test_main_happy_path(start_ncl, mock_ncc, monkeypatch):
    """Test the main function for successful execution."""

    # Patch sys.exit to prevent exiting
    monkeypatch.setattr("sys.exit", lambda code: None)

    # Simulate KeyboardInterrupt to exit after first loop
    async def exit_after_first_cycle():
        await asyncio.sleep(0.1)
        raise KeyboardInterrupt()
    
    monkeypatch.setattr("asyncio.sleep", exit_after_first_cycle)

    exit_code = await start_ncl()
    mock_ncc.initialize.assert_called_once_with()
    assert exit_code == 0, "Expected exit code 0 for successful run"

@pytest.mark.asyncio
async def test_main_initialization_failure(monkeypatch, start_ncl):
    """Test the main function when initialization fails."""
    mock_ncc = AsyncMock()
    mock_ncc.initialize.return_value = False

    monkeypatch.setattr("start_ncl.NCC", lambda: mock_ncc)

    exit_code = await start_ncl()
    assert exit_code == 1, "Expected exit code 1 if initialization fails"

@pytest.mark.asyncio
async def test_main_orchestrate_cycle_error(monkeypatch, mock_ncc, start_ncl):
    """Test the main function with error in orchestrate_cycle."""
    error_msg = "Simulated orchestrate_cycle error."
    mock_ncc.orchestrate_cycle.side_effect = Exception(error_msg)

    # Patch sys.exit to prevent exiting
    monkeypatch.setattr("sys.exit", lambda code: None)

    # Simulate KeyboardInterrupt after error handling
    async def exit_after_first_cycle():
        await asyncio.sleep(0.1)
        raise KeyboardInterrupt()
    
    monkeypatch.setattr("asyncio.sleep", exit_after_first_cycle)

    exit_code = await start_ncl()
    mock_ncc.initialize.assert_called_once_with()
    assert exit_code == 0, "Expected exit code 0, even after error in cycle"
    
@pytest.mark.asyncio
async def test_main_startup_failure(monkeypatch, capsys):
    """Test the main function with a startup failure."""
    with patch("start_ncl.NCC", side_effect=Exception("Module import failure")):
        from start_ncl import main
        exit_code = await main()
        captured = capsys.readouterr()
        assert "❌ Startup failed: Module import failure" in captured.out, \
            "Expected startup failure message on module import failure"
        assert exit_code == 1, "Expected exit code 1 on startup failure"
