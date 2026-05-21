#!/usr/bin/env python3
"""YouTube Transcription Pipeline for GOAT Academy + J Bravo strategy videos.

Enumerates channel videos, filters for strategy/education content (not market
commentary clickbait), pulls transcripts, and saves as structured .md files.

Usage:
    python3 youtube_transcribe.py --channel felix     # Felix Friends / GOAT Academy
    python3 youtube_transcribe.py --channel bravo     # J Bravo / Bill Stenzel
    python3 youtube_transcribe.py --channel both      # Both channels
    python3 youtube_transcribe.py --video VIDEO_ID    # Single video
    python3 youtube_transcribe.py --install           # Install dependencies

Output: /NCL/data/transcripts/<channel>/<video_id>.md
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path

# ── Dependency check + installer ──────────────────────────────────────────

def check_and_install_deps():
    """Check for required packages and offer to install missing ones."""
    missing = []
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # noqa: F401
    except ImportError:
        missing.append("youtube-transcript-api")

    try:
        import scrapetube  # noqa: F401
    except ImportError:
        missing.append("scrapetube")

    if missing:
        print(f"Missing packages: {', '.join(missing)}")
        print(f"Installing: pip install {' '.join(missing)}")
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", *missing
        ])
        print("Dependencies installed. Re-run the script.\n")
        # Re-import after install
        if "youtube-transcript-api" in missing:
            from youtube_transcript_api import YouTubeTranscriptApi  # noqa: F401
        if "scrapetube" in missing:
            import scrapetube  # noqa: F401
        print("All dependencies ready.\n")

    # Optional: yt-dlp (not required, scrapetube is primary)
    try:
        subprocess.run([sys.executable, "-m", "yt_dlp", "--version"],
                       capture_output=True, timeout=10)
    except Exception:
        print("NOTE: yt-dlp not installed (optional). Using scrapetube for enumeration.")
        print("      Install with: pip install yt-dlp\n")


# Run dependency check on import
check_and_install_deps()

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound, TranscriptsDisabled, VideoUnavailable,
)

# ── Configuration ──────────────────────────────────────────────────────────

CHANNELS = {
    "felix": {
        "name": "Felix Friends / GOAT Academy",
        "channel_url": "https://www.youtube.com/@felixfriends",
        "channel_id": "UCJtfma0mE_XrBAD9uakcjfA",
        "output_dir": "felix_friends",
        "search_terms": [
            "strategy", "goat", "scanner", "moving average", "technical analysis",
            "how to trade", "options", "breakout", "portfolio", "beginners",
            "swing trade", "day trade", "momentum", "indicators", "entry exit",
        ],
    },
    "bravo": {
        "name": "J Bravo / Bill Stenzel",
        "channel_url": "https://www.youtube.com/channel/UCXmAl7cO_eWT_JFxgI74lgA",
        "channel_id": "UCXmAl7cO_eWT_JFxgI74lgA",
        "output_dir": "j_bravo",
        # Strategy search terms for playlist/search-based enumeration
        "search_terms": [
            "bravo swing trade", "bravo kit", "gogo juice", "trading strategy",
            "how to trade", "technical analysis", "stock setup", "entry exit",
            "9 sma 20 ema", "ma alignment", "trading tutorial", "lesson",
        ],
    },
}

# Keywords that indicate strategy/education content (case-insensitive)
STRATEGY_KEYWORDS = [
    # GOAT Academy specific
    "goat", "goat academy", "strategy", "scanner", "moving average",
    "sma", "ema", "rsi", "macd", "bollinger", "technical analysis",
    "how to trade", "trading strategy", "stock scanner", "screener",
    "options strategy", "entry", "exit", "stop loss", "take profit",
    "swing trade", "day trade", "momentum", "breakout", "volume",
    "indicators", "chart pattern", "support", "resistance",
    "risk management", "position size", "portfolio",
    # J Bravo / Bravo Swing specific
    "bravo", "bravo swing", "gogo juice", "bravo kit",
    "vwap", "squeeze", "setup", "9 sma", "20 ema", "180 sma",
    "ma alignment", "sloping", "tutorial", "lesson", "course",
    "how i trade", "my strategy", "step by step", "beginners",
    "learn to trade", "trade like", "exact entries", "exact exits",
    # General education
    "webinar", "masterclass", "workshop", "education", "teaching",
    "explained", "guide", "walkthrough", "backtest", "investing",
    "invest", "advice",
    # Broader catch — stock analysis patterns
    "scan", "watchlist", "setup", "weekly plan",
    "top stocks", "stocks to buy", "watch list",
    "chart review", "market analysis", "trading plan",
]

# Keywords that indicate market commentary / clickbait (skip these)
COMMENTARY_KEYWORDS = [
    "crash", "collapse", "panic", "emergency", "urgent warning",
    "run now", "get out", "it's happening", "holy sh", "protect your",
    "too late", "about to happen", "catastroph", "distressing",
    "unthinkable", "trap", "destroyed", "insolvency", "bank run",
    "pissed off", "it's bad", "it's ugly", "unimaginable",
    "we are screwed", "black swan", "it's begun", "much lower",
    "chaos in", "final straw", "protect your family", "i'm sorry",
    "i'm worried", "going lower", "worthless", "final chance",
    "usd is worthless", "fall out of your chair", "must watch before",
    "short squeeze", "great squeeze",
    # Non-stock content (Amazon FBA, make money online, etc.)
    "amazon fba", "dropshipping", "sell on amazon", "amazon",
    "ebay", "make money online", "passive income", "paypal",
    "shopify", "credit score", "youtube money", "make $",
    "earn $", "$1000", "$500", "$300", "$200", "$150", "$100",
    "a day online", "a month online", "nut butter",
]

BASE_DIR = Path(__file__).resolve().parent.parent / "data" / "transcripts"


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word/phrase in text (not as substring).

    e.g. 'ema' matches 'EMA crossover' but NOT 'email' or 'cinema'.
    """
    pattern = r'(?<![a-z])' + re.escape(keyword) + r'(?![a-z])'
    return bool(re.search(pattern, text))


