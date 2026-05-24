# NCL Secrets Management

**Status**: macOS Keychain is the single source of truth for every API key, token, and credential.
**Disk `.env` is being deprecated.** Existing `runtime/api/config.py` already hydrates `os.environ` from keychain at startup via `bootstrap_env_from_keychain()` — no code change needed downstream.

---

## 1. Naming Convention

Every keychain entry uses this exact shape:

```
service:  ncl-<lowercase-hyphenated-name>
account:  $USER  (the macOS login user, e.g. "natrix")
```

The full mapping lives in `runtime/api/config.py` under `_KEYCHAIN_ENV` and `_KEYCHAIN_FIELDS`. Keep those two dicts and `scripts/migrate_secrets_to_keychain.sh::KEY_MAP` in sync.

| ENV var                       | Keychain service             | Provider           |
|-------------------------------|------------------------------|--------------------|
| `ANTHROPIC_API_KEY`           | `ncl-anthropic`              | Anthropic          |
| `STRIKE_AUTH_TOKEN`           | `ncl-strike-auth-token`      | NATRIX (internal)  |
| `XAI_API_KEY`                 | `ncl-xai`                    | xAI                |
| `GOOGLE_API_KEY`              | `ncl-google`                 | Google AI Studio   |
| `GEMINI_API_KEY`              | `ncl-gemini`                 | Google             |
| `OPENAI_API_KEY`              | `ncl-openai`                 | OpenAI             |
| `PERPLEXITY_API_KEY`          | `ncl-perplexity`             | Perplexity         |
| `COPILOT_API_KEY`             | `ncl-copilot`                | GitHub Copilot     |
| `X_BEARER_TOKEN`              | `ncl-x-bearer`               | X / Twitter        |
| `YOUTUBE_API_KEY`             | `ncl-youtube`                | YouTube Data API   |
| `REDDIT_CLIENT_ID`            | `ncl-reddit-client-id`       | Reddit             |
| `REDDIT_CLIENT_SECRET`        | `ncl-reddit-client-secret`   | Reddit             |
| `UNUSUAL_WHALES_API_KEY`      | `ncl-unusual-whales`         | Unusual Whales     |
| `SNAPTRADE_CLIENT_ID`         | `ncl-snaptrade-client-id`    | SnapTrade          |
| `SNAPTRADE_CONSUMER_KEY`      | `ncl-snaptrade-consumer-key` | SnapTrade          |
| `SNAPTRADE_USER_ID`           | `ncl-snaptrade-user-id`      | SnapTrade          |
| `SNAPTRADE_USER_SECRET`       | `ncl-snaptrade-user-secret`  | SnapTrade          |
| `DISCORD_BOT_TOKEN`           | `ncl-discord-bot`            | Discord            |
| `GNEWS_API_KEY`               | `ncl-gnews`                  | GNews              |
| `NEWSAPI_KEY`                 | `ncl-newsapi`                | NewsAPI            |
| `TICKETMASTER_API_KEY`        | `ncl-ticketmaster`           | Ticketmaster       |
| `COHERE_API_KEY`              | `ncl-cohere`                 | Cohere             |
| `NTFY_TOPIC`                  | `ncl-ntfy-topic`             | ntfy.sh            |
| `PUSHOVER_APP_TOKEN`          | `ncl-pushover-app-token`     | Pushover           |
| `PUSHOVER_USER_KEY`           | `ncl-pushover-user-key`      | Pushover           |

---

## 2. How `config.py` Reads Keychain

`runtime/api/config.py:bootstrap_env_from_keychain()` runs once at the top of `load_config()`. For each `ENV_VAR -> service` pair in `_KEYCHAIN_ENV`:

1. If `os.environ[ENV_VAR]` is already set (from launchd plist, `.env`, or shell export), it is left untouched.
2. Otherwise it calls `security find-generic-password -s <service> -a $USER -w` and stuffs the result into `os.environ`.

Pydantic `Settings.model_post_init` then runs a second pass for typed fields via `_KEYCHAIN_FIELDS`.

Net effect: **any code path that does `os.getenv("ANTHROPIC_API_KEY")` keeps working** — no changes required.

---

## 3. Debug One-Liner

Read a single key (output to stdout, exits 0 on success):

