"""Helix News — AI avatar news anchor for NCC daily briefings.

Pipeline: Script → TTS → Avatar → Compositor → Episode

Cached pipeline (clip_cache):
    Daytime: IncrementalRenderer pre-renders clips as predictions arrive.
    Evening: BriefAssembler stitches cached clips + fresh intro/outro → episode.
"""

__version__ = "1.1.0"

from .avatar_engine import AvatarEngine
from .clip_cache import BriefAssembler, ClipCache, IncrementalRenderer
from .clip_producer import ClipProducer
from .compositor import Compositor
from .producer import Producer
from .script_generator import ScriptGenerator
from .tts_engine import TTSEngine

__all__ = [
    "AvatarEngine",
    "BriefAssembler",
    "ClipCache",
    "ClipProducer",
    "Compositor",
    "IncrementalRenderer",
    "Producer",
    "ScriptGenerator",
    "TTSEngine",
]