# Short keywords that need word-boundary matching to avoid false positives
# (e.g. 'ema' in 'email', 'rsi' in 'surprise', 'course' in 'of course')
_BOUNDARY_KEYWORDS = {
    "ema", "sma", "rsi", "macd", "vwap", "scan", "exit", "entry",
    "course", "setup", "volume", "guide", "explained",
    "invest", "advice",
}


def is_strategy_content(title: str) -> bool:
    """Classify a video title as strategy/education vs. market commentary."""
    title_lower = title.lower()

    # Strong skip signals (substring match is fine — these are specific)
    for kw in COMMENTARY_KEYWORDS:
        if kw in title_lower:
            return False

    # Strong include signals — use word boundary for short/ambiguous keywords
    for kw in STRATEGY_KEYWORDS:
        if kw in _BOUNDARY_KEYWORDS:
            if _word_match(kw, title_lower):
                return True
        else:
            if kw in title_lower:
                return True

    # Default: skip (most videos are commentary)
    return False


# ── Channel Enumeration (multiple methods with fallback) ──────────────────

def enumerate_channel(channel_key: str, limit: int = None) -> list:
    """Enumerate channel videos using multiple methods with auto-fallback.

    Priority:
    1. scrapetube (pure Python, no CLI dependency)
    2. yt-dlp (if installed)
    3. YouTube RSS feed (limited to ~15 most recent)
    """
    cfg = CHANNELS[channel_key]
    print(f"\n{'='*60}")
    print(f"Enumerating: {cfg['name']}")
    print(f"{'='*60}")

    videos = []

    # Method 1: scrapetube
    videos = _enumerate_scrapetube(cfg, limit)
    if videos:
        print(f"[scrapetube] Found {len(videos)} videos")
        return videos

    # Method 2: yt-dlp
    videos = _enumerate_ytdlp(cfg, limit)
    if videos:
        print(f"[yt-dlp] Found {len(videos)} videos")
        return videos

    # Method 3: YouTube channel-scoped search (finds older strategy videos)
    if cfg.get("channel_id"):
        print(f"[YT search] Searching within channel...")
        videos = _enumerate_yt_search(cfg, limit)
        if videos:
            return videos

    # Method 4: YouTube RSS feed (last resort, limited to ~15 recent)
    videos = _enumerate_rss(cfg, limit)
    if videos:
        print(f"[RSS feed] Found {len(videos)} videos (limited to recent)")
        return videos

    print("WARNING: All enumeration methods failed. Check network/dependencies.")
    return []


