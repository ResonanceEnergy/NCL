"""NCL test fixtures."""
import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory for NCL brain."""
    d = tmp_path / "ncl_data"
    d.mkdir()
    return str(d)


@pytest.fixture
def mock_env(monkeypatch):
    """Set minimal env vars for testing."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("PAPERCLIP_URL", "http://localhost:3100")
    monkeypatch.setenv("PAPERCLIP_COMPANY_ID", "test-company")
