"""
Hierarchical 3-tier write-back (Reflexion / H²R)
================================================

Every council session yields three memory artifacts at three depths, written
through the existing AsyncMemoryWriter:

    Tier 1 — GIST            ~1 line. The headline takeaway. Stored as
                              ``memory_type="semantic"`` so it lands in the
                              semantic-typed Chroma collection used by quick
                              "what did the council decide on X" recall.

    Tier 2 — SUMMARY         ~200 tokens. Decision + confidence + the two
                              strongest disconfirmers + the open conflicts
                              the chair flagged. Stored as
                              ``memory_type="decisions"`` (typed Chroma).

    Tier 3 — TRANSCRIPT      Full transcript including round-1 positions,
                              peer-review critiques, chair synthesis, and
                              citation-resolved evidence. Stored as
                              ``memory_type="episodic"``.

Why three and not one
---------------------
The Reflexion / H²R pattern: short queries get answered from the gist (fast,
1-shot recall), medium queries pull the 200-token summary, only deep dive
queries reach the full transcript. Working context can carry the gist + maybe
the summary; full transcripts stay in cold storage but remain searchable.

Stamping
--------
All three are stamped with:
- ``source="council:<type>:<session_id>"`` → COUNCIL authority tier (80).
- ``tags=[session_id, council_type, "council_writeback", "<tier_label>"]``.
- ``metadata={..., "session_id": ..., "writeback_tier": "gist"|"summary"|"transcript",
              "calibrations": [...], "citations": [...], "consensus": ...}``.
"""

from __future__ import annotations  # noqa: I001

import json
import logging
from typing import Any, Optional  # noqa: F401

log = logging.getLogger("ncl.council_pack.write_back")


def _build_gist(session: dict) -> str:
    """One-line gist. Falls back through several fields."""
    for key in ("headline", "consensus", "decision", "summary"):
        v = session.get(key)
        if v:
            line = str(v).strip().splitlines()[0]
            return line[:240]
    return "Council reached no surfaceable conclusion."


def _build_summary(session: dict, max_chars: int = 1400) -> str:
    """~200-token plain-text summary with structured headline."""
    parts: list[str] = []

    topic = session.get("topic")
    if topic:
        parts.append(f"Topic: {topic}")

    consensus = session.get("consensus") or session.get("decision")
    if consensus:
        parts.append(f"Consensus: {consensus}")

    confidence = session.get("confidence")
    if confidence is not None:
        parts.append(f"Council confidence: {confidence:.2f}")

    # Strongest disconfirmers — pull from each member calibration block.
    calibrations = session.get("calibrations") or []
    disconfirmers: list[str] = []
    for cal in calibrations:
        member = cal.get("member") or "member"
        for d in (cal.get("disconfirmers") or [])[:1]:
            disconfirmers.append(f"[{member}] {d}")
        if len(disconfirmers) >= 3:
            break
    if disconfirmers:
        parts.append("Disconfirmers:\n- " + "\n- ".join(disconfirmers[:3]))

    # Conflicts the chair surfaced.
    conflicts = session.get("surfaced_conflicts") or []
    if conflicts:
        names = [c.get("entity") or "(unknown)" for c in conflicts[:3]]
        parts.append("Open conflicts addressed: " + ", ".join(names))

    # Cited unit ids — proof of grounding.
    citations = session.get("citations") or []
    if citations:
        cited_ids = []
        for c in citations[:5]:
            t = c.get("doc_title")
            if t:
                cited_ids.append(t)
        if cited_ids:
            parts.append("Citations: " + ", ".join(cited_ids))

    body = "\n".join(parts)
    return body[:max_chars]


def _build_transcript(session: dict, max_chars: int = 60000) -> str:
    """Full transcript dump — JSON-pretty so downstream tools can re-parse."""
    try:
        return json.dumps(session, indent=2, default=str)[:max_chars]
    except Exception:
        return str(session)[:max_chars]


async def write_back_council(
    async_writer,
    session: dict,
    council_type: str = "delphi_mad",
) -> dict[str, str]:
    """Persist a 3-tier write-back for the council session via AsyncWriter.

    Parameters
    ----------
    async_writer : AsyncMemoryWriter
        Must expose ``enqueue(WriteRequest)``.
    session : dict
        The council session payload. Recognized keys (all optional except
        ``session_id``): ``session_id, topic, consensus, decision, headline,
        summary, confidence, calibrations, surfaced_conflicts, citations,
        rounds, members``.
    council_type : str, default "delphi_mad"

    Returns
    -------
    dict[str, str]
        ``{"gist": "<text>", "summary": "<text>", "transcript_len": <int>}``
        — useful for callers that want to log the artifacts they just wrote.
    """
    session_id = session.get("session_id") or "unknown"

    # Lazy import — async_writer module pulls in cost_tracker which is heavy.
    try:
        from ..memory.async_writer import WriteRequest
    except Exception:
        from runtime.memory.async_writer import WriteRequest  # type: ignore

    gist = _build_gist(session)
    summary = _build_summary(session)
    transcript = _build_transcript(session)

    base_source = f"council:{council_type}:{session_id}"
    base_tags = [str(session_id), council_type, "council_writeback"]

    common_meta: dict[str, Any] = {
        "session_id": session_id,
        "council_type": council_type,
        "confidence": session.get("confidence"),
        "calibrations_count": len(session.get("calibrations") or []),
        "citations_count": len(session.get("citations") or []),
    }

    # Tier 1 — GIST -----------------------------------------------------------
    await async_writer.enqueue(
        WriteRequest(
            content=gist,
            source=base_source,
            importance=85.0,
            memory_type="semantic",
            tags=base_tags + ["gist"],
            metadata={**common_meta, "writeback_tier": "gist"},
        )
    )

    # Tier 2 — SUMMARY --------------------------------------------------------
    await async_writer.enqueue(
        WriteRequest(
            content=summary,
            source=base_source,
            importance=80.0,
            memory_type="decisions",
            tags=base_tags + ["summary"],
            metadata={**common_meta, "writeback_tier": "summary"},
        )
    )

    # Tier 3 — TRANSCRIPT -----------------------------------------------------
    await async_writer.enqueue(
        WriteRequest(
            content=transcript,
            source=base_source,
            importance=70.0,
            memory_type="episodic",
            tags=base_tags + ["transcript"],
            metadata={**common_meta, "writeback_tier": "transcript"},
        )
    )

    log.info(
        "[WRITEBACK] session=%s council=%s gist=%d summary=%d transcript=%d",
        session_id,
        council_type,
        len(gist),
        len(summary),
        len(transcript),
    )
    return {
        "gist": gist,
        "summary": summary,
        "transcript_len": len(transcript),
    }


__all__ = ["write_back_council"]
