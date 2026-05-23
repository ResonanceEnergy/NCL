"""
FusedRetriever — Reciprocal Rank Fusion across multiple retrieval signals.

Signals:
  1. Vector similarity (ChromaDB cosine, via memory_store.semantic_search)
  2. BM25 keyword scoring (BM25Index)
  3. Entity overlap (KnowledgeGraph.query_entity neighborhoods)

RRF formula (Cormack, Clarke, Buettcher 2009):
    score(d) = sum( w_i / (k + rank_i(d)) ) for each signal i

with k = 60 by default. Rank is 1-based per signal; documents that do
not appear in a signal's top-N contribute 0 from that signal.

Optional second-pass reranking via Claude Haiku, gated by
``NCL_FUSION_RERANK=1`` — useful when surfacing top-3 to a downstream
consumer, but adds ~1-3s latency and Anthropic cost per query.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING, Iterable, Optional

from ..authority import (
    AuthorityTier,
    authority_weight,
    tier_for_source,
)

log = logging.getLogger("ncl.memory.retrieval.fusion")

if TYPE_CHECKING:
    from ..store import MemoryStore
    from ..knowledge_graph import KnowledgeGraph
    from .bm25 import BM25Index

# Default per-signal weights — entity overlap is noisier so it gets a
# slightly lower weight. Vector and BM25 are co-equal.
DEFAULT_WEIGHTS = {"vector": 1.0, "bm25": 1.0, "entity": 0.7}
FIRST_PASS_TOP_N = 50
RRF_K_DEFAULT = 60


_TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b")
_CAP_PHRASE_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")


def _extract_query_entities(query: str) -> list[str]:
    """Lightweight entity extraction over the query string — mirrors the
    fast extractor in ``entity_extractor.py`` but inline to avoid a hard
    dependency on it.
    """
    out: set[str] = set()
    for m in _TICKER_RE.finditer(query):
        out.add(f"${m.group(1)}")
    for m in _CAP_PHRASE_RE.finditer(query):
        phrase = m.group(1).strip()
        if len(phrase) >= 3:
            out.add(phrase)
    # Also include single bare-capitalized words (e.g. "Awarebot")
    for w in re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", query):
        out.add(w)
    return list(out)


class FusedRetriever:
    """RRF fusion of vector + BM25 + entity-overlap signals."""

    def __init__(
        self,
        memory_store: "MemoryStore",
        bm25_index: "BM25Index",
        knowledge_graph: Optional["KnowledgeGraph"] = None,
        k: int = RRF_K_DEFAULT,
    ) -> None:
        self.store = memory_store
        self.bm25 = bm25_index
        self.kg = knowledge_graph
        self.k = max(1, int(k))

    # ------------------------------------------------------------------

    async def _vector_ranks(self, query: str, top_n: int) -> list[tuple[str, float]]:
        """Top-N from ChromaDB via the existing semantic_search path."""
        try:
            units = await self.store.semantic_search(
                query=query,
                n_results=top_n,
                importance_threshold=0.0,
            )
            return [(u.unit_id, float(getattr(u, "importance", 0.0))) for u in units]
        except Exception as e:
            log.warning("[FUSION] vector signal failed: %s", e)
            return []

    async def _bm25_ranks(self, query: str, top_n: int) -> list[tuple[str, float]]:
        """Top-N from BM25 — runs in a thread because get_scores() is CPU-bound."""
        if self.bm25 is None:
            return []
        try:
            return await asyncio.to_thread(self.bm25.search, query, top_n)
        except Exception as e:
            log.warning("[FUSION] bm25 signal failed: %s", e)
            return []

    async def _entity_ranks(self, query: str, top_n: int) -> list[tuple[str, float]]:
        """Top-N from entity-overlap via the knowledge graph.

        Strategy: extract entities from the query, look up each in the KG,
        and pull the union of their `source_units` (capped per-entity). The
        score per unit is the number of distinct query entities it shares.
        """
        if not self.kg:
            return []
        query_entities = _extract_query_entities(query)
        if not query_entities:
            return []
        # Per-unit score = number of distinct query-entities that mention it.
        unit_scores: dict[str, float] = {}
        for ent in query_entities:
            try:
                node = await self.kg.query_entity(ent, depth=1)
            except Exception as e:
                log.debug("[FUSION] kg query for %s failed: %s", ent, e)
                continue
            if not node or not node.get("found"):
                continue
            attrs = node.get("attributes", {}) or {}
            for uid in attrs.get("source_units", []) or []:
                if not uid:
                    continue
                unit_scores[uid] = unit_scores.get(uid, 0.0) + 1.0
            # Walk one-hop neighbors so multi-hop queries get partial credit
            for nb in (node.get("neighbors") or [])[:10]:
                try:
                    nb_node = await self.kg.query_entity(nb, depth=1)
                except Exception:
                    continue
                if not nb_node or not nb_node.get("found"):
                    continue
                nb_attrs = nb_node.get("attributes", {}) or {}
                for uid in (nb_attrs.get("source_units") or [])[:5]:
                    if not uid:
                        continue
                    # Neighbor mentions get half-credit
                    unit_scores[uid] = unit_scores.get(uid, 0.0) + 0.5

        ranked = sorted(unit_scores.items(), key=lambda kv: kv[1], reverse=True)
        return ranked[:top_n]

    # ------------------------------------------------------------------ RRF

    def _rrf_fuse(
        self,
        per_signal_ranks: dict[str, list[tuple[str, float]]],
        weights: dict[str, float],
    ) -> list[tuple[str, float, dict[str, dict[str, float]]]]:
        """Reciprocal Rank Fusion.

        Returns ``[(unit_id, fused_score, breakdown), ...]`` sorted desc,
        where breakdown is ``{signal: {rank: int, raw: float, contrib: float}}``.
        """
        k = self.k
        fused_scores: dict[str, float] = {}
        breakdown: dict[str, dict[str, dict[str, float]]] = {}

        for signal, ranked in per_signal_ranks.items():
            w = float(weights.get(signal, 1.0))
            for rank, (uid, raw) in enumerate(ranked, start=1):
                contrib = w / (k + rank)
                fused_scores[uid] = fused_scores.get(uid, 0.0) + contrib
                breakdown.setdefault(uid, {})[signal] = {
                    "rank": rank,
                    "raw": float(raw),
                    "contrib": contrib,
                }

        out: list[tuple[str, float, dict[str, dict[str, float]]]] = [
            (uid, score, breakdown.get(uid, {})) for uid, score in fused_scores.items()
        ]
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    # ------------------------------------------------------------ retrieve

    async def retrieve(
        self,
        query: str,
        top_k: int = 10,
        weights: Optional[dict[str, float]] = None,
    ) -> list[dict]:
        """Run all three signals in parallel, fuse via RRF, hydrate top-k."""
        if not query or not query.strip():
            return []

        eff_weights = dict(DEFAULT_WEIGHTS)
        if weights:
            for k_, v in weights.items():
                eff_weights[k_] = float(v)

        t0 = time.perf_counter()
        vec_task = asyncio.create_task(self._vector_ranks(query, FIRST_PASS_TOP_N))
        bm25_task = asyncio.create_task(self._bm25_ranks(query, FIRST_PASS_TOP_N))
        ent_task = asyncio.create_task(self._entity_ranks(query, FIRST_PASS_TOP_N))
        vector_r, bm25_r, entity_r = await asyncio.gather(
            vec_task, bm25_task, ent_task, return_exceptions=False
        )

        per_signal = {
            "vector": vector_r,
            "bm25": bm25_r,
            "entity": entity_r,
        }
        fused = self._rrf_fuse(per_signal, eff_weights)

        # ── Authority weighting ────────────────────────────────────────────
        # Multiply the raw RRF score by the unit's authority weight so a
        # NATRIX-tier unit (w=1.0) at modest rank beats a SCANNER-tier unit
        # (w=0.2) sitting at the top of every signal.
        #
        # The hydration pass is the cheapest place to know each unit's tier,
        # but a top-k slice taken BEFORE authority reranking would silently
        # drop a high-tier unit that landed at, say, RRF rank-15 — exactly
        # the case this whole system exists to fix. So we hydrate the
        # top-N×3 (capped at 60) candidate window first, apply authority
        # weighting, then take the final top-k.
        candidate_window = fused[: max(top_k * 3, 30)][:60]
        wanted_ids = {uid for uid, _, _ in candidate_window}
        units_by_id = await self.store._load_units_batch(wanted_ids) if wanted_ids else {}

        reweighted: list[tuple[str, float, float, float, dict]] = []
        # tuple: (uid, final_score, raw_rrf, authority_w, breakdown)
        for uid, raw_score, br in candidate_window:
            unit = units_by_id.get(uid)
            if not unit:
                # Unit pruned between rank time and hydrate — skip.
                continue
            meta = getattr(unit, "metadata", None) or {}
            tv = meta.get("authority_tier")
            if tv is None:
                tier = tier_for_source(getattr(unit, "source", ""))
                tv = int(tier)
            aw = authority_weight(int(tv))
            final = raw_score * aw
            reweighted.append((uid, final, raw_score, aw, br))

        reweighted.sort(key=lambda x: x[1], reverse=True)

        # 2026-05-22 cross-cutting quality directive: drop sub-threshold
        # noise so the top-k surfaces real matches. Tunable via env so
        # eval / debugging can lower it temporarily.
        import os
        try:
            min_fused = float(os.environ.get("NCL_FUSION_MIN_SCORE", "0.0"))
        except ValueError:
            min_fused = 0.0

        # ── Optional Cohere Rerank 3.5 cross-encoder ──────────────────────
        # When NCL_FUSION_RERANK_ENABLED=true, hydrate the top-30 RRF
        # candidates, hand them to Cohere for a relevance cross-pass, then
        # take final top_k. Graceful: any failure path returns the original
        # ordering, so this is safe to opt in.
        rerank_enabled = os.environ.get(
            "NCL_FUSION_RERANK_ENABLED", "false"
        ).strip().lower() in ("1", "true", "yes", "on")

        slice_n = 30 if rerank_enabled else max(top_k, 1)

        prelim: list[dict] = []
        for uid, final_score, raw_score, aw, br in reweighted[:slice_n]:
            if final_score < min_fused:
                continue
            unit = units_by_id[uid]
            meta = getattr(unit, "metadata", None) or {}
            tier_val = int(meta.get("authority_tier",
                                    int(tier_for_source(getattr(unit, "source", "")))))
            try:
                tier_name = AuthorityTier(tier_val).name.lower()
            except ValueError:
                tier_name = "raw"
            awarebot_tier = meta.get("tier") or meta.get("route_level")
            prelim.append({
                "unit_id": uid,
                "content": (unit.content[:500] + ("…" if len(unit.content) > 500 else "")),
                "source": unit.source,
                "importance": float(unit.importance),
                "memory_type": getattr(unit, "memory_type", "episodic"),
                "memory_tier": getattr(unit, "memory_tier", "SML"),
                "tags": list(unit.tags or []),
                "fused_score": round(final_score, 6),
                "rrf_score": round(raw_score, 6),
                "authority_tier": tier_val,
                "authority_tier_name": tier_name,
                "authority_weight": round(aw, 3),
                "tier": awarebot_tier,
                "signal_id": meta.get("signal_id"),
                "signal_breakdown": br,
            })

        if rerank_enabled and len(prelim) > 1:
            prelim = await self._rerank_with_cohere(query, prelim, top_k=top_k)

        results = prelim[: max(top_k, 1)]

        elapsed = round(time.perf_counter() - t0, 3)
        log.info(
            "[FUSION] q=%r top_k=%d vector=%d bm25=%d entity=%d fused=%d "
            "candidates=%d rerank=%s in %.3fs",
            query[:60], top_k,
            len(vector_r), len(bm25_r), len(entity_r), len(fused),
            len(candidate_window), "on" if rerank_enabled else "off", elapsed,
        )
        return results

    # ------------------------------------------------------- rerank wrapper

    async def retrieve_with_rerank(
        self,
        query: str,
        top_k: int = 10,
        weights: Optional[dict[str, float]] = None,
    ) -> list[dict]:
        """First-pass RRF top-N, then optional Haiku cross-encoder rerank.

        Controlled by ``NCL_FUSION_RERANK`` env var. When disabled,
        this is just a passthrough to ``retrieve()``.
        """
        first_pass = await self.retrieve(query, top_k=max(top_k * 5, 20), weights=weights)
        if not first_pass:
            return []
        if os.getenv("NCL_FUSION_RERANK", "0") not in ("1", "true", "yes"):
            return first_pass[:top_k]

        reranked = await self._haiku_rerank(query, first_pass, top_k)
        return reranked or first_pass[:top_k]

    async def _haiku_rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int,
    ) -> list[dict]:
        """Ask Claude Haiku to score each candidate 0-100 for relevance to
        the query, then return top_k sorted by Haiku score.

        On any failure (no API key, timeout, parse error, cost-cap), returns
        an empty list so the caller falls back to RRF order.
        """
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return []

        # Cost-cap awareness — skip the rerank if the anthropic source is
        # already over budget. Best-effort lookup.
        try:
            from ...cost_tracker import get_tracker
            tracker = await get_tracker()
            if hasattr(tracker, "can_spend"):
                ok, _ = await tracker.can_spend("anthropic", 0.01)
                if not ok:
                    log.info("[FUSION-RERANK] skipped — anthropic budget exhausted")
                    return []
        except Exception:
            pass

        # Compact JSON over the wire — index ↔ unit_id mapping is local.
        compact = [
            {"i": i, "text": (c["content"] or "")[:300]}
            for i, c in enumerate(candidates)
        ]
        prompt = (
            "Rank these memory snippets by relevance to the QUERY. "
            "Reply ONLY with JSON: {\"scores\": [[i, score_0_100], ...]}.\n\n"
            f"QUERY: {query}\n\nSNIPPETS:\n{json.dumps(compact, ensure_ascii=False)}"
        )

        try:
            import httpx
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 800,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
            if resp.status_code != 200:
                log.warning("[FUSION-RERANK] HTTP %d", resp.status_code)
                return []
            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "")
            text = re.sub(r"```json\s*", "", text)
            text = re.sub(r"```\s*", "", text)
            parsed = json.loads(text.strip())
            scores = parsed.get("scores", [])

            # Cost tracking
            try:
                from ...cost_tracker import record_cost
                usage = data.get("usage", {})
                in_t = usage.get("input_tokens", 0)
                out_t = usage.get("output_tokens", 0)
                # Haiku pricing (USD per 1M tokens, in/out)
                cost = (in_t * 0.80 + out_t * 4.00) / 1_000_000
                await record_cost("anthropic", cost, "fusion_rerank",
                                  f"rerank in={in_t} out={out_t}")
            except Exception:
                pass

            # Memory budget telemetry — log the prompt-context tokens fed
            # into the reranker. Prefer Anthropic's reported usage when
            # available, fall back to a chars/4 estimate of the prompt.
            try:
                from ..budget_tracker import record as _bt_record
                usage = data.get("usage", {}) or {}
                tokens_in = int(usage.get("input_tokens") or max(1, len(prompt) // 4))
                tokens_out = int(usage.get("output_tokens") or 0)
                await _bt_record(
                    "retrieval_rerank",
                    tokens_in,
                    tokens_out=tokens_out,
                    source=f"rerank:{len(candidates)}cands",
                )
            except Exception:
                pass

            score_map = {int(i): float(s) for i, s in scores if 0 <= int(i) < len(candidates)}
            if not score_map:
                return []
            ranked = sorted(
                candidates,
                key=lambda c: score_map.get(candidates.index(c), 0.0),
                reverse=True,
            )
            return ranked[:top_k]
        except Exception as e:
            log.warning("[FUSION-RERANK] failed: %s", e)
            return []

    # ------------------------------------------------- cohere rerank-3.5
    async def _rerank_with_cohere(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 10,
    ) -> list[dict]:
        """Second-pass cross-encoder rerank via Cohere Rerank 3.5.

        Graceful: returns candidates unchanged on every failure path —
        missing env key, missing ``cohere`` lib, budget exhausted, HTTP
        429/503, timeout, parse error. Only the happy path mutates ordering.

        Cost: Cohere rerank-3.5 is $2.00 per 1,000 searches (one search =
        one rerank call regardless of document count, up to the 4K
        document cap). We estimate $0.002 per call.
        """
        if not candidates:
            return candidates

        api_key = os.getenv("COHERE_API_KEY")
        if not api_key:
            log.debug("[FUSION:RERANK] skipped — no COHERE_API_KEY")
            return candidates

        try:
            import cohere  # type: ignore
        except ImportError:
            log.debug("[FUSION:RERANK] skipped — cohere lib not installed")
            return candidates

        # Budget gate — Cohere rerank ≈ $0.002 per call.
        try:
            from ...cost_tracker import get_tracker
            tracker = await get_tracker()
            ok = await tracker.can_spend("cohere", 0.002)
            if not ok:
                log.info("[FUSION:RERANK] skipped — cohere budget exhausted")
                return candidates
        except Exception as e:
            log.debug("[FUSION:RERANK] budget check failed (proceeding): %s", e)

        # Documents: keep them compact — Cohere will truncate at its own
        # token limit, but feeding the full 500-char content is fine.
        docs = [(c.get("content") or "")[:1000] for c in candidates]
        # Guard against empty-string docs which Cohere rejects.
        docs = [d if d.strip() else " " for d in docs]

        async def _call_cohere() -> object:
            client = cohere.AsyncClientV2(api_key=api_key)
            try:
                return await asyncio.wait_for(
                    client.rerank(
                        model="rerank-v3.5",
                        query=query,
                        documents=docs,
                        top_n=min(top_k, len(docs)),
                    ),
                    timeout=8.0,
                )
            finally:
                # AsyncClientV2 has a close() — call it if present.
                try:
                    close = getattr(client, "close", None)
                    if close:
                        await close()
                except Exception:
                    pass

        # Single retry on transient failure (429 / 503 / timeout).
        resp = None
        for attempt in (1, 2):
            try:
                resp = await _call_cohere()
                break
            except asyncio.TimeoutError:
                log.warning("[FUSION:RERANK] timeout (attempt %d)", attempt)
                if attempt == 2:
                    return candidates
                await asyncio.sleep(0.5)
            except Exception as e:
                msg = str(e)
                transient = any(s in msg for s in ("429", "503", "timeout", "Timeout"))
                if transient and attempt == 1:
                    log.warning("[FUSION:RERANK] transient err (retry): %s", msg[:120])
                    await asyncio.sleep(0.5)
                    continue
                log.warning("[FUSION:RERANK] failed: %s", msg[:200])
                return candidates

        if resp is None:
            return candidates

        # Parse cohere response — results is a list of objects with
        # .index and .relevance_score. Tolerate dict-shaped responses too.
        try:
            results = getattr(resp, "results", None)
            if results is None and isinstance(resp, dict):
                results = resp.get("results", [])
            if not results:
                log.warning("[FUSION:RERANK] failed: empty results")
                return candidates

            ranked: list[dict] = []
            for r in results:
                idx = getattr(r, "index", None)
                score = getattr(r, "relevance_score", None)
                if idx is None and isinstance(r, dict):
                    idx = r.get("index")
                    score = r.get("relevance_score")
                if idx is None or not (0 <= int(idx) < len(candidates)):
                    continue
                item = dict(candidates[int(idx)])
                if score is not None:
                    item["rerank_score"] = round(float(score), 6)
                ranked.append(item)
        except Exception as e:
            log.warning("[FUSION:RERANK] failed: parse error %s", e)
            return candidates

        # Record cost — flat $0.002 per search regardless of doc count.
        try:
            from ...cost_tracker import record_cost
            await record_cost(
                "cohere",
                0.002,
                "fusion_rerank",
                f"rerank-v3.5 cands={len(candidates)} top={len(ranked)}",
                model="rerank-v3.5",
                candidates=len(candidates),
            )
        except Exception:
            pass

        log.info(
            "[FUSION:RERANK] applied — model=rerank-v3.5 cands=%d top=%d",
            len(candidates), len(ranked),
        )
        return ranked[:top_k] if ranked else candidates
