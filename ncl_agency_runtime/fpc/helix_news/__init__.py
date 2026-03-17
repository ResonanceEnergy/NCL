"""Helix News — AI avatar news anchor for NCC daily briefings.

Pipeline: Script → TTS → Avatar → Compositor → Episode
"""

__version__ = "1.0.0"

from .avatar_engine import AvatarEngine
from .clip_producer import ClipProducer
from .compositor import Compositor
from .producer import Producer
from .script_generator import ScriptGenerator
from .tts_engine import TTSEngine

__all__ = [
    "AvatarEngine",
    "ClipProducer",
    "Compositor",
    "Producer",
    "ScriptGenerator",
    "TTSEngine",
]
