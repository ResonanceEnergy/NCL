"""
YouTube Council — Channel Scraper

Uses yt-dlp to scrape video metadata and download audio from configured
YouTube channels. Filters by recency (default: last 24 hours) and respects
a total duration cap to avoid runaway scraping.

Optimized for Mac Mini M4 Pro — no CUDA dependencies.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("ncl.councils.youtube.scraper")


# Default channels — extend via config file or env
DEFAULT_CHANNELS: list[str] = [
    "https://www.youtube.com/@J_Bravo",
    "https://www.youtube.com/@eurodollaruniversity",
    "https://www.youtube.com/@brighterwithherbert",
    "https://www.youtube.com/@cryptosenseii",
    "https://www.youtube.com/@bullrunners",
    "https://www.youtube.com/@felixfriends",
    "https://www.youtube.com/@stockmoe",
    "https://www.youtube.com/@tombilyeu",
    "https://www.youtube.com/@andreijikh",
    "https://www.youtube.com/@thediaryofaceo",
    "https://www.youtube.com/@following-the-money",
    "https://www.youtube.com/@chriswillx",
    "https://www.youtube.com/@theicedcoffeehour",
    "https://www.youtube.com/@dumbmoneylive",
]

# Path to runtime-editable channel config (no code change required to add/remove)
NCL_BASE_DIR = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
CHANNEL_CONFIG_PATH = NCL_BASE_DIR / "config" / "youtube_channels.json"

# How far back to look (hours)
DEFAULT_LOOKBACK_HOURS = 24

# Maximum total audio duration to download (hours) — prevents runaway
MAX_TOTAL_DURATION_HOURS = 24

# Strike Point relevance keywords — scored for priority selection
STRIKE_POINT_KEYWORDS: list[str] = [
    "crypto", "bitcoin", "ethereum", "altcoin", "defi",
    "market", "stocks", "trading", "investing", "economy",
    "eurodollar", "fed", "interest rate", "inflation", "macro",
    "AI", "artificial intelligence", "machine learning", "automation",
    "mindset", "entrepreneur", "business", "wealth",
    "polymarket", "prediction", "forecast",
]

# Where to store downloaded audio temporarily
AUDIO_CACHE_DIR = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / ".cache" / "youtube-audio"


# YouTube Data API v3 quota: 10,000 units/day. yt-dlp doesn't consume quota
# but we respect a polite crawl rate to avoid bot-detection blocks.
_CHANNEL_SCRAPE_DELAY_SECONDS = 2.0   # minimum gap between channel scrapes
_MAX_RETRIES_PER_CHANNEL = 2          # retry once on transient failure


def get_channel_list() -> list[str]:
    """Resolve YouTube channel URLs.

    Resolution order (first match wins):
      1. ``YOUTUBE_COUNCIL_CHANNELS`` env var (comma-separated)
      2. ``config/youtube_channels.json`` (`{"channels": [...]}` shape)
      3. ``DEFAULT_CHANNELS`` constant
    """
    env_channels = os.getenv("YOUTUBE_COUNCIL_CHANNELS", "")
    if env_channels:
        return [c.strip() for c in env_channels.split(",") if c.strip()]

    if CHANNEL_CONFIG_PATH.exists():
        try:
            data = json.loads(CHANNEL_CONFIG_PATH.read_text())
            channels = data.get("channels") if isinstance(data, dict) else data
            if isinstance(channels, list):
                cleaned = [str(c).strip() for c in channels if str(c).strip()]
                if cleaned:
                    return cleaned
            log.warning(f"{CHANNEL_CONFIG_PATH} present but has no usable 'channels' list")
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Failed to read {CHANNEL_CONFIG_PATH}: {e}")

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

    last_scrape_time: float = 0.0

    for channel_url in channels:
        log.info(f"Scraping channel: {channel_url}")

        # Polite rate limiting between channel requests
        now = time.monotonic()
        gap = now - last_scrape_time
        if gap < _CHANNEL_SCRAPE_DELAY_SECONDS:
            time.sleep(_CHANNEL_SCRAPE_DELAY_SECONDS - gap)
        last_scrape_time = time.monotonic()

        for attempt in range(_MAX_RETRIES_PER_CHANNEL):
            try:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(channel_url + "/videos", download=False)
                    if not info or "entries" not in info:
                        log.warning(f"No entries found for {channel_url}")
                        break  # Nothing to retry

                    channel_name = info.get("channel", info.get("uploader", "Unknown"))
                    for entry in info["entries"]:
                        if not entry:
                            continue
                        # Post-filter by date: yt-dlp ignores dateafter in
                        # extract_flat mode, so we filter manually here.
                        upload_date = entry.get("upload_date", "")
                        if upload_date and upload_date < cutoff_str:
                            continue
                        all_videos.append({
                            "video_id": entry.get("id", ""),
                            "title": entry.get("title", "Untitled"),
                            "channel": channel_name,
                            "channel_id": info.get("channel_id", ""),
                            "upload_date": upload_date,
                            "duration": entry.get("duration") or 0,
                            "url": f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                            "description": entry.get("description", "")[:500],
                            "view_count": entry.get("view_count") or 0,
                            "like_count": entry.get("like_count") or 0,
                            "tags": entry.get("tags") or [],
                            "thumbnail": entry.get("thumbnail", ""),
                        })
                break  # Success — no retry needed
            except Exception as e:
                if attempt < _MAX_RETRIES_PER_CHANNEL - 1:
                    wait = 5.0 * (attempt + 1)
                    log.warning(f"Scrape attempt {attempt+1} failed for {channel_url}: {e} — retrying in {wait:.0f}s")
                    time.sleep(wait)
                else:
                    log.error(f"Failed to scrape {channel_url} after {_MAX_RETRIES_PER_CHANNEL} attempts: {e}")

    # ── Strike Point scoring ─────────────────────────────────────────
    # Score each video by keyword relevance, then select highest-scoring
    # videos that fit under the duration cap. This replaces naive
    # chronological ordering with intelligent prioritization.
    for video in all_videos:
        video["strike_score"] = _strike_point_score(video)

    # Sort by score (highest first), break ties by upload date (newest first)
    all_videos.sort(
        key=lambda v: (v.get("strike_score", 0), v.get("upload_date", "")),
        reverse=True,
    )

    # Greedy selection under duration cap
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

    log.info(
        f"Strike Point selected {len(selected)} videos "
        f"({total_seconds/3600:.1f}h total) from {len(channels)} channels"
    )
    if selected:
        top = selected[0]
        log.info(f"  Top hit: \"{top['title']}\" (score={top.get('strike_score', 0)}, {top.get('duration', 0)//60}m)")
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

        # Skip if already cached (check all common audio formats)
        out_dir = output_dir or AUDIO_CACHE_DIR
        video_id = video.get("video_id", "")
        cached_path = None
        for ext in ("mp3", "mp4", "webm", "m4a", "opus", "ogg", "wav"):
            candidate = out_dir / f"{video_id}.{ext}"
            if candidate.exists():
                cached_path = candidate
                break
        if cached_path:
            log.info(f"Cache hit: {cached_path.name}")
            results.append((video, cached_path))
            continue

        audio_path = download_audio(url, output_dir)
        if audio_path:
            results.append((video, audio_path))
        else:
            log.warning(f"Skipping {video.get('title', 'unknown')} — download failed")

    log.info(f"Downloaded {len(results)}/{len(videos)} audio files")
    return results


# ── Strike Point Scoring ──────────────────────────────────────────────

def _strike_point_score(video: dict) -> float:
    """
    Score a video for Strike Point selection.

    Higher score = higher priority for inclusion under the duration cap.

    Factors:
    - Keyword density in title (2 points per keyword hit)
    - Keyword density in description (0.5 per hit)
    - Keyword density in tags (1 per hit)
    - Recency bias (today's uploads get +3)
    - View count signal (+1 if >1000 views, +2 if >10000)
    """
    score = 0.0
    title = (video.get("title") or "").lower()
    desc = (video.get("description") or "").lower()
    tags = " ".join(video.get("tags") or []).lower()

    for kw in STRIKE_POINT_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title:
            score += 2.0
        if kw_lower in desc:
            score += 0.5
        if kw_lower in tags:
            score += 1.0

    # Recency bias — today's uploads get a boost
    upload_date = video.get("upload_date", "")
    if upload_date:
        try:
            today = datetime.now(timezone.utc).strftime("%Y%m%d")
            if upload_date == today:
                score += 3.0
            elif upload_date >= (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d"):
                score += 1.5
        except (ValueError, TypeError):
            pass

    # View count signal
    views = video.get("view_count", 0) or 0
    if views >= 10000:
        score += 2.0
    elif views >= 1000:
        score += 1.0

    return score
