"""
Anthropic Citations API document blocks
=======================================

When you send a Claude message with ``citations.enabled: true`` on each
document content block, the model's text reply comes back annotated with
``citations[]`` arrays that point back at the exact (document, char_start,
char_end) span the answer drew from. Source-hallucination rate drops from
roughly 10% to roughly 0%.

This module turns the council's evidence items into the document blocks the
API expects, and exposes ``parse_citations()`` to extract the citation spans
out of the response on the way back in.

Spec reference
--------------
https://docs.anthropic.com/en/docs/build-with-claude/citations

Block shape (custom-content variant — what we use, because our evidence is
already paragraph-shaped text)::

    {
        "type": "document",
        "source": {
            "type": "content",
            "content": [{"type": "text", "text": "<verbatim evidence>"}]
        },
        "title": "<unit_id or display label>",
        "context": "<source authority tier + recency hint>",
        "citations": {"enabled": True}
    }

When responding, Claude can emit either ``text`` blocks (free prose), or
``text`` blocks tagged with ``citations`` pointing at the documents above.
We collect those into a flat per-claim citation list for write-back.

Graceful degradation
--------------------
Citations are a request-level feature on the Anthropic API. If the caller is
still hitting raw httpx without the feature flag, ``build_citation_documents``
output is still safe to pass — the documents will be treated as regular
content blocks and the run will succeed with no citation annotations. So a
caller can opt-in incrementally.
"""

from __future__ import annotations

from typing import Any, Iterable  # noqa: F401


def build_citation_documents(items: Iterable[dict]) -> list[dict]:
    """Convert pack items to Anthropic Citations document blocks.

    Each ``item`` is expected to have at least ``content``. Optional fields
    consumed: ``unit_id``, ``source``, ``authority_tier_name``, ``recency_label``.

    Returns
    -------
    list[dict]
        Document content blocks ready to drop into the ``content`` array of
        a ``messages.create`` call. Order is preserved.
    """
    docs: list[dict] = []
    for item in items:
        content = (item.get("content") or "").strip()
        if not content:
            continue
        title = str(item.get("unit_id") or item.get("source") or "evidence")
        context_parts: list[str] = []
        tier = item.get("authority_tier_name")
        if tier:
            context_parts.append(f"authority:{tier}")
        recency = item.get("recency_label")
        if recency:
            context_parts.append(f"recency:{recency}")
        source = item.get("source")
        if source:
            context_parts.append(f"source:{source}")
        context = " | ".join(context_parts) or "evidence"

        docs.append(
            {
                "type": "document",
                "source": {
                    "type": "content",
                    "content": [{"type": "text", "text": content}],
                },
                "title": title[:240],
                "context": context[:240],
                "citations": {"enabled": True},
            }
        )
    return docs


def parse_citations(response_json: dict) -> list[dict]:
    """Flatten the citation annotations on a ``messages.create`` response.

    Each emitted dict carries::

        {
            "claim_text":   "<the sentence that cites>",
            "doc_index":    <int — index into the documents array we sent>,
            "doc_title":    "<the title we sent>",
            "doc_text":     "<verbatim cited substring>",
            "start_char":   <int>,
            "end_char":     <int>,
        }

    Safe on any input shape: returns ``[]`` for non-Anthropic responses or
    malformed annotations.
    """
    out: list[dict] = []
    if not isinstance(response_json, dict):
        return out
    blocks = response_json.get("content")
    if not isinstance(blocks, list):
        return out
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "text":
            continue
        claim = block.get("text") or ""
        cites = block.get("citations") or []
        if not isinstance(cites, list):
            continue
        for c in cites:
            if not isinstance(c, dict):
                continue
            out.append(
                {
                    "claim_text": claim,
                    "doc_index": c.get("document_index"),
                    "doc_title": c.get("document_title"),
                    "doc_text": c.get("cited_text"),
                    "start_char": c.get("start_char_index"),
                    "end_char": c.get("end_char_index"),
                }
            )
    return out


__all__ = ["build_citation_documents", "parse_citations"]
