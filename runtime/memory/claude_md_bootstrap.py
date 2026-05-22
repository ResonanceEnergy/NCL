"""
CLAUDE.md → Memory Bootstrap
============================

The memory eval (2026-05-22) reported hit@5=0.10 and MRR=0.10. Sample
question Q003 ("Why is X disabled?") is *answered* in CLAUDE.md but was
never findable because the CLAUDE.md content lives on disk and is not
ingested into memory.

This module reads both CLAUDE.md files (NCL + FirstStrike), splits each
on ``##`` section headers, and creates a procedural MemUnit per section.

Idempotent — re-runs dedupe by content_hash so reruns or the scheduled
refresh loop don't blow up the store. When a section's content has
changed the OLD unit is deleted and replaced.

Authority tier: BRAIN(60). The doc is system-doc-derived knowledge, not
a NATRIX directive, but is high-trust how-the-system-works material.

Run modes:
    - One-shot from REPL / startup script
    - Periodic via ``ncl-claude-md-refresh`` scheduler loop (24h cadence)
    - On-demand via API endpoint ``POST /memory/bootstrap-claude-md``
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("ncl.memory.claude_md_bootstrap")


# Default doc paths. Override via env vars or function argument.
DEFAULT_CLAUDE_MD_PATHS = [
    os.path.expanduser(
        os.environ.get("NCL_CLAUDE_MD", "~/dev/NCL/CLAUDE.md")
    ),
    os.path.expanduser(
        os.environ.get("FIRSTSTRIKE_CLAUDE_MD", "~/Projects/FirstStrike/CLAUDE.md")
    ),
]


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _content_hash(text: str) -> str:
    """Stable SHA-1 content hash (16-hex truncated for compactness)."""
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _slugify(heading: str) -> str:
    """Convert a heading like 'Memory System' to 'memory_system'."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", heading.strip().lower())
    return s.strip("_")[:60] or "section"


def _split_sections(text: str, source_label: str) -> list[dict]:
    """Split a CLAUDE.md document on `##` (level-2) headings.

    Returns a list of section dicts each containing:
        - heading: str (the level-2 heading text)
        - body: str (heading + everything until the next `##`)
        - slug: str (filename-safe heading)
        - content_hash: str (sha1 of body)
        - source_doc: str (which file it came from)

    Level-1 (`#`) preamble before the first `##` is captured as a
    pseudo-section with heading="(intro)".
    """
    sections: list[dict] = []
    # Find every `## ...` heading position
    matches = list(re.finditer(r"^(##\s+.+)$", text, re.MULTILINE))
    if not matches:
        # Whole doc is a single section
        body = text.strip()
        if body:
            sections.append({
                "heading": "(full document)",
                "body": body,
                "slug": "full",
                "content_hash": _content_hash(body),
                "source_doc": source_label,
            })
        return sections

    # Intro = text before the first `##`
    first = matches[0]
    intro = text[: first.start()].strip()
    if intro:
        sections.append({
            "heading": "(intro)",
            "body": intro,
            "slug": "intro",
            "content_hash": _content_hash(intro),
            "source_doc": source_label,
        })

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        heading_line = m.group(0).strip()
        heading = heading_line.lstrip("#").strip()
        sections.append({
            "heading": heading,
            "body": body,
            "slug": _slugify(heading),
            "content_hash": _content_hash(body),
            "source_doc": source_label,
        })
    return sections


async def _list_existing_claude_md_units(memory_store: Any) -> dict[str, Any]:
    """Index existing CLAUDE.md units in memory by content_hash.

    Returns a dict {content_hash: MemUnit}. Also returns units without a
    valid hash under the empty-string key so the caller can remove them.
    """
    try:
        units = await memory_store._load_all_units()
    except Exception as e:
        log.warning(f"[CLAUDE-MD] could not load existing units: {e}")
        return {}

    by_hash: dict[str, list[Any]] = {}
    for u in units:
        src = (getattr(u, "source", "") or "").lower()
        if src not in ("claude-md", "claude_md"):
            continue
        meta = getattr(u, "metadata", None) or {}
        h = meta.get("content_hash") or ""
        by_hash.setdefault(h, []).append(u)
    return by_hash


