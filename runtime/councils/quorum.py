"""
Council Quorum — Cheap pre-pass that short-circuits agreement.

Most council topics produce agreement, so paying for the full 5-LLM
Delphi-MAD debate (~$0.10/session) is wasted spend. This module runs a
2-model pre-pass — Sonnet-4 + Haiku-3.5 in parallel — and only escalates
to the full council when the two responses meaningfully disagree.

Research (and our own ledger) suggests ~34% of council cost is recoverable
this way without losing decision quality on agreed-upon topics.

Wire-up:
    from runtime.councils.quorum import CouncilQuorum, QuorumDecision

    quorum = CouncilQuorum(
        anthropic_client=brain.http_client,        # existing httpx.AsyncClient
        embedder_callable=None,                    # auto-loads sentence-transformers
        threshold=0.6,
        cost_gate_callable=cost_tracker.can_spend, # async (source, est_usd) -> bool
    )
    result = await quorum.run_quorum(topic, context, prompt)
    if result.decision == QuorumDecision.AGREE_SHORT_CIRCUIT:
        return result.sonnet_response          # ship answer
    # else fall through to brain.council_engine.run_debate(...)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional

import httpx

log = logging.getLogger("ncl.councils.quorum")

# ---------------------------------------------------------------------------
# Model IDs (locked per CLAUDE.md — sonnet-4-6 returned HTTP 404)
# ---------------------------------------------------------------------------
SONNET_MODEL = "claude-sonnet-4-20250514"
HAIKU_MODEL = "claude-haiku-3-5-20241022"

# Per-1K-token pricing (USD) — used for cost gating + ledger
PRICING = {
    SONNET_MODEL: {"input": 0.003, "output": 0.015},
    HAIKU_MODEL: {"input": 0.0008, "output": 0.004},
}

# Conservative pre-call estimate for the budget gate (input + 1K output guess)
EST_CALL_COST = {SONNET_MODEL: 0.018, HAIKU_MODEL: 0.0048}

ANTHROPIC_BASE = os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com")
ANTHROPIC_KEY_ENV = "ANTHROPIC_API_KEY"

QUORUM_LOG_PATH = Path(
    os.getenv("NCL_QUORUM_LOG", str(Path.home() / "dev" / "NCL" / "data" / "councils" / "quorum_log.jsonl"))
)

# Embedder is lazy-loaded once per process
_EMBEDDER: Any = None
_EMBEDDER_TRIED = False


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------
class QuorumDecision(Enum):
    AGREE_SHORT_CIRCUIT = "agree"       # Return Sonnet's answer directly
    ESCALATE_FULL_COUNCIL = "escalate"  # Run the full 5-LLM debate
    ERROR_ESCALATE = "error_escalate"   # Quorum failed, default to full council


@dataclass
class QuorumResult:
    decision: QuorumDecision
    sonnet_response: str
    haiku_response: str
    similarity: float            # cosine 0-1 (or Jaccard fallback)
    disagreement_score: float    # 1 - similarity
    confidence: float            # 0-1 — how sure we are this is a real agree/disagree
    cost_usd: float              # actual recorded cost of the two calls
    reason: str
    duration_s: float
    sonnet_tokens: tuple[int, int] = (0, 0)   # (input, output)
    haiku_tokens: tuple[int, int] = (0, 0)
    similarity_method: str = "cosine"          # "cosine" | "jaccard"
    topic: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d


# ---------------------------------------------------------------------------
# Embedder helpers
# ---------------------------------------------------------------------------
def _try_load_embedder() -> Optional[Any]:
    """Lazy-load sentence-transformers all-MiniLM. Returns None if unavailable."""
    global _EMBEDDER, _EMBEDDER_TRIED
    if _EMBEDDER_TRIED:
        return _EMBEDDER
    _EMBEDDER_TRIED = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
        _EMBEDDER = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("[quorum] Loaded sentence-transformers all-MiniLM-L6-v2 embedder")
    except Exception as e:
        log.warning(f"[quorum] sentence-transformers unavailable ({e}) — falling back to Jaccard")
        _EMBEDDER = None
    return _EMBEDDER


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    # Clamp into [0, 1] — sentence-transformer outputs are already non-negative
    # in practice but rounding can push it out by a hair.
    return max(0.0, min(1.0, dot / (na * nb)))


_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity fallback when no embedder is available."""
    sa = set(t.lower() for t in _TOKEN_RE.findall(a or ""))
    sb = set(t.lower() for t in _TOKEN_RE.findall(b or ""))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _embed_pair(embedder: Any, a: str, b: str) -> tuple[List[float], List[float]]:
    """Encode a pair of strings; tolerates numpy or list returns."""
    vecs = embedder.encode([a, b], normalize_embeddings=True)
    out: List[List[float]] = []
    for v in vecs:
        try:
            out.append([float(x) for x in v.tolist()])  # numpy.ndarray
        except AttributeError:
            out.append([float(x) for x in v])
    return out[0], out[1]


