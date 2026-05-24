"""NCL test fixtures.

W8-A14 (2026-05-24): expanded with autouse env setup and Brain/auth mocking
hooks so handler-level tests can run without booting the full Brain. The
goal is to lock in invariants (envelope fences, pump-prompt validation,
mandate enum gating, outcome schema, A/B harness math) that concurrent
agent waves keep silently regressing.
"""

import os
from pathlib import Path

import pytest


# Known token surfaced to handler-level tests that need a Bearer header.
KNOWN_STRIKE_TOKEN = "test-strike-token-w8a14"


@pytest.fixture(autouse=True)
def monkeypatch_env(monkeypatch):
    """Autouse: stamp a known STRIKE_AUTH_TOKEN + redirect NCL_DATA_DIR.

    Every test in the suite gets a deterministic token and a tmp data root
    so on-disk writes (ab_test scores.jsonl, etc.) never pollute the real
    ``data/`` tree. Tests can override per-test via ``monkeypatch`` again.
    """
    monkeypatch.setenv("STRIKE_AUTH_TOKEN", KNOWN_STRIKE_TOKEN)
    # Don't clobber if a test set its own data root via a parent fixture.
    if "NCL_DATA_DIR" not in os.environ or "/Users/natrix/dev/NCL/data" in os.environ.get(
        "NCL_DATA_DIR", ""
    ):
        monkeypatch.setenv(
            "NCL_DATA_DIR", str(Path(os.environ.get("PYTEST_TMP_DATA_DIR", "/tmp/ncl-test-data")))
        )
    # Quiet the optional-env-var warnings emitted on import.
    monkeypatch.setenv("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "test-key"))
    monkeypatch.setenv("PAPERCLIP_URL", "http://localhost:3100")
    monkeypatch.setenv("PAPERCLIP_COMPANY_ID", "test-company")


@pytest.fixture
def data_dir(tmp_path):
    """Temporary data directory for NCL brain."""
    d = tmp_path / "ncl_data"
    d.mkdir()
    return str(d)


@pytest.fixture
def mock_env(monkeypatch):
    """Set minimal env vars for testing (legacy fixture — autouse covers it)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("PAPERCLIP_URL", "http://localhost:3100")
    monkeypatch.setenv("PAPERCLIP_COMPANY_ID", "test-company")


@pytest.fixture
def ab_test_data_root(tmp_path, monkeypatch):
    """Point runtime.memory.ab_test at a fresh tmp data dir.

    ``_data_root()`` resolves ``$NCL_DATA_DIR/memory/ab_test`` lazily on
    every call, so just stamping the env var is enough.
    """
    root = tmp_path / "ncl_data"
    root.mkdir()
    monkeypatch.setenv("NCL_DATA_DIR", str(root))
    return root / "memory" / "ab_test"


@pytest.fixture
def mock_brain(monkeypatch):
    """Replace ``runtime.api.routes.brain`` with a MagicMock.

    Lets handler-level tests exercise routes without booting the full Brain
    (which spins up 32 autonomous loops, opens ChromaDB, etc.). Tests that
    need specific async returns should set ``brain.<method>.return_value``
    or use ``AsyncMock`` directly.
    """
    from unittest.mock import MagicMock

    fake = MagicMock(name="brain")
    try:
        import runtime.api.routes as routes_mod

        monkeypatch.setattr(routes_mod, "brain", fake, raising=False)
    except Exception:
        # Routes module unavailable in slim test envs — tests that need it
        # will fail explicitly on their own import; nothing to do here.
        pass
    return fake


@pytest.fixture
def mock_strike_auth(monkeypatch):
    """No-op the ``_verify_strike_token`` Bearer check.

    For handler tests that want to focus on payload validation rather than
    auth plumbing. Replaces the verifier with a function that returns None
    unconditionally.
    """

    def _noop(authorization: str = ""):
        return None

    try:
        import runtime.api.routes as routes_mod

        monkeypatch.setattr(routes_mod, "_verify_strike_token", _noop, raising=False)
    except Exception:
        pass
    return _noop


@pytest.fixture
def strike_auth_header():
    """Bearer header that matches the autouse-stamped token."""
    return {"Authorization": f"Bearer {KNOWN_STRIKE_TOKEN}"}
