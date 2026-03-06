#!/usr/bin/env python3
"""
NCL Super OpenClaw — Discord Channel Connector
════════════════════════════════════════════════
Connects the SuperOpenClawAgent to a Discord server via discord.py (or the
py-cord fork).  Operates as a bot that:

  • Listens in configured channels for user messages
  • Routes them through the NCL policy gate → skill router pipeline
  • Replies inline with skill results
  • Publishes events to the NCL EventBus

Environment variables:
    NCL_DISCORD_TOKEN       — Bot token (required)
    NCL_DISCORD_CHANNELS    — Comma-separated channel IDs to listen in (optional,
                              defaults to all channels the bot can read)
    NCL_DISCORD_PREFIX      — Command prefix (default: ``!ncl``)

Setup:
    1. Create a Discord Application at https://discord.com/developers
    2. Add a Bot, copy the token
    3. Invite to server with MESSAGE_CONTENT + SEND_MESSAGES intents
    4. export NCL_DISCORD_TOKEN=<token>
    5. Run:  python -m ncl_agency_runtime.agents.discord_connector

Author:  NCL Agency Runtime (AZ_PRIME authorised)
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Path setup
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from super_openclaw_agent import (  # noqa: E402
    ChannelConnector,
    ChannelType,
    InboundMessage,
    OutboundMessage,
    SuperOpenClawAgent,
    create_agent,
)

LOG = logging.getLogger("ncl.openclaw.discord")
LOG.setLevel(logging.DEBUG)

# ── Try to import discord.py ─────────────────────────────────

try:
    import discord
    from discord import Intents
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    LOG.warning(
        "discord.py not installed.  Install with:  pip install discord.py\n"
        "The connector will still register but cannot run until the library is present."
    )


# ═══════════════════════════════════════════════════════════════
#  Discord Connector
# ═══════════════════════════════════════════════════════════════

class DiscordConnector(ChannelConnector):
    """NCL ↔ Discord bridge.

    Lifecycle:
        agent.add_channel(DiscordConnector(token=...))
        await agent.start()          # starts the bot
        ...
        await agent.stop()           # gracefully disconnects
    """

    channel_type = ChannelType.DISCORD

    def __init__(
        self,
        token: str | None = None,
        listen_channel_ids: list[int] | None = None,
        prefix: str = "!ncl",
    ):
        self.token = token or os.environ.get("NCL_DISCORD_TOKEN", "")
        self.prefix = prefix
        self.listen_channel_ids: set[int] = set(listen_channel_ids or [])
        self._agent: SuperOpenClawAgent | None = None
        self._client: Any | None = None  # discord.Client
        self._task: asyncio.Task | None = None

        # Parse channel IDs from env if not provided
        if not self.listen_channel_ids:
            env_channels = os.environ.get("NCL_DISCORD_CHANNELS", "")
            if env_channels:
                self.listen_channel_ids = {
                    int(c.strip()) for c in env_channels.split(",") if c.strip().isdigit()
                }

    async def start(self, agent: SuperOpenClawAgent):
        if not DISCORD_AVAILABLE:
            LOG.error("discord.py not installed — Discord connector cannot start")
            return
        if not self.token:
            LOG.error("NCL_DISCORD_TOKEN not set — Discord connector cannot start")
            return

        self._agent = agent

        # Configure intents
        intents = Intents.default()
        intents.message_content = True
        intents.messages = True

        self._client = discord.Client(intents=intents)

        # ── Event handlers ────────────────────────────────

        @self._client.event
        async def on_ready():
            assert self._client is not None
            LOG.info("Discord bot connected as %s (ID: %s)",
                     self._client.user.name, self._client.user.id)
            guilds = [g.name for g in self._client.guilds]
            LOG.info("Serving guilds: %s", ", ".join(guilds))
            await agent.event_bus.publish("discord.connected", {
                "bot_user": str(self._client.user),  # type: ignore[union-attr]
                "guilds": guilds,
            })

        @self._client.event
        async def on_message(message: discord.Message):
            # Ignore our own messages
            if message.author == self._client.user:  # type: ignore[union-attr]
                return

            # Channel filter
            if self.listen_channel_ids and message.channel.id not in self.listen_channel_ids:
                return

            # Check for prefix or direct mention
            text = message.content.strip()
            is_command = text.lower().startswith(self.prefix)
            is_mention = self._client.user in message.mentions  # type: ignore[union-attr]

            if not is_command and not is_mention:
                return  # not addressed to us

            # Strip prefix / mention
            if is_command:
                text = text[len(self.prefix):].strip()
            elif is_mention:
                text = text.replace(f"<@{self._client.user.id}>", "").strip()  # type: ignore[union-attr]
                text = text.replace(f"<@!{self._client.user.id}>", "").strip()  # type: ignore[union-attr]

            if not text:
                text = "help"

            # Build normalised message
            inbound = InboundMessage(
                channel=ChannelType.DISCORD,
                sender_id=str(message.author.id),
                sender_name=message.author.display_name,
                text=text,
                metadata={
                    "guild_id": str(message.guild.id) if message.guild else "",
                    "channel_id": str(message.channel.id),
                    "channel_name": getattr(message.channel, "name", "DM"),
                },
                raw=message,
            )

            # Attachments
            for att in message.attachments:
                inbound.attachments.append({
                    "filename": att.filename,
                    "url": att.url,
                    "size": att.size,
                    "content_type": att.content_type,
                })

            # Process through agent pipeline
            result = await agent.process_message(inbound)

            # Reply
            reply_text = result.reply or "(no response)"
            # Discord has a 2000 char limit
            if len(reply_text) > 1950:
                reply_text = reply_text[:1950] + "\n... (truncated)"

            try:
                await message.reply(reply_text)
            except discord.HTTPException as exc:
                LOG.error("Discord reply failed: %s", exc)
                try:
                    await message.channel.send(reply_text)
                except discord.HTTPException:
                    LOG.error("Discord send also failed — dropping reply")

        # Start the bot in a background task
        self._task = asyncio.create_task(self._run_bot())
        LOG.info("Discord connector starting...")

    async def _run_bot(self):
        try:
            await self._client.start(self.token)  # type: ignore[union-attr]
        except Exception as exc:
            LOG.error("Discord bot crashed: %s", exc)

    async def stop(self):
        if self._client and not self._client.is_closed():
            await self._client.close()
            LOG.info("Discord bot disconnected")
        if self._task:
            self._task.cancel()

    async def send(self, msg: OutboundMessage):
        """Send a proactive message to a Discord channel."""
        if not self._client or self._client.is_closed():
            LOG.error("Discord client not connected — cannot send")
            return

        channel_id = msg.metadata.get("channel_id")
        if not channel_id:
            LOG.error("No channel_id in OutboundMessage metadata")
            return

        channel = self._client.get_channel(int(channel_id))
        if not channel:
            LOG.error("Discord channel %s not found", channel_id)
            return

        try:
            text = msg.text
            if len(text) > 1950:
                text = text[:1950] + "\n... (truncated)"
            await channel.send(text)
        except discord.HTTPException as exc:
            LOG.error("Discord send failed: %s", exc)


# ═══════════════════════════════════════════════════════════════
#  Standalone entry point
# ═══════════════════════════════════════════════════════════════

async def main():
    """Run SuperOpenClaw with Discord connector."""
    token = os.environ.get("NCL_DISCORD_TOKEN")
    if not token:
        print("ERROR: Set NCL_DISCORD_TOKEN environment variable first.")
        print("  export NCL_DISCORD_TOKEN=your_bot_token_here")
        sys.exit(1)

    agent = create_agent()
    connector = DiscordConnector(token=token)
    agent.add_channel(connector)

    print("NCL Super OpenClaw — Discord Mode")
    print(f"  Agent: {agent.agent_id}")
    print(f"  Skills: {len(agent.skill_router.skills)}")
    print(f"  Prefix: {connector.prefix}")
    print()

    await agent.start()

    # Keep running until interrupted
    try:
        await asyncio.Event().wait()  # block forever
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
