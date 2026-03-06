#!/usr/bin/env python3
"""Quick launcher for NCL Telegram bot — t.me/nclbrainbot"""
import asyncio
import logging
import os
import sys
from pathlib import Path

# Force unbuffered stdout
os.environ["PYTHONUNBUFFERED"] = "1"

# Setup logging to stdout so we see everything
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,
)

# Setup paths
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ncl_agency_runtime" / "agents"))

print("=" * 50, flush=True)
print("  NCL SUPER OPENCLAW — TELEGRAM BOT", flush=True)
print("=" * 50, flush=True)

# Token — must be set via environment variable
TOKEN = os.environ.get("NCL_TELEGRAM_TOKEN", "")
if not TOKEN:
    print("ERROR: NCL_TELEGRAM_TOKEN not set", flush=True)
    print("  export NCL_TELEGRAM_TOKEN=<your-bot-token>", flush=True)
    sys.exit(1)

print(f"  Token: {TOKEN[:4]}****{TOKEN[-4:]}", flush=True)

# Imports — use bare names since agents dir is on sys.path
print("  Loading agent...", flush=True)
from super_openclaw_agent import create_agent  # noqa: E402

print("  Loading telegram connector...", flush=True)
from telegram_connector import TELEGRAM_AVAILABLE, TelegramConnector  # noqa: E402

print(f"  Telegram lib: {'READY' if TELEGRAM_AVAILABLE else 'MISSING'}", flush=True)
if not TELEGRAM_AVAILABLE:
    print("ERROR: python-telegram-bot not installed", flush=True)
    sys.exit(1)

# Build agent
agent = create_agent()
connector = TelegramConnector(token=TOKEN)
agent.add_channel(connector)

print(f"  Agent: {agent.agent_id}", flush=True)
print(f"  Skills: {len(agent.skill_router.skills)}", flush=True)
print(f"  Memory: {'ON' if agent._memory_manager else 'OFF'}", flush=True)
print("=" * 50, flush=True)
print("  Bot starting... Open t.me/nclbrainbot", flush=True)
print("  Send /start to begin. Ctrl+C to stop.", flush=True)
print("=" * 50, flush=True)


async def run():
    await agent.start()
    print("[OK] Agent started — polling Telegram...", flush=True)
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[STOP] Shutting down...", flush=True)
    finally:
        await agent.stop()
        print("[DONE] Bot stopped.", flush=True)

asyncio.run(run())