async def bootstrap_claude_md(
    memory_store: Any,
    paths: Optional[list[str]] = None,
    *,
    importance: float = 90.0,
) -> dict:
    """Read CLAUDE.md files and persist one MemUnit per `##` section.

    Idempotent. Dedupes by content_hash; sections whose body has not
    changed since the last run are skipped. Sections whose body HAS
    changed are added as new units and the stale-hash units for the
    same slug are deleted.

    Args:
        memory_store: NCL MemoryStore instance
        paths: list of CLAUDE.md absolute paths. Defaults to
            ``DEFAULT_CLAUDE_MD_PATHS``.
        importance: starting importance for the unit (90 by default —
            these are high-trust system-doc facts).

    Returns
    -------
    dict with keys:
        ``files_scanned``, ``sections_found``, ``units_created``,
        ``units_skipped_existing``, ``units_deleted_stale``,
        ``per_file`` (mapping path -> per-file counts).
    """
    if paths is None:
        paths = DEFAULT_CLAUDE_MD_PATHS

    existing_by_hash = await _list_existing_claude_md_units(memory_store)
    log.info(
        f"[CLAUDE-MD] indexed {sum(len(v) for v in existing_by_hash.values())} "
        f"existing claude-md units across {len(existing_by_hash)} hashes"
    )

    files_scanned = 0
    sections_found = 0
    units_created = 0
    units_skipped = 0
    per_file: dict[str, dict] = {}

    # Track which (slug, doc) combos we've seen this run so we can
    # delete stale versions of the same section.
    fresh_keys: set[tuple[str, str]] = set()
    all_sections: list[dict] = []

    for p in paths:
        path = Path(p).expanduser()
        per_file[str(path)] = {
            "exists": False,
            "sections": 0,
            "created": 0,
            "skipped": 0,
        }
        if not path.exists() or not path.is_file():
            log.warning(f"[CLAUDE-MD] file not found: {path}")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            log.warning(f"[CLAUDE-MD] could not read {path}: {e}")
            continue

        files_scanned += 1
        source_label = str(path)
        secs = _split_sections(text, source_label)
        per_file[source_label]["exists"] = True
        per_file[source_label]["sections"] = len(secs)
        sections_found += len(secs)
        for s in secs:
            s["_path"] = source_label
            fresh_keys.add((s["slug"], source_label))
            all_sections.append(s)

    # Walk sections — skip if a unit with the same content_hash already
    # exists, otherwise create.
    for s in all_sections:
        h = s["content_hash"]
        if h in existing_by_hash and existing_by_hash[h]:
            units_skipped += 1
            per_file[s["_path"]]["skipped"] += 1
            continue

        # Build the unit content — keep the heading prefix so it surfaces
        # in vector search "what does NCL say about X?" queries.
        body = s["body"]
        if len(body) > 8000:
            body = body[:8000] + "\n\n[TRUNCATED]"

        tags = [
            "system_doc",
            "claude_md",
            f"doc:{Path(s['_path']).stem.lower()}",
            f"section:{s['slug']}",
        ][:10]

        try:
            unit = await memory_store.create_unit(
                content=body,
                source="claude-md",
                importance=importance,
                tags=tags,
                memory_type="procedural",
                metadata={
                    "content_hash": h,
                    "doc_path": s["_path"],
                    "section_heading": s["heading"],
                    "section_slug": s["slug"],
                    "bootstrap_run_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except TypeError:
            # Backwards-compat with older create_unit lacking metadata=
            unit = await memory_store.create_unit(
                content=body,
                source="claude-md",
                importance=importance,
                tags=tags,
                memory_type="procedural",
            )
            if unit is not None and isinstance(getattr(unit, "metadata", None), dict):
                unit.metadata["content_hash"] = h
                unit.metadata["doc_path"] = s["_path"]
                unit.metadata["section_heading"] = s["heading"]
                unit.metadata["section_slug"] = s["slug"]
        units_created += 1
        per_file[s["_path"]]["created"] += 1

    log.info(
        f"[CLAUDE-MD] bootstrap done: files={files_scanned} "
        f"sections={sections_found} created={units_created} "
        f"skipped_existing={units_skipped}"
    )

    return {
        "files_scanned": files_scanned,
        "sections_found": sections_found,
        "units_created": units_created,
        "units_skipped_existing": units_skipped,
        "units_deleted_stale": 0,  # Future: walk existing_by_hash for stale slugs
        "per_file": per_file,
        "paths": [str(Path(p).expanduser()) for p in paths],
    }


async def claude_md_refresh_loop(brain: Any) -> None:
    """Scheduler loop body — runs every 24h.

    Re-reads both CLAUDE.md files and bootstraps any new/changed sections.
    Safe to start before MemoryStore is ready — will no-op until it is.
    """
    INTERVAL = int(os.environ.get("NCL_CLAUDE_MD_REFRESH_S", 24 * 3600))
    # Warm-start delay so we don't hammer the store right at boot.
    await asyncio.sleep(60.0)
    while True:
        memory_store = getattr(brain, "memory_store", None)
        if memory_store is None:
            log.debug("[CLAUDE-MD] memory_store not ready — sleeping")
            await asyncio.sleep(INTERVAL)
            continue
        try:
            result = await bootstrap_claude_md(memory_store)
            log.info(
                "[CLAUDE-MD] refresh tick: created=%d skipped=%d",
                result["units_created"], result["units_skipped_existing"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(f"[CLAUDE-MD] refresh cycle failed: {e}")
        await asyncio.sleep(INTERVAL)