def _enumerate_scrapetube(cfg: dict, limit: int = None) -> list:
    """Enumerate using scrapetube (pure Python, most reliable)."""
    try:
        import scrapetube
    except ImportError:
        print("[scrapetube] Not installed, skipping...")
        return []

    import concurrent.futures

    def _fetch():
        channel_url = cfg["channel_url"]
        channel_id = cfg.get("channel_id")
        if channel_id:
            gen = scrapetube.get_channel(channel_id=channel_id, limit=limit)
        else:
            handle = channel_url.rstrip("/").split("/")[-1]
            gen = scrapetube.get_channel(
                channel_url=channel_url if handle.startswith("@") else channel_url,
                limit=limit,
            )
        videos = []
        for v in gen:
            vid_id = v.get("videoId", "")
            title_runs = v.get("title", {}).get("runs", [{}])
            title = title_runs[0].get("text", "") if title_runs else ""
            if not title:
                title = (v.get("title", {}).get("accessibility", {})
                          .get("accessibilityData", {}).get("label", ""))
            if vid_id:
                videos.append({
                    "id": vid_id,
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                })
        return videos

    try:
        print(f"[scrapetube] Fetching videos (30s timeout)...")
        import threading
        result_box = [None]
        error_box = [None]

        def _run():
            try:
                result_box[0] = _fetch()
            except Exception as exc:
                error_box[0] = exc

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=30)

        if t.is_alive():
            print(f"[scrapetube] Timed out after 30s, skipping...")
            return []
        if error_box[0]:
            raise error_box[0]
        return result_box[0] or []

    except Exception as e:
        print(f"[scrapetube] Error: {e}")
        return []


def _enumerate_ytdlp(cfg: dict, limit: int = None) -> list:
    """Enumerate using yt-dlp CLI (needs yt-dlp installed)."""
    try:
        # Check if yt-dlp is available
        check = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if check.returncode != 0:
            print("[yt-dlp] Not available, skipping...")
            return []
    except Exception:
        print("[yt-dlp] Not installed, skipping...")
        return []

    try:
        url = cfg["channel_url"] + "/videos"
        print(f"[yt-dlp] Fetching from {url}...")

        cmd = [sys.executable, "-m", "yt_dlp", "--flat-playlist", "--dump-json", url]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            print(f"[yt-dlp] Command failed: {result.stderr[:200]}")
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                videos.append({
                    "id": data.get("id", ""),
                    "title": data.get("title", ""),
                    "url": f"https://www.youtube.com/watch?v={data.get('id', '')}",
                })
            except json.JSONDecodeError:
                continue

        if limit:
            videos = videos[:limit]
        return videos

    except subprocess.TimeoutExpired:
        print("[yt-dlp] Timed out")
        return []
    except Exception as e:
        print(f"[yt-dlp] Error: {e}")
        return []


def _enumerate_yt_search(cfg: dict, limit: int = None) -> list:
    """Enumerate by searching within a YouTube channel using channel-scoped search.

    Uses YouTube's /channel/{id}/search?query= endpoint which returns only
    videos from that specific channel. Much more reliable than global search
    when scrapetube/yt-dlp fail.
    """
    channel_id = cfg.get("channel_id")
    if not channel_id:
        return []

    search_terms = cfg.get("search_terms", [])
    if not search_terms:
        # Default search terms for stock/trading channels
        search_terms = [
            "strategy", "tutorial", "how to", "indicator", "setup",
            "lesson", "course", "step by step", "beginners", "swing",
            "scan", "entry", "exit", "trade",
        ]

    seen_ids = set()
    videos = []

    for term in search_terms:
        if limit and len(videos) >= limit:
            break

        query = urllib.parse.quote(term)
        search_url = f"https://www.youtube.com/channel/{channel_id}/search?query={query}"

        try:
            req = urllib.request.Request(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Extract from ytInitialData JSON blob
            yt_match = re.search(
                r'var ytInitialData = ({.*?});</script>', html, re.DOTALL
            )
            if not yt_match:
                continue

            data_str = yt_match.group(1)
            vid_blocks = re.findall(
                r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".*?'
                r'"title":\{"runs":\[\{"text":"([^"]+)"',
                data_str,
            )

            new_count = 0
            for vid_id, title in vid_blocks:
                if vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)
                videos.append({
                    "id": vid_id,
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                })
                new_count += 1

            if new_count:
                print(f"  [search '{term}'] +{new_count} videos")

            time.sleep(0.5)  # Be polite between search queries

        except Exception as e:
            print(f"  [search '{term}'] Error: {e}")
            continue

    if videos:
        print(f"[YT search] Found {len(videos)} unique videos from {len(search_terms)} queries")
    return videos


