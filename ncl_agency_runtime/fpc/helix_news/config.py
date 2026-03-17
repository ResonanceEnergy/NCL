"""Helix News configuration."""

import json
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "episode_max_minutes": 10,
    "tts": {
        "engine": "edge-tts",
        "voice": "en-US-AriaNeural",
        "rate": "+5%",
    },
    "avatar": {
        "engine": "sadtalker",
        "source_image": "src/helix_news/assets/helix_portrait.png",
        "enhancer": "gfpgan",
    },
    "output": {
        "resolution": [1920, 1080],
        "fps": 30,
        "format": "mp4",
        "output_dir": "reports/helix_news",
    },
    "segments": {
        "cold_open_seconds": 15,
        "headlines_count": 5,
        "predictions_count": 5,
        "max_alerts": 5,
    },
}


def load_config(path: str = "config/helix_news.json") -> dict[str, Any]:
    """Load Helix News config, falling back to defaults."""
    cfg = dict(DEFAULT_CONFIG)
    p = Path(path)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            user = json.load(f)
        # Shallow merge top-level keys, deep merge nested dicts
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    return cfg
