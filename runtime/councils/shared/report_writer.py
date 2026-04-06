"""
Markdown report writer for council output.

Generates clean .md files from CouncilReport data, formatted for
human reading and Obsidian compatibility. Reports are saved to
NCL/intelligence-scan/signals/ for the Awarebot-FPC pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import CouncilReport, CouncilSource, Insight, VideoMeta, XPost

log = logging.getLogger("ncl.councils.report_writer")

# Default output locations within NCL
NCL_BASE = Path.home() / "Projects" / "NCL"
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

    # Write markdown
    md_path = out / f"{base_name}.md"
    md_content = _render_markdown(report)
    md_path.write_text(md_content, encoding="utf-8")
    log.info(f"Report written → {md_path}")

    # Write JSON
    json_path = out / f"{base_name}.json"
    report.save_json(json_path)
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
    lines.append(f"")
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
            confidence_bar = "█" * int(insight.confidence * 10) + "░" * (10 - int(insight.confidence * 10))
            lines.append(f"### {i}. {insight.title}")
            lines.append(f"")
            lines.append(f"**Category**: {insight.category.value} | **Confidence**: {confidence_bar} {insight.confidence:.0%}")
            lines.append(f"")
            lines.append(insight.description)
            if insight.tags:
                lines.append(f"")
                lines.append(f"**Tags**: {', '.join(f'`{t}`' for t in insight.tags)}")
            if insight.actionable and insight.action_suggestion:
                lines.append(f"")
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
            lines.append(f"")
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
    lines.append(f"_Pipeline: NCL intelligence-scan → Awarebot-FPC_")

    return "\n".join(lines)


def _write_signals(report: CouncilReport, date_str: str) -> None:
    """Write processed signals to the Awarebot-FPC signals directory."""
    SIGNALS_DIR.mkdir(parents=True, exist_ok=True)
    signals_file = SIGNALS_DIR / f"signals-{date_str}.jsonl"

    signals = []
    for i, insight in enumerate(report.insights):
        signal = {
            "signal_id": f"sig-{date_str}-{report.council_type.value}-{i+1:03d}",
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

    # Append to daily signals file (JSONL)
    with open(signals_file, "a", encoding="utf-8") as f:
        for sig in signals:
            f.write(json.dumps(sig) + "\n")

    log.info(f"Wrote {len(signals)} signals → {signals_file}")


def _write_alerts(report: CouncilReport) -> None:
    """Write high-severity alerts to the alerts directory."""
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)

    high_insights = [i for i in report.insights if i.confidence >= 0.8 and i.actionable]
    for insight in high_insights:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
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
        alert_path.write_text(json.dumps(alert, indent=2))
        log.info(f"Alert raised → {alert_path.name}: {insight.title}")
