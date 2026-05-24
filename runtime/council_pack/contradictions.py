"""
Read ``data/memory/contradicts_index.jsonl`` and surface open conflicts that
overlap the council's evidence pack.

The conflict_resolver loop has been writing this index for weeks but nothing
was reading it back at council time. ConRAG / MADAM-RAG show that explicitly
surfacing the *known* disagreements before debate begins dramatically tightens
final consensus — the council spends round 1 adjudicating real disputes
instead of re-discovering them mid-debate.

Surfacing rule
--------------
A contradiction is "relevant" to the current pack if EITHER of its two units
already appears in the pack's evidence list, OR its ``entity`` field matches
any token from the topic / query. We never surface contradictions whose entity
is not present in the conversation — that would just be noise.

Output is a list of dicts ready to render into the PACK_TEMPLATE
``CONFLICTS`` section.
"""

from __future__ import annotations  # noqa: I001

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("ncl.council_pack.contradictions")


def _data_dir() -> Path:
    base = os.environ.get("NCL_BASE") or os.path.expanduser("~/dev/NCL")
    return Path(base) / "data" / "memory"


def _load_recent(index_path: Path, lookback_days: int) -> list[dict]:
    """Stream the contradicts index, return rows from the lookback window."""
    if not index_path.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, lookback_days))
    rows: list[dict] = []
    try:
        with index_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = obj.get("ts") or ""
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts < cutoff:
                        continue
                except (ValueError, TypeError):
                    # Tolerate malformed timestamps — keep the row.
                    pass
                rows.append(obj)
    except Exception as exc:
        log.warning("[CONTRADICTIONS] failed to read %s: %s", index_path, exc)
    return rows


def _tokens(text: str) -> set[str]:
    if not text:
        return set()
    return {t.lower().strip("$#@") for t in text.split() if len(t) >= 3}


def find_relevant_contradictions(
    pack_unit_ids: Iterable[str],
    topic: str,
    query: str,
    lookback_days: int = 7,
    max_results: int = 10,
    index_path: Optional[Path] = None,
) -> list[dict]:
    """Return contradictions overlapping the pack's evidence or topic.

    Parameters
    ----------
    pack_unit_ids : iterable of str
        unit_ids that ARE in the assembled pack. Any contradiction whose
        ``units`` field contains one of these is automatically relevant.
    topic : str
        Council topic — used for entity-token overlap matching.
    query : str
        Retrieval query — also used for token overlap.
    lookback_days : int, default 7
        How far back in the index to consider.
    max_results : int, default 10
        Cap on returned contradictions.
    index_path : Path, optional
        Override for tests. Defaults to ``$NCL_BASE/data/memory/contradicts_index.jsonl``.

    Returns
    -------
    list[dict]
        Each dict carries: ``conflict_id, entity, severity, units, sources,
        polarities, importances, reason, surfaced_because`` (matched via
        ``unit_in_pack`` or ``entity_in_topic``).
    """
    idx = index_path or (_data_dir() / "contradicts_index.jsonl")
    rows = _load_recent(idx, lookback_days)
    if not rows:
        return []

    pack_set = {str(u) for u in (pack_unit_ids or [])}
    topic_q_tokens = _tokens(f"{topic} {query}")

    relevant: list[dict] = []
    for row in rows:
        units = [str(u) for u in row.get("units") or []]
        entity = (row.get("entity") or "").strip()

        because: list[str] = []
        if pack_set and any(u in pack_set for u in units):
            because.append("unit_in_pack")
        if entity:
            ent_tokens = _tokens(entity)
            if ent_tokens and (ent_tokens & topic_q_tokens):
                because.append("entity_in_topic")

        if not because:
            continue

        relevant.append(
            {
                "conflict_id": row.get("conflict_id"),
                "ts": row.get("ts"),
                "entity": entity,
                "severity": row.get("severity") or "medium",
                "units": units,
                "sources": row.get("sources") or [],
                "polarities": row.get("polarities") or [],
                "importances": row.get("importances") or [],
                "reason": row.get("reason") or "",
                "surfaced_because": because,
            }
        )

    # Critical first, then high, then by recency. ISO timestamps sort
    # lexically — invert by sorting the negative form: pick a max-string
    # sentinel so missing-ts rows land last.
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def _sort_key(c: dict) -> tuple:
        sev = severity_rank.get(str(c.get("severity") or "medium").lower(), 4)
        # Inverse-lex hack: bigger ts -> smaller sort key.
        ts = str(c.get("ts") or "")
        # Sort tuple by (sev asc, ts desc) — convert ts desc via tuple of
        # negated codepoints. Simpler: sort, then reverse stably within sev.
        return (sev, ts)

    relevant.sort(key=_sort_key)
    # Second pass: stable secondary sort to put later ts first within sev.
    relevant.sort(key=lambda c: str(c.get("ts") or ""), reverse=True)
    relevant.sort(key=lambda c: severity_rank.get(
        str(c.get("severity") or "medium").lower(), 4
    ))
    return relevant[: max(0, max_results)]


def render_conflicts_section(conflicts: list[dict]) -> str:
    """Format conflicts into the CONFLICTS pack-section body."""
    if not conflicts:
        return "(no open contradictions intersect this pack)"

    lines: list[str] = []
    for i, c in enumerate(conflicts, start=1):
        entity = c.get("entity") or "(unknown entity)"
        sev = (c.get("severity") or "medium").upper()
        # Real contradicts_index rows in production sometimes carry int
        # polarities (1/-1) and mixed-type sources — coerce everything to
        # str so we don't crash on a 'join' against int items.
        polarities = [str(p) for p in (c.get("polarities") or [])]
        sources = [str(s) for s in (c.get("sources") or [])]
        reason = str(c.get("reason") or "").strip()
        why = ", ".join(str(x) for x in (c.get("surfaced_because") or [])) or "in scope"

        pol_summary = " vs ".join(polarities) if polarities else "(polarity unknown)"
        src_summary = ", ".join(sources[:4]) if sources else "(sources unknown)"

        lines.append(
            f"{i}. [{sev}] {entity} — {pol_summary} ({src_summary}). "
            f"Surfaced because: {why}."
        )
        if reason:
            lines.append(f"   Reason on file: {reason[:240]}")
    return "\n".join(lines)


__all__ = ["find_relevant_contradictions", "render_conflicts_section"]
