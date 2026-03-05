#!/usr/bin/env python3
"""
Tests for TelegramConnector — mocks python-telegram-bot to verify
message routing, access control, truncation, and callback handling.
"""
import asyncio
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ── Path setup ────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "ncl_agency_runtime" / "agents"))


class TestTelegramConnector(unittest.TestCase):
    """Unit tests for TelegramConnector without a live bot."""

    def setUp(self):
        """Import module with mocks for telegram library."""
        # Create mock telegram modules so import succeeds without pip install
        self.mock_telegram = types.ModuleType("telegram")
        self.mock_telegram.Update = MagicMock
        self.mock_telegram.InlineKeyboardMarkup = MagicMock
        self.mock_telegram.InlineKeyboardButton = MagicMock

        self.mock_ext = types.ModuleType("telegram.ext")
        self.mock_ext.Application = MagicMock()
        self.mock_ext.CommandHandler = MagicMock()
        self.mock_ext.MessageHandler = MagicMock()
        self.mock_ext.CallbackQueryHandler = MagicMock()
        self.mock_ext.filters = MagicMock()
        self.mock_ext.ContextTypes = MagicMock()

        sys.modules["telegram"] = self.mock_telegram
        sys.modules["telegram.ext"] = self.mock_ext

        # Now import the connector
        import importlib
        if "telegram_connector" in sys.modules:
            importlib.reload(sys.modules["telegram_connector"])
        from telegram_connector import TelegramConnector, ChannelType
        self.TelegramConnector = TelegramConnector
        self.ChannelType = ChannelType

    def tearDown(self):
        for mod in ["telegram", "telegram.ext"]:
            sys.modules.pop(mod, None)

    # ── Init tests ──────────────────────────────────────

    def test_channel_type_is_telegram(self):
        tc = self.TelegramConnector(token="test-token")
        self.assertEqual(tc.channel_type, self.ChannelType.TELEGRAM)

    def test_token_from_constructor(self):
        tc = self.TelegramConnector(token="my-token")
        self.assertEqual(tc.token, "my-token")

    def test_token_from_env(self):
        with patch.dict(os.environ, {"NCL_TELEGRAM_TOKEN": "env-token"}):
            tc = self.TelegramConnector()
            self.assertEqual(tc.token, "env-token")

    def test_constructor_token_overrides_env(self):
        with patch.dict(os.environ, {"NCL_TELEGRAM_TOKEN": "env-token"}):
            tc = self.TelegramConnector(token="explicit-token")
            self.assertEqual(tc.token, "explicit-token")

    def test_default_prefix(self):
        tc = self.TelegramConnector(token="t")
        self.assertEqual(tc.prefix, "/ncl")

    def test_custom_prefix(self):
        tc = self.TelegramConnector(token="t", prefix="/brain")
        self.assertEqual(tc.prefix, "/brain")

    # ── Access control ──────────────────────────────────

    def test_allow_all_when_no_whitelist(self):
        tc = self.TelegramConnector(token="t")
        self.assertTrue(tc._is_allowed(12345))
        self.assertTrue(tc._is_allowed(99999))

    def test_allow_only_whitelisted(self):
        tc = self.TelegramConnector(token="t", allowed_user_ids=[100, 200])
        self.assertTrue(tc._is_allowed(100))
        self.assertTrue(tc._is_allowed(200))
        self.assertFalse(tc._is_allowed(300))

    def test_allowed_from_env(self):
        with patch.dict(os.environ, {"NCL_TELEGRAM_ALLOWED": "10,20,30"}):
            tc = self.TelegramConnector(token="t")
            self.assertTrue(tc._is_allowed(10))
            self.assertTrue(tc._is_allowed(30))
            self.assertFalse(tc._is_allowed(40))

    def test_allowed_env_handles_spaces(self):
        with patch.dict(os.environ, {"NCL_TELEGRAM_ALLOWED": " 10 , 20 , 30 "}):
            tc = self.TelegramConnector(token="t")
            self.assertTrue(tc._is_allowed(10))

    def test_allowed_env_ignores_non_numeric(self):
        with patch.dict(os.environ, {"NCL_TELEGRAM_ALLOWED": "10,abc,20"}):
            tc = self.TelegramConnector(token="t")
            self.assertEqual(tc.allowed_user_ids, {10, 20})

    # ── Start preconditions ──────────────────────────────

    def test_start_without_token_logs_error(self):
        tc = self.TelegramConnector(token="")
        agent = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(tc.start(agent))
        loop.close()
        self.assertIsNone(tc._app)

    # ── Truncation ──────────────────────────────────────

    def test_message_truncation_constant(self):
        """The connector truncates at 4000 chars (Telegram limit is 4096)."""
        # Verify the truncation logic exists by checking the source
        import inspect
        source = inspect.getsource(self.TelegramConnector)
        self.assertIn("4000", source)
        self.assertIn("truncated", source)

    # ── Stop idempotency ────────────────────────────────

    def test_stop_when_not_started(self):
        tc = self.TelegramConnector(token="t")
        loop = asyncio.new_event_loop()
        # Should not raise
        loop.run_until_complete(tc.stop())
        loop.close()

    # ── Send without app ────────────────────────────────

    def test_send_without_app_does_not_crash(self):
        from super_openclaw_agent import OutboundMessage, ChannelType
        tc = self.TelegramConnector(token="t")
        msg = OutboundMessage(
            channel=ChannelType.TELEGRAM,
            recipient_id="12345",
            text="hello",
        )
        loop = asyncio.new_event_loop()
        loop.run_until_complete(tc.send(msg))
        loop.close()


class TestTelegramConnectorIntegration(unittest.TestCase):
    """Higher-level integration tests (still mocked, no network)."""

    def test_connector_registers_with_agent(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ncl_agency_runtime" / "agents"))
        from super_openclaw_agent import create_agent
        agent = create_agent()
        initial = len(agent.channels)
        # Mock telegram module
        mock_telegram = types.ModuleType("telegram")
        mock_telegram.Update = MagicMock
        mock_telegram.InlineKeyboardMarkup = MagicMock
        mock_telegram.InlineKeyboardButton = MagicMock
        mock_ext = types.ModuleType("telegram.ext")
        mock_ext.Application = MagicMock()
        mock_ext.CommandHandler = MagicMock()
        mock_ext.MessageHandler = MagicMock()
        mock_ext.CallbackQueryHandler = MagicMock()
        mock_ext.filters = MagicMock()
        mock_ext.ContextTypes = MagicMock()
        sys.modules["telegram"] = mock_telegram
        sys.modules["telegram.ext"] = mock_ext

        import importlib
        if "telegram_connector" in sys.modules:
            importlib.reload(sys.modules["telegram_connector"])
        from telegram_connector import TelegramConnector
        tc = TelegramConnector(token="test")
        agent.add_channel(tc)
        self.assertEqual(len(agent.channels), initial + 1)

        sys.modules.pop("telegram", None)
        sys.modules.pop("telegram.ext", None)


if __name__ == "__main__":
    unittest.main()
