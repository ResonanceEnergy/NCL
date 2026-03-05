# NCL Bot Setup Guide

This guide covers deploying the NCL Telegram and Discord bots powered by
the **SuperOpenClaw** agent.

---

## Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.11+ |
| python-telegram-bot | 22.x |
| discord.py | 2.x |
| NCL repo cloned | latest `main` |

Install runtime dependencies:

```bash
pip install python-telegram-bot discord.py
pip install -r requirements-dev.txt   # for tests
```

---

## Telegram Bot

### 1. Create a bot with BotFather

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot` and follow the prompts.
3. Copy the **HTTP API token** (e.g. `123456:ABC-DEF...`).

### 2. Configure environment

```bash
export NCL_TELEGRAM_TOKEN="<your-token>"

# Optional: restrict to specific Telegram user IDs
export NCL_TELEGRAM_ALLOWED="123456789,987654321"
```

Or set values in `ncl_config.json` → `openclaw.telegram`:

```json
{
  "openclaw": {
    "telegram": {
      "enabled": true,
      "token_env": "NCL_TELEGRAM_TOKEN",
      "prefix": "/ncl",
      "allowed_user_ids": [123456789]
    }
  }
}
```

### 3. Run the bot

```bash
python run_telegram_bot.py
```

The bot will log `Bot started on @<your_bot_username>`.

### 4. Test

Send `/ncl help` or `/ncl status` to the bot in Telegram.

---

## Discord Bot

### 1. Create a Discord application

1. Go to <https://discord.com/developers/applications>.
2. Click **New Application** → name it → go to **Bot** tab.
3. Click **Reset Token** and copy it.
4. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
5. Generate an OAuth2 invite URL with the `bot` scope and `Send Messages` +
   `Read Message History` permissions.

### 2. Configure environment

```bash
export NCL_DISCORD_TOKEN="<your-token>"

# Optional: restrict to specific channel IDs
export NCL_DISCORD_CHANNELS="111111111111111111,222222222222222222"
```

Or in `ncl_config.json` → `openclaw.discord`:

```json
{
  "openclaw": {
    "discord": {
      "enabled": true,
      "token_env": "NCL_DISCORD_TOKEN",
      "prefix": "!ncl",
      "listen_channel_ids": []
    }
  }
}
```

### 3. Run the bot

```bash
python run_discord_bot.py
```

### 4. Test

Send `!ncl help` in a permitted channel.

---

## Security Notes

- **Never commit tokens.** Use environment variables.
- Tokens logged to console are automatically masked (`xxxx****xxxx`).
- Set `allowed_user_ids` / `listen_channel_ids` to restrict access.
- The relay server defaults to `127.0.0.1` (local-only).
- API keys are required by default (`api_keys_required: true`).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: telegram` | `pip install python-telegram-bot` |
| `ModuleNotFoundError: discord` | `pip install discord.py` |
| Bot doesn't respond | Check token, ensure Message Content Intent is on (Discord) |
| `403 Forbidden` from relay | Verify `allowed_origins` in `ncl_config.json` |
| Rate limited | Adjust `access.rate_limiting` in config |
