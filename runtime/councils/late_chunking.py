"""
Late chunking for long council reports and YTC transcripts.

Implements the "late chunking" pattern from Jina v3 (arXiv:2409.04701,
Günther et al. 2024). The standard "naive" chunking pipeline embeds each
chunk independently — every chunk loses awareness of the rest of the
document, so anaphora ("it", "this", "the company"), discourse markers,
and cross-section context all evaporate before the embedding sees them.

LATE CHUNKING inverts the order:

    1. Tokenize the FULL document once.
    2. Run a long-context embedding model that returns one vector per
       token (Jina v3 supports 8192 tokens). Every token's vector now
       carries the full bidirectional context of the document.
    3. Carve the token stream into chunks AFTER embedding.
    4. Derive each chunk's vector by mean-pooling its constituent token
       embeddings (the same pooling the model would do internally for a
       sentence, just applied at the chunk span).

The pooled chunk vectors are still each ~768/1024-d, identical in shape
to "early chunking" output and therefore drop-in compatible with any
ChromaDB / FAISS / pgvector index. The paper reports +24.47% retrieval
quality on average across BEIR & LongEmbed.

INTEGRATION (`runtime/councils/runner.py` — `_auto_ingest_report`)
─────────────────────────────────────────────────────────────────
Today `_auto_ingest_report()` indexes a summary blob plus each insight
as separate ChromaDB docs. For long YTC rollups + per-video transcripts
that lose the cross-video context. Replace the bare `memory_content`
write with chunked, late-chunked embeddings before enqueuing to
async_writer or feeding the vector store:

    from runtime.councils.late_chunking import LateChunker

    chunker = LateChunker(jina_api_key=os.getenv("JINA_API_KEY"))
    chunks = await chunker.chunk_and_embed(
        memory_content,
        max_tokens=512,
    )
    for ch in chunks:
        await writer.enqueue(WriteRequest(
            content=ch["chunk_text"],
            source=f"{rollup_source}:chunk:{ch['position']}",
            memory_type="semantic",
            importance=85.0,
            tags=list(all_tags)[:20],
            metadata={
                **rollup_meta,
                "chunk_position": ch["position"],
                "chunk_span": ch["span"],
                "late_chunked": True,
                # ch["embedding"] is the pre-computed vector — pass it
                # through if your MemoryStore writer can accept one.
            },
        ))

FALLBACK
────────
When no `JINA_API_KEY` is set we degrade gracefully to sentence-grouped
chunking + a sentence-transformers (`all-MiniLM-L6-v2`) per-chunk embed
pass. That recovers the "chunk + embed" pipeline but loses the
late-chunking *benefit* (each chunk is embedded in isolation again).
The shape of the returned dict is identical so callers don't branch.

If neither Jina nor sentence-transformers is reachable, embeddings come
back as None — chunks are still returned so MemoryStore can index them
text-only and let ChromaDB compute its own embeddings downstream.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── Optional deps ──────────────────────────────────────────────────────
try:
    import httpx  # type: ignore
    _HTTPX_OK = True
except ImportError:  # pragma: no cover
    _HTTPX_OK = False
    httpx = None  # type: ignore

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _ST_OK = True
except ImportError:  # pragma: no cover
    _ST_OK = False
    SentenceTransformer = None  # type: ignore


# ── Sentence segmentation ─────────────────────────────────────────────
# Conservative regex-based splitter. Avoids the nltk download dance and
# handles the punctuation classes we see in YTC transcripts & council
# briefs (URLs, abbreviations, list markers).
_SENT_SPLIT_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z\"'(\[])"
    r"|\n{2,}"
)
# Rough token estimator — ~4 chars/token for English; we use this only
# to bound chunk sizes when we don't have the model's real tokenizer.
_CHARS_PER_TOKEN = 4


def _est_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def chunk_by_sentences(
    text: str,
    max_tokens: int = 512,
) -> list[tuple[str, int, int]]:
    """Tokenize by sentence boundaries, group into chunks <= max_tokens.

    Returns a list of ``(chunk_text, start_tok, end_tok)`` triples where
    the token offsets are *estimated* (chars/4). When the caller has the
    model's real tokenizer it can re-derive precise offsets; these
    estimates are sufficient for the late-chunking pooler because the
    Jina API path returns its own offsets-per-segment array.
    """
    if not text or not text.strip():
        return []

    # Pre-collapse runs of blank lines but preserve paragraph boundaries.
    norm = re.sub(r"[ \t]+", " ", text).strip()
    raw_sents = _SENT_SPLIT_RE.split(norm)
    sents = [s.strip() for s in raw_sents if s and s.strip()]
    if not sents:
        return [(text.strip(), 0, _est_tokens(text))]

    chunks: list[tuple[str, int, int]] = []
    cur_parts: list[str] = []
    cur_tokens = 0
    cur_start = 0
    cursor = 0

    for sent in sents:
        s_toks = _est_tokens(sent)
        if cur_tokens + s_toks > max_tokens and cur_parts:
            chunk_text = " ".join(cur_parts).strip()
            chunks.append((chunk_text, cur_start, cursor))
            cur_parts = []
            cur_tokens = 0
            cur_start = cursor
        cur_parts.append(sent)
        cur_tokens += s_toks
        cursor += s_toks

    if cur_parts:
        chunk_text = " ".join(cur_parts).strip()
        chunks.append((chunk_text, cur_start, cursor))

    return chunks


# ── Pooling ───────────────────────────────────────────────────────────
def _mean_pool(token_vecs: list[list[float]]) -> list[float]:
    """Mean-pool a list of equal-length token vectors. Pure-Python; no
    numpy dependency so the module imports cleanly on the Brain even
    when numpy is uninstalled."""
    if not token_vecs:
        return []
    dim = len(token_vecs[0])
    acc = [0.0] * dim
    for tv in token_vecs:
        if len(tv) != dim:
            # Skip malformed rows defensively (rare; jina has been
            # stable but offline replays of older responses sometimes
            # mix vector dims).
            continue
        for i, v in enumerate(tv):
            acc[i] += v
    n = float(len(token_vecs))
    return [a / n for a in acc]


# ── Public functional API ─────────────────────────────────────────────
def late_chunk(
    text: str,
    max_tokens: int = 512,
    overlap: int = 50,
    embed_full_callable: Optional[Callable[[str], dict]] = None,
) -> list[dict]:
    """Apply the late-chunking pattern synchronously.

    Args:
        text: Full document text.
        max_tokens: Max tokens per chunk (~4 chars/token estimate).
        overlap: Token overlap between adjacent chunks (preserves
            anaphora resolution across chunk boundaries; default 50).
        embed_full_callable: ``text -> dict`` returning at least
            ``{"embedding": [...], "token_embeddings": [[...], ...]}``.
            Use the Jina v3 helper from ``LateChunker.embed_document``
            when available. If ``None`` or the callable raises, every
            returned chunk will have ``embedding=None`` and callers
            should fall back to per-chunk embedding (no late benefit).

    Returns:
        ``[{"chunk_text", "embedding", "span": (start, end), "position"}]``
        ordered by position. ``embedding`` is ``None`` when no embedder
        was supplied or the embed call failed.
    """
    if not text or not text.strip():
        return []

    spans = chunk_by_sentences(text, max_tokens=max_tokens)
    if not spans:
        return []

    # Apply overlap by extending each chunk's start backwards into the
    # tail of the previous chunk. We never modify positions/spans —
    # overlap is realised by re-pooling extra token vectors.
    full_embed: dict | None = None
    token_vecs: list[list[float]] | None = None

    if embed_full_callable is not None:
        try:
            full_embed = embed_full_callable(text)
            if isinstance(full_embed, dict):
                tvs = full_embed.get("token_embeddings")
                if isinstance(tvs, list) and tvs and isinstance(tvs[0], list):
                    token_vecs = tvs
        except Exception as e:
            logger.warning(f"late_chunk: embed_full_callable failed ({e}); "
                           f"returning text-only chunks")
            full_embed = None
            token_vecs = None

    # When the embedder returned per-token vectors, map the estimated
    # char/4 spans onto token indices proportional to the embedded
    # length. This is an approximation but it is monotone & total —
    # adjacent chunks tile the token axis without gaps.
    out: list[dict] = []
    if token_vecs:
        n_toks = len(token_vecs)
        # Re-scale our (estimated) spans onto the real token axis.
        max_est = max(s[2] for s in spans) or 1
        scale = n_toks / max_est
        for pos, (chunk_text, est_start, est_end) in enumerate(spans):
            tok_start = max(0, int(round(est_start * scale)) - overlap)
            tok_end = min(n_toks, int(round(est_end * scale)))
            if tok_end <= tok_start:
                tok_end = min(n_toks, tok_start + 1)
            pooled = _mean_pool(token_vecs[tok_start:tok_end])
            out.append({
                "chunk_text": chunk_text,
                "embedding": pooled or None,
                "span": (tok_start, tok_end),
                "position": pos,
            })
    else:
        for pos, (chunk_text, est_start, est_end) in enumerate(spans):
            out.append({
                "chunk_text": chunk_text,
                "embedding": None,
                "span": (est_start, est_end),
                "position": pos,
            })

    return out


# ── Class wrapper with the Jina v3 path + ST fallback ────────────────
class LateChunker:
    """Stateful late-chunking helper.

    Holds the Jina API key (or sentence-transformers model) so callers
    don't pay model-load cost per call. Methods are async to fit cleanly
    into the existing async ingest paths in `runtime/councils/runner.py`
    and `runtime/memory/async_writer.py`.
    """

    JINA_URL = "https://api.jina.ai/v1/embeddings"
    # Cap text we send to the API to avoid the 413 + bill spikes the
    # M1 dedup loop has hit historically. 8192 is the Jina v3 ceiling.
    JINA_MAX_DOC_TOKENS = 8192

    def __init__(
        self,
        jina_api_key: str | None = None,
        model: str = "jina-embeddings-v3",
        st_model: str = "all-MiniLM-L6-v2",
    ):
        """Initialise the chunker.

        Args:
            jina_api_key: When provided AND ``httpx`` is importable we
                use the Jina v3 long-context API for full-document
                embedding (the path that yields the +24% reported
                gain). Falls back to env ``JINA_API_KEY``.
            model: Jina model id. Default ``jina-embeddings-v3``.
            st_model: sentence-transformers fallback model id.
        """
        self.jina_api_key = jina_api_key or os.getenv("JINA_API_KEY") or None
        self.model = model
        self.st_model_id = st_model
        self._st_model: Any | None = None  # lazy
        self._lock = asyncio.Lock()

        # Resolve the embedder strategy once so callers can inspect it.
        if self.jina_api_key and _HTTPX_OK:
            self.backend = "jina"
        elif _ST_OK:
            self.backend = "sentence-transformers"
        else:
            self.backend = "none"
            logger.warning(
                "LateChunker: no Jina key and no sentence-transformers — "
                "chunks will be returned without embeddings. Install with "
                "`pip3 install --break-system-packages sentence-transformers` "
                "or set JINA_API_KEY for the full late-chunking benefit."
            )

    # ── Embedding paths ────────────────────────────────────────────
    async def embed_document(
        self,
        text: str,
        max_tokens: int = 8192,
    ) -> dict:
        """Embed the FULL document once.

        Returns ``{"embedding": [...], "token_embeddings": [[...], ...]}``
        when Jina is available (token_embeddings carry full-document
        context — this is the load-bearing piece of late chunking).
        When falling back to sentence-transformers we return only the
        doc-level pooled embedding and an empty ``token_embeddings``
        list — `late_chunk()` then degrades to per-chunk embedding.
        """
        if not text or not text.strip():
            return {"embedding": [], "token_embeddings": []}

        if self.backend == "jina":
            try:
                return await self._embed_jina(text, max_tokens=max_tokens)
            except Exception as e:
                logger.warning(f"LateChunker: Jina embed failed ({e}); "
                               f"falling back to sentence-transformers")
                # Fall through to ST path below.

        if _ST_OK:
            try:
                pooled = await self._embed_st_single(text)
                return {"embedding": pooled, "token_embeddings": []}
            except Exception as e:
                logger.warning(f"LateChunker: ST embed failed ({e})")

        return {"embedding": [], "token_embeddings": []}

    async def _embed_jina(self, text: str, max_tokens: int) -> dict:
        """Call Jina embeddings API with ``return_token_embeddings=true``."""
        if not _HTTPX_OK:
            raise RuntimeError("httpx not installed")
        if not self.jina_api_key:
            raise RuntimeError("JINA_API_KEY not set")

        # Truncate hard to keep cost bounded — Jina enforces 8192 anyway.
        # ~4 chars/token is a safe overestimate of the tokenizer.
        max_chars = min(max_tokens, self.JINA_MAX_DOC_TOKENS) * _CHARS_PER_TOKEN
        payload_text = text[:max_chars]

        payload = {
            "model": self.model,
            "input": [payload_text],
            "task": "retrieval.passage",
            # The two knobs that make late chunking possible:
            "late_chunking": True,
            "return_token_embeddings": True,
        }
        headers = {
            "Authorization": f"Bearer {self.jina_api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.JINA_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        # Jina shape: {"data": [{"embedding": [...], "embeddings": [[...], ...]}], ...}
        # The "embeddings" key (plural) carries per-token vectors when
        # late_chunking=true; "embedding" is the pooled doc vector.
        items = data.get("data") or []
        if not items:
            return {"embedding": [], "token_embeddings": []}
        first = items[0] or {}
        return {
            "embedding": first.get("embedding") or [],
            "token_embeddings": (
                first.get("embeddings")
                or first.get("token_embeddings")
                or []
            ),
        }

    async def _embed_st_single(self, text: str) -> list[float]:
        """Pooled embedding via sentence-transformers — fallback path."""
        async with self._lock:
            if self._st_model is None:
                # Model load is sync + heavy (~80MB download first time).
                # Hop to a thread so we don't stall the event loop.
                self._st_model = await asyncio.to_thread(
                    SentenceTransformer, self.st_model_id
                )
        vec = await asyncio.to_thread(self._st_model.encode, text)  # type: ignore[union-attr]
        try:
            return [float(x) for x in vec.tolist()]
        except AttributeError:
            return [float(x) for x in vec]

    async def _embed_st_chunks(self, texts: list[str]) -> list[list[float]]:
        """Batch ST embedding for the fallback per-chunk path."""
        async with self._lock:
            if self._st_model is None:
                self._st_model = await asyncio.to_thread(
                    SentenceTransformer, self.st_model_id
                )
        vecs = await asyncio.to_thread(
            self._st_model.encode, texts  # type: ignore[union-attr]
        )
        out: list[list[float]] = []
        for v in vecs:
            try:
                out.append([float(x) for x in v.tolist()])
            except AttributeError:
                out.append([float(x) for x in v])
        return out

    # ── Public chunk_and_embed ─────────────────────────────────────
    async def chunk_and_embed(
        self,
        text: str,
        max_tokens: int = 512,
        overlap: int = 50,
    ) -> list[dict]:
        """Apply the late-chunking pattern end-to-end.

        Returns ``[{"chunk_text", "embedding", "span", "position"}]``.

        When the Jina backend is live we get the genuine +24% retrieval
        win. With the ST fallback we still chunk + embed (so the writer
        gets vectors) but each chunk is embedded in isolation — the
        function is functionally identical to "early chunking" in that
        mode, advertised in ``self.backend``.
        """
        if not text or not text.strip():
            return []

        spans = chunk_by_sentences(text, max_tokens=max_tokens)
        if not spans:
            return []

        if self.backend == "jina":
            try:
                full = await self.embed_document(text, max_tokens=self.JINA_MAX_DOC_TOKENS)
                token_vecs = full.get("token_embeddings") or []
                if token_vecs:
                    # Re-use the sync late_chunk() pooler — but pass a
                    # callable that just returns the cached dict so we
                    # don't re-call Jina.
                    return late_chunk(
                        text,
                        max_tokens=max_tokens,
                        overlap=overlap,
                        embed_full_callable=lambda _t: full,
                    )
                # Jina returned only a pooled vector — fall through to
                # per-chunk embedding so callers still get vectors.
                logger.info("LateChunker: Jina returned no token_embeddings; "
                            "falling back to per-chunk embed")
            except Exception as e:
                logger.warning(f"LateChunker: Jina path failed ({e}); falling back")

        # Per-chunk fallback path. Returns matching shape; loses the
        # late-chunking benefit but stays drop-in compatible.
        chunk_texts = [s[0] for s in spans]
        embeddings: list[list[float] | None] = [None] * len(chunk_texts)
        if _ST_OK:
            try:
                vecs = await self._embed_st_chunks(chunk_texts)
                if len(vecs) == len(chunk_texts):
                    embeddings = vecs  # type: ignore[assignment]
            except Exception as e:
                logger.warning(f"LateChunker: ST chunk embed failed ({e})")

        out: list[dict] = []
        for pos, ((chunk_text, est_start, est_end), emb) in enumerate(
            zip(spans, embeddings)
        ):
            out.append({
                "chunk_text": chunk_text,
                "embedding": emb,
                "span": (est_start, est_end),
                "position": pos,
            })
        return out


__all__ = ["late_chunk", "chunk_by_sentences", "LateChunker"]
