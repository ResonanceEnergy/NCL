"""Configuration management for NCL brain service."""

import logging
import os
import subprocess
from pathlib import Path
from typing import Optional, Union

import yaml
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


logger = logging.getLogger(__name__)


# ── macOS keychain helper (single source of truth for secrets) ────────────────
def keychain_get(service: str, account: str = "natrix") -> Optional[str]:
    """Read a secret from the macOS login keychain.

    Returns None if the entry doesn't exist or `security` isn't available
    (e.g. running in Docker/Linux). Never raises.
    """
    try:
        r = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode == 0:
            return r.stdout.strip() or None
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass
    return None


# Mapping of Settings field name → keychain service name
_KEYCHAIN_FIELDS: dict[str, str] = {
    "anthropic_api_key": "ncl-anthropic",
    "strike_auth_token": "ncl-strike-auth-token",
    "xai_api_key": "ncl-xai",
    "google_api_key": "ncl-google",
    "openai_api_key": "ncl-openai",
    "perplexity_api_key": "ncl-perplexity",
    "copilot_api_key": "ncl-copilot",
    "x_bearer_token": "ncl-x-bearer",
    "youtube_api_key": "ncl-youtube",
    "unusual_whales_api_key": "ncl-unusual-whales",
    "paperclip_api_key": "ncl-paperclip",
    "gnews_api_key": "ncl-gnews",
    "newsapi_key": "ncl-newsapi",
    "reddit_client_id": "ncl-reddit-client-id",
    "reddit_client_secret": "ncl-reddit-client-secret",
    "pushover_app_token": "ncl-pushover-app-token",
    "pushover_user_key": "ncl-pushover-user-key",
    "discord_bot_token": "ncl-discord-bot",
    "snaptrade_client_id": "ncl-snaptrade-client-id",
    "snaptrade_consumer_key": "ncl-snaptrade-consumer-key",
    "ntfy_topic": "ncl-ntfy-topic",
}

# Mapping of raw ENV var name → keychain service name.
# These are populated into os.environ at process start so that legacy
# `os.getenv(...)` call sites keep working without code changes.
_KEYCHAIN_ENV: dict[str, str] = {
    "ANTHROPIC_API_KEY": "ncl-anthropic",
    "STRIKE_AUTH_TOKEN": "ncl-strike-auth-token",
    "XAI_API_KEY": "ncl-xai",
    "GOOGLE_API_KEY": "ncl-google",
    "GEMINI_API_KEY": "ncl-gemini",
    "OPENAI_API_KEY": "ncl-openai",
    "PERPLEXITY_API_KEY": "ncl-perplexity",
    "YOUTUBE_API_KEY": "ncl-youtube",
    "UNUSUAL_WHALES_API_KEY": "ncl-unusual-whales",
    "UNUSUAL_WHALES_TOKEN": "ncl-unusual-whales",
    "PAPERCLIP_AGENT_KEY": "ncl-paperclip-agent",
    "PAPERCLIP_API_KEY": "ncl-paperclip-agent",
    "PAPERCLIP_COMPANY_ID": "ncl-paperclip-company",
    "REDDIT_CLIENT_ID": "ncl-reddit-client-id",
    "REDDIT_CLIENT_SECRET": "ncl-reddit-client-secret",
}


def bootstrap_env_from_keychain() -> int:
    """Populate os.environ from macOS keychain for legacy os.getenv() consumers.

    Idempotent: if an env var is already set (from launchd plist, .env, or shell),
    it's left alone. Returns the number of vars hydrated from keychain.
    """
    hydrated = 0
    for env_name, service in _KEYCHAIN_ENV.items():
        if os.environ.get(env_name):
            continue
        value = keychain_get(service)
        if value:
            os.environ[env_name] = value
            hydrated += 1
    if hydrated:
        logger.info(f"keychain: hydrated {hydrated} env vars from macOS keychain")
    return hydrated


