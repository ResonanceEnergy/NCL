"""
X (Twitter) Liked-Video Scanner

Tracks NATRIX's liked videos on X, downloads them via yt-dlp,
transcribes with Whisper, analyzes with AI council, and stores
reports + transcripts in long-term memory.

Requires OAuth 2.0 User Context (not just Bearer Token) to access
the authenticated user's liked tweets. The OAuth flow is handled
by x_oauth.py — this module consumes the access token.

Pipeline: liked tweets → filter videos → yt-dlp download → Whisper
→ AI analysis → per-video report → memory store.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..shared.models import CouncilReport, CouncilSource, XPost, VideoMeta

log = logging.getLogger("ncl.councils.xai.liked_scanner")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
LIKED_VIDEOS_DIR = NCL_BASE / "intelligence-scan" / "x-liked-videos"
PROCESSED_LOG = LIKED_VIDEOS_DIR / "processed_ids.json"

# OAuth 2.0 user token — set by x_oauth.py after auth flow
def _get_user_access_token() -> str:
    return os.getenv("X_USER_ACCESS_TOKEN", "")


# Shared HTTP client — reused across liked-scanner calls to avoid
# creating a new connection pool per request.
_shared_liked_client: Optional["httpx.AsyncClient"] = None


async def _get_shared_liked_client() -> "httpx.AsyncClient":
    """Return (and lazily create) the module-level shared httpx client."""
    global _shared_liked_client
    import httpx
    if _shared_liked_client is None or _shared_liked_client.is_closed:
        _shared_liked_client = httpx.AsyncClient(timeout=30.0)
    return _shared_liked_client


async def close_liked_scanner_client() -> None:
    """Close the shared HTTP client. Call on application shutdown."""
    global _shared_liked_client
    if _shared_liked_client is not None:
        await _shared_liked_client.aclose()
        _shared_liked_client = None


def _load_processed_ids() -> set[str]:
    """Load set of already-processed tweet IDs to avoid re-processing."""
    if not PROCESSED_LOG.exists():
        return set()
    try:
        data = json.loads(PROCESSED_LOG.read_text())
        return set(data.get("processed", []))
    except Exception:
        return set()


def _save_processed_ids(ids: set[str]) -> None:
    """Persist processed tweet IDs. Keep last 5000 to prevent unbounded growth."""
    LIKED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    # Sort numerically — higher tweet IDs are more recent on Twitter
    trimmed = sorted(ids, key=lambda x: int(x) if x.isdigit() else 0)[-5000:]
    PROCESSED_LOG.write_text(json.dumps({"processed": trimmed, "updated": datetime.now(timezone.utc).isoformat()}, indent=2))


async def fetch_liked_tweets(
    max_results: int = 100,
    user_id: Optional[str] = None,
    client: Optional["httpx.AsyncClient"] = None,
) -> list[dict]:
    """
    Fetch the authenticated user's recent liked tweets from X API v2.

    Requires OAuth 2.0 User Context token (X_USER_ACCESS_TOKEN env var).
    Returns raw tweet dicts with media expansion.

    Args:
        client: Optional shared httpx.AsyncClient. If not provided, the
                module-level shared client is used to avoid per-call overhead.
    """
    import httpx

    token = _get_user_access_token()
    if not token:
        log.warning("[LIKED] No X_USER_ACCESS_TOKEN set — cannot fetch liked tweets")
        return []

    # If no user_id, get the authenticated user's ID first
    if not user_id:
        user_id = await _get_authenticated_user_id(token, client=client)
        if not user_id:
            return []

    url = f"https://api.twitter.com/2/users/{user_id}/liked_tweets"
    params = {
        "max_results": min(max_results, 100),
        "tweet.fields": "created_at,author_id,attachments,entities,public_metrics,text",
        "expansions": "attachments.media_keys,author_id",
        "media.fields": "type,url,preview_image_url,variants,duration_ms",
        "user.fields": "username,name,verified",
    }
    headers = {
        "Authorization": f"Bearer {token}",
    }

    http = client or await _get_shared_liked_client()
    try:
        resp = await http.get(url, params=params, headers=headers)
        if resp.status_code == 401:
            log.error("[LIKED] OAuth token expired — need to re-authenticate")
            return []
        if resp.status_code == 402:
            log.error("[LIKED] X API 402 — subscription expired")
            return []
        resp.raise_for_status()
        data = resp.json()

        tweets = data.get("data", [])
        # Build media lookup from includes
        media_lookup: dict[str, dict] = {}
        for media in data.get("includes", {}).get("media", []):
            media_lookup[media["media_key"]] = media

        # Build user lookup from includes
        user_lookup: dict[str, dict] = {}
        for user in data.get("includes", {}).get("users", []):
            user_lookup[user["id"]] = user

        # Attach media and user info to each tweet
        for tweet in tweets:
            tweet["_media"] = []
            for mk in tweet.get("attachments", {}).get("media_keys", []):
                if mk in media_lookup:
                    tweet["_media"].append(media_lookup[mk])
            author_id = tweet.get("author_id", "")
            if author_id in user_lookup:
                tweet["_author"] = user_lookup[author_id]

        log.info(f"[LIKED] Fetched {len(tweets)} liked tweets")
        return tweets

    except httpx.HTTPStatusError as e:
        log.error(f"[LIKED] X API error: {e.response.status_code} — {e.response.text[:200]}")
        return []
    except Exception as e:
        log.error(f"[LIKED] Failed to fetch liked tweets: {e}", exc_info=True)
        return []


async def _get_authenticated_user_id(
    token: str,
    client: Optional["httpx.AsyncClient"] = None,
) -> Optional[str]:
    """Get the authenticated user's ID from the token."""
    import httpx

    http = client or await _get_shared_liked_client()
    try:
        resp = await http.get(
            "https://api.twitter.com/2/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        user_id = data.get("data", {}).get("id")
        log.info(f"[LIKED] Authenticated as user ID: {user_id}")
        return user_id
    except Exception as e:
        log.error(f"[LIKED] Failed to get authenticated user ID: {e}")
        return None


def filter_video_tweets(tweets: list[dict]) -> list[dict]:
    """Filter liked tweets to only those containing video content."""
    video_tweets = []
    for tweet in tweets:
        media_list = tweet.get("_media", [])
        has_video = any(m.get("type") == "video" for m in media_list)

        # Also check for embedded video URLs (YouTube, etc.)
        text = tweet.get("text", "")
        entities = tweet.get("entities", {})
        urls = entities.get("urls", [])
        has_video_url = False
        for url_entity in urls:
            expanded = url_entity.get("expanded_url", "")
            if _is_video_url(expanded):
                has_video_url = True
                tweet["_video_url"] = expanded
                break

        if has_video or has_video_url:
            video_tweets.append(tweet)

    log.info(f"[LIKED] Filtered to {len(video_tweets)} video tweets from {len(tweets)} total")
    return video_tweets


def _is_video_url(url: str) -> bool:
    """Check if a URL points to a video platform supported by yt-dlp."""
    video_domains = [
        "youtube.com", "youtu.be", "x.com", "twitter.com",
        "vimeo.com", "twitch.tv", "dailymotion.com",
        "rumble.com", "bitchute.com", "odysee.com",
    ]
    return any(domain in url.lower() for domain in video_domains)


def extract_video_url(tweet: dict) -> Optional[str]:
    """Extract the best downloadable video URL from a tweet."""
    # Check for native X video
    media_list = tweet.get("_media", [])
    for media in media_list:
        if media.get("type") == "video":
            # Get the best quality variant
            variants = media.get("variants", [])
            # Filter for mp4 and sort by bitrate
            mp4_variants = [v for v in variants if v.get("content_type") == "video/mp4"]
            if mp4_variants:
                best = max(mp4_variants, key=lambda v: v.get("bit_rate", 0))
                return best.get("url")
            # Fallback to any URL
            for v in variants:
                if v.get("url"):
                    return v["url"]

    # Check for external video URL (YouTube, etc.)
    if "_video_url" in tweet:
        return tweet["_video_url"]

    # Build X tweet URL for yt-dlp to extract natively
    tweet_id = tweet.get("id", "")
    author = tweet.get("_author", {})
    username = author.get("username", "")
    if tweet_id and username:
        return f"https://x.com/{username}/status/{tweet_id}"

    return None


async def download_video(url: str, output_dir: Path) -> Optional[Path]:
    """Download video audio via yt-dlp. Returns path to audio file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(id)s.%(ext)s")

    cmd = [
        "yt-dlp",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "3",
        "--no-playlist",
        "--max-filesize", "100M",
        "--output", output_template,
        "--quiet",
        "--no-warnings",
        url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode != 0:
            err = stderr.decode(errors="replace")[:300]
            log.warning(f"[LIKED] yt-dlp failed for {url}: {err}")
            return None

        # Find the output file
        for f in output_dir.glob("*.mp3"):
            if f.stat().st_size > 0:
                log.info(f"[LIKED] Downloaded audio: {f.name} ({f.stat().st_size / 1024:.0f}KB)")
                return f

        log.warning(f"[LIKED] yt-dlp produced no output for {url}")
        return None

    except asyncio.TimeoutError:
        log.warning(f"[LIKED] yt-dlp timed out for {url}")
        return None
    except Exception as e:
        log.error(f"[LIKED] Download failed for {url}: {e}")
        return None


async def transcribe_audio_file(audio_path: Path) -> Optional[str]:
    """Transcribe audio file using the existing YTC transcriber."""
    try:
        from ..youtube.transcriber import transcribe_audio as _transcribe
        transcript = await asyncio.to_thread(_transcribe, audio_path, video_id=audio_path.stem)
        if transcript and transcript.full_text:
            log.info(f"[LIKED] Transcribed {audio_path.name}: {len(transcript.full_text)} chars")
            return transcript.timestamped_text
        return None
    except Exception as e:
        log.error(f"[LIKED] Transcription failed for {audio_path}: {e}")
        return None


async def analyze_liked_video(
    tweet: dict,
    transcript_text: str,
    session_id: str,
) -> CouncilReport:
    """Analyze a single liked video using the YouTube analyzer infrastructure."""
    from ..youtube.analyzer import analyze_single_video
    from ..shared.models import TranscriptSegment, Transcript

    author = tweet.get("_author", {})
    tweet_text = tweet.get("text", "")
    tweet_id = tweet.get("id", "unknown")
    username = author.get("username", "unknown")

    # Build a VideoMeta-compatible dict
    video_info = {
        "video_id": f"xliked-{tweet_id}",
        "title": f"Liked video by @{username}: {tweet_text[:80]}",
        "channel": f"@{username} ({author.get('name', 'Unknown')})",
        "channel_id": author.get("id", ""),
        "upload_date": tweet.get("created_at", ""),
        "duration": 0,  # Will be estimated from transcript
        "url": f"https://x.com/{username}/status/{tweet_id}",
        "description": tweet_text,
        "view_count": tweet.get("public_metrics", {}).get("impression_count", 0),
        "like_count": tweet.get("public_metrics", {}).get("like_count", 0),
        "tags": ["x_liked_video", f"author_{username}"],
        "thumbnail": "",
    }

    # Build a Transcript object from the text
    segments = []
    for line in transcript_text.split("\n"):
        match = re.match(r'\[(\d+):(\d+)\]\s*(.*)', line)
        if match:
            mins, secs = int(match.group(1)), int(match.group(2))
            start = mins * 60 + secs
            segments.append(TranscriptSegment(start=start, end=start + 5, text=match.group(3)))
        elif line.strip():
            segments.append(TranscriptSegment(start=0, end=0, text=line.strip()))

    transcript = Transcript(
        video_id=f"xliked-{tweet_id}",
        segments=segments,
    )

    # Estimate duration from last segment
    if segments:
        video_info["duration"] = int(segments[-1].end)

    report = await analyze_single_video(video_info, transcript, session_id)
    return report


async def run_liked_video_scan(
    max_tweets: int = 50,
    session_id: Optional[str] = None,
) -> list[CouncilReport]:
    """
    Full pipeline: fetch likes → filter videos → download → transcribe → analyze → store.

    Returns list of per-video CouncilReports.
    """
    from ..shared.report_writer import write_report

    if not session_id:
        session_id = f"xliked-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    log.info(f"[LIKED] Starting liked-video scan: {session_id}")

    # Load already-processed IDs
    processed = _load_processed_ids()
    initial_count = len(processed)

    # Step 1: Fetch liked tweets
    tweets = await fetch_liked_tweets(max_results=max_tweets)
    if not tweets:
        log.info("[LIKED] No liked tweets fetched")
        return []

    # Step 2: Filter for videos
    video_tweets = filter_video_tweets(tweets)
    if not video_tweets:
        log.info("[LIKED] No video tweets found in likes")
        return []

    # Step 3: Skip already processed
    new_tweets = [t for t in video_tweets if t.get("id", "") not in processed]
    if not new_tweets:
        log.info(f"[LIKED] All {len(video_tweets)} video tweets already processed")
        return []

    log.info(f"[LIKED] {len(new_tweets)} new video tweets to process")

    # Step 4: Download, transcribe, analyze each
    reports: list[CouncilReport] = []
    work_dir = Path(tempfile.mkdtemp(prefix="xliked_"))

    for i, tweet in enumerate(new_tweets):
        tweet_id = tweet.get("id", f"unknown_{i}")
        log.info(f"[LIKED] Processing [{i + 1}/{len(new_tweets)}]: tweet {tweet_id}")

        try:
            # Extract video URL
            video_url = extract_video_url(tweet)
            if not video_url:
                log.warning(f"[LIKED] No downloadable URL for tweet {tweet_id}")
                processed.add(tweet_id)  # Mark as processed to skip next time
                continue

            # Download audio
            audio_path = await download_video(video_url, work_dir)
            if not audio_path:
                processed.add(tweet_id)
                continue

            # Transcribe
            transcript_text = await transcribe_audio_file(audio_path)
            if not transcript_text:
                processed.add(tweet_id)
                continue

            # Analyze
            vid_session = f"{session_id}-{tweet_id}"
            report = await analyze_liked_video(tweet, transcript_text, vid_session)

            # Save report
            LIKED_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
            report_data = report.to_dict()
            report_data.update({
                "status": "complete",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "source_type": "x_liked_video",
                "tweet_id": tweet_id,
                "tweet_text": tweet.get("text", ""),
                "transcript": transcript_text[:5000],  # Save first 5K chars of transcript
            })
            report_path = LIKED_VIDEOS_DIR / f"{vid_session}.json"
            report_path.write_text(json.dumps(report_data, default=str, indent=2))

            # Also write via report_writer for council-reports/ directory
            md_path, json_path = write_report(report)
            log.info(f"[LIKED] Report saved: {report_path.name}")

            reports.append(report)
            processed.add(tweet_id)

            # Clean up audio
            try:
                audio_path.unlink()
            except Exception:
                pass

        except Exception as e:
            log.error(f"[LIKED] Failed to process tweet {tweet_id}: {e}", exc_info=True)
            processed.add(tweet_id)

    # Save updated processed list
    _save_processed_ids(processed)
    log.info(
        f"[LIKED] Scan complete: {len(reports)} reports from {len(new_tweets)} tweets "
        f"(total processed: {len(processed)}, new this run: {len(processed) - initial_count})"
    )

    # Clean up temp dir
    try:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:
        pass

    return reports