```bash
security find-generic-password -s ncl-anthropic -a "$USER" -w
```

Print first 8 chars only:

```bash
security find-generic-password -s ncl-anthropic -a "$USER" -w | head -c 8 ; echo
```

List all NCL entries currently in the login keychain:

```bash
security dump-keychain | awk '/"svce"<blob>="ncl-/{gsub(/.*"ncl-/,"ncl-");gsub(/".*/,"");print}' | sort -u
```

---

## 4. Provider Revocation Checklist

**Do this AFTER `migrate_secrets_to_keychain.sh` succeeds and Brain restart smoke-test passes.**
Rotate every key that was sitting in plaintext on disk. Old key is burned regardless of git history because `.env` was readable to anything on the Mac.

| Provider           | Revoke / Rotate URL                                            |
|--------------------|----------------------------------------------------------------|
| Anthropic          | https://console.anthropic.com/settings/keys                    |
| xAI                | https://console.x.ai                                           |
| OpenAI             | https://platform.openai.com/api-keys                           |
| Google AI Studio   | https://aistudio.google.com/app/apikey                         |
| Google Cloud (YT)  | https://console.cloud.google.com/apis/credentials              |
| Perplexity         | https://www.perplexity.ai/settings/api                         |
| X / Twitter        | https://developer.twitter.com/en/portal/dashboard              |
| Discord (bot)      | https://discord.com/developers/applications  → Bot → Reset     |
| SnapTrade          | https://dashboard.snaptrade.com  → API Credentials             |
| NewsAPI            | https://newsapi.org/account                                    |
| GNews              | https://gnews.io/dashboard                                     |
| Ticketmaster       | https://developer.ticketmaster.com/user/me/apps                |
| Unusual Whales     | https://unusualwhales.com/api  → Token settings                |
| Cohere             | https://dashboard.cohere.com/api-keys                          |
| Pushover           | https://pushover.net  → Your Applications                      |
| Reddit             | https://www.reddit.com/prefs/apps                              |

**Strike-Token** (`STRIKE_AUTH_TOKEN`): regenerate with
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```
then update both keychain (`ncl-strike-auth-token`) and iOS FirstStrike app Settings.

---

## 5. End-to-End Migration Steps

```bash
# 1. Migrate values from .env into keychain (idempotent)
bash ~/dev/NCL/scripts/migrate_secrets_to_keychain.sh

# 2. Verify Brain still boots with .env temporarily moved aside
mv ~/dev/NCL/.env ~/dev/NCL/.env.disabled
launchctl kickstart -k gui/$(id -u)/com.resonanceenergy.ncl-brain
sleep 5
curl -s http://localhost:8800/health | jq .

# 3. If healthy, rotate provider keys (see section 4), then re-run migrate
#    with the new values written into ~/dev/NCL/.env temporarily.

# 4. After ALL providers rotated and keychain re-migrated, permanently delete:
rm ~/dev/NCL/.env.disabled
[ -f ~/dev/NCL/.strike_token ] && rm ~/dev/NCL/.strike_token
```

---

## 6. Git History Audit

As of 2026-05-23, `git log --all --full-history -- .env` returns **empty** — `.env` has never been committed to this repo. `.strike_token` likewise absent.

**If that ever changes** (someone force-commits a secret), purge with `git filter-repo`:

```bash
# Install once: brew install git-filter-repo
cd ~/dev/NCL
git filter-repo --invert-paths --path .env --path .strike_token --force
git remote add origin <repo-url>   # filter-repo strips remotes
git push --force --all
git push --force --tags
# Then revoke every key in the offending commit per section 4 — even though
# the blob is now unreachable, it lived in someone's clone for some time.
```

---

## 7. Don'ts

- **Don't** hardcode keys in plist files. The Brain's launchd plist intentionally has NO `EnvironmentVariables` block with secrets — `scripts/launch-brain.sh` + keychain hydration does the work.
- **Don't** echo full key values in logs, error messages, or chat. Mask with `${value:0:4}…${value: -4}`.
- **Don't** add new secret env vars without also adding them to `_KEYCHAIN_ENV` in `runtime/api/config.py` AND `KEY_MAP` in the migration script.
- **Don't** commit `.env`, `.env.local`, `.strike_token`, or `data/feedback/source_authority.json` — all are in `.gitignore`.
