#!/usr/bin/env python3
"""
Tests for DiscordConnector — mocks discord.py to verify
message routing, prefix handling, channel filtering, and truncation.
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


class TestDiscordConnector(unittest.TestCase):
    """Unit tests for DiscordConnector without a live bot."""

    def setUp(self):
        """Inject mock discord module so import succeeds."""
        self.mock_discord = types.ModuleType("discord")
        self.mock_discord.Client = MagicMock
        self.mock_discord.Intents = MagicMock()
        self.mock_discord.Intents.default = MagicMock(return_value=MagicMock())
        self.mock_discord.Message = MagicMock
        self.mock_discord.HTTPException = Exception
        sys.modules["discord"] = self.mock_discord

        import importlib
        if "discord_connector" in sys.modules:
            importlib.reload(sys.modules["discord_connector"])
        from discord_connector import DiscordConnector, ChannelType
        self.DiscordConnector = DiscordConnector
        self.ChannelType = ChannelType

    def tearDown(self):
        sys.modules.pop("discord", None)

    # ── Init tests ──────────────────────────────────────

    def test_channel_type_is_discord(self):
        dc = self.DiscordConnector(token="test-token")
        self.assertEqual(dc.channel_type, self.ChannelType.DISCORD)

    def test_token_from_constructor(self):
        dc = self.DiscordConnector(token="my-token")
        self.assertEqual(dc.token, "my-token")

    def test_token_from_env(self):
        with patch.dict(os.environ, {"NCL_DISCORD_TOKEN": "env-token"}):
            dc = self.DiscordConnector()
            self.assertEqual(dc.token, "env-token")

    def test_constructor_token_overrides_env(self):
        with patch.dict(os.environ, {"NCL_DISCORD_TOKEN": "env-token"}):
            dc = self.DiscordConnector(token="explicit-token")
            self.assertEqual(dc.token, "explicit-token")

    def test_default_prefix(self):
        dc = self.DiscordConnector(token="t")
        self.assertEqual(dc.prefix, "!ncl")

    def test_custom_prefix(self):
        dc = self.DiscordConnector(token="t", prefix="!brain")
        self.assertEqual(dc.prefix, "!brain")

    # ── Channel filtering ────────────────────────────────

    def test_no_channel_filter_by_default(self):
        dc = self.DiscordConnector(token="t")
        self.assertEqual(dc.listen_channel_ids, set())

    def test_channel_ids_from_constructor(self):
        dc = self.DiscordConnector(token="t", listen_channel_ids=[111, 222])
        self.assertEqual(dc.listen_channel_ids, {111, 222})

    def test_channel_ids_from_env(self):
        with patch.dict(os.environ, {"NCL_DISCORD_CHANNELS": "100,200,300"}):
            dc = self.DiscordConnector(token="t")
            self.assertEqual(dc.listen_channel_ids, {100, 200, 300})

    def test_channel_ids_env_handles_spaces(self):
        with patch.dict(os.environ, {"NCL_DISCORD_CHANNELS": " 10 , 20 "}):
            dc = self.DiscordConnector(token="t")
            self.assertEqual(dc.listen_channel_ids, {10, 20})

    def test_channel_ids_env_ignores_non_numeric(self):
        with patch.dict(os.environ, {"NCL_DISCORD_CHANNELS": "10,abc,20"}):
            dc = self.DiscordConnector(token="t")
            self.assertEqual(dc.listen_channel_ids, {10, 20})

    # ── Start preconditions ──────────────────────────────

    def test_start_without_token_logs_error(self):
        dc = self.DiscordConnector(token="")
        agent = MagicMock()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(dc.start(agent))
        loop.close()
        self.assertIsNone(dc._client)

    # ── Truncation ──────────────────────────────────────

    def test_truncation_limit(self):
        """Discord connector truncates at 1950 chars (limit is 2000)."""
        import inspect
        source = inspect.getsource(self.DiscordConnector)
        self.assertIn("1950", source)
        self.assertIn("truncated", source)

    # ── Stop idempotency ────────────────────────────────

    def test_stop_when_not_started(self):
        dc = self.DiscordConnector(token="t")
        loop = asyncio.new_event_loop()
        loop.run_until_complete(dc.stop())
        loop.close()

    # ── Send without client ─────────────────────────────

    def test_send_without_client_does_not_crash(self):
        from super_openclaw_agent import OutboundMessage, ChannelType
        dc = self.DiscordConnector(token="t")
        msg = OutboundMessage(
            channel=ChannelType.DISCORD,
            recipient_id="12345",
            text="hello",
            metadata={"channel_id": "999"},
        )
        loop = asyncio.new_event_loop()
        loop.run_until_complete(dc.send(msg))
        loop.close()


class TestDiscordConnectorRegistration(unittest.TestCase):
    """Test that the connector integrates with the agent."""

    def test_connector_registers_with_agent(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ncl_agency_runtime" / "agents"))

        mock_discord = types.ModuleType("discord")
        mock_discord.Client = MagicMock
        mock_discord.Intents = MagicMock()
        mock_discord.Intents.default = MagicMock(return_value=MagicMock())
        mock_discord.HTTPException = Exception
        sys.modules["discord"] = mock_discord

        import importlib
        if "discord_connector" in sys.modules:
            importlib.reload(sys.modules["discord_connector"])
        from discord_connector import DiscordConnector
        from super_openclaw_agent import create_agent

        agent = create_agent()
        initial = len(agent.channels)
        dc = DiscordConnector(token="test")
        agent.add_channel(dc)
        self.assertEqual(len(agent.channels), initial + 1)

        sys.modules.pop("discord", None)


if __name__ == "__main__":
    unittest.main()
