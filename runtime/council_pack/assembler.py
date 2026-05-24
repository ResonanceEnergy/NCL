"""
Universal Council Context Assembler
===================================

ONE function — ``assemble_council_pack(...)`` — is called by every council
surface (v1 Delphi-MAD runner, v2 parallel-agent runner, YouTube council, X
council, /council/spawn endpoint, /councils/run). It replaces the per-caller
string concatenation those surfaces used to do by hand.

Responsibilities
----------------
1. Pull retrieval candidates via FusedRetriever (vector + BM25 + entity-graph,
   already authority-weighted).
2. Apply MMR diversity to kill paraphrase echo.
3. Pull the working-context items for stable long-running themes.
4. Tag every candidate with a temporal label ("hot_4h" vs "arc_30d") and
   split the pack into two SEPARATE sections so the model attends to them
   distinctly.
5. Read ``contradicts_index.jsonl`` and surface the conflicts that actually
   intersect this pack into a dedicated CONFLICTS section.
6. Apply the "position trick" — duplicate the top-3 most salient items at
   the very START and very END of the pack to mitigate lost-in-middle.
7. Enforce the 40% utilization cap — total assembled tokens never exceed
   ~40% of the model's context window.
8. If still over the MapReduce trigger (30K tokens), fan out per-section
   Sonnet summarization and merge back into a compressed pack.
9. Apply the learned source-authority adjustment (Beta-Bernoulli) on top of
   the static tier weight so empirically-strong sources beat the static prior.

The return value is a ``CouncilPack`` carrying everything the runner needs:
- A ``prompt_text`` field — the assembled pack as a single multi-section
  string, ready for legacy callers that still take raw text.
- A ``document_blocks`` field — the same evidence rendered as Anthropic
  Citations API document content blocks for callers that have migrated.
- Structured metadata (token estimate, section counts, surfaced conflicts,
  candidate provenance) for write-back + observability.

This module is intentionally LARGE-but-flat. Every piece of behavior is in
one of the helper sub-modules (mmr, contradictions, citations, calibration,
peer_review, write_back) so this file is the orchestrator only.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import logging
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional  # noqa: F401

from .citations import build_citation_documents
from .contradictions import find_relevant_contradictions, render_conflicts_section  # noqa: F401
from .mmr import mmr_select

log = logging.getLogger("ncl.council_pack.assembler")


# ── tuning constants ───────────────────────────────────────────────────────

# Sonnet 4 / 4.6 advertise 200K input context. Anthropic's own research shows
# task accuracy degrades beyond ~40% utilization — the rest of the window has
# to be reserved for the model's reasoning. We hard-cap at 40% to leave a 60%
# scratch budget. Adjust via env if you want to push it.
DEFAULT_MODEL_CONTEXT_TOKENS = int(os.getenv("NCL_COUNCIL_MODEL_CONTEXT", "200000"))
UTILIZATION_CAP_FRACTION = float(os.getenv("NCL_COUNCIL_UTIL_CAP", "0.40"))

# When the assembled pack exceeds this token estimate, run MapReduce
# compression: fan out per-section to Sonnet, summarize, merge.
MAPREDUCE_TRIGGER_TOKENS = int(os.getenv("NCL_COUNCIL_MAPREDUCE_TRIGGER", "30000"))

# Position-trick — duplicate this many top items at the END of the pack
# (top-K already sits naturally at the start).
POSITION_TRICK_DUPLICATE_TOP_N = 3

# Hot/arc temporal split — items newer than this are "hot_4h", everything
# else falls into "arc_30d" (or further-back which we drop).
HOT_WINDOW = timedelta(hours=4)
ARC_WINDOW = timedelta(days=30)

# How many MMR-survivors we want per section by default. The 40% cap will
# trim further if necessary.
DEFAULT_HOT_TOP_K = 8
DEFAULT_ARC_TOP_K = 12
DEFAULT_WORKING_CONTEXT_TOP = 8

# Char-to-token rough conversion. 4 chars/token is the Anthropic guideline
# for English prose and matches the budget_tracker calculation we use elsewhere.
CHARS_PER_TOKEN = 4


# ── data classes ───────────────────────────────────────────────────────────


@dataclass
class PackItem:
    """A single evidence item in the pack — same shape regardless of source."""

    unit_id: str
    content: str
    source: str
    authority_tier: int
    authority_tier_name: str
    static_tier_weight: float
    learned_adjustment: float
    effective_weight: float
    fused_score: float
    mmr_score: Optional[float] = None
    recency_label: str = "arc_30d"  # "hot_4h" | "arc_30d" | "pinned"
    created_at: str = ""
    signal_id: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_brief(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "source": self.source,
            "authority_tier": self.authority_tier_name,
            "effective_weight": round(self.effective_weight, 3),
            "fused_score": round(self.fused_score, 4),
            "recency_label": self.recency_label,
            "content": self.content[:280],
        }


@dataclass
class PackSection:
    label: str
    description: str
    items: list[PackItem] = field(default_factory=list)


@dataclass
class CouncilPack:
    """The structured pack returned by the universal assembler."""

    topic: str
    query: str
    sections: list[PackSection]
    surfaced_conflicts: list[dict]
    prompt_text: str
    document_blocks: list[dict]
    token_estimate: int
    utilization_fraction: float
    model_context_tokens: int
    mapreduce_applied: bool = False
    candidate_count: int = 0
    pack_size_items: int = 0
    notes: list[str] = field(default_factory=list)
    # W8-A1 D1 (2026-05-24): per-pack nonce for the <EVIDENCE-{nonce}> fences
    # that wrap every section body in the rendered prompt. Same nonce for all
    # sections in a single pack (per-section, not per-item), so the runner can
    # emit one matching system-prompt directive.
    evidence_nonce: str = ""

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "query": self.query,
            "section_count": len(self.sections),
            "candidate_count": self.candidate_count,
            "pack_size_items": self.pack_size_items,
            "token_estimate": self.token_estimate,
            "utilization_fraction": round(self.utilization_fraction, 4),
            "model_context_tokens": self.model_context_tokens,
            "mapreduce_applied": self.mapreduce_applied,
            "surfaced_conflicts": [
                {
                    "conflict_id": c.get("conflict_id"),
                    "entity": c.get("entity"),
                    "severity": c.get("severity"),
                }
                for c in self.surfaced_conflicts
            ],
            "sections": [
                {
                    "label": s.label,
                    "items": [i.to_brief() for i in s.items],
                }
                for s in self.sections
            ],
            "notes": self.notes,
        }


# ── helpers ────────────────────────────────────────────────────────────────


def _estimate_tokens(s: str) -> int:
    return max(1, len(s) // CHARS_PER_TOKEN)


def _max_pack_tokens(model_context_tokens: int) -> int:
    return int(model_context_tokens * UTILIZATION_CAP_FRACTION)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _recency_label(created_at: str | None, now: datetime) -> str:
    ts = _parse_ts(created_at)
    if ts is None:
        return "arc_30d"
    age = now - ts
    if age <= HOT_WINDOW:
        return "hot_4h"
    if age <= ARC_WINDOW:
        return "arc_30d"
    return "stale"


def _build_pack_item(raw: dict, now: datetime, learner=None) -> PackItem:
    """Materialize a PackItem from a FusedRetriever dict + working-context item."""
    from ..memory.authority import authority_weight, tier_for_source, AuthorityTier  # noqa: I001

    source = raw.get("source") or ""
    tier_val = raw.get("authority_tier")
    if tier_val is None:
        tier_val = int(tier_for_source(source))
    try:
        tier_name = AuthorityTier(int(tier_val)).name.lower()
    except ValueError:
        tier_name = "raw"
    static_w = authority_weight(int(tier_val))

    learned_adj = 1.0
    if learner is not None:
        try:
            learned_adj = learner.adjustment_for(source)
        except Exception:
            learned_adj = 1.0
    effective = max(0.05, min(1.5, static_w * learned_adj))

    return PackItem(
        unit_id=str(raw.get("unit_id") or raw.get("item_id") or ""),
        content=raw.get("content") or "",
        source=source,
        authority_tier=int(tier_val),
        authority_tier_name=tier_name,
        static_tier_weight=static_w,
        learned_adjustment=learned_adj,
        effective_weight=effective,
        fused_score=float(raw.get("fused_score") or raw.get("salience_score") or 0.0),
        mmr_score=raw.get("mmr_score"),
        recency_label=_recency_label(raw.get("created_at"), now),
        created_at=str(raw.get("created_at") or ""),
        signal_id=raw.get("signal_id"),
        tags=list(raw.get("tags") or []),
        metadata=dict(raw.get("metadata") or {}),
    )


def _render_section_body(section: PackSection, *, evidence_nonce: str = "") -> str:
    """Render the body of a single section.

    W8-A1 D1: when ``evidence_nonce`` is supplied, the rendered body is wrapped
    in ``<EVIDENCE-{nonce}>...</EVIDENCE-{nonce}>`` fences so untrusted member
    models (Grok / Gemini / GPT / Perplexity) can be instructed via a single
    system-prompt directive (see ``runners.enrich_prompt_with_pack``) to treat
    fenced text as DATA, never instructions. The Anthropic chair already gets
    citation-grade isolation via the Citations API document_blocks path.
    """
    if not section.items:
        inner = "(no items in this section)"
    else:
        lines: list[str] = []
        for i, it in enumerate(section.items, start=1):
            head = (
                f"{i}. [{it.authority_tier_name.upper()} w={it.effective_weight:.2f}] "
                f"<{it.unit_id or 'no-id'}> {it.source}"
            )
            if it.recency_label:
                head += f" ({it.recency_label})"
            lines.append(head)
            body = (it.content or "").strip()
            if body:
                lines.append(body[:1600])
            lines.append("")
        inner = "\n".join(lines).rstrip()

    if evidence_nonce:
        return f"<EVIDENCE-{evidence_nonce}>\n{inner}\n</EVIDENCE-{evidence_nonce}>"
    return inner


def _render_prompt_text(pack: CouncilPack) -> str:
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"COUNCIL CONTEXT PACK — topic: {pack.topic}")
    out.append(f"query: {pack.query}")
    out.append(
        f"sections: {len(pack.sections)} | items: {pack.pack_size_items} | "
        f"tokens≈{pack.token_estimate} ({pack.utilization_fraction:.1%} of {pack.model_context_tokens}-tok window)"  # noqa: E501
    )
    if pack.mapreduce_applied:
        out.append("** MapReduce compression applied: per-section Sonnet summaries below. **")
    if pack.notes:
        out.append("notes: " + " | ".join(pack.notes))
    out.append("=" * 72)
    out.append("")

    for section in pack.sections:
        out.append(f"--- {section.label} ---")
        if section.description:
            out.append(section.description)
        out.append(_render_section_body(section, evidence_nonce=pack.evidence_nonce))
        out.append("")
    return "\n".join(out)


# ── MapReduce compression ─────────────────────────────────────────────────


async def _summarize_section_mapreduce(
    section: PackSection, *, max_tokens_out: int = 1200
) -> PackSection:  # noqa: E501
    """Run Sonnet summarization over a single section.

    The summary REPLACES the section's items with a single synthetic PackItem
    carrying the summary text. We keep the section label / description.

    On any failure (no API key, budget exhausted, parse error) we fall back
    to a deterministic truncation: keep top items by effective_weight until
    we fit ``max_tokens_out`` tokens.
    """
    if not section.items:
        return section

    section_body = _render_section_body(section)
    if _estimate_tokens(section_body) <= max_tokens_out:
        return section

    prompt = (
        "You are summarizing one section of a council evidence pack. "
        "Compress it to ~1000 tokens. Preserve: ticker symbols, named entities, "
        "numeric claims, source attributions, and any conflict between items. "
        "Drop: stylistic prose, hedging, duplicated framing.\n\n"
        f"=== {section.label} ===\n"
        f"{section.description}\n\n"
        f"{section_body}"
    )

    summary_text: Optional[str] = None
    try:
        # W6-D: routed through runtime.llm facade. Budget gate, retries,
        # circuit breaker, and cost recording all live in the facade.
        # The ANTHROPIC_API_KEY check is preserved as a fast-path return
        # so we don't spin up the facade just to fail.
        if os.getenv("ANTHROPIC_API_KEY"):
            from ..llm import chat as _llm_chat

            result = await _llm_chat(
                model="claude-sonnet-4-20250514",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens_out,
                temperature=0.7,
                budget_key="anthropic",
                timeout_s=30.0,
            )
            summary_text = (result.text or "").strip()
            if not summary_text:
                log.warning("[MAPREDUCE] empty response on section %s", section.label)
    except Exception as exc:
        log.warning(
            "[MAPREDUCE] section %s failed (%s) — falling back to truncation", section.label, exc
        )  # noqa: E501

    if not summary_text:
        # Deterministic fallback: keep highest-weight items until we fit.
        ranked = sorted(section.items, key=lambda i: i.effective_weight, reverse=True)
        kept: list[PackItem] = []
        running_tokens = 0
        for it in ranked:
            t = _estimate_tokens(it.content)
            if running_tokens + t > max_tokens_out:
                break
            kept.append(it)
            running_tokens += t
        section.items = kept
        return section

    # Replace items with a synthetic summary PackItem.
    section.items = [
        PackItem(
            unit_id=f"summary:{section.label}",
            content=summary_text,
            source=f"mapreduce:{section.label}",
            authority_tier=60,
            authority_tier_name="brain",
            static_tier_weight=0.6,
            learned_adjustment=1.0,
            effective_weight=0.6,
            fused_score=0.0,
            recency_label="arc_30d",
        )
    ]
    return section


async def _apply_mapreduce(
    sections: list[PackSection], max_tokens_total: int
) -> tuple[list[PackSection], bool]:  # noqa: E501
    """Compress sections until they fit ``max_tokens_total``.

    Returns ``(sections, applied_flag)``.
    """
    current = sum(_estimate_tokens(_render_section_body(s)) for s in sections)
    if current <= max_tokens_total:
        return sections, False

    log.info("[MAPREDUCE] pack at %d tokens > trigger; compressing in parallel", current)
    # Run all section summarizations in parallel for speed.
    coros = []
    for s in sections:
        # Allocate proportional budget per section, floor 800.
        share = max(800, int(max_tokens_total / max(1, len(sections))))
        coros.append(_summarize_section_mapreduce(s, max_tokens_out=share))
    # One failed summarization must not nuke the whole council pack — fall
    # back to the original (uncompressed) section so the pack still ships.
    raw = await asyncio.gather(*coros, return_exceptions=True)
    summarized: list[PackSection] = []
    for idx, r in enumerate(raw):
        if isinstance(r, Exception):
            log.warning("[GATHER] mapreduce_section task %d failed: %s", idx, r)
            summarized.append(sections[idx])
            continue
        summarized.append(r)
    return summarized, True


# ── 40% utilization cap (deterministic trim) ───────────────────────────────


def _enforce_utilization_cap(
    sections: list[PackSection], max_tokens_total: int
) -> tuple[list[PackSection], bool]:  # noqa: E501
    """Hard-trim sections until they fit ``max_tokens_total`` by dropping the
    LOWEST-effective-weight items first.

    Returns ``(sections, was_trimmed)``.
    """

    def _total() -> int:
        return sum(_estimate_tokens(_render_section_body(s)) for s in sections)

    trimmed = False
    while _total() > max_tokens_total:
        # Find the section with the most items and drop its lowest-weight item.
        target: Optional[PackSection] = None
        for s in sections:
            if not s.items:
                continue
            if target is None or len(s.items) > len(target.items):
                target = s
        if target is None or not target.items:
            break
        target.items.sort(key=lambda i: i.effective_weight, reverse=True)
        target.items.pop()  # drop lowest-weight
        trimmed = True
    return sections, trimmed


# ── public entry point ────────────────────────────────────────────────────


async def assemble_council_pack(
    *,
    topic: str,
    query: str,
    fused_retriever,
    working_context=None,
    learner=None,
    hot_top_k: int = DEFAULT_HOT_TOP_K,
    arc_top_k: int = DEFAULT_ARC_TOP_K,
    working_context_top: int = DEFAULT_WORKING_CONTEXT_TOP,
    candidate_pool: int = 50,
    model_context_tokens: int = DEFAULT_MODEL_CONTEXT_TOKENS,
    enable_mapreduce: bool = True,
    enable_position_trick: bool = True,
    mmr_lambda: float = 0.7,
    contradicts_lookback_days: int = 7,
) -> CouncilPack:
    """Assemble the universal council context pack.

    Parameters
    ----------
    topic : str
        Human-facing council topic (used in section headers + conflict matching).
    query : str
        Retrieval query for the FusedRetriever. Often a more concrete
        keyword string than the topic.
    fused_retriever : FusedRetriever
        Required. We don't try to bootstrap one — caller owns lifecycle.
    working_context : DailyContextWindow, optional
        Pulls today's pinned + high-salience items if provided.
    learner : SourceAuthorityLearner, optional
        Applies Beta-Bernoulli adjustment to each candidate's effective
        weight. If None, learned_adjustment defaults to 1.0.
    hot_top_k, arc_top_k : int
        MMR survivors per temporal section.
    working_context_top : int
        Items pulled from working_context (always present if available).
    candidate_pool : int, default 50
        How many candidates to ask the retriever for before MMR.
    model_context_tokens : int
        Total context window of the downstream model. 40% cap is applied.
    enable_mapreduce : bool, default True
    enable_position_trick : bool, default True
    mmr_lambda : float, default 0.7
        Relevance vs diversity trade-off in MMR.
    contradicts_lookback_days : int, default 7

    Returns
    -------
    CouncilPack
        Structured pack ready to drop into any council surface.
    """
    notes: list[str] = []
    now = datetime.now(timezone.utc)

    # 1) Retrieve from FusedRetriever.
    try:
        raw_candidates = await fused_retriever.retrieve(query=query, top_k=candidate_pool)
    except Exception as exc:
        log.warning("[ASSEMBLER] fused retrieve failed: %s", exc)
        raw_candidates = []
    notes.append(f"retrieved={len(raw_candidates)}")

    # 2) Apply MMR diversity, separately keep enough headroom for both
    #    temporal sections. We pull MMR survivors generously and bucket
    #    them by recency next.
    mmr_total = min(len(raw_candidates), max(hot_top_k + arc_top_k, 8) * 2)
    mmr_survivors = mmr_select(
        raw_candidates,
        top_k=mmr_total,
        lambda_=mmr_lambda,
    )
    notes.append(f"mmr={len(mmr_survivors)}")

    # 3) Materialize PackItems with the learned authority adjustment.
    items = [_build_pack_item(r, now, learner=learner) for r in mmr_survivors]

    # 4) Bucket into HOT vs ARC by recency label. Drop "stale".
    hot_items = [i for i in items if i.recency_label == "hot_4h"]
    arc_items = [i for i in items if i.recency_label == "arc_30d"]

    # Pick top-K per bucket by effective_weight (already MMR-diversified).
    hot_items.sort(key=lambda i: i.effective_weight, reverse=True)
    arc_items.sort(key=lambda i: i.effective_weight, reverse=True)
    hot_items = hot_items[:hot_top_k]
    arc_items = arc_items[:arc_top_k]

    # 5) Working context items (always present if available).
    wc_items: list[PackItem] = []
    if working_context is not None:
        try:
            wc_text_dict = getattr(working_context, "get_current", lambda: None)()
            if wc_text_dict is not None:
                # ``DailyContext`` returned — iterate items.
                for ci in (getattr(wc_text_dict, "items", []) or [])[:working_context_top]:
                    raw = {
                        "unit_id": ci.item_id,
                        "content": ci.content,
                        "source": ci.source,
                        "authority_tier": (ci.metadata or {}).get("authority_tier"),
                        "fused_score": ci.salience_score,
                        "created_at": ci.created_at,
                        "tags": ci.tags,
                        "metadata": ci.metadata,
                        "signal_id": (ci.metadata or {}).get("signal_id"),
                    }
                    pi = _build_pack_item(raw, now, learner=learner)
                    pi.recency_label = "pinned" if ci.pinned else pi.recency_label
                    wc_items.append(pi)
        except Exception as exc:
            log.warning("[ASSEMBLER] working_context pull failed: %s", exc)
    notes.append(f"working_ctx={len(wc_items)}")

    # 6) Build the sections in their final order. CONFLICTS first
    #    (chair must address before round 1), then HOT, then ARC, then
    #    WORKING CONTEXT. The position-trick footer is added last.
    pack_unit_ids = [it.unit_id for it in hot_items + arc_items + wc_items if it.unit_id]
    conflicts = find_relevant_contradictions(
        pack_unit_ids=pack_unit_ids,
        topic=topic,
        query=query,
        lookback_days=contradicts_lookback_days,
    )
    notes.append(f"conflicts={len(conflicts)}")

    sections: list[PackSection] = []
    if conflicts:
        # One PackItem per conflict so each lands as its own evidence row.
        # We use render_conflicts_section style on a per-conflict basis so
        # the chair sees the same "[SEV] entity — polarity (sources). Reason."
        # shape.
        def _one_conflict_text(c: dict) -> str:
            sev = (c.get("severity") or "medium").upper()
            entity = c.get("entity") or "(unknown)"
            # contradicts_index.jsonl in production sometimes stores
            # polarities as ints (1/-1) and sources as mixed types — coerce
            # everything to str() defensively so we never crash on real data.
            polarities = [str(p) for p in (c.get("polarities") or [])]
            sources = [str(s) for s in (c.get("sources") or [])]
            why = ", ".join(str(x) for x in (c.get("surfaced_because") or [])) or "in scope"
            head = (
                f"[{sev}] {entity} — {' vs '.join(polarities) or '(polarity unknown)'} "
                f"({', '.join(sources[:4]) or 'sources unknown'}). "
                f"Surfaced because: {why}."
            )
            reason = str(c.get("reason") or "").strip()
            if reason:
                head += f"\nReason on file: {reason[:280]}"
            return head

        sections.append(
            PackSection(
                label="CONFLICTS (address in round 1)",
                description=(
                    "Open contradictions in the corpus that intersect this pack. "
                    "Each council member MUST take an explicit position on each "
                    "conflict before issuing a recommendation."
                ),
                items=[
                    PackItem(
                        unit_id=f"conflict:{c.get('conflict_id') or i}",
                        content=_one_conflict_text(c),
                        source=f"contradicts_index:{c.get('severity')}",
                        authority_tier=80,
                        authority_tier_name="council",
                        static_tier_weight=0.8,
                        learned_adjustment=1.0,
                        effective_weight=0.8,
                        fused_score=1.0,
                        recency_label="hot_4h",
                        metadata={"conflict": c},
                    )
                    for i, c in enumerate(conflicts, start=1)
                ],
            )
        )

    sections.append(
        PackSection(
            label="LAST 4H HOT",
            description="Recent items (≤ 4h old). Treat as situational, fast-changing context.",
            items=hot_items,
        )
    )
    sections.append(
        PackSection(
            label="30D NARRATIVE ARC",
            description="Persistent items spanning the last 30 days. Use for trend / regime context.",  # noqa: E501
            items=arc_items,
        )
    )
    if wc_items:
        sections.append(
            PackSection(
                label="WORKING CONTEXT",
                description="Today's curated working context (NATRIX pinned + high-salience items).",  # noqa: E501
                items=wc_items,
            )
        )

    # 7) Position trick first — duplicate top-3 most salient items as a
    #    trailing EMPHASIS section. We pick from ALL items (not just within
    #    one section) so the final emphasis reflects whatever ended up at
    #    the top globally. Done BEFORE the cap so the cap accounts for the
    #    duplicated content; otherwise emphasis can push us back over budget.
    if enable_position_trick:
        all_items = [i for s in sections for i in s.items if not i.unit_id.startswith("conflict:")]
        all_items.sort(key=lambda i: i.effective_weight, reverse=True)
        emphasis = all_items[:POSITION_TRICK_DUPLICATE_TOP_N]
        if emphasis:
            sections.append(
                PackSection(
                    label="EMPHASIS (do not skim)",
                    description=(
                        "Top items duplicated here as the closing block — they appear "
                        "in their original section above too. Long-context models attend "
                        "best to the START and the END of the input."
                    ),
                    items=list(emphasis),
                )
            )
            notes.append("position_trick")

    # 8) Apply 40% utilization cap (deterministic trim) — accounts for the
    #    emphasis section now that it's been appended.
    max_tokens = _max_pack_tokens(model_context_tokens)
    sections, trimmed = _enforce_utilization_cap(sections, max_tokens)
    if trimmed:
        notes.append("util_cap_trim")

    # 9) MapReduce if still over the trigger.
    mapreduce_applied = False
    pre_mr_tokens = sum(_estimate_tokens(_render_section_body(s)) for s in sections)
    if enable_mapreduce and pre_mr_tokens > MAPREDUCE_TRIGGER_TOKENS:
        sections, mapreduce_applied = await _apply_mapreduce(sections, max_tokens)
        if mapreduce_applied:
            notes.append("mapreduce")

    # 10) Second-pass cap after MapReduce in case the summaries are still
    #     over budget (defensive — Sonnet sometimes returns longer than asked).
    if mapreduce_applied:
        sections, _trimmed2 = _enforce_utilization_cap(sections, max_tokens)
        if _trimmed2:
            notes.append("util_cap_trim_post_mr")

    # 10) Render final prompt + document blocks.
    all_pack_items = [i for s in sections for i in s.items]
    document_blocks = build_citation_documents(
        [
            {
                "unit_id": it.unit_id,
                "source": it.source,
                "content": it.content,
                "authority_tier_name": it.authority_tier_name,
                "recency_label": it.recency_label,
            }
            for it in all_pack_items
        ]
    )

    # W8-A1 D1: per-pack nonce for evidence fences. 16 hex chars is plenty;
    # we just need the model to be unable to guess and emit a closing tag
    # from within an evidence body.
    evidence_nonce = secrets.token_hex(8)

    # Two-pass render so the header's token / utilization line reflects the
    # FINAL pack, not zero.
    pack = CouncilPack(
        topic=topic,
        query=query,
        sections=sections,
        surfaced_conflicts=conflicts,
        prompt_text="",
        document_blocks=document_blocks,
        token_estimate=0,
        utilization_fraction=0.0,
        model_context_tokens=model_context_tokens,
        mapreduce_applied=mapreduce_applied,
        candidate_count=len(raw_candidates),
        pack_size_items=len(all_pack_items),
        notes=notes,
        evidence_nonce=evidence_nonce,
    )
    # Pass 1 — estimate body tokens without header.
    body_estimate = sum(_estimate_tokens(_render_section_body(s)) for s in sections)
    pack.token_estimate = body_estimate
    pack.utilization_fraction = body_estimate / max(1, model_context_tokens)
    # Pass 2 — render full prompt with the accurate token line.
    pack.prompt_text = _render_prompt_text(pack)
    # Final token estimate of the rendered text (header inflates by ~30 tokens).
    pack.token_estimate = _estimate_tokens(pack.prompt_text)
    pack.utilization_fraction = pack.token_estimate / max(1, model_context_tokens)

    log.info(
        "[ASSEMBLER] topic=%r items=%d tokens≈%d util=%.1f%% mr=%s conflicts=%d",
        topic[:60],
        pack.pack_size_items,
        pack.token_estimate,
        pack.utilization_fraction * 100,
        mapreduce_applied,
        len(conflicts),
    )

    # Memory-budget telemetry — best effort.
    try:
        from ..memory.budget_tracker import record as _bt_record

        await _bt_record(
            "council_pack_assembly",
            pack.token_estimate,
            source=f"council:assembler:{topic[:40]}",
            metadata={
                "items": pack.pack_size_items,
                "candidates": pack.candidate_count,
                "mapreduce": mapreduce_applied,
                "conflicts": len(conflicts),
            },
        )
    except Exception as _bt_err:
        log.debug("[ASSEMBLER] budget telemetry failed: %s", _bt_err)

    return pack


__all__ = [
    "PackItem",
    "PackSection",
    "CouncilPack",
    "assemble_council_pack",
    "DEFAULT_MODEL_CONTEXT_TOKENS",
    "UTILIZATION_CAP_FRACTION",
    "MAPREDUCE_TRIGGER_TOKENS",
]