# ── Required vars — startup fails without these ───────────────────────────────
_REQUIRED_VARS: list[tuple[str, str]] = [
    ("ANTHROPIC_API_KEY", "Claude API key — get from https://console.anthropic.com/settings/keys"),
    ("STRIKE_AUTH_TOKEN", "Strike Point auth token — must match iOS Shortcuts config"),
]

# ── Recommended vars — degraded but functional without them ───────────────────
_RECOMMENDED_VARS: list[tuple[str, str]] = [
    (
        "XAI_API_KEY",
        "xAI Grok — Council Strategist + X Intelligence (get from https://console.x.ai)",
    ),
    ("GOOGLE_API_KEY", "Google Gemini — Council Analyst (get from https://aistudio.google.com)"),
    ("OPENAI_API_KEY", "OpenAI GPT — Council Creative + Whisper fallback"),
    ("PERPLEXITY_API_KEY", "Perplexity — Council Researcher (fact-checking)"),
]

# ── Optional vars — specific features only ────────────────────────────────────
_OPTIONAL_VARS: list[tuple[str, str]] = [
    ("X_BEARER_TOKEN", "X/Twitter API — tweet scanning for X Council"),
    ("YOUTUBE_API_KEY", "YouTube Data API — video search for YouTube Council"),
    ("REDDIT_CLIENT_ID", "Reddit — subreddit scanning"),
    ("REDDIT_CLIENT_SECRET", "Reddit — subreddit scanning (pair with REDDIT_CLIENT_ID)"),
    ("NTFY_TOPIC", "ntfy.sh — push notifications to iPhone"),
    ("PUSHOVER_APP_TOKEN", "Pushover — iPhone push notification fallback"),
    ("PUSHOVER_USER_KEY", "Pushover — user key (pair with PUSHOVER_APP_TOKEN)"),
    ("UNUSUAL_WHALES_API_KEY", "Unusual Whales — options flow / dark pool intelligence"),
    ("SNAPTRADE_CLIENT_ID", "SnapTrade — brokerage data"),
    ("DISCORD_BOT_TOKEN", "Discord bot — push notifications to Discord channels"),
    ("GNEWS_API_KEY", "GNews — news intelligence (at least one news key recommended)"),
    ("NEWSAPI_KEY", "NewsAPI — news intelligence"),
    ("COPILOT_API_KEY", "GitHub Copilot / engineering council (falls back to OPENAI_API_KEY)"),
]


