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
# Known limitation: no file locking on this config. Concurrent reads during a
# write could see partial JSON. In practice this is fine — config changes are
# rare and manual, and the fallback to DEFAULT_CHANNELS handles parse failures.
NCL_BASE_DIR = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
CHANNEL_CONFIG_PATH = NCL_BASE_DIR / "config" / "youtube_channels.json"

# How far back to look (hours).
# Wave 14CC (2026-05-30) — dropped 72 → 24. The 3-day window meant every
# scrape was re-eligible for videos already analyzed in prior cycles
# (dedup is per-video-id, but 72h overlap forces J Bravo's last 8
# uploads back into the pool every single scan). 24h matches the
# 1-day dedup window in runner.py so each cycle only sees genuinely
# new content.
DEFAULT_LOOKBACK_HOURS = 24

# Maximum total audio duration to download (hours) — prevents runaway.
# Wave 14CC: lowered 24 → 8 for tighter per-cycle scope alongside the
# per-channel cap. With 14 channels × max 2 videos each × ~20m average,
# 8h is the right ceiling.
MAX_TOTAL_DURATION_HOURS = 8

# Wave 14CC (2026-05-30) — max videos a single channel can contribute
# to one cycle, enforced BEFORE the merged date-desc sort. Without
# this cap, a fast-posting channel (J Bravo: 3-5 videos/day) crowds
# out slower channels (Stock Moe: 1/week) in the post-merge pool
# because all of its videos sort to the top by recency. Cap of 2
# allows back-to-back uploads from a single channel while still
# leaving room for the rest.
MAX_PER_CHANNEL_PER_CYCLE = 2

# Wave 14X-3 (2026-05-29): STRIKE_POINT_KEYWORDS list + _strike_point_score
# function REMOVED. The keyword-bias scoring was vestigial from the retired
# strike-point pillar and was implicitly favoring crypto/macro-titled
# videos, starving Stock Moe / Chris Williamson / Follow the Money for
# weeks. Wave 14X-1A switched selection to date-desc sort. This block
# completes the deletion. Wave 14CC adds the per-channel pre-merge cap
# above to round out the channel-fairness fix.

# Where to store downloaded audio temporarily
AUDIO_CACHE_DIR = (
    Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL"))) / ".cache" / "youtube-audio"
)


