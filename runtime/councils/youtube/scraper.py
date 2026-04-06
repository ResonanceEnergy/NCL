"""
YouTube Council — Channel Scraper

Uses yt-dlp to scrape video metadata and download audio from configured
YouTube channels. Filters by recency (default: last 24 hours) and respects
a total duration cap to avoid runaway scraping.

Optimized for Mac Mini M4 Pro — no CUDA dependencies.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.councils.youtube.scraper")


# Default channels — extend via config or env
DEFAULT_CHANNELS: list[str] = [
    "https://www.youtube.com/@NathansMRE",
    "https://www.youtube.com/@substandard5858",
]

# How far back to look (hours)
DEFAULT_LOOKBACK_HOURS = 24

# Maximum total audio duration to download (hours) — prevents runaway
MAX_TOTAL_DURATION_HOURS = 24

# Where to store downloaded audio temporarily
AUDIO_CACHE_DIR = Path.home() / "Projects" / "NCL" / ".cache" / "youtube-audio"


def get_channel_list() -> list[str]:
    """Get YouTube channel URLs from env or defaults."""
    env_channels = os.getenv("YOUTUBE_COUNCIL_CHANNELS", "")
    if env_channels:
        return [c.strip() for c in env_channels.split(",") if c.strip()]
    return DEFAULT_CHANNELS


def scrape_recent_videos(
    channels: Optional[list[str]] = None,
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS,
    max_total_hours: float = MAX_TOTAL_DURATION_HOURS,
    max_per_channel: int = 50,
) -> list[dict]:
    """
    Scrape recent video metadata from YouTube channels.

    Returns list of video info dicts (yt-dlp format) sorted by upload date,
    filtered to the lookback window, capped at max_total_hours of content.
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        log.error("yt-dlp not installed. Run: pip install yt-dlp")
        return []

    channels = channels or get_channel_list()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    cutoff_str = cutoff.strftime("%Y%m%d")

    all_videos: list[dict] = []

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": max_per_channel,
        "dateafter": cutoff_str,
    }

    for channel_url in channels:
        log.info(f"Scraping channel: {channel_url}")
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url + "/videos", download=False)
                if not info or "entries" not in info:
                    log.warning(f"No entries found for {channel_url}")
                    continue

                channel_name = info.get("channel", info.get("uploader", "Unknown"))
                for entry in info["entries"]:
                    if not entry:
                        continue
                    all_videos.append({
                        "video_id": entry.get("id", ""),
                        "title": entry.get("title", "Untitled"),
                        "channel": channel_name,
                        "channel_id": info.get("channel_id", ""),
                        "upload_date": entry.get("upload_date", ""),
                        "duration": entry.get("duration") or 0,
                        "url": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                        "description": entry.get("description", "")[:500],
                        "view_count": entry.get("view_count") or 0,
                        "like_count": entry.get("like_count") or 0,
                        "tags": entry.get("tags") or [],
                        "thumbnail": entry.get("thumbnail", ""),
                    })
        except Exception as e:
            log.error(f"Failed to scrape {channel_url}: {e}")

    # Sort by upload date (newest first)
    all_videos.sort(key=lambda v: v.get("upload_date", ""), reverse=True)

    # Cap at max total duration
    selected: list[dict] = []
    total_seconds = 0.0
    max_seconds = max_total_hours * 3600

    for video in all_videos:
        dur = video.get("duration", 0) or 0
        if total_seconds + dur > max_seconds:
            log.info(f"Duration cap reached ({total_seconds/3600:.1f}h) — stopping at {len(selected)} videos")
            break
        selected.append(video)
        total_seconds += dur

    log.info(f"Selected {len(selected)} videos ({total_seconds/3600:.1f}h total) from {len(channels)} channels")
    return selected


def download_audio(
    video_url: str,
    output_dir: Optional[Path] = None,
) -> Optional[Path]:
    """
    Download audio from a YouTube video as MP3.

    Returns path to the downloaded audio file, or None on failure.
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        log.error("yt-dlp not installed")
        return None

    out_dir = output_dir or AUDIO_CACHE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            video_id = info.get("id", "unknown")
            mp3_path = out_dir / f"{video_id}.mp3"
            if mp3_path.exists():
                log.info(f"Audio downloaded → {mp3_path.name} ({mp3_path.stat().st_size / 1024 / 1024:.1f}MB)")
                return mp3_path

            # yt-dlp might use a different extension
            for ext in ["mp3", "m4a", "opus", "webm"]:
                alt = out_dir / f"{video_id}.{ext}"
                if alt.exists():
                    log.info(f"Audio downloaded → {alt.name}")
                    return alt

    except Exception as e:
        log.error(f"Failed to download audio from {video_url}: {e}")

    return None


def download_batch(
    videos: list[dict],
    output_dir: Optional[Path] = None,
) -> list[tuple[dict, Path]]:
    """
    Download audio for a batch of videos.

    Returns list of (video_info, audio_path) tuples for successful downloads.
    """
    results: list[tuple[dict, Path]] = []

    for video in videos:
        url = video.get("url", "")
        if not url:
            continue

        # Skip if already cached
        out_dir = output_dir or AUDIO_CACHE_DIR
        video_id = video.get("video_id", "")
        cached = out_dir / f"{video_id}.mp3"
        if cached.exists():
            log.info(f"Cache hit: {cached.name}")
            results.append((video, cached))
            continue

        audio_path = download_audio(url, output_dir)
        if audio_path:
            results.append((video, audio_path))
        else:
            log.warning(f"Skipping {video.get('title', 'unknown')} — download failed")

    log.info(f"Downloaded {len(results)}/{len(videos)} audio files")
    return results