class Settings(BaseSettings):
    """Configuration settings for NCL brain service."""

    # Service
    service_name: str = "ncl-brain"
    service_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8800
    debug: bool = False

    # Data storage — paths auto-expanded in model_post_init
    data_dir: str = "~/dev/NCL/data"
    config_dir: str = "~/dev/NCL/config"

    def model_post_init(self, __context: object) -> None:
        """Expand ~ in path fields and pull missing secrets from macOS keychain."""
        self.data_dir = os.path.expanduser(self.data_dir)
        self.config_dir = os.path.expanduser(self.config_dir)
        self.digital_labour_path = os.path.expanduser(self.digital_labour_path)

        # Keychain fallback: any secret field that's empty/None gets pulled
        # from the macOS keychain. Env vars still win (loaded by pydantic first).
        for field, service in _KEYCHAIN_FIELDS.items():
            current = getattr(self, field, None)
            if current:
                continue
            value = keychain_get(service)
            if value:
                setattr(self, field, value)
                logger.debug(f"loaded {field} from keychain ({service})")

    # ── Required API keys ─────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    strike_auth_token: str = ""

    # ── Recommended API keys ──────────────────────────────────────────────────
    xai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    copilot_api_key: Optional[str] = None  # Falls back to openai_api_key if unset

    # ── News APIs ─────────────────────────────────────────────────────────────
    gnews_api_key: Optional[str] = None
    newsapi_key: Optional[str] = None

    # ── Intelligence Engine ───────────────────────────────────────────────────
    intelligence_brief_interval: int = 14400  # 4 hours between full briefs
    intelligence_collection_interval: int = 1800  # 30 min between signal sweeps

    # ── Social media APIs ─────────────────────────────────────────────────────
    x_bearer_token: Optional[str] = None
    youtube_api_key: Optional[str] = None
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None

    # ── Local models ──────────────────────────────────────────────────────────
    ollama_host: str = "localhost:11434"

    # ── Digital Labour integration ────────────────────────────────────────────
    digital_labour_path: str = "~/dev/NCL/digital-labour"

    # ── Notifications ─────────────────────────────────────────────────────────
    ntfy_topic: Optional[str] = None
    ntfy_server: str = "https://ntfy.sh"
    pushover_app_token: Optional[str] = None
    pushover_user_key: Optional[str] = None
    discord_bot_token: Optional[str] = None

    # ── Market intelligence ───────────────────────────────────────────────────
    unusual_whales_api_key: Optional[str] = None
    snaptrade_client_id: Optional[str] = None
    snaptrade_consumer_key: Optional[str] = None

    # ── Scan intervals (seconds) ──────────────────────────────────────────────
    x_scan_interval: int = 1800  # 30 minutes (was 5min — burned $25-36/day)
    youtube_scan_interval: int = 600  # 10 minutes
    reddit_scan_interval: int = 600  # 10 minutes
    prediction_interval: int = 1800  # 30 minutes
    memory_consolidation_interval: int = 3600  # 1 hour

    # ── Memory parameters ─────────────────────────────────────────────────────
    memory_importance_threshold: float = 20.0
    memory_decay_rate: float = 0.95
    memory_consolidation_batch_size: int = 50

    # ── Council settings ──────────────────────────────────────────────────────
    council_timeout: int = 120  # seconds
    council_model: str = "claude-sonnet-4-20250514"

    # ── WAR Room integration ──────────────────────────────────────────────────
    aac_war_room_url: Optional[str] = None

    # ── Autonomous scheduler ──────────────────────────────────────────────────
    autonomous_enabled: bool = True
    council_trigger_threshold: float = 75.0  # importance score to auto-spawn council
    council_min_signals: int = 3  # minimum signals before council auto-spawn
    strategic_review_interval: int = 14400  # 4 hours between scheduled reviews
    aac_sync_interval: int = 900  # 15 minutes between pillar syncs
    workspace_health_interval: int = 1800  # 30 minutes between workspace checks

    # ── Execution mode ────────────────────────────────────────────────────────
    ncl_execution_mode: str = "auto"  # "auto" | "manual"

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def validate_config(settings: Settings) -> None:
    """
    Validate configuration on startup.

    Raises RuntimeError for missing required variables.
    Logs warnings for missing recommended variables.
    Logs debug notices for missing optional variables.

    Args:
        settings: Loaded Settings instance.

    Raises:
        RuntimeError: If any required environment variable is absent or empty.
    """
    missing_required: list[str] = []

    for env_name, description in _REQUIRED_VARS:
        # Check both bare name and NCL_ prefixed form
        value = (
            os.environ.get(env_name)
            or os.environ.get(f"NCL_{env_name}")
            or getattr(settings, env_name.lower(), None)
        )
        if not value:
            missing_required.append(f"  {env_name}: {description}")

    if missing_required:
        joined = "\n".join(missing_required)
        raise RuntimeError(
            f"NCL Brain cannot start — missing required environment variables:\n{joined}"
        )

    for env_name, description in _RECOMMENDED_VARS:
        value = (
            os.environ.get(env_name)
            or os.environ.get(f"NCL_{env_name}")
            or getattr(settings, env_name.lower(), None)
        )
        if not value:
            logger.warning(
                "Optional but recommended env var not set — feature degraded: %s (%s)",
                env_name,
                description,
            )

    for env_name, description in _OPTIONAL_VARS:
        value = (
            os.environ.get(env_name)
            or os.environ.get(f"NCL_{env_name}")
            or getattr(settings, env_name.lower(), None)
        )
        if not value:
            logger.debug(
                "Optional env var not set — feature disabled: %s (%s)", env_name, description
            )


