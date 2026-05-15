"""
Council Knowledge Base Manager — Obsidian-Compatible Markdown.

Maintains a structured knowledge base from council outputs:
    - Each insight → individual .md note with YAML frontmatter
    - Cross-links between related insights via [[wiki-links]]
    - Auto-generated index pages (by category, by session, by date)
    - Tags for Obsidian tag search
    - Transcript chunks saved as reference notes

Directory structure:
    ~/dev/NCL/knowledge-base/
    ├── insights/          # Individual insight notes
    ├── sessions/          # Session summary notes
    ├── transcripts/       # Video transcript chunks
    ├── war-room/          # War Room briefings
    ├── indices/           # Auto-generated index pages
    │   ├── by-category.md
    │   ├── by-date.md
    │   └── by-source.md
    └── _templates/        # Note templates
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .models import CouncilReport, CouncilSource, Insight, VideoMeta, XPost

log = logging.getLogger("ncl.councils.knowledge_base")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
KB_DIR = NCL_BASE / "knowledge-base"


class KnowledgeBase:
    """
    Obsidian-compatible knowledge base built from council outputs.

    Call ingest_report() after each council session to update the KB.
    """

    # Size and staleness limits
    MAX_INSIGHTS = 5_000          # Hard cap on insight notes
    MAX_TRANSCRIPTS = 1_000       # Hard cap on transcript notes
    MAX_WAR_ROOM = 500            # Hard cap on war-room notes
    STALE_AFTER_DAYS = 90         # Notes older than this are candidates for pruning

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base = Path(base_dir) if base_dir else KB_DIR
        self.insights_dir = self.base / "insights"
        self.sessions_dir = self.base / "sessions"
        self.transcripts_dir = self.base / "transcripts"
        self.war_room_dir = self.base / "war-room"
        self.indices_dir = self.base / "indices"

        for d in [self.insights_dir, self.sessions_dir, self.transcripts_dir,
                  self.war_room_dir, self.indices_dir]:
            d.mkdir(parents=True, exist_ok=True)

    async def ingest_report(
        self,
        report: CouncilReport,
        vector_store: Any | None = None,
    ) -> dict[str, int]:
        """
        Ingest a full council report into the knowledge base.

        Creates individual insight notes, a session summary, and
        optionally indexes everything in the vector store.

        Returns stats: {"insights": n, "transcripts": n, "notes_created": n}
        """
        stats = {"insights": 0, "transcripts": 0, "notes_created": 0}
        source = report.council_type.value
        session = report.session_id
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. Create insight notes (enforce size cap)
        current_insight_count = len(list(self.insights_dir.glob("*.md")))
        insight_links: list[str] = []
        for i, insight in enumerate(report.insights):
            if current_insight_count + stats["insights"] >= self.MAX_INSIGHTS:
                log.warning(
                    f"Insight cap ({self.MAX_INSIGHTS}) reached — skipping remaining insights. "
                    "Run cleanup_stale() to free space."
                )
                break
            slug = _slugify(insight.title)
            note_name = f"{date_str}-{source}-{slug}"
            note_path = self.insights_dir / f"{note_name}.md"

            content = _render_insight_note(
                insight=insight,
                source=source,
                session_id=session,
                date=date_str,
                index=i + 1,
                total=len(report.insights),
            )
            note_path.write_text(content, encoding="utf-8")
            insight_links.append(f"[[{note_name}|{insight.title}]]")
            stats["insights"] += 1
            stats["notes_created"] += 1

            # Index in vector store
            if vector_store:
                try:
                    await vector_store.index_insight(
                        insight_title=insight.title,
                        insight_description=insight.description,
                        session_id=session,
                        source=source,
                        category=insight.category.value if hasattr(insight.category, 'value') else str(insight.category),
                        tags=insight.tags,
                        confidence=insight.confidence,
                    )
                except Exception as e:
                    log.warning(f"Vector index failed for insight: {e}")

        # 2. Create transcript notes (YouTube only, enforce size cap)
        current_transcript_count = len(list(self.transcripts_dir.glob("*.md")))
        if report.videos:
            for video in report.videos:
                if current_transcript_count + stats["transcripts"] >= self.MAX_TRANSCRIPTS:
                    log.warning(
                        f"Transcript cap ({self.MAX_TRANSCRIPTS}) reached — run cleanup_stale()."
                    )
                    break
                # We don't have the transcript text in the report, but we create
                # a reference note linking to the video
                slug = _slugify(video.title)
                note_name = f"{date_str}-transcript-{slug}"
                note_path = self.transcripts_dir / f"{note_name}.md"

                content = _render_video_reference_note(video, source, session, date_str)
                note_path.write_text(content, encoding="utf-8")
                stats["transcripts"] += 1
                stats["notes_created"] += 1

        # 3. Create session summary note
        session_note_name = f"{date_str}-{source}-session-{session}"
        session_note_path = self.sessions_dir / f"{session_note_name}.md"
        session_content = _render_session_note(
            report=report,
            date=date_str,
            insight_links=insight_links,
        )
        session_note_path.write_text(session_content, encoding="utf-8")
        stats["notes_created"] += 1

        # Index session summary
        if vector_store and report.summary:
            try:
                await vector_store.index_report_summary(
                    session_id=session,
                    source=source,
                    summary=report.summary,
                    insight_count=len(report.insights),
                )
            except Exception as e:
                log.warning(f"Vector index failed for session: {e}")

        # 4. Rebuild indices
        self._rebuild_indices()

        log.info(
            f"Knowledge base updated: {stats['insights']} insights, "
            f"{stats['transcripts']} transcripts, "
            f"{stats['notes_created']} total notes"
        )
        return stats

    async def ingest_war_room_briefing(
        self,
        briefing_text: str,
        session_id: str,
        date_str: str | None = None,
    ) -> Path:
        """Save a War Room briefing as a knowledge base note."""
        date = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        note_name = f"{date}-war-room-{session_id}"
        note_path = self.war_room_dir / f"{note_name}.md"

        frontmatter = _yaml_frontmatter({
            "type": "war-room-briefing",
            "session_id": session_id,
            "date": date,
            "tags": ["war-room", "briefing", "strategic"],
            "created": datetime.now(timezone.utc).isoformat(),
        })

        content = f"{frontmatter}\n{briefing_text}\n"
        note_path.write_text(content, encoding="utf-8")
        log.info(f"War Room briefing saved to KB → {note_path.name}")
        return note_path

    def _rebuild_indices(self) -> None:
        """Rebuild auto-generated index pages."""
        try:
            self._build_category_index()
            self._build_date_index()
            self._build_source_index()
        except Exception as e:
            log.warning(f"Index rebuild failed: {e}")

    def _build_category_index(self) -> None:
        """Build index of insights grouped by category."""
        by_category: dict[str, list[str]] = {}
        for note in sorted(self.insights_dir.glob("*.md")):
            meta = _extract_frontmatter(note)
            cat = meta.get("category", "uncategorized")
            by_category.setdefault(cat, []).append(note.stem)

        lines = ["# Insights by Category\n"]
        for cat, notes in sorted(by_category.items()):
            lines.append(f"\n## {cat.replace('-', ' ').title()}\n")
            for name in notes:
                lines.append(f"- [[{name}]]")

        (self.indices_dir / "by-category.md").write_text("\n".join(lines))

    def _build_date_index(self) -> None:
        """Build index of all notes grouped by date."""
        by_date: dict[str, list[str]] = {}
        for subdir in [self.insights_dir, self.sessions_dir, self.war_room_dir]:
            for note in sorted(subdir.glob("*.md")):
                date = note.stem[:10] if len(note.stem) >= 10 else "unknown"
                by_date.setdefault(date, []).append(f"{subdir.name}/{note.stem}")

        lines = ["# Knowledge Base Timeline\n"]
        for date, notes in sorted(by_date.items(), reverse=True):
            lines.append(f"\n## {date}\n")
            for name in notes:
                lines.append(f"- [[{name}]]")

        (self.indices_dir / "by-date.md").write_text("\n".join(lines))

    def _build_source_index(self) -> None:
        """Build index grouped by source (youtube, x)."""
        by_source: dict[str, list[str]] = {}
        for note in sorted(self.insights_dir.glob("*.md")):
            meta = _extract_frontmatter(note)
            source = meta.get("source", "unknown")
            by_source.setdefault(source, []).append(note.stem)

        lines = ["# Insights by Source\n"]
        for source, notes in sorted(by_source.items()):
            lines.append(f"\n## {source.upper()}\n")
            for name in notes:
                lines.append(f"- [[{name}]]")

        (self.indices_dir / "by-source.md").write_text("\n".join(lines))

    def cleanup_stale(self, older_than_days: Optional[int] = None) -> dict[str, int]:
        """
        Delete notes older than `older_than_days` (default: STALE_AFTER_DAYS).

        Only removes insight, transcript, and session notes — war-room briefings
        are kept (they're historical records).

        Returns counts of deleted notes per directory.
        """
        max_age = older_than_days if older_than_days is not None else self.STALE_AFTER_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age)
        deleted: dict[str, int] = {"insights": 0, "transcripts": 0, "sessions": 0}

        dirs = [
            (self.insights_dir, "insights"),
            (self.transcripts_dir, "transcripts"),
            (self.sessions_dir, "sessions"),
        ]
        for directory, key in dirs:
            for note in directory.glob("*.md"):
                try:
                    mtime = datetime.fromtimestamp(note.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff:
                        note.unlink()
                        deleted[key] += 1
                except Exception as e:
                    log.warning(f"Failed to evaluate/delete stale note {note.name}: {e}")

        total = sum(deleted.values())
        if total:
            log.info(f"Cleaned up {total} stale notes (>{max_age}d): {deleted}")
            self._rebuild_indices()
        return deleted

    def get_stats(self) -> dict[str, Any]:
        """Return knowledge base statistics."""
        insight_count = len(list(self.insights_dir.glob("*.md")))
        transcript_count = len(list(self.transcripts_dir.glob("*.md")))
        war_room_count = len(list(self.war_room_dir.glob("*.md")))
        return {
            "insights": insight_count,
            "insights_cap": self.MAX_INSIGHTS,
            "insights_pct_full": round(insight_count / self.MAX_INSIGHTS * 100, 1),
            "sessions": len(list(self.sessions_dir.glob("*.md"))),
            "transcripts": transcript_count,
            "transcripts_cap": self.MAX_TRANSCRIPTS,
            "war_room_briefings": war_room_count,
            "war_room_cap": self.MAX_WAR_ROOM,
            "stale_after_days": self.STALE_AFTER_DAYS,
            "base_dir": str(self.base),
        }


# ── Rendering helpers ────────────────────────────────────────────────────


def _yaml_frontmatter(data: dict) -> str:
    """Render YAML frontmatter block."""
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {item}")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f'{key}: "{value}"')
    lines.append("---\n")
    return "\n".join(lines)


def _render_insight_note(
    insight: Insight,
    source: str,
    session_id: str,
    date: str,
    index: int,
    total: int,
) -> str:
    """Render a single insight as an Obsidian note."""
    cat_value = insight.category.value if hasattr(insight.category, 'value') else str(insight.category)
    tags = ["insight", source, cat_value] + insight.tags

    frontmatter = _yaml_frontmatter({
        "type": "insight",
        "source": source,
        "session_id": session_id,
        "category": cat_value,
        "confidence": round(insight.confidence, 2),
        "actionable": insight.actionable,
        "tags": tags,
        "date": date,
        "created": datetime.now(timezone.utc).isoformat(),
    })

    confidence_bar = "█" * int(insight.confidence * 10) + "░" * (10 - int(insight.confidence * 10))

    lines = [
        frontmatter,
        f"# {insight.title}\n",
        f"**Source**: {source.upper()} Council | **Session**: {session_id}",
        f"**Confidence**: {confidence_bar} {insight.confidence:.0%}",
        f"**Category**: #{cat_value}\n",
        insight.description,
    ]

    if insight.actionable and insight.action_suggestion:
        lines.append(f"\n## Recommended Action\n\n{insight.action_suggestion}")

    if insight.tags:
        lines.append(f"\n## Tags\n\n{' '.join(f'#{t}' for t in insight.tags)}")

    lines.append(f"\n---\n_Insight {index}/{total} from {source} council session {session_id}_")
    return "\n".join(lines)


def _render_video_reference_note(
    video: VideoMeta,
    source: str,
    session_id: str,
    date: str,
) -> str:
    """Render a video reference note."""
    frontmatter = _yaml_frontmatter({
        "type": "video-reference",
        "video_id": video.video_id,
        "channel": video.channel,
        "duration_minutes": video.duration_seconds // 60,
        "views": video.view_count,
        "tags": ["video", "transcript", source] + video.tags[:5],
        "date": date,
        "url": video.url,
    })

    return "\n".join([
        frontmatter,
        f"# {video.title}\n",
        f"**Channel**: {video.channel}",
        f"**Duration**: {video.duration_seconds // 60} min",
        f"**Views**: {video.view_count:,}",
        f"**URL**: {video.url}",
        f"**Uploaded**: {video.upload_date}\n",
        f"## Description\n\n{video.description[:500] if video.description else '_No description._'}",
        f"\n---\n_Processed in session {session_id}_",
    ])


def _render_session_note(
    report: CouncilReport,
    date: str,
    insight_links: list[str],
) -> str:
    """Render a session summary note."""
    source = report.council_type.value
    frontmatter = _yaml_frontmatter({
        "type": "session-summary",
        "source": source,
        "session_id": report.session_id,
        "sources_processed": report.sources_processed,
        "insight_count": len(report.insights),
        "tags": ["session", source],
        "date": date,
    })

    lines = [
        frontmatter,
        f"# {source.upper()} Council — Session {report.session_id}\n",
        f"**Date**: {date}",
        f"**Sources processed**: {report.sources_processed}",
    ]

    if report.total_duration_hours > 0:
        lines.append(f"**Content duration**: {report.total_duration_hours:.1f}h")

    lines.append(f"**Insights extracted**: {len(report.insights)}\n")
    lines.append(f"## Summary\n\n{report.summary or '_No summary._'}\n")

    if insight_links:
        lines.append("## Insights\n")
        for link in insight_links:
            lines.append(f"- {link}")

    if report.raw_analysis:
        lines.append(f"\n## Full Analysis\n\n{report.raw_analysis[:2000]}")

    return "\n".join(lines)


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    slug = re.sub(r"[^\w\s-]", "", text.lower())
    slug = re.sub(r"[\s_]+", "-", slug)
    return slug[:60].strip("-")


def _extract_frontmatter(note_path: Path) -> dict:
    """Quick extraction of YAML frontmatter from a note."""
    try:
        text = note_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        end = text.index("---", 3)
        yaml_block = text[4:end]
        result = {}
        for line in yaml_block.strip().split("\n"):
            if ":" in line and not line.startswith("  "):
                key, val = line.split(":", 1)
                val = val.strip().strip('"')
                result[key.strip()] = val
        return result
    except Exception:
        return {}
