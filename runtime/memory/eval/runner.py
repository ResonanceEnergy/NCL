"""Memory eval harness (Loop 2).

Hand-graded retrieval-quality regression tests for the NCL memory store.
Computes hit@5, hit@10, MRR, recall@10 against a fixed Q/A set.

Persists per-run results to ``data/memory/eval/results-YYYY-MM-DD.json`` and
exposes a ``compare_to_baseline`` helper that diffs the current run against
the most recent prior run on disk.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

from ...config import flags


log = logging.getLogger("ncl.memory.eval")


# ── SQLite units-index fast path (W6-A) ───────────────────────────────────
#
# The weekly eval harness loads the entire corpus once per ``run_eval``
# cycle. When ``NCL_UNITS_INDEX_SQLITE=true``, try the SQLite ``units_index``
# table first (W4-14, store.py:_search_units_via_sqlite_index) — same
# semantic result, no JSONL full-scan. Falls back to ``search_units`` on
# flag-off or ANY failure — flag-off behavior is bit-identical to before
# this retrofit so eval correctness is preserved.
async def _maybe_indexed_search(memory_store, **kwargs):
    """Drop-in replacement for ``memory_store.search_units(**kwargs)``."""
    if flags.units_index_sqlite():
        try:
            unit_ids = await memory_store._search_units_via_sqlite_index(**kwargs)
            if unit_ids:
                units_by_id = await memory_store._load_units_batch(set(unit_ids))
                return [units_by_id[uid] for uid in unit_ids if uid in units_by_id]
        except Exception as e:
            log.debug("[EVAL] sqlite index search failed (%s) — falling back", e)
    return await memory_store.search_units(**kwargs)


# ─── Optional dependency: rank_bm25 ──────────────────────────────────────
# Loop 11 may already ship a shared BM25 retriever at
# runtime/memory/retrieval/bm25.py. If so, prefer it. Otherwise fall back
# to the rank_bm25 package, then to a minimal in-module implementation
# (so the harness still runs in CI containers without the package).
try:
    from ..retrieval.bm25 import BM25Retriever  # type: ignore

    _HAVE_SHARED_BM25 = True
except Exception:
    _HAVE_SHARED_BM25 = False

try:  # pragma: no cover — exercised when rank_bm25 is installed
    from rank_bm25 import BM25Okapi  # type: ignore

    _HAVE_RANK_BM25 = True
except Exception:
    _HAVE_RANK_BM25 = False


_TOKEN_RE = re.compile(r"[A-Za-z0-9_$]+")


def _tokenize(text: str) -> list[str]:
    """Cheap word-level tokenizer — lowercased alphanum + $/_."""
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


class _MiniBM25:
    """Minimal BM25 implementation with an inverted index — used only when
    no faster ranker is available. Inverted-index design keeps per-query cost
    proportional to the number of postings for the query terms, not |corpus|.
    """

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.N = max(1, len(corpus_tokens))
        self.doc_len = [len(d) for d in corpus_tokens]
        self.avgdl = (sum(self.doc_len) / self.N) if self.N else 1.0
        # Inverted index: term -> list[(doc_id, tf)]
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for doc_id, doc in enumerate(corpus_tokens):
            tf_local: dict[str, int] = {}
            for tok in doc:
                tf_local[tok] = tf_local.get(tok, 0) + 1
            for tok, f in tf_local.items():
                self.postings.setdefault(tok, []).append((doc_id, f))
        # Cache IDF per term
        self._idf_cache: dict[str, float] = {}

    def _idf(self, term: str) -> float:
        cached = self._idf_cache.get(term)
        if cached is not None:
            return cached
        df = len(self.postings.get(term, ()))
        val = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))
        self._idf_cache[term] = val
        return val

    def get_scores(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self.N
        if self.avgdl == 0:
            return scores
        k1 = self.k1
        b = self.b
        avgdl = self.avgdl
        doc_len = self.doc_len
        # Deduplicate query terms — repeated tokens give same score contribution
        for term in set(query_tokens):
            postings = self.postings.get(term)
            if not postings:
                continue
            idf = self._idf(term)
            if idf <= 0:
                continue
            for doc_id, f in postings:
                dl = doc_len[doc_id] or 1
                denom = f + k1 * (1.0 - b + b * dl / avgdl)
                scores[doc_id] += idf * (f * (k1 + 1.0)) / denom
        return scores


# ─── Eval runner ─────────────────────────────────────────────────────────


class MemoryEvalRunner:
    """Run the weekly memory retrieval eval and diff against the prior run."""

    DEFAULT_LIMIT = 10
    REGRESSION_THRESHOLD = 0.05  # 5 percentage points

    def __init__(
        self,
        memory_store: Any,
        working_context: Optional[Any] = None,
        questions_path: Optional[Path | str] = None,
        results_dir: Optional[Path | str] = None,
    ) -> None:
        self.memory_store = memory_store
        self.working_context = working_context
        self.questions_path = Path(
            questions_path or (Path(__file__).resolve().parent / "questions.jsonl")
        )
        # ``data/memory/eval/`` next to the live units.jsonl by default.
        if results_dir is not None:
            self.results_dir = Path(results_dir)
        else:
            data_dir = getattr(memory_store, "data_dir", None)
            if data_dir is not None:
                # MemoryStore.data_dir points at .../memory; results sit beside it.
                self.results_dir = Path(data_dir) / "eval"
            else:
                self.results_dir = Path("data/memory/eval")
        self.results_dir.mkdir(parents=True, exist_ok=True)

    # ───── question loading ─────

    async def load_questions(self) -> list[dict]:
        if not self.questions_path.exists():
            raise FileNotFoundError(f"questions file missing: {self.questions_path}")
        async with aiofiles.open(self.questions_path, "r", encoding="utf-8") as f:
            raw = await f.read()
        questions: list[dict] = []
        for ln, line in enumerate(raw.splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                q = json.loads(line)
            except json.JSONDecodeError as e:
                log.warning("questions.jsonl line %d invalid JSON: %s", ln, e)
                continue
            # Validate required fields
            if not all(k in q for k in ("id", "question", "expected_keywords")):
                log.warning("questions.jsonl line %d missing required field", ln)
                continue
            q.setdefault("min_units", 1)
            q.setdefault("category", "uncategorized")
            q["expected_keywords"] = [str(k).lower() for k in q["expected_keywords"]]
            questions.append(q)
        return questions

    # ───── retrieval ─────

    async def _load_corpus(self) -> tuple[list[Any], list[list[str]]]:
        """Load all memory units and tokenize once per ``run_eval`` cycle."""
        try:
            units = await _maybe_indexed_search(self.memory_store, days_back=None)
        except TypeError:
            units = await _maybe_indexed_search(self.memory_store)
        except Exception as e:
            log.error("search_units failed: %s", e)
            return [], []
        tokens: list[list[str]] = []
        for u in units:
            content = getattr(u, "content", "") or ""
            tags = getattr(u, "tags", None) or []
            tag_str = " ".join(tags) if isinstance(tags, list) else ""
            tokens.append(_tokenize(f"{content} {tag_str}"))
        return units, tokens

    def _build_ranker(self, corpus_tokens: list[list[str]]):
        """Return a BM25 ranker with a ``.get_scores`` method."""
        if _HAVE_SHARED_BM25:
            try:
                return BM25Retriever(corpus_tokens)  # type: ignore[call-arg]
            except Exception as e:
                log.debug("shared BM25 init failed (%s) — falling back", e)
        if _HAVE_RANK_BM25:
            return BM25Okapi(corpus_tokens)  # type: ignore[arg-type]
        return _MiniBM25(corpus_tokens)

    async def _retrieve(self, query_text: str, limit: int = DEFAULT_LIMIT) -> list[Any]:
        """Retrieve up to ``limit`` memory units ranked for ``query_text``.

        Single-query convenience path — re-builds the corpus on each call. Use
        the ``run_eval`` flow when scoring many questions in sequence (it
        reuses one ranker across the whole batch).
        """
        units, corpus_tokens = await self._load_corpus()
        if not units:
            return []
        q_tokens = _tokenize(query_text)
        if not q_tokens:
            return units[:limit]
        ranker = self._build_ranker(corpus_tokens)
        scores = ranker.get_scores(q_tokens)
        ranked = sorted(zip(units, scores), key=lambda x: float(x[1]), reverse=True)
        return [u for u, s in ranked[:limit] if s > 0] or [u for u, _ in ranked[:limit]]

    # ───── metric math ─────

    @staticmethod
    def _unit_text(unit: Any) -> str:
        content = getattr(unit, "content", "") or ""
        tags = getattr(unit, "tags", None) or []
        if isinstance(tags, list):
            content = f"{content} {' '.join(tags)}"
        return content.lower()

    @classmethod
    def _matches_all_keywords(cls, unit: Any, keywords: list[str]) -> bool:
        text = cls._unit_text(unit)
        return all(kw.lower() in text for kw in keywords)

    @classmethod
    def _keyword_coverage(cls, units: list[Any], keywords: list[str]) -> float:
        """Fraction of expected keywords that appear in ANY of the supplied units."""
        if not keywords:
            return 1.0
        joined = " ".join(cls._unit_text(u) for u in units)
        hit = sum(1 for kw in keywords if kw.lower() in joined)
        return hit / len(keywords)

    @classmethod
    def _first_hit_rank(cls, units: list[Any], keywords: list[str]) -> Optional[int]:
        for i, u in enumerate(units, start=1):
            if cls._matches_all_keywords(u, keywords):
                return i
        return None

    @classmethod
    def score_question(cls, units: list[Any], question: dict) -> dict:
        """Score retrieval for a single question — returns metrics dict."""
        keywords = question.get("expected_keywords", [])
        top5 = units[:5]  # noqa: F841
        top10 = units[:10]
        rank = cls._first_hit_rank(top10, keywords)
        hit5 = bool(rank is not None and rank <= 5)
        hit10 = bool(rank is not None and rank <= 10)
        mrr = (1.0 / rank) if rank else 0.0
        recall = cls._keyword_coverage(top10, keywords)
        min_units = int(question.get("min_units", 1))
        passing_units = sum(1 for u in top10 if any(kw in cls._unit_text(u) for kw in keywords))
        return {
            "hit5": hit5,
            "hit10": hit10,
            "mrr": mrr,
            "recall10": recall,
            "first_hit_rank": rank,
            "retrieved": len(units),
            "min_units_met": passing_units >= min_units,
        }

    # ───── full run ─────

    async def run_eval(self) -> dict:
        """Execute the full eval suite and persist results."""
        questions = await self.load_questions()
        if not questions:
            raise RuntimeError("no questions loaded — refusing to write empty result")

        per_q: list[dict] = []
        categories: dict[str, dict[str, list[float]]] = {}

        # Load + tokenize the full corpus ONCE per cycle, then build a
        # single BM25 ranker. This is the hot path — 50 questions * 10k
        # units cannot afford to rebuild the index for each question.
        units_all, corpus_tokens = await self._load_corpus()
        ranker = self._build_ranker(corpus_tokens) if corpus_tokens else None

        for q in questions:
            if ranker is None:
                retrieved: list[Any] = []
            else:
                q_tokens = _tokenize(q["question"])
                if not q_tokens:
                    retrieved = units_all[: self.DEFAULT_LIMIT]
                else:
                    scores = ranker.get_scores(q_tokens)
                    ranked = sorted(
                        zip(units_all, scores),
                        key=lambda x: float(x[1]),
                        reverse=True,
                    )
                    retrieved = [u for u, s in ranked[: self.DEFAULT_LIMIT] if s > 0] or [
                        u for u, _ in ranked[: self.DEFAULT_LIMIT]
                    ]
            metrics = self.score_question(retrieved, q)
            entry = {
                "id": q["id"],
                "category": q["category"],
                "question": q["question"],
                **metrics,
            }
            per_q.append(entry)
            cat = q["category"]
            bucket = categories.setdefault(
                cat, {"hit5": [], "hit10": [], "mrr": [], "recall10": []}
            )
            bucket["hit5"].append(1.0 if metrics["hit5"] else 0.0)
            bucket["hit10"].append(1.0 if metrics["hit10"] else 0.0)
            bucket["mrr"].append(metrics["mrr"])
            bucket["recall10"].append(metrics["recall10"])

        def _avg(xs: list[float]) -> float:
            return (sum(xs) / len(xs)) if xs else 0.0

        agg = {
            "hit5": _avg([1.0 if e["hit5"] else 0.0 for e in per_q]),
            "hit10": _avg([1.0 if e["hit10"] else 0.0 for e in per_q]),
            "mrr": _avg([e["mrr"] for e in per_q]),
            "recall10": _avg([e["recall10"] for e in per_q]),
        }

        per_category = {
            cat: {k: _avg(v) for k, v in scores.items()} for cat, scores in categories.items()
        }

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "date": datetime.now(timezone.utc).date().isoformat(),
            "question_count": len(per_q),
            "aggregate": agg,
            "per_category": per_category,
            "per_question": per_q,
            "retriever": (
                "shared-bm25"
                if _HAVE_SHARED_BM25
                else "rank_bm25"
                if _HAVE_RANK_BM25
                else "minibm25"
            ),
        }

        await self._persist_result(result)
        return result

    async def _persist_result(self, result: dict) -> None:
        """Atomic write to data/memory/eval/results-YYYY-MM-DD.json."""
        out = self.results_dir / f"results-{result['date']}.json"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(result, indent=2, default=str)
        # Atomic write — tmp file in the same dir then os.replace
        fd, tmp_path = tempfile.mkstemp(
            prefix=".results-",
            suffix=".json.tmp",
            dir=str(self.results_dir),
        )
        try:
            os.close(fd)
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as f:
                await f.write(payload)
            os.replace(tmp_path, out)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        log.info("memory eval results persisted: %s", out)

    # ───── baseline diff ─────

    def _list_prior_results(self) -> list[Path]:
        if not self.results_dir.exists():
            return []
        return sorted(self.results_dir.glob("results-*.json"))

    async def _load_result_file(self, path: Path) -> dict:
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            raw = await f.read()
        return json.loads(raw)

    async def compare_to_baseline(self, current: Optional[dict] = None) -> dict:
        """Diff the latest result against the prior run.

        Returns ``{"regression": bool, "deltas": {...}, "baseline_date": str|None,
        "current_date": str, "threshold": float}``.
        """
        prior_files = self._list_prior_results()

        if current is None:
            if not prior_files:
                return {
                    "regression": False,
                    "deltas": {},
                    "baseline_date": None,
                    "current_date": None,
                    "threshold": self.REGRESSION_THRESHOLD,
                    "reason": "no prior runs",
                }
            current = await self._load_result_file(prior_files[-1])
            # Baseline is the second-to-last
            baseline_file = prior_files[-2] if len(prior_files) >= 2 else None
        else:
            current_date = current.get("date")
            baseline_file = None
            for p in reversed(prior_files):
                if current_date and p.stem == f"results-{current_date}":
                    continue
                baseline_file = p
                break

        if baseline_file is None:
            return {
                "regression": False,
                "deltas": {},
                "baseline_date": None,
                "current_date": current.get("date"),
                "threshold": self.REGRESSION_THRESHOLD,
                "reason": "no baseline available",
            }

        baseline = await self._load_result_file(baseline_file)
        deltas: dict[str, float] = {}
        regression = False
        for metric in ("hit5", "hit10", "mrr", "recall10"):
            cur = float(current.get("aggregate", {}).get(metric, 0.0))
            base = float(baseline.get("aggregate", {}).get(metric, 0.0))
            delta = cur - base
            deltas[metric] = delta
            if delta < -self.REGRESSION_THRESHOLD:
                regression = True

        return {
            "regression": regression,
            "deltas": deltas,
            "baseline_date": baseline.get("date"),
            "current_date": current.get("date"),
            "threshold": self.REGRESSION_THRESHOLD,
        }


__all__ = ["MemoryEvalRunner"]
