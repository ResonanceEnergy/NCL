#!/usr/bin/env python3
"""
NCL YouTube Digest Pipeline
============================
Monitors Chris Williamson (Modern Wisdom) and Diary of a CEO YouTube channels
via RSS feeds.  Outputs a structured NDJSON digest of new videos for agent
ingestion through the relay server or direct memory storage.

Usage:
    python tools/youtube_digest.py                  # fetch latest from all channels
    python tools/youtube_digest.py --channel doac   # fetch only DOAC
    python tools/youtube_digest.py --since 2026-03-01  # only after date
    python tools/youtube_digest.py --output digest.ndjson  # custom output path

Scheduling (Windows):
    schtasks /create /tn "NCL_YouTubeDigest" /tr "python C:\\dev\\NCL\\tools\\youtube_digest.py" /sc daily /st 06:00

Scheduling (macOS/Linux):
    See ncl_agency_runtime/launchd/ for launchd plist templates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

# ── Channel Registry ──────────────────────────────────────────

CHANNELS: dict[str, dict[str, str]] = {
    "modern_wisdom": {
        "name": "Chris Williamson — Modern Wisdom",
        "alias": "cw",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCIaH-gZIVC432YRjNVvnyCA",
        "creator": "Chris Williamson",
    },
    "doac": {
        "name": "The Diary Of A CEO",
        "alias": "doac",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCGq-a57w-aPwyi3pW7XLiHw",
        "creator": "Steven Bartlett",
    },
    "andrei_jikh": {
        "name": "Andrei Jikh",
        "alias": "aj",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCGy7SkBjcIAgTiwkXEtPnYg",
        "creator": "Andrei Jikh",
    },
    "tom_bilyeu": {
        "name": "Tom Bilyeu — Impact Theory",
        "alias": "tb",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCnYMOamNKLGVlJgRUbamveA",
        "creator": "Tom Bilyeu",
    },
    "nate_b_jones": {
        "name": "Nate B Jones — AI News & Strategy",
        "alias": "nbj",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UC0C-17n9iuUQPylguM1d-lQ",
        "creator": "Nate B Jones",
    },
    "j_bravo": {
        "name": "J Bravo",
        "alias": "jb",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCXmAl7cO_eWT_JFxgI74lgA",
        "creator": "J Bravo",
    },
    "agentic_lab": {
        "name": "Agentic Lab",
        "alias": "al",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UC2xbIQqhPKUR4TYSw1ZuzcQ",
        "creator": "Agentic Lab",
    },
    "ian_carroll": {
        "name": "Ian Carroll",
        "alias": "ic",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCuMsEqN_YA5TTKbtpOHrr0g",
        "creator": "Ian Carroll",
    },
    "spencer_gatten": {
        "name": "Spencer Gatten",
        "alias": "sg",
        "rss": "https://www.youtube.com/feeds/videos.xml?channel_id=UCU0FLw38pXj6tRct2yygWlA",
        "creator": "Spencer Gatten",
    },
}

# YouTube Atom namespace
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# Paths
DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "data" / "youtube_digest.ndjson"
SEEN_FILE = Path(__file__).resolve().parent.parent / "data" / "youtube_seen.json"


def fetch_feed(url: str, timeout: int = 30) -> str:
    """Fetch RSS feed XML from YouTube."""
    req = Request(url, headers={"User-Agent": "NCL-YouTubeDigest/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")


def parse_feed(xml_text: str, channel_key: str) -> list[dict[str, Any]]:
    """Parse YouTube Atom feed into structured video entries."""
    root = ET.fromstring(xml_text)
    entries = []

    for entry in root.findall("atom:entry", NS):
        video_id_el = entry.find("yt:videoId", NS)
        title_el = entry.find("atom:title", NS)
        published_el = entry.find("atom:published", NS)
        updated_el = entry.find("atom:updated", NS)
        author_el = entry.find("atom:author/atom:name", NS)
        media_group = entry.find("media:group", NS)

        description = ""
        if media_group is not None:
            desc_el = media_group.find("media:description", NS)
            if desc_el is not None and desc_el.text:
                description = desc_el.text[:500]  # truncate long descriptions

        video_id = video_id_el.text if video_id_el is not None else ""
        title = title_el.text if title_el is not None else ""
        published = published_el.text if published_el is not None else ""
        updated = updated_el.text if updated_el is not None else ""
        author = author_el.text if author_el is not None else CHANNELS[channel_key]["creator"]

        entries.append({
            "video_id": video_id,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "published": published,
            "updated": updated,
            "author": author,
            "description": description,
            "channel_key": channel_key,
            "channel_name": CHANNELS[channel_key]["name"],
        })

    return entries


def load_seen() -> set[str]:
    """Load previously seen video IDs."""
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
            return set(data.get("seen_ids", []))
        except (json.JSONDecodeError, KeyError):
            return set()
    return set()


def save_seen(seen: set[str]) -> None:
    """Persist seen video IDs."""
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(
        json.dumps({"seen_ids": sorted(seen), "updated": datetime.now(tz=UTC).isoformat()},
                    indent=2),
        encoding="utf-8",
    )


def video_to_event(video: dict[str, Any]) -> dict[str, Any]:
    """Convert a video entry to an NCL-compatible event for relay ingestion."""
    event_id = hashlib.sha256(
        f"youtube:{video['video_id']}".encode()
    ).hexdigest()[:16]

    return {
        "event_id": f"yt_{event_id}",
        "schema": "ncl.iphone.v1",
        "event_type": "youtube_digest",
        "timestamp": video.get("published", datetime.now(tz=UTC).isoformat()),
        "source": {
            "channel": video["channel_key"],
            "channel_name": video["channel_name"],
            "creator": video["author"],
        },
        "payload": {
            "video_id": video["video_id"],
            "title": video["title"],
            "url": video["url"],
            "description": video["description"],
            "published": video["published"],
        },
        "tags": ["youtube", "digest", video["channel_key"]],
    }


def run_digest(
    channels: list[str] | None = None,
    since: str | None = None,
    output_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Main digest pipeline.  Returns list of new video events."""
    output_path = output_path or DEFAULT_OUTPUT
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen = load_seen()
    target_channels = channels or list(CHANNELS.keys())
    all_new: list[dict[str, Any]] = []

    since_dt = None
    if since:
        since_dt = datetime.fromisoformat(since).replace(tzinfo=UTC)

    for ch_key in target_channels:
        if ch_key not in CHANNELS:
            # Try alias match
            alias_match = [k for k, v in CHANNELS.items() if v["alias"] == ch_key]
            if alias_match:
                ch_key = alias_match[0]
            else:
                print(f"Unknown channel: {ch_key}, skipping")
                continue

        ch = CHANNELS[ch_key]
        print(f"Fetching: {ch['name']}...")

        try:
            xml_text = fetch_feed(ch["rss"])
        except (URLError, TimeoutError) as exc:
            print(f"  ERROR fetching {ch['name']}: {exc}")
            continue

        videos = parse_feed(xml_text, ch_key)
        new_videos = [v for v in videos if v["video_id"] not in seen]

        if since_dt:
            filtered = []
            for v in new_videos:
                try:
                    pub = datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
                    if pub >= since_dt:
                        filtered.append(v)
                except (ValueError, TypeError):
                    filtered.append(v)  # include if can't parse date
            new_videos = filtered

        print(f"  Found {len(videos)} total, {len(new_videos)} new")

        for video in new_videos:
            event = video_to_event(video)
            all_new.append(event)
            seen.add(video["video_id"])

    # Write NDJSON digest
    if all_new:
        with open(output_path, "a", encoding="utf-8") as f:
            for event in all_new:
                f.write(json.dumps(event) + "\n")
        print(f"\nWrote {len(all_new)} new events to {output_path}")
    else:
        print("\nNo new videos found.")

    save_seen(seen)
    return all_new


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NCL YouTube Digest Pipeline — monitors CW & DOAC channels"
    )
    parser.add_argument(
        "--channel", "-c",
        choices=[*CHANNELS.keys(), *[v["alias"] for v in CHANNELS.values()]],
        help="Fetch a specific channel only (default: all)",
    )
    parser.add_argument(
        "--since", "-s",
        help="Only include videos published after this ISO date (e.g. 2026-03-01)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help=f"Output NDJSON file path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--list-channels", action="store_true",
        help="List available channels and exit",
    )

    args = parser.parse_args()

    if args.list_channels:
        print("Available channels:")
        for key, ch in CHANNELS.items():
            print(f"  {key:20s} ({ch['alias']:5s}) — {ch['name']}")
        sys.exit(0)

    channels = [args.channel] if args.channel else None
    run_digest(channels=channels, since=args.since, output_path=args.output)


if __name__ == "__main__":
    main()
