#!/usr/bin/env python3
"""
NCL Super OpenClaw — Unified Launcher
══════════════════════════════════════
Starts the SuperOpenClawAgent with all configured channel connectors
(Discord, Telegram, CLI) based on environment variables and config.

Usage:
    # CLI mode (default, no tokens needed):
    python -m ncl_agency_runtime.agents.launch

    # Discord only:
    NCL_DISCORD_TOKEN=... python -m ncl_agency_runtime.agents.launch --discord

    # Telegram only:
    NCL_TELEGRAM_TOKEN=... python -m ncl_agency_runtime.agents.launch --telegram

    # Both Discord + Telegram:
    NCL_DISCORD_TOKEN=... NCL_TELEGRAM_TOKEN=... python -m ncl_agency_runtime.agents.launch --discord --telegram

    # All channels + CLI:
    NCL_DISCORD_TOKEN=... NCL_TELEGRAM_TOKEN=... python -m ncl_agency_runtime.agents.launch --all
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Path setup
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from super_openclaw_agent import create_agent  # noqa: E402

LOG = logging.getLogger("ncl.openclaw.launch")


def parse_args():
    parser = argparse.ArgumentParser(
        description="NCL Super OpenClaw Agent — Unified Launcher"
    )
    parser.add_argument("--discord", action="store_true",
                        help="Enable Discord connector (requires NCL_DISCORD_TOKEN)")
    parser.add_argument("--telegram", action="store_true",
                        help="Enable Telegram connector (requires NCL_TELEGRAM_TOKEN)")
    parser.add_argument("--cli", action="store_true", default=True,
                        help="Enable CLI interactive mode (default)")
    parser.add_argument("--all", action="store_true",
                        help="Enable all available connectors")
    parser.add_argument("--config", type=str, default=None,
                        help="Path to ncl_config.json")
    parser.add_argument("--no-cli", action="store_true",
                        help="Disable CLI mode (useful when running only Discord/Telegram)")
    return parser.parse_args()


async def launch():
    args = parse_args()

    # Create agent
    agent = create_agent(config_path=args.config)

    channels_added = []

    # ── Discord ───────────────────────────────────────
    if args.discord or args.all:
        try:
            from discord_connector import DiscordConnector
            token = os.environ.get("NCL_DISCORD_TOKEN", "")
            if token:
                connector = DiscordConnector(token=token)
                agent.add_channel(connector)
                channels_added.append("Discord")
            else:
                LOG.warning("--discord requested but NCL_DISCORD_TOKEN not set")
        except ImportError:
            LOG.warning("discord_connector not importable")

    # ── Telegram ──────────────────────────────────────
    if args.telegram or args.all:
        try:
            from telegram_connector import TelegramConnector
            token = os.environ.get("NCL_TELEGRAM_TOKEN", "")
            if token:
                connector = TelegramConnector(token=token)
                agent.add_channel(connector)
                channels_added.append("Telegram")
            else:
                LOG.warning("--telegram requested but NCL_TELEGRAM_TOKEN not set")
        except ImportError:
            LOG.warning("telegram_connector not importable")

    # ── Print banner ──────────────────────────────────

    print()
    print("  ╔════════════════════════════════════════════════╗")
    print("  ║     NCL SUPER OPENCLAW AGENT                  ║")
    print("  ║     Cognitive Augmentation × OpenClaw Skills   ║")  # noqa: RUF001
    print("  ╠════════════════════════════════════════════════╣")
    print(f"  ║  Agent ID : {agent.agent_id:<35}║")
    print(f"  ║  Skills   : {len(agent.skill_router.skills):<35}║")
    print(f"  ║  Memory   : {'ONLINE' if agent._memory_manager else 'OFFLINE':<35}║")
    print(f"  ║  Channels : {', '.join(channels_added) if channels_added else 'CLI only':<35}║")
    print("  ╚════════════════════════════════════════════════╝")
    print()

    # ── Run ───────────────────────────────────────────

    if (args.cli and not args.no_cli) and not channels_added:
        # Pure CLI mode
        await agent.run_cli()
    else:
        # Server mode (Discord/Telegram running, optional CLI)
        await agent.start()
        try:
            if args.cli and not args.no_cli:
                # Also run CLI alongside server connectors
                print("  CLI mode active alongside server connectors.")
                print("  Type 'quit' to stop.\n")
                while True:
                    try:
                        user_input = await asyncio.get_event_loop().run_in_executor(
                            None, lambda: input("you > ")
                        )
                    except EOFError:
                        break
                    if user_input.strip().lower() in ("quit", "exit", "q"):
                        break
                    from super_openclaw_agent import ChannelType, InboundMessage
                    msg = InboundMessage(
                        channel=ChannelType.CLI,
                        sender_id="AZ_PRIME",
                        sender_name="AZ",
                        text=user_input,
                    )
                    result = await agent.process_message(msg)
                    print(f"\nagent > {result.reply}\n")
            else:
                # No CLI — block until interrupted
                print("  Running in headless mode. Ctrl+C to stop.\n")
                await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await agent.stop()


def main():
    asyncio.run(launch())


if __name__ == "__main__":
    main()