# YouTube Data API v3 quota: 10,000 units/day. yt-dlp doesn't consume quota
# but we respect a polite crawl rate to avoid bot-detection blocks.
_CHANNEL_SCRAPE_DELAY_SECONDS = 2.0  # minimum gap between channel scrapes
_MAX_RETRIES_PER_CHANNEL = 2  # retry once on transient failure


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
        except json.JSONDecodeError as e:
            log.warning(
                f"Channel config {CHANNEL_CONFIG_PATH} failed to parse: {e} "
                f"— falling back to {len(DEFAULT_CHANNELS)} default channels"
            )
        except OSError as e:
            log.warning(
                f"Could not read channel config {CHANNEL_CONFIG_PATH}: {e} "
                f"— falling back to {len(DEFAULT_CHANNELS)} default channels"
            )

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
                    # Wave 14CC — per-channel pre-merge cap. Take the
                    # top N most-recent entries from THIS channel only,
                    # before the global merge sort. yt-dlp returns the
                    # channel's entries in upload-date desc order, so
                    # the first N are the freshest.
                    channel_entries: list[dict] = []
                    for entry in info["entries"]:
                        if not entry:
                            continue
                        # Post-filter by date: yt-dlp ignores dateafter in
                        # extract_flat mode, so we filter manually here.
                        upload_date = entry.get("upload_date", "")
                        if upload_date and upload_date < cutoff_str:
                            continue
                        channel_entries.append(
                            {
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
                            }
                        )
                        if len(channel_entries) >= MAX_PER_CHANNEL_PER_CYCLE:
                            break  # cap hit — stop reading entries for this channel
                    all_videos.extend(channel_entries)
                    if channel_entries:
                        log.info(
                            "  → %s: kept %d of channel's recent uploads (cap=%d)",
                            channel_name,
                            len(channel_entries),
                            MAX_PER_CHANNEL_PER_CYCLE,
                        )
                break  # Success — no retry needed
            except Exception as e:
                if attempt < _MAX_RETRIES_PER_CHANNEL - 1:
                    wait = 5.0 * (attempt + 1)
                    log.warning(
                        f"Scrape attempt {attempt+1} failed for {channel_url}: {e} — retrying in {wait:.0f}s"  # noqa: E501
                    )
                    time.sleep(wait)
                else:
                    log.error(
                        f"Failed to scrape {channel_url} after {_MAX_RETRIES_PER_CHANNEL} attempts: {e}"  # noqa: E501
                    )

    # ── Channel-fair selection (Wave 14X-1A, 2026-05-29) ──────────────
    # Previously: keyword-scored sort (`_strike_point_score`) + greedy
    # duration cap. That created an implicit channel bias — channels whose
    # title patterns didn't match the STRIKE_POINT_KEYWORDS list (Stock Moe,
    # Chris Williamson, Follow the Money) silently produced 0 reports for
    # weeks while crypto-titled channels won every selection.
    #
    # Fix: pure date-desc sort + greedy under duration cap. Each channel
    # competes only on recency. Crypto channels still get more reports
    # because they post more often (natural velocity) — but every channel
    # that posts gets fair attention. We KEEP recording strike_score on
    # each video as a metric for downstream analysis but no longer use it
    # for ranking. Wave 14X-3: _strike_point_score function fully removed —
    # the per-video score field is gone too. Date-desc is the only sort.

    # Sort by upload date (newest first) — channel-neutral
    all_videos.sort(
        key=lambda v: v.get("upload_date", ""),
        reverse=True,
    )

    # Per-channel observability — log how many entries each channel
    # contributed to this scrape so silent failures become visible in the
    # log stream instead of disappearing into the void.
    _per_channel_count: dict[str, int] = {}
    for v in all_videos:
        ch = v.get("channel") or "?"
        _per_channel_count[ch] = _per_channel_count.get(ch, 0) + 1
    if _per_channel_count:
        log.info(
            "Per-channel entry counts: %s",
            ", ".join(
                f"{c}={n}" for c, n in sorted(_per_channel_count.items(), key=lambda kv: -kv[1])
            ),
        )
    # Identify channels in the config that contributed ZERO entries — these
    # are silently failing scrapes worth surfacing.
    contributing = {(v.get("channel") or "").lower() for v in all_videos}
    silent = []
    for channel_url in channels:
        handle = channel_url.rsplit("@", 1)[-1].lower() if "@" in channel_url else ""
        if not handle:
            continue
        norm_handle = handle.replace("-", "").replace("_", "")
        matched = any(
            norm_handle in c.replace(" ", "").replace("-", "").replace("_", "")
            or c.replace(" ", "").replace("-", "").replace("_", "") in norm_handle
            for c in contributing
            if c
        )
        if not matched:
            silent.append(handle)
    if silent:
        log.warning("Silent channels this cycle (zero entries): %s", ", ".join(silent))

    # Greedy selection under duration cap
    selected: list[dict] = []
    total_seconds = 0.0
    max_seconds = max_total_hours * 3600

    for video in all_videos:
        dur = video.get("duration", 0) or 0
        if total_seconds + dur > max_seconds:
            log.info(
                f"Duration cap reached ({total_seconds/3600:.1f}h) — stopping at {len(selected)} videos"  # noqa: E501
            )
            break
        selected.append(video)
        total_seconds += dur

    log.info(
        f"Strike Point selected {len(selected)} videos "
        f"({total_seconds/3600:.1f}h total) from {len(channels)} channels"
    )
    if selected:
        top = selected[0]
        log.info(
            f"  Top hit: \"{top['title']}\" (score={top.get('strike_score', 0)}, {top.get('duration', 0)//60}m)"  # noqa: E501
        )
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
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            video_id = info.get("id", "unknown")
            mp3_path = out_dir / f"{video_id}.mp3"
            if mp3_path.exists():
                log.info(
                    f"Audio downloaded → {mp3_path.name} ({mp3_path.stat().st_size / 1024 / 1024:.1f}MB)"  # noqa: E501
                )
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


# Wave 14X-3 (2026-05-29): _strike_point_score function fully removed.
# The keyword-bias scoring was vestigial from the retired strike-point
# pillar. Wave 14X-1A switched selection to date-desc; this completes
# the deletion of the dead code path.