# ---------------------------------------------------------------------------
# CouncilQuorum
# ---------------------------------------------------------------------------
class CouncilQuorum:
    """Two-model agreement pre-pass for the full council."""

    def __init__(
        self,
        anthropic_client: Optional[httpx.AsyncClient] = None,
        embedder_callable: Optional[Callable[[str], List[float]]] = None,
        threshold: float = 0.6,
        cost_gate_callable: Optional[Callable[[str, float], Awaitable[bool]]] = None,
        api_key: Optional[str] = None,
        timeout_s: float = 30.0,
        max_tokens: int = 1024,
    ) -> None:
        """
        Args:
            anthropic_client: Existing httpx.AsyncClient (re-use brain's pool).
                              A new one is created if not provided.
            embedder_callable: text -> List[float]. If None, sentence-transformers
                               all-MiniLM is loaded lazily; if unavailable, falls
                               back to token-set Jaccard.
            threshold: Disagreement score above which the full council is
                       convened. Default 0.6 — i.e. similarity must be >= 0.4
                       to short-circuit. Tune via NCL_QUORUM_THRESHOLD.
            cost_gate_callable: Async (source, est_cost_usd) -> bool. If either
                                pre-call check fails, we ESCALATE (better to
                                spend on the full debate than skip on a
                                budget-blocked quorum).
            api_key: ANTHROPIC_API_KEY override. Read from env if absent.
            timeout_s: Per-call HTTP timeout.
            max_tokens: Cap for each model's response.
        """
        self.http = anthropic_client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_http = anthropic_client is None
        self.embedder_callable = embedder_callable
        self.threshold = float(os.getenv("NCL_QUORUM_THRESHOLD", str(threshold)))
        self.cost_gate = cost_gate_callable
        self.api_key = api_key or os.getenv(ANTHROPIC_KEY_ENV, "")
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens

    # ---- public API ------------------------------------------------------
    async def run_quorum(self, topic: str, context: str, prompt: str) -> QuorumResult:
        """
        Run the two-model pre-pass and decide whether to short-circuit.

        Returns a QuorumResult; callers inspect `.decision` to route. On any
        error (missing key, gate fail, HTTP fail) the result is
        ERROR_ESCALATE/ESCALATE_FULL_COUNCIL — never silently agree.
        """
        start = time.monotonic()
        full_prompt = self._build_prompt(topic, context, prompt)

        if not self.api_key:
            return self._fail(
                start, "Anthropic API key not configured",
                decision=QuorumDecision.ERROR_ESCALATE, topic=topic,
            )

        # Pre-call budget gates — fail OPEN to the full council, never silently agree
        if self.cost_gate is not None:
            try:
                ok_sonnet = await self.cost_gate("anthropic", EST_CALL_COST[SONNET_MODEL])
                ok_haiku = await self.cost_gate("anthropic", EST_CALL_COST[HAIKU_MODEL])
                if not (ok_sonnet and ok_haiku):
                    return self._fail(
                        start, "budget gate blocked quorum — escalating to full council",
                        decision=QuorumDecision.ESCALATE_FULL_COUNCIL, topic=topic,
                    )
            except Exception as e:
                log.warning(f"[quorum] cost gate raised {e!r} — escalating")
                return self._fail(
                    start, f"cost gate error: {e}",
                    decision=QuorumDecision.ERROR_ESCALATE, topic=topic,
                )

        # Parallel calls
        try:
            sonnet_task = asyncio.create_task(self._call(SONNET_MODEL, full_prompt))
            haiku_task = asyncio.create_task(self._call(HAIKU_MODEL, full_prompt))
            (sonnet_text, sonnet_in, sonnet_out), (haiku_text, haiku_in, haiku_out) = \
                await asyncio.gather(sonnet_task, haiku_task)
        except Exception as e:
            log.warning(f"[quorum] model call failed: {e}")
            return self._fail(
                start, f"model call failed: {e}",
                decision=QuorumDecision.ERROR_ESCALATE, topic=topic,
            )

        cost = (
            (sonnet_in / 1000.0) * PRICING[SONNET_MODEL]["input"]
            + (sonnet_out / 1000.0) * PRICING[SONNET_MODEL]["output"]
            + (haiku_in / 1000.0) * PRICING[HAIKU_MODEL]["input"]
            + (haiku_out / 1000.0) * PRICING[HAIKU_MODEL]["output"]
        )

        # Similarity
        similarity, method = self._similarity(sonnet_text, haiku_text)
        disagreement = 1.0 - similarity

        # Decision — short-circuit when disagreement is BELOW the threshold
        if disagreement <= self.threshold:
            decision = QuorumDecision.AGREE_SHORT_CIRCUIT
            reason = (
                f"agreement: similarity={similarity:.3f} "
                f"(disagreement={disagreement:.3f} <= threshold={self.threshold})"
            )
        else:
            decision = QuorumDecision.ESCALATE_FULL_COUNCIL
            reason = (
                f"disagreement: similarity={similarity:.3f} "
                f"(disagreement={disagreement:.3f} > threshold={self.threshold})"
            )

        # Confidence = how far we are from the threshold (0 at threshold, 1 at extremes)
        confidence = min(1.0, abs(disagreement - self.threshold) / max(self.threshold, 1 - self.threshold))

        result = QuorumResult(
            decision=decision,
            sonnet_response=sonnet_text,
            haiku_response=haiku_text,
            similarity=similarity,
            disagreement_score=disagreement,
            confidence=confidence,
            cost_usd=cost,
            reason=reason,
            duration_s=time.monotonic() - start,
            sonnet_tokens=(sonnet_in, sonnet_out),
            haiku_tokens=(haiku_in, haiku_out),
            similarity_method=method,
            topic=topic,
        )
        self._persist(result)
        log.info(
            f"[quorum] {decision.value} similarity={similarity:.3f} "
            f"cost=${cost:.4f} dur={result.duration_s:.2f}s topic={topic[:60]!r}"
        )
        return result

    async def aclose(self) -> None:
        """Close the http client if we own it."""
        if self._owns_http:
            await self.http.aclose()

    # ---- internals -------------------------------------------------------
    def _build_prompt(self, topic: str, context: str, prompt: str) -> str:
        parts = [f"TOPIC: {topic}"]
        if context:
            parts.append(f"\nCONTEXT:\n{context}")
        parts.append(f"\nQUESTION:\n{prompt}")
        parts.append(
            "\nProvide your best answer concisely. Lead with your recommendation, "
            "then 2-4 sentences of reasoning."
        )
        return "\n".join(parts)

    async def _call(self, model: str, prompt: str) -> tuple[str, int, int]:
        """Single Anthropic Messages call. Returns (text, input_tokens, output_tokens)."""
        resp = await self.http.post(
            f"{ANTHROPIC_BASE}/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=self.timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", [])
        text = content[0].get("text", "") if content else ""
        usage = data.get("usage", {}) or {}
        return text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))

    def _similarity(self, a: str, b: str) -> tuple[float, str]:
        """Compute similarity. Prefer embedder, fall back to Jaccard."""
        # 1. User-supplied embedder callable
        if self.embedder_callable is not None:
            try:
                va = list(self.embedder_callable(a))
                vb = list(self.embedder_callable(b))
                return _cosine(va, vb), "cosine"
            except Exception as e:
                log.warning(f"[quorum] custom embedder failed ({e}) — trying sentence-transformers")

        # 2. sentence-transformers (lazy)
        embedder = _try_load_embedder()
        if embedder is not None:
            try:
                va, vb = _embed_pair(embedder, a, b)
                return _cosine(va, vb), "cosine"
            except Exception as e:
                log.warning(f"[quorum] sentence-transformers encode failed ({e}) — Jaccard fallback")

        # 3. Token-set Jaccard
        return _jaccard(a, b), "jaccard"

    def _fail(
        self,
        start: float,
        reason: str,
        decision: QuorumDecision,
        topic: str,
    ) -> QuorumResult:
        """Build + persist a failure/no-op result."""
        result = QuorumResult(
            decision=decision,
            sonnet_response="",
            haiku_response="",
            similarity=0.0,
            disagreement_score=1.0,
            confidence=0.0,
            cost_usd=0.0,
            reason=reason,
            duration_s=time.monotonic() - start,
            similarity_method="none",
            topic=topic,
        )
        self._persist(result)
        log.info(f"[quorum] {decision.value} (no-op): {reason}")
        return result

    def _persist(self, result: QuorumResult) -> None:
        """Append a single JSONL row. Best-effort — never raise into caller."""
        try:
            QUORUM_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            row = result.to_dict()
            row["ts"] = datetime.now(timezone.utc).isoformat()
            # Truncate large response bodies in the ledger
            row["sonnet_response"] = row["sonnet_response"][:2000]
            row["haiku_response"] = row["haiku_response"][:2000]
            with QUORUM_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"[quorum] failed to persist log: {e}")


__all__ = ["CouncilQuorum", "QuorumDecision", "QuorumResult"]
