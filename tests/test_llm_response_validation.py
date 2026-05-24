"""
Schema-validation tests for the Anthropic response shape (W4-04).

These tests exercise ``runtime.llm.client._validate_anthropic_response``
in isolation — no live API calls, no httpx mocking required. The helper
is pure / synchronous, so we can call it directly with crafted dicts.
"""

from __future__ import annotations

import pytest

from runtime.llm.client import _validate_anthropic_response
from runtime.llm.errors import MalformedResponseError


# ── valid cases ───────────────────────────────────────────────────────


def test_valid_response_passes() -> None:
    """A well-formed Anthropic response should validate without raising."""
    data = {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-20250514",
        "content": [
            {"type": "text", "text": "Hello, world."},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    # Should not raise
    _validate_anthropic_response(data)


def test_valid_response_with_multiple_block_types_passes() -> None:
    """All allowed block types (text/tool_use/document/thinking) accepted."""
    data = {
        "content": [
            {"type": "thinking", "thinking": "internal trace"},
            {"type": "text", "text": "Here's the answer."},
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "search",
                "input": {"q": "foo"},
            },
            {"type": "document", "source": {"type": "text", "data": "..."}},
        ],
    }
    _validate_anthropic_response(data)


def test_valid_response_with_citation_annotations_passes() -> None:
    """Text block with citations as a list should validate."""
    data = {
        "content": [
            {
                "type": "text",
                "text": "Per the doc, X is true.",
                "citations": [
                    {"type": "char_location", "cited_text": "X is true"},
                ],
            }
        ],
    }
    _validate_anthropic_response(data)


# ── invalid cases ─────────────────────────────────────────────────────


def test_missing_content_raises_MalformedResponseError() -> None:  # noqa: N802
    """A response without the ``content`` key must raise."""
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response({"id": "msg_01"})
    assert exc.value.provider == "anthropic"
    assert "content" in exc.value.reason


def test_content_not_list_raises() -> None:
    """``content`` must be a list, not a string or dict."""
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response({"content": "should be a list"})
    assert "list" in exc.value.reason

    with pytest.raises(MalformedResponseError):
        _validate_anthropic_response({"content": {"type": "text"}})


def test_block_missing_type_raises() -> None:
    """Each block must declare a ``type`` field."""
    data = {"content": [{"text": "no type field here"}]}
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response(data)
    assert "type" in exc.value.reason


def test_block_unknown_type_raises() -> None:
    """Unknown block types must be rejected (defense vs. MITM injection)."""
    data = {
        "content": [
            {"type": "text", "text": "ok"},
            {"type": "evil_inject", "payload": "rm -rf /"},
        ],
    }
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response(data)
    assert "evil_inject" in exc.value.reason


def test_text_block_missing_text_field_raises() -> None:
    """A ``text`` block without a string ``text`` field must raise."""
    # Missing entirely
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response({"content": [{"type": "text"}]})
    assert "text" in exc.value.reason

    # Wrong type
    with pytest.raises(MalformedResponseError):
        _validate_anthropic_response(
            {"content": [{"type": "text", "text": ["not", "a", "string"]}]}
        )


# ── extra defense-in-depth coverage ───────────────────────────────────


def test_top_level_not_dict_raises() -> None:
    """A non-dict top-level response is rejected outright."""
    with pytest.raises(MalformedResponseError):
        _validate_anthropic_response(["content", []])  # type: ignore[arg-type]
    with pytest.raises(MalformedResponseError):
        _validate_anthropic_response("totally wrong")  # type: ignore[arg-type]


def test_block_not_dict_raises() -> None:
    """A block that isn't a dict (e.g. a bare string) must raise."""
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response({"content": ["bare string"]})
    assert "dict" in exc.value.reason


def test_citation_annotations_not_list_raises() -> None:
    """When present, ``citations`` MUST be a list (not a dict)."""
    data = {
        "content": [
            {
                "type": "text",
                "text": "x",
                "citations": {"type": "char_location"},  # WRONG: dict, not list
            }
        ],
    }
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response(data)
    assert "citations" in exc.value.reason


def test_raw_payload_is_capped_at_500_chars() -> None:
    """The ``raw`` attribute on the exception must be capped at 500 chars."""
    big_blob = "x" * 5000
    data = {"content": "not a list", "blob": big_blob}
    with pytest.raises(MalformedResponseError) as exc:
        _validate_anthropic_response(data)
    assert len(exc.value.raw) <= 500