def _enumerate_rss(cfg: dict, limit: int = None) -> list:
    """Enumerate using YouTube RSS feed (no dependencies, but limited to ~15 videos)."""
    channel_id = cfg.get("channel_id")
    if not channel_id:
        # Try to extract from URL
        url = cfg["channel_url"]
        if "/channel/" in url:
            channel_id = url.split("/channel/")[-1].strip("/")
        else:
            print("[RSS] Cannot determine channel ID for RSS feed")
            return []

    try:
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        print(f"[RSS] Fetching {rss_url}...")

        req = urllib.request.Request(rss_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml_data = resp.read().decode("utf-8")

        # Simple XML parsing (no lxml dependency)
        videos = []
        entries = xml_data.split("<entry>")[1:]  # Skip feed header
        for entry in entries:
            vid_match = re.search(r'<yt:videoId>([^<]+)</yt:videoId>', entry)
            title_match = re.search(r'<title>([^<]+)</title>', entry)
            if vid_match:
                vid_id = vid_match.group(1)
                title = title_match.group(1) if title_match else ""
                videos.append({
                    "id": vid_id,
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                })

        if limit:
            videos = videos[:limit]
        return videos

    except Exception as e:
        print(f"[RSS] Error: {e}")
        return []


# ── Transcription ─────────────────────────────────────────────────────────

def fetch_transcript(video_id: str) -> str:
    """Fetch transcript for a single video. Returns formatted text."""
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)
        # Join all text segments
        lines = []
        for entry in transcript.snippets:
            text = entry.text.strip()
            if text:
                lines.append(text)
        return " ".join(lines)
    except (NoTranscriptFound, TranscriptsDisabled):
        return ""
    except VideoUnavailable:
        return ""
    except Exception as e:
        err_str = str(e)
        if "blocking" in err_str.lower() or "ip" in err_str.lower():
            print(f"  RATE LIMITED — pausing 30s...")
            time.sleep(30)
            # Retry once
            try:
                ytt_api = YouTubeTranscriptApi()
                transcript = ytt_api.fetch(video_id)
                lines = []
                for entry in transcript.snippets:
                    text = entry.text.strip()
                    if text:
                        lines.append(text)
                return " ".join(lines)
            except Exception:
                return ""
        print(f"  Transcript error for {video_id}: {e}")
        return ""


