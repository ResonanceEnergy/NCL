"""
Markdown report writer for council output.

Generates clean .md files from CouncilReport data, formatted for
human reading and Obsidian compatibility. Reports are saved to
NCL/intelligence-scan/signals/ for the Awarebot-FPC pipeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import CouncilReport, CouncilSource, XPost


log = logging.getLogger("ncl.councils.report_writer")

# Default output locations within NCL
NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
SIGNALS_DIR = NCL_BASE / "intelligence-scan" / "signals"
ALERTS_DIR = NCL_BASE / "intelligence-scan" / "alerts"
REPORTS_DIR = NCL_BASE / "intelligence-scan" / "council-reports"


def write_report(
    report: CouncilReport,
    output_dir: Optional[Path] = None,
) -> tuple[Path, Path]:
    """
    Write a council report as both .md and .json files.

    Returns:
        Tuple of (md_path, json_path)
    """
    out = output_dir or REPORTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    slug = report.council_type.value
    base_name = f"{slug}-council-{date_str}-{report.session_id}"

    # Write markdown atomically (temp + rename)
    md_path = out / f"{base_name}.md"
    md_content = _render_markdown(report)
    md_tmp = md_path.with_suffix(".md.tmp")
    md_tmp.write_text(md_content, encoding="utf-8")
    md_tmp.replace(md_path)
    log.info(f"Report written → {md_path}")

    # Write JSON atomically (temp + rename) so a mid-write crash cannot
    # leave a half-formed report on disk for downstream consumers.
    json_path = out / f"{base_name}.json"
    json_tmp = json_path.with_suffix(".json.tmp")
    report.save_json(json_tmp)
    json_tmp.replace(json_path)
    log.info(f"Report data → {json_path}")

    # Write signals for Awarebot-FPC pipeline
    _write_signals(report, date_str)

    # Write alerts for high-severity insights
    _write_alerts(report)

    return md_path, json_path


def _render_markdown(report: CouncilReport) -> str:
    """Render a full markdown report."""
    lines: list[str] = []
    source_label = "YouTube" if report.council_type == CouncilSource.YOUTUBE else "X (Twitter)"
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Header
    lines.append(f"# {source_label} Council Report")
    lines.append("")
    lines.append(f"**Session**: {report.session_id}")
    lines.append(f"**Date**: {date_str}")
    lines.append(f"**Period**: Last {report.period_hours} hours")
    lines.append(f"**Sources processed**: {report.sources_processed}")
    if report.total_duration_hours > 0:
        lines.append(f"**Total content duration**: {report.total_duration_hours:.1f} hours")
    lines.append("")

    # Executive summary
    lines.append("---")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(report.summary or "_No summary generated._")
    lines.append("")

    # Insights
    if report.insights:
        lines.append("---")
        lines.append("")
        lines.append("## Key Insights")
        lines.append("")
        for i, insight in enumerate(report.insights, 1):
            confidence_bar = "█" * int(insight.confidence * 10) + "░" * (
                10 - int(insight.confidence * 10)
            )
            lines.append(f"### {i}. {insight.title}")
            lines.append("")
            lines.append(
                f"**Category**: {insight.category.value} | **Confidence**: {confidence_bar} {insight.confidence:.0%}"  # noqa: E501
            )
            lines.append("")
            lines.append(insight.description)
            if insight.tags:
                lines.append("")
                lines.append(f"**Tags**: {', '.join(f'`{t}`' for t in insight.tags)}")
            if insight.actionable and insight.action_suggestion:
                lines.append("")
                lines.append(f"**Action**: {insight.action_suggestion}")
            lines.append("")

    # Source details
    if report.videos:
        lines.append("---")
        lines.append("")
        lines.append("## Videos Processed")
        lines.append("")
        for v in report.videos:
            dur_m = v.duration_seconds // 60
            lines.append(f"### {v.title}")
            lines.append("")
            lines.append(f"- **Channel**: {v.channel}")
            lines.append(f"- **Duration**: {dur_m} min")
            lines.append(f"- **Views**: {v.view_count:,}")
            lines.append(f"- **URL**: {v.url}")
            lines.append(f"- **Uploaded**: {v.upload_date}")
            lines.append("")

    if report.posts:
        lines.append("---")
        lines.append("")
        lines.append("## Posts Analyzed")
        lines.append("")
        # Group by author
        by_author: dict[str, list[XPost]] = {}
        for p in report.posts:
            by_author.setdefault(p.author_handle, []).append(p)
        for handle, posts in sorted(by_author.items()):
            lines.append(f"### @{handle} ({len(posts)} posts)")
            lines.append("")
            for p in posts[:5]:  # Cap at 5 per author in report
                engagement = p.like_count + p.retweet_count + p.reply_count
                preview = p.text[:200].replace("\n", " ")
                lines.append(f"- [{p.created_at}] {preview}... (engagement: {engagement:,})")
            if len(posts) > 5:
                lines.append(f"- _...and {len(posts) - 5} more_")
            lines.append("")

    # Full analysis
    if report.raw_analysis:
        lines.append("---")
        lines.append("")
        lines.append("## Full Analysis")
        lines.append("")
        lines.append(report.raw_analysis)
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append(f"_Generated by NARTIX {source_label} Council | {date_str}_")
    lines.append("_Pipeline: NCL intelligence-scan → Awarebot-FPC_")

    return "\n".join(lines)


_SIGNALS_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_SIGNALS_ROTATE_BACKUPS = 5


def _rotate_signals_file(path: Path) -> None:
    """Rotate signals JSONL when it exceeds the size limit."""
    try:
        if path.exists() and path.stat().st_size > _SIGNALS_FILE_MAX_BYTES:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            rotated = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
            path.rename(rotated)
            # Prune old backups beyond _SIGNALS_ROTATE_BACKUPS
            existing = sorted(path.parent.glob(f"{path.stem}_*{path.suffix}"))
            for old in existing[:-_SIGNALS_ROTATE_BACKUPS]:
                old.unlink(missing_ok=True)
            log.info(f"Rotated {path.name} → {rotated.name}")
    except OSError as e:
        log.warning(f"Signal file rotation failed: {e}")


def _write_signals(report: CouncilReport, date_str: str) -> None:
    """Write processed signals to the Awarebot-FPC signals directory."""
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    signals_file = SIGNALS_DIR / f"signals-{date_str}.jsonl"
    _rotate_signals_file(signals_file)

    signals = []
    seen_signal_ids: set[str] = set()
    for i, insight in enumerate(report.insights):
        # Derive signal ID from content hash so identical insights dedup properly
        # (uuid4 would generate unique IDs every time, defeating dedup)
        content_hash = hashlib.sha256(
            f"{insight.title}:{insight.description}:{insight.category.value}".encode()
        ).hexdigest()[:8]
        signal_id = f"sig-{date_str}-{report.council_type.value}-{content_hash}"
        # Deduplicate: skip any signal whose ID has already been recorded
        if signal_id in seen_signal_ids:
            log.debug(f"Skipping duplicate signal_id={signal_id}")
            continue
        seen_signal_ids.add(signal_id)
        signal = {
            "signal_id": signal_id,
            "source_council": report.council_type.value,
            "session_id": report.session_id,
            "category": insight.category.value,
            "title": insight.title,
            "description": insight.description[:500],
            "importance_score": int(insight.confidence * 100),
            "convergence_tags": insight.tags,
            "timestamp": report.timestamp,
        }
        signals.append(signal)

    # Append to daily signals file (JSONL) — flush after write to minimize
    # data loss window on crash.
    with open(signals_file, "a", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(sig) + "\n")
        f.flush()
        os.fsync(f.fileno())

    log.info(f"Wrote {len(signals)} signals → {signals_file}")


def _write_alerts(report: CouncilReport) -> None:
    """Write high-severity alerts to the alerts directory."""
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)

    high_insights = [i for i in report.insights if i.confidence >= 0.8 and i.actionable]
    for insight in high_insights:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d-%H%M%S") + f"-{now.microsecond:06d}"
        alert = {
            "alert_id": f"alert-{ts}-{report.council_type.value}",
            "source": report.council_type.value,
            "severity": "HIGH" if insight.confidence >= 0.9 else "MEDIUM",
            "category": insight.category.value,
            "title": insight.title,
            "summary": insight.description,
            "recommended_action": insight.action_suggestion or "review",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "acknowledged": False,
        }
        alert_path = ALERTS_DIR / f"{alert['alert_id']}.json"
        alert_tmp = alert_path.with_suffix(".json.tmp")
        alert_tmp.write_text(json.dumps(alert, indent=2))
        alert_tmp.replace(alert_path)
        log.info(f"Alert raised → {alert_path.name}: {insight.title}")


# W13-P2: alerts/ pruner. Before this, ALERTS_DIR grew unbounded — 2,657
# files at the time of the W13 audit (the oldest from mid-May, never cleaned
# up). Called from the autonomous scheduler's chroma_gc loop and on startup.
ALERTS_PRUNE_DAYS = int(os.getenv("NCL_ALERTS_PRUNE_DAYS", "14"))


def prune_alerts(max_age_days: int = ALERTS_PRUNE_DAYS) -> dict[str, int]:
    """Delete alert files older than ``max_age_days``.

    Walks ``ALERTS_DIR`` once. Skips ``README.md`` and any non-JSON file.
    Returns a dict with ``scanned``, ``deleted``, ``errors``, ``kept``.
    """
    stats = {"scanned": 0, "deleted": 0, "errors": 0, "kept": 0}
    if not ALERTS_DIR.exists():
        return stats
    cutoff = datetime.now(timezone.utc).timestamp() - max_age_days * 86400
    for entry in ALERTS_DIR.iterdir():
        if not entry.is_file():
            continue
        if not entry.name.endswith(".json"):
            # Preserve README.md and anything else non-JSON.
            continue
        stats["scanned"] += 1
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
                stats["deleted"] += 1
            else:
                stats["kept"] += 1
        except OSError as e:
            stats["errors"] += 1
            log.warning(f"[ALERTS:PRUNE] could not delete {entry.name}: {e}")
    if stats["deleted"]:
        log.info(
            f"[ALERTS:PRUNE] deleted {stats['deleted']} of {stats['scanned']} "
            f"alerts older than {max_age_days}d (kept {stats['kept']})"
        )
    return stats