def load_config() -> Settings:
    """
    Load configuration from environment and YAML file.

    Priority:
    1. NCL_* prefixed environment variables (Docker / production)
    2. Bare environment variables / .env file (local dev)
    3. ~/dev/NCL/config/ncl.yaml
    4. Defaults

    Returns:
        Populated Settings instance.
    """
    # Hydrate os.environ from macOS keychain BEFORE Settings is constructed
    # so pydantic-settings sees keychain-sourced values. Plist/.env still wins
    # because we only fill vars that are missing.
    bootstrap_env_from_keychain()

    settings = Settings()

    # Try to load YAML config (lower priority than env vars).
    # Only apply a YAML value when the corresponding env var (bare or NCL_-prefixed)
    # was NOT set — this ensures env vars always win over YAML.
    config_file = Path(settings.config_dir).expanduser() / "ncl.yaml"
    if config_file.exists():
        with open(config_file) as f:
            yaml_config = yaml.safe_load(f) or {}
            for key, value in yaml_config.items():
                if not hasattr(settings, key) or value in (None, ""):
                    continue
                env_key_bare = key.upper()
                env_key_prefixed = f"NCL_{env_key_bare}"
                # Skip if either form of the env var was explicitly set
                if env_key_bare in os.environ or env_key_prefixed in os.environ:
                    continue
                setattr(settings, key, value)

    # Override with NCL_* prefixed environment variables (Docker)
    for field_name, field_info in settings.model_fields.items():
        env_var = f"NCL_{field_name.upper()}"
        if env_var in os.environ:
            env_value = os.environ[env_var]
            annotation = field_info.annotation
            # Unwrap Optional[X] (i.e. Union[X, None]) → X for type conversion
            origin = getattr(annotation, "__origin__", None)
            args = getattr(annotation, "__args__", ())
            if origin is Union and args:
                # Filter out NoneType to get the real type
                non_none = [a for a in args if a is not type(None)]
                base_type = non_none[0] if non_none else annotation
            else:
                base_type = annotation
            try:
                if base_type is bool:
                    setattr(settings, field_name, env_value.lower() in ("true", "1", "yes"))
                elif base_type in (int, float):
                    setattr(settings, field_name, base_type(env_value))
                else:
                    setattr(settings, field_name, env_value)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Could not coerce %s=%r to %s: %s", env_var, env_value, base_type, exc
                )

    return settings


def create_config_file(config_dir: str | Path = "~/dev/NCL/config") -> Path:
    """
    Create a template config file if it doesn't exist.

    Args:
        config_dir: Configuration directory

    Returns:
        Path to config file
    """
    config_dir = Path(config_dir).expanduser()
    config_dir.mkdir(parents=True, exist_ok=True)

    config_file = config_dir / "ncl.yaml"
    if not config_file.exists():
        template = """# NCL Brain Service Configuration

# Service
service_name: ncl-brain
port: 8800
debug: false

# Storage
data_dir: ~/dev/NCL/data
config_dir: ~/dev/NCL/config

# API Keys (set via environment or here)
anthropic_api_key: ""
xai_api_key: ""
google_api_key: ""
perplexity_api_key: ""
openai_api_key: ""

# Social Media APIs
x_bearer_token: ""
youtube_api_key: ""
reddit_client_id: ""
reddit_client_secret: ""

# Ollama
ollama_host: "localhost:11434"

# Paperclip
# Scan Intervals (seconds)
x_scan_interval: 1800
youtube_scan_interval: 600
reddit_scan_interval: 600
prediction_interval: 1800
memory_consolidation_interval: 3600

# Memory
memory_importance_threshold: 20.0
memory_decay_rate: 0.95

# Council
council_timeout: 120
council_model: "claude-sonnet-4-20250514"

# War Room
aac_war_room_url: ""

# Autonomous Scheduler
autonomous_enabled: true
council_trigger_threshold: 75.0
council_min_signals: 3
strategic_review_interval: 14400
aac_sync_interval: 900
workspace_health_interval: 1800
"""
        with open(config_file, "w") as f:
            f.write(template)

    return config_file
