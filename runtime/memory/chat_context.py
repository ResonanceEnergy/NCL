"""
Chat context injector — Loop 1 of the NATRIX memory swarm.

Pure-retrieval helper that builds a formatted context block to prepend to
the /chat system prompt. Pulls from three sources:

  1. Working Context (top-N by salience)
  2. Recent same-session chat turns (memory units tagged with this session)
  3. Top relevant memories (semantic search on the incoming message)

The output is a single string of <= ~4000 tokens (~16k chars). Fully
defensive: any internal failure falls through to an empty string so the
chat path stays alive.

This module performs NO LLM calls — it is pure retrieval against
MemoryStore + DailyContextWindow. The only cost-tracker interaction is
an optional budget check on the *upstream* anthropic chat call, exposed
via `precheck_anthropic_budget()`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

log = logging.getLogger("ncl.memory.chat_context")

# Hard cap — total characters of the assembled block.
# ~4 chars per token → 16_000 chars ≈ 4_000 tokens.
MAX_CONTEXT_CHARS = 16_000

# Per-section caps (chars) — sum stays well under MAX_CONTEXT_CHARS so headers
# + spacing fit. Working context dominates because it is the curated daily view.
WORKING_CTX_BUDGET = 7_000
SESSION_BUDGET = 4_000
RELEVANT_BUDGET = 4_000

# Per-item content trim
WORKING_CTX_ITEM_TRIM = 220
SESSION_ITEM_TRIM = 400
RELEVANT_ITEM_TRIM = 240

# Recall windows
SESSION_LOOKBACK_HOURS = 24
SESSION_MAX_MESSAGES = 5
WORKING_CTX_MAX_ITEMS = 10
RELEVANT_MAX_MEMORIES = 3
RELEVANT_IMPORTANCE_THRESHOLD = 40.0


def _trim(text: str, limit: int) -> str:
    """Trim text to `limit` chars, appending an ellipsis when truncated."""
    if not text:
        return ""
    text = text.replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _humanize_age(then: Optional[datetime]) -> str:
    """Return a short human-readable age (e.g. '2h ago', '3 days ago')."""
    if then is None:
        return "?"
    now = datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    delta = now - then
    secs = max(0, int(delta.total_seconds()))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86_400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86_400} days ago"


def _is_chat_unit(unit: Any) -> bool:
    """True if this memory unit looks like a stored chat turn."""
    src = getattr(unit, "source", "") or ""
    return src in ("first-strike-chat", "brain-chat-response")


def _format_chat_unit(unit: Any) -> str:
    """Format one stored chat turn into a single readable line."""
    src = getattr(unit, "source", "") or ""
    created = getattr(unit, "created_at", None)
    age = _humanize_age(created)
    content = getattr(unit, "content", "") or ""

    # Stored as "Chat from FirstStrike: ..." / "Brain response: ..." —
    # strip those prefixes for cleaner replay.
    speaker = "NATRIX" if src == "first-strike-chat" else "Brain"
    for prefix in ("Chat from FirstStrike:", "Brain response:"):
        if content.startswith(prefix):
            content = content[len(prefix):].strip()
            break

    return f"{speaker} ({age}): {_trim(content, SESSION_ITEM_TRIM)}"


# ── Section builders ──────────────────────────────────────────────────────

def _build_working_context_section(working_ctx) -> tuple[str, int, list[str]]:
    """
    Pull top-N working context items by salience.

    Returns (rendered_text, item_count, item_ids).
    `item_ids` is returned so the caller can mark them accessed in one batch.
    """
    item_ids: list[str] = []
    if working_ctx is None:
        return "", 0, item_ids

    try:
        current = working_ctx.get_current()
    except Exception as e:
        log.debug(f"[CHAT-CTX] working_context.get_current failed: {e}")
        return "", 0, item_ids

    if not current or not getattr(current, "items", None):
        return "", 0, item_ids

    # Items are kept sorted by salience_score desc when assembled, but we sort
    # defensively in case external mutators (pin/promote) disrupted order.
    items = sorted(
        current.items,
        key=lambda i: getattr(i, "salience_score", 0.0),
        reverse=True,
    )[:WORKING_CTX_MAX_ITEMS]

    if not items:
        return "", 0, item_ids

    lines = ["### Working Context (top salience):"]
    used = len(lines[0])
    rendered = 0
    for it in items:
        content = getattr(it, "content", "") or ""
        salience = getattr(it, "salience_score", 0.0)
        pinned = " [PINNED]" if getattr(it, "pinned", False) else ""
        line = f"- {_trim(content, WORKING_CTX_ITEM_TRIM)} (salience={salience:.2f}){pinned}"
        if used + len(line) + 1 > WORKING_CTX_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
        rendered += 1
        iid = getattr(it, "item_id", None)
        if iid:
            item_ids.append(iid)

    if rendered == 0:
        return "", 0, item_ids
    return "\n".join(lines), rendered, item_ids


async def _build_session_history_section(
    memory_store, session_id: str
) -> tuple[str, int]:
    """
    Pull the last N chat turns for this session (within lookback window).

    Looks up units carrying the `session:<id>` tag we add at write time.
    Falls back to a broader `chat` tag scan + per-unit filter when no
    session_id is provided (rare; callers should pass one).
    """
    if memory_store is None or not session_id:
        return "", 0

    tag_filter = [f"session:{session_id}"]
    try:
        units = await memory_store.search_units(
            tags=tag_filter,
            importance_threshold=0.0,
            days_back=1,
        )
    except Exception as e:
        log.debug(f"[CHAT-CTX] session search_units failed: {e}")
        return "", 0

    # Keep only the chat-tagged units in case other systems wrote with the
    # same session tag, then order chronologically (oldest → newest).
    chat_units = [u for u in units if _is_chat_unit(u)]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=SESSION_LOOKBACK_HOURS)
    fresh: list[Any] = []
    for u in chat_units:
        created = getattr(u, "created_at", None)
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created >= cutoff:
            fresh.append(u)

    fresh.sort(key=lambda u: getattr(u, "created_at"))
    # Keep the last N by recency, then re-emit chronologically.
    fresh = fresh[-SESSION_MAX_MESSAGES:]

    if not fresh:
        return "", 0

    lines = ["### Recent Conversation (this session):"]
    used = len(lines[0])
    rendered = 0
    for u in fresh:
        line = _format_chat_unit(u)
        if used + len(line) + 1 > SESSION_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
        rendered += 1

    if rendered == 0:
        return "", 0
    return "\n".join(lines), rendered


async def _build_relevant_memories_section(
    memory_store,
    query: str,
    exclude_unit_ids: set[str],
) -> tuple[str, int, list[Any]]:
    """
    Semantic search on the incoming message text.

    Returns (rendered_text, count, units). `units` is returned so the caller
    can persist reinforcement in a single batched rewrite.
    """
    if memory_store is None or not query:
        return "", 0, []

    try:
        units = await memory_store.semantic_search(
            query=query,
            n_results=RELEVANT_MAX_MEMORIES * 4,  # over-fetch, we filter below
            importance_threshold=RELEVANT_IMPORTANCE_THRESHOLD,
        )
    except Exception as e:
        log.debug(f"[CHAT-CTX] semantic_search failed: {e}")
        return "", 0, []

    # Exclude chat units already shown in the session section and anything
    # we already pulled, then cap to RELEVANT_MAX_MEMORIES.
    filtered: list[Any] = []
    for u in units:
        uid = getattr(u, "unit_id", None)
        if not uid or uid in exclude_unit_ids:
            continue
        if _is_chat_unit(u):
            # Chat turns belong to the session section, not "relevant memories".
            continue
        filtered.append(u)
        if len(filtered) >= RELEVANT_MAX_MEMORIES:
            break

    if not filtered:
        return "", 0, []

    lines = ["### Relevant Memories:"]
    used = len(lines[0])
    rendered = 0
    kept_units: list[Any] = []
    for u in filtered:
        content = getattr(u, "content", "") or ""
        importance = getattr(u, "importance", 0.0)
        age = _humanize_age(getattr(u, "created_at", None))
        line = f"- {_trim(content, RELEVANT_ITEM_TRIM)} (importance={importance:.0f}, {age})"
        if used + len(line) + 1 > RELEVANT_BUDGET:
            break
        lines.append(line)
        used += len(line) + 1
        rendered += 1
        kept_units.append(u)

    if rendered == 0:
        return "", 0, []
    return "\n".join(lines), rendered, kept_units


# ── Reinforcement (single batched rewrite) ────────────────────────────────

async def _reinforce_units(memory_store, units: list[Any]) -> int:
    """
    Bump reinforcement_count + last_accessed on each retrieved unit and
    persist them in a *single* JSONL rewrite.

    MemoryStore.get_unit() rewrites the whole file per unit — calling it in a
    loop would be O(N²). We update in-memory and call _persist_reinforcement
    via a manual single-pass rewrite.
    """
    if not units or memory_store is None:
        return 0

    now = datetime.now(timezone.utc)
    updated_ids: dict[str, Any] = {}
    for u in units:
        try:
            u.last_accessed = now
            u.reinforcement_count = int(getattr(u, "reinforcement_count", 0)) + 1
            # mild bump capped at 100; mirrors get_unit() behaviour but
            # smaller (×1.05 vs ×1.2) since chat-context recall is implicit,
            # not a deliberate query by the user.
            u.importance = min(100.0, float(getattr(u, "importance", 0.0)) * 1.05)
            uid = getattr(u, "unit_id", None)
            if uid:
                updated_ids[uid] = u
        except Exception as e:
            log.debug(f"[CHAT-CTX] reinforce prep failed for unit: {e}")

    if not updated_ids:
        return 0

    # Single batched rewrite by loading all units, swapping the updated ones
    # in place, and asking the store to rewrite the JSONL once.
    try:
        await memory_store._acquire_write()
        try:
            all_units = await memory_store._load_all_units()
            for i, existing in enumerate(all_units):
                uid = getattr(existing, "unit_id", None)
                if uid in updated_ids:
                    all_units[i] = updated_ids[uid]
            await memory_store._rewrite_units(all_units)
        finally:
            memory_store._release_write()
        return len(updated_ids)
    except Exception as e:
        log.warning(f"[CHAT-CTX] batched reinforce rewrite failed: {e}")
        return 0


# ── Public entry point ────────────────────────────────────────────────────

async def build_chat_context(
    message: str,
    session_id: str,
    brain: Any,
    autonomous: Any = None,
) -> str:
    """
    Assemble the conversation context block for /chat.

    Returns a formatted string ready to prepend to the static system prompt.
    Empty string if nothing is available or if anything goes wrong — chat
    must keep working even when memory recall fails.

    Args:
        message: incoming user message (used for semantic search)
        session_id: session/conversation id (used to recall recent turns)
        brain: NCLBrain instance — provides .memory_store
        autonomous: AutonomousScheduler — provides ._working_context
    """
    try:
        memory_store = getattr(brain, "memory_store", None) if brain else None
        working_ctx = getattr(autonomous, "_working_context", None) if autonomous else None

        # 1. Working context (sync read)
        wc_text, wc_count, wc_item_ids = _build_working_context_section(working_ctx)

        # 2. Session history (async read)
        sess_text, sess_count = await _build_session_history_section(memory_store, session_id)

        # 3. Relevant memories (async semantic search)
        # Exclude unit_ids already counted in the session — we don't carry them
        # forward as "relevant memories" too. The session section pulled chat
        # units only, but defensive exclusion is cheap.
        exclude_ids: set[str] = set()
        rel_text, rel_count, rel_units = await _build_relevant_memories_section(
            memory_store, message, exclude_ids
        )

        if wc_count == 0 and sess_count == 0 and rel_count == 0:
            log.info(f"[CHAT-CTX] injected 0 working_ctx + 0 session + 0 relevant memories")
            return ""

        # Assemble — header + three sections separated by blank lines.
        parts = ["## CONVERSATION CONTEXT", ""]
        if wc_text:
            parts.append(wc_text)
            parts.append("")
        if sess_text:
            parts.append(sess_text)
            parts.append("")
        if rel_text:
            parts.append(rel_text)
            parts.append("")
        block = "\n".join(parts).rstrip() + "\n"

        # Hard truncation safety net (should never trigger given per-section caps).
        if len(block) > MAX_CONTEXT_CHARS:
            block = block[: MAX_CONTEXT_CHARS - 32].rstrip() + "\n…[context truncated]\n"

        # Reinforcement — best-effort, must not break chat.
        try:
            if working_ctx is not None and wc_item_ids:
                await working_ctx.mark_accessed_batch(wc_item_ids)
        except Exception as e:
            log.debug(f"[CHAT-CTX] mark_accessed_batch failed: {e}")

        try:
            if memory_store is not None and rel_units:
                await _reinforce_units(memory_store, rel_units)
        except Exception as e:
            log.debug(f"[CHAT-CTX] reinforce relevant units failed: {e}")

        log.info(
            f"[CHAT-CTX] injected {wc_count} working_ctx + {sess_count} session "
            f"+ {rel_count} relevant memories ({len(block)} chars)"
        )
        return block

    except Exception as e:
        # Any unhandled failure → chat path keeps working with empty context.
        log.warning(f"[CHAT-CTX] build_chat_context failed, returning empty: {e}")
        return ""
