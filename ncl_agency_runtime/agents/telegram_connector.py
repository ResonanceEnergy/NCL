#!/usr/bin/env python3
"""
NCL Super OpenClaw — Telegram Channel Connector
═════════════════════════════════════════════════
Connects the SuperOpenClawAgent to Telegram via python-telegram-bot (v20+).

Features:
    • Receives text messages and forwards through the NCL pipeline
    • Supports /commands as skill triggers
    • Inline keyboard for brain map, doctrine, status
    • Photo/document attachment metadata capture
    • Group chat support with @mention filtering

Environment variables:
    NCL_TELEGRAM_TOKEN      — Bot token from @BotFather (required)
    NCL_TELEGRAM_ALLOWED    — Comma-separated Telegram user IDs (optional,
                              defaults to all users)
    NCL_TELEGRAM_PREFIX     — Command prefix (default: ``/ncl``)

Setup:
    1. Talk to @BotFather on Telegram → /newbot
    2. Copy the token
    3. export NCL_TELEGRAM_TOKEN=<token>
    4. python -m ncl_agency_runtime.agents.telegram_connector

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

LOG = logging.getLogger("ncl.openclaw.telegram")
LOG.setLevel(logging.DEBUG)

# ── Try to import telegram library ───────────────────────────

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    LOG.warning(
        "python-telegram-bot not installed.  Install with:\n"
        "  pip install python-telegram-bot>=20\n"
        "The connector will register but cannot run until the library is present."
    )


# ═══════════════════════════════════════════════════════════════
#  Telegram Connector
# ═══════════════════════════════════════════════════════════════

class TelegramConnector(ChannelConnector):
    """NCL ↔ Telegram bridge using python-telegram-bot v20+ (asyncio).

    Lifecycle:
        agent.add_channel(TelegramConnector(token=...))
        await agent.start()
        ...
        await agent.stop()
    """

    channel_type = ChannelType.TELEGRAM

    def __init__(
        self,
        token: str | None = None,
        allowed_user_ids: list[int] | None = None,
        prefix: str = "/ncl",
    ):
        self.token = token or os.environ.get("NCL_TELEGRAM_TOKEN", "")
        self.prefix = prefix
        self.allowed_user_ids: set[int] = set(allowed_user_ids or [])
        self._agent: SuperOpenClawAgent | None = None
        self._app: Any | None = None  # telegram.ext.Application
        self._task: asyncio.Task | None = None

        # Parse from env
        if not self.allowed_user_ids:
            env_users = os.environ.get("NCL_TELEGRAM_ALLOWED", "")
            if env_users:
                self.allowed_user_ids = {
                    int(u.strip()) for u in env_users.split(",") if u.strip().isdigit()
                }

    def _is_allowed(self, user_id: int) -> bool:
        """Check if user is allowed (empty set = allow all)."""
        if not self.allowed_user_ids:
            return True
        return user_id in self.allowed_user_ids

    async def start(self, agent: SuperOpenClawAgent):
        if not TELEGRAM_AVAILABLE:
            LOG.error("python-telegram-bot not installed — Telegram connector cannot start")
            return
        if not self.token:
            LOG.error("NCL_TELEGRAM_TOKEN not set — Telegram connector cannot start")
            return

        self._agent = agent

        # Build the Application
        self._app = Application.builder().token(self.token).build()

        # ── Command handlers ──────────────────────────────

        async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /start — welcome message."""
            if not self._is_allowed(update.effective_user.id):
                await update.message.reply_text("Access denied.")
                return

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Brain Map", callback_data="brain_map"),
                    InlineKeyboardButton("Status", callback_data="status"),
                ],
                [
                    InlineKeyboardButton("Doctrine", callback_data="doctrine"),
                    InlineKeyboardButton("Help", callback_data="help"),
                ],
            ])
            await update.message.reply_text(
                f"**NCL Super OpenClaw Agent**\n"
                f"Agent ID: `{agent.agent_id}`\n"
                f"Skills: {len(agent.skill_router.skills)}\n\n"
                f"Send any message or use the buttons below.",
                reply_markup=keyboard,
                parse_mode="Markdown",
            )

        async def cmd_ncl(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle /ncl <command> — direct skill dispatch."""
            if not self._is_allowed(update.effective_user.id):
                return

            text = " ".join(context.args) if context.args else "help"
            await self._handle_text(update, text)

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle plain text messages."""
            if not update.message or not update.message.text:
                return
            if not self._is_allowed(update.effective_user.id):
                return

            text = update.message.text.strip()

            # In groups, only respond to /ncl or @mention
            if update.message.chat.type in ("group", "supergroup"):
                assert self._app is not None
                bot_username = (await self._app.bot.get_me()).username
                if not text.startswith("/ncl") and f"@{bot_username}" not in text:
                    return
                text = text.replace(f"@{bot_username}", "").strip()
                if text.startswith("/ncl"):
                    text = text[4:].strip()

            if not text:
                text = "help"

            await self._handle_text(update, text)

        async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
            """Handle inline keyboard button presses."""
            query = update.callback_query
            if not query:
                return
            await query.answer()

            if not self._is_allowed(query.from_user.id):
                return

            await self._handle_text_from_callback(query, query.data)

        # Register handlers
        self._app.add_handler(CommandHandler("start", cmd_start))
        self._app.add_handler(CommandHandler("ncl", cmd_ncl))
        self._app.add_handler(CallbackQueryHandler(handle_callback))
        self._app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, handle_message
        ))

        # Start polling in background
        self._task = asyncio.create_task(self._run_polling())
        LOG.info("Telegram connector starting...")

    async def _handle_text(self, update: Update, text: str):
        """Process text through the agent pipeline and reply."""
        user = update.effective_user
        msg = InboundMessage(
            channel=ChannelType.TELEGRAM,
            sender_id=str(user.id),
            sender_name=user.full_name or user.username or str(user.id),
            text=text,
            metadata={
                "chat_id": str(update.effective_chat.id),
                "chat_type": update.effective_chat.type,
                "username": user.username or "",
            },
            raw=update,
        )

        # Capture photo attachments if any
        if update.message and update.message.photo:
            largest = update.message.photo[-1]
            msg.attachments.append({
                "type": "photo",
                "file_id": largest.file_id,
                "width": largest.width,
                "height": largest.height,
            })

        if update.message and update.message.document:
            doc = update.message.document
            msg.attachments.append({
                "type": "document",
                "file_id": doc.file_id,
                "file_name": doc.file_name,
                "mime_type": doc.mime_type,
                "file_size": doc.file_size,
            })

        result = await self._agent.process_message(msg)  # type: ignore[union-attr]

        reply_text = result.reply or "(no response)"
        # Telegram has a 4096 char limit
        if len(reply_text) > 4000:
            reply_text = reply_text[:4000] + "\n... (truncated)"

        try:
            await update.message.reply_text(
                reply_text,
                parse_mode="Markdown",
            )
        except Exception:
            # Fallback without markdown if parsing fails
            try:
                await update.message.reply_text(reply_text)
            except Exception as exc:
                LOG.error("Telegram reply failed: %s", exc)

    async def _handle_text_from_callback(self, query, text: str):
        """Process callback query text through agent."""
        user = query.from_user
        msg = InboundMessage(
            channel=ChannelType.TELEGRAM,
            sender_id=str(user.id),
            sender_name=user.full_name or user.username or str(user.id),
            text=text,
            metadata={
                "chat_id": str(query.message.chat_id),
                "callback": True,
            },
        )

        result = await self._agent.process_message(msg)  # type: ignore[union-attr]
        reply_text = result.reply or "(no response)"
        if len(reply_text) > 4000:
            reply_text = reply_text[:4000] + "\n... (truncated)"

        try:
            await query.message.reply_text(reply_text, parse_mode="Markdown")
        except Exception:
            try:
                await query.message.reply_text(reply_text)
            except Exception as exc:
                LOG.error("Telegram callback reply failed: %s", exc)

    async def _run_polling(self):
        """Run the Telegram bot polling loop."""
        assert self._app is not None
        try:
            await self._app.initialize()
            await self._app.start()
            LOG.info("Telegram bot started polling")
            await self._app.updater.start_polling(drop_pending_updates=True)
            # Block until cancelled
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            LOG.error("Telegram polling error: %s", exc)

    async def stop(self):
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                LOG.info("Telegram bot disconnected")
            except Exception as exc:
                LOG.warning("Telegram shutdown error: %s", exc)
        if self._task:
            self._task.cancel()

    async def send(self, msg: OutboundMessage):
        """Send a proactive message to a Telegram chat."""
        if not self._app:
            LOG.error("Telegram app not initialised — cannot send")
            return

        chat_id = msg.recipient_id or msg.metadata.get("chat_id")
        if not chat_id:
            LOG.error("No chat_id in OutboundMessage")
            return

        text = msg.text
        if len(text) > 4000:
            text = text[:4000] + "\n... (truncated)"

        try:
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text=text,
                parse_mode="Markdown",
            )
        except Exception:
            try:
                await self._app.bot.send_message(chat_id=int(chat_id), text=text)
            except Exception as exc:
                LOG.error("Telegram send failed: %s", exc)


# ═══════════════════════════════════════════════════════════════
#  Standalone entry point
# ═══════════════════════════════════════════════════════════════

async def main():
    """Run SuperOpenClaw with Telegram connector."""
    token = os.environ.get("NCL_TELEGRAM_TOKEN")
    if not token:
        print("ERROR: Set NCL_TELEGRAM_TOKEN environment variable first.")
        print("  1. Talk to @BotFather on Telegram")
        print("  2. /newbot → follow prompts → copy token")
        print("  3. export NCL_TELEGRAM_TOKEN=your_token_here")
        sys.exit(1)

    agent = create_agent()
    connector = TelegramConnector(token=token)
    agent.add_channel(connector)

    print("NCL Super OpenClaw — Telegram Mode")
    print(f"  Agent: {agent.agent_id}")
    print(f"  Skills: {len(agent.skill_router.skills)}")
    print()

    await agent.start()

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())
