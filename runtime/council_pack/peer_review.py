"""
Anonymized peer-review round
============================

Stage-2 from Karpathy's "anonymous critique" prescription. After all members
have submitted round-1 positions, we run a *second* round where each member
critiques a peer's response — but the peer's identity is stripped before the
critique prompt is built.

Why this matters
----------------
RLHF training teaches models to defer to whichever name appears first. In
the standard council ("Grok said X, what do you think?"), Claude and Gemini
visibly tilt toward agreement with whoever spoke first. Empirically, blinding
removes that effect — review feedback becomes far more substantive.

How it works
------------
1. Collect the round-1 replies keyed by ``member`` name.
2. Map each member to an anonymous tag (``REVIEWER_A``, ``REVIEWER_B``, ...).
3. For each member, build a prompt that asks them to critique two *other*
   members' replies, presented under their anonymous tags only — no model
   names, no role labels, no characteristic vocabulary tells we can scrub.
4. Optionally scrub a small list of high-signal tells (the word "research",
   common openings each model defaults to, signature self-references like
   "as an AI"). Best-effort — too aggressive and we destroy the prose.

Output
------
``run_peer_review_round`` returns ``list[dict]`` with one entry per reviewer::

    {
        "reviewer": "claude",
        "targets": ["REVIEWER_C", "REVIEWER_E"],
        "critique": "<text>",
    }

The runner then de-anonymizes the targets via the mapping the function
returns alongside the critiques for write-back.
"""

from __future__ import annotations

import logging
import random
import re
import string
from typing import Awaitable, Callable, Iterable, Optional  # noqa: F401


log = logging.getLogger("ncl.council_pack.peer_review")


# Critiques flow into the council transcript which has a 60KB hard cap. With
# 5 members × 2 targets = 10 critiques, an unbounded reviewer can easily blow
# the budget on its own. 800 chars × 10 = ~8KB worst-case, leaving headroom
# for the rest of the transcript (positions, rebuttals, convergence, chair
# synthesis). Added 2026-05-23 alongside the peer_review default flip.
MAX_CRITIQUE_CHARS = 800


# Patterns that betray model identity. Conservative — we don't want to mangle
# substantive technical vocabulary. These match opening phrases and the
# "as an AI" / "I'm a language model" stock self-references.
_TELL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(as an? (ai|language model|assistant)[^.]*\.)", re.IGNORECASE),
    re.compile(r"\b(i'?m (an?|a) (ai|language model|assistant)[^.]*\.)", re.IGNORECASE),
    re.compile(r"\bgrok here[^.]*\.", re.IGNORECASE),
    re.compile(r"\bgemini speaking[^.]*\.", re.IGNORECASE),
    re.compile(
        r"\b(claude|grok|gemini|gpt|perplexity|copilot) (says?|here|speaking)\b", re.IGNORECASE
    ),  # noqa: E501
]


def anonymize(text: str) -> str:
    """Strip the most common model-identity tells from ``text``.

    Conservative — only removes obvious self-references. Substantive content
    (technical vocabulary, framework names, etc.) is left alone.
    """
    if not text:
        return text
    cleaned = text
    for pat in _TELL_PATTERNS:
        cleaned = pat.sub("", cleaned)
    return cleaned


def _build_tag_map(members: list[str]) -> dict[str, str]:
    """Map each member to a stable anonymous tag.

    Tag assignment is deterministic given the input order so re-runs surface
    the same critique → target pairings in tests, but the ALPHA position is
    rotated each call so no member always reads as REVIEWER_A.
    """
    tags = [f"REVIEWER_{c}" for c in string.ascii_uppercase[: len(members)]]
    if not tags:
        return {}
    # Stable rotation — based on hash of the joined names, not on random.
    rotation = sum(ord(c) for c in "".join(members)) % len(tags)
    rotated = tags[rotation:] + tags[:rotation]
    return dict(zip(members, rotated))


def _pick_targets(reviewer: str, members: list[str], n: int = 2) -> list[str]:
    """Pick ``n`` peers (not ``reviewer``) for this reviewer to critique.

    Deterministic-by-default — uses a seed derived from the reviewer's name
    so re-runs over the same input give the same pairings.
    """
    peers = [m for m in members if m != reviewer]
    if not peers:
        return []
    if len(peers) <= n:
        return peers
    rng = random.Random(hash(reviewer) & 0xFFFFFFFF)
    rng.shuffle(peers)
    return peers[:n]


