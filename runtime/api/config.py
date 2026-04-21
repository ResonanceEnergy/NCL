"""Configuration management for NCL brain service."""

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration settings for NCL brain service."""

    # Service
    service_name: str = "ncl-brain"
    service_version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8800
    debug: bool = False

    # Data storage — paths auto-expanded in validator
    data_dir: str = "~/NCL/data"
    config_dir: str = "~/NCL/config"

    def model_post_init(self, __context) -> None:
        """Expand ~ in all path fields after init."""
        self.data_dir = os.path.expanduser(self.data_dir)
        self.config_dir = os.path.expanduser(self.config_dir)

    # API keys
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"

    xai_api_key: Optional[str] = None
    google_api_key: Optional[str] = None
    perplexity_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    copilot_api_key: Optional[str] = None  # GitHub Copilot / separate OpenAI key for engineering role

    # News APIs (for Intelligence Engine)
    gnews_api_key: Optional[str] = None
    newsapi_key: Optional[str] = None

    # Intelligence Engine
    intelligence_brief_interval: int = 14400  # 4 hours between full briefs
    intelligence_collection_interval: int = 1800  # 30 min between signal collection sweeps

    # Social media APIs
    x_bearer_token: Optional[str] = None
    youtube_api_key: Optional[str] = None
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[str] = None

    # Local models
    ollama_host: str = "localhost:11434"

    # Paperclip integration
    paperclip_host: str = "localhost"
    paperclip_port: int = 3100
    paperclip_api_key: Optional[str] = None

    # Scan intervals (seconds)
    x_scan_interval: int = 300  # 5 minutes
    youtube_scan_interval: int = 600  # 10 minutes
    reddit_scan_interval: int = 600  # 10 minutes
    prediction_interval: int = 1800  # 30 minutes
    memory_consolidation_interval: int = 3600  # 1 hour

    # Memory parameters
    memory_importance_threshold: float = 20.0
    memory_decay_rate: float = 0.95
    memory_consolidation_batch_size: int = 50

    # Council settings
    council_timeout: int = 120  # seconds
    council_model: str = "claude-sonnet-4-6"

    # WAR Room integration
    aac_war_room_url: Optional[str] = None

    # Autonomous scheduler
    autonomous_enabled: bool = True
    council_trigger_threshold: float = 75.0  # importance score to auto-spawn council
    council_min_signals: int = 3  # minimum signals before council auto-spawn
    strategic_review_interval: int = 14400  # 4 hours between scheduled reviews
    aac_sync_interval: int = 900  # 15 minutes between pillar syncs
    workspace_health_interval: int = 1800  # 30 minutes between workspace checks

    # Strike-Point pipeline auth
    strike_auth_token: str = ""

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def load_config() -> Settings:
    """
    Load configuration from environment and YAML file.

    Priority:
    1. Environment variables
    2. ~/NCL/config/ncl.yaml
    3. Defaults

    Returns:
        Settings object
    """
    settings = Settings()

    # Try to load YAML config
    config_file = Path(settings.config_dir).expanduser() / "ncl.yaml"
    if config_file.exists():
        with open(config_file) as f:
            yaml_config = yaml.safe_load(f) or {}
            for key, value in yaml_config.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)

    # Override with environment variables
    for field_name, field in settings.model_fields.items():
        env_var = f"NCL_{field_name.upper()}"
        if env_var in os.environ:
            env_value = os.environ[env_var]
            # Type conversion
            if field.annotation in (int, float, bool):
                if field.annotation == bool:
                    setattr(settings, field_name, env_value.lower() in ("true", "1", "yes"))
                else:
                    setattr(settings, field_name, field.annotation(env_value))
            else:
                setattr(settings, field_name, env_value)

    return settings


def create_config_file(config_dir: str | Path = "~/NCL/config") -> Path:
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
data_dir: ~/NCL/data
config_dir: ~/NCL/config

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
paperclip_host: "localhost"
paperclip_port: 3100

# Scan Intervals (seconds)
x_scan_interval: 300
youtube_scan_interval: 600
reddit_scan_interval: 600
prediction_interval: 1800
memory_consolidation_interval: 3600

# Memory
memory_importance_threshold: 20.0
memory_decay_rate: 0.95

# Council
council_timeout: 120
council_model: "claude-sonnet-4-6"

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