def save_transcript(video: dict, transcript: str, channel_key: str):
    """Save transcript as structured .md file."""
    cfg = CHANNELS[channel_key]
    output_dir = BASE_DIR / cfg["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize title for filename
    safe_title = re.sub(r'[^\w\s-]', '', video["title"])
    safe_title = re.sub(r'\s+', '_', safe_title.strip())[:80]
    filename = f"{video['id']}_{safe_title}.md"

    filepath = output_dir / filename
    with open(filepath, "w") as f:
        f.write(f"# {video['title']}\n\n")
        f.write(f"**Channel**: {cfg['name']}\n")
        f.write(f"**Video ID**: {video['id']}\n")
        f.write(f"**URL**: {video['url']}\n")
        f.write(f"**Transcribed**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write("---\n\n")
        f.write("## Transcript\n\n")

        # Break into paragraphs (~200 words each)
        words = transcript.split()
        para_size = 200
        for i in range(0, len(words), para_size):
            chunk = " ".join(words[i:i + para_size])
            f.write(f"{chunk}\n\n")

    return filepath


# ── Pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(channel_key: str, limit: int = None, force_all: bool = False):
    """Run the full transcription pipeline for a channel."""
    videos = enumerate_channel(channel_key, limit=limit)

    if not videos:
        return

    if force_all:
        strategy_videos = videos
        print(f"Force-all mode: transcribing all {len(videos)} videos")
    else:
        strategy_videos = filter_strategy_videos(videos)

    if not strategy_videos:
        print("No strategy videos found to transcribe.")
        return

    # Check for existing transcripts
    cfg = CHANNELS[channel_key]
    output_dir = BASE_DIR / cfg["output_dir"]
    existing = set()
    if output_dir.exists():
        for f in output_dir.iterdir():
            if f.suffix == ".md":
                vid_id = f.stem.split("_")[0]
                existing.add(vid_id)

    new_videos = [v for v in strategy_videos if v["id"] not in existing]
    print(f"Already transcribed: {len(existing)}")
    print(f"New to transcribe: {len(new_videos)}")

    if not new_videos:
        print("All strategy videos already transcribed!")
        return

    # Transcribe with rate-limit awareness
    success = 0
    failed = 0
    consecutive_fails = 0
    for i, video in enumerate(new_videos, 1):
        print(f"\n[{i}/{len(new_videos)}] {video['title'][:70]}...")

        # Back off if we're getting rate limited
        if consecutive_fails >= 3:
            print(f"  3 consecutive failures — pausing 60s before retry...")
            time.sleep(60)
            consecutive_fails = 0

        transcript = fetch_transcript(video["id"])
        if transcript:
            path = save_transcript(video, transcript, channel_key)
            print(f"  Saved: {path.name} ({len(transcript.split())} words)")
            success += 1
            consecutive_fails = 0
            # Small delay between successful fetches to be polite
            if i < len(new_videos):
                time.sleep(1)
        else:
            print(f"  SKIP: No transcript available")
            failed += 1
            consecutive_fails += 1

    print(f"\n{'='*60}")
    print(f"Done! Transcribed: {success}, Skipped: {failed}")
    print(f"Output: {output_dir}")
    print(f"{'='*60}")


def filter_strategy_videos(videos: list) -> list:
    """Filter for strategy/education content."""
    strategy = [v for v in videos if is_strategy_content(v["title"])]
    print(f"Filtered to {len(strategy)} strategy/education videos (from {len(videos)} total)")
    return strategy


def main():
    parser = argparse.ArgumentParser(description="YouTube Transcription Pipeline")
    parser.add_argument("--channel", choices=["felix", "bravo", "both"], default="both",
                       help="Which channel to transcribe")
    parser.add_argument("--video", type=str, help="Transcribe a single video by ID")
    parser.add_argument("--limit", type=int, help="Max videos to enumerate per channel")
    parser.add_argument("--force-all", action="store_true",
                       help="Transcribe ALL videos, not just strategy-filtered")
    parser.add_argument("--install", action="store_true",
                       help="Just install dependencies and exit")
    parser.add_argument("--list-titles", action="store_true",
                       help="List all video titles found (debug: see what filter catches)")
    args = parser.parse_args()

    if args.install:
        print("Dependencies checked and installed.")
        return

    if args.video:
        print(f"Transcribing single video: {args.video}")
        transcript = fetch_transcript(args.video)
        if transcript:
            video = {
                "id": args.video,
                "title": args.video,
                "url": f"https://www.youtube.com/watch?v={args.video}",
            }
            channel_key = "felix"  # default
            path = save_transcript(video, transcript, channel_key)
            print(f"Saved: {path}")
        else:
            print("No transcript available for this video.")
        return

    if args.list_titles:
        # Debug mode: show all titles and filter results
        channels = ["felix", "bravo"] if args.channel == "both" else [args.channel]
        for key in channels:
            videos = enumerate_channel(key, limit=args.limit)
            print(f"\n--- All titles ({len(videos)}) ---")
            for v in videos:
                tag = "STRATEGY" if is_strategy_content(v["title"]) else "skip"
                print(f"  [{tag}] {v['title']}")
        return

    if args.channel == "both":
        for key in ["felix", "bravo"]:
            run_pipeline(key, limit=args.limit, force_all=args.force_all)
    else:
        run_pipeline(args.channel, limit=args.limit, force_all=args.force_all)


if __name__ == "__main__":
    main()