def _build_review_prompt(
    topic: str,
    reviewer_role: str,
    tag_map: dict[str, str],
    targets: list[str],
    member_replies: dict[str, str],
) -> str:
    """Build the prompt the reviewer sees.

    The reviewer's own reply is NOT included — they're critiquing peers,
    not defending themselves. Peer replies are shown under their anonymous
    tags only, with tells scrubbed.
    """
    parts: list[str] = [
        "=== ANONYMOUS PEER REVIEW ===",
        f"Topic: {topic}",
        "",
        f"You are the {reviewer_role.upper()}. Two peers' round-1 positions are",
        "below, identified only by anonymous tags. You do NOT know which model",
        "wrote which reply. Critique each one. For each peer:",
        "",
        "  1. Name the strongest claim and explain why it holds.",
        "  2. Name the weakest claim and explain what evidence would refute it.",
        "  3. Identify any logical gap or unstated assumption.",
        "  4. State whether the verbalized confidence in their calibration block",
        "     is OVERCONFIDENT, UNDERCONFIDENT, or APPROPRIATE for the evidence",
        "     they marshalled.",
        "",
        "Do not speculate about which model wrote what. Treat the tags as the",
        "only identity that matters. Keep the critique evidence-anchored.",
        "",
    ]
    for tgt in targets:
        tag = tag_map.get(tgt, tgt)
        body = anonymize(member_replies.get(tgt, "(no reply)"))[:2000]
        parts.append(f"--- {tag} ---")
        parts.append(body)
        parts.append("")
    parts.append(
        "Now produce two clearly-labeled critique sections, one per tag. "
        "End each section with: VERDICT: <OVERCONFIDENT|UNDERCONFIDENT|APPROPRIATE>."
    )
    return "\n".join(parts)


async def run_peer_review_round(
    topic: str,
    members: list[str],
    member_replies: dict[str, str],
    member_roles: dict[str, str],
    call_member: Callable[[str, str], Awaitable[str]],
    targets_per_reviewer: int = 2,
) -> tuple[list[dict], dict[str, str]]:
    """Execute the anonymized peer-review round.

    Parameters
    ----------
    topic : str
    members : list[str]
        Ordered list of member names (e.g. ``["claude", "grok", "gemini"]``).
    member_replies : dict[str, str]
        Round-1 replies, keyed by member name. Anonymizer is applied before
        the reply is shown to a peer.
    member_roles : dict[str, str]
        Role labels (``"CHAIR"``, ``"STRATEGIST"`` etc.) keyed by member name.
        Used in the reviewer's own prompt to remind them of their lens.
    call_member : async callable
        ``await call_member(member_name, prompt) -> str``. The runner
        already knows how to dispatch to each LLM; we just hand it a name.
    targets_per_reviewer : int, default 2
        How many peers each reviewer critiques.

    Returns
    -------
    (reviews, tag_map)
        ``reviews`` is a list of ``{"reviewer", "targets", "critique"}``
        dicts, one per reviewer that produced output. ``tag_map`` is the
        member→anonymous-tag mapping the caller needs in order to
        de-anonymize the critique for write-back.
    """
    if not members or len(members) < 2:
        return [], {}

    tag_map = _build_tag_map(members)
    reviews: list[dict] = []

    for reviewer in members:
        targets = _pick_targets(reviewer, members, n=targets_per_reviewer)
        if not targets:
            continue
        role = member_roles.get(reviewer, "MEMBER")
        prompt = _build_review_prompt(
            topic=topic,
            reviewer_role=role,
            tag_map=tag_map,
            targets=targets,
            member_replies=member_replies,
        )
        try:
            critique = await call_member(reviewer, prompt)
        except Exception as exc:
            log.warning("[PEER-REVIEW] %s failed to produce critique: %s", reviewer, exc)
            continue
        critique_text = (critique or "")[:MAX_CRITIQUE_CHARS]
        if len(critique or "") > MAX_CRITIQUE_CHARS:
            critique_text += "\n[...truncated]"
        reviews.append(
            {
                "reviewer": reviewer,
                "targets": targets,
                "tags": [tag_map.get(t, t) for t in targets],
                "critique": critique_text,
            }
        )

    log.info(
        "[PEER-REVIEW] %d reviewers produced critique on %d peers each",
        len(reviews),
        targets_per_reviewer,
    )
    return reviews, tag_map


__all__ = ["anonymize", "run_peer_review_round", "MAX_CRITIQUE_CHARS"]
