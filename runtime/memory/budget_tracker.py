"""
NCL Memory Budget Tracker — per-tier context-window telemetry.

This is the **context-token** equivalent of `cost_tracker.py`. Where the
cost tracker counts dollars spent on outbound LLM API calls, this tracker
counts how many *tokens of context* the Brain is stuffing into prompts on
the way in. Without it, we have zero visibility into:

  • how much working-context we silently rebuild every day
  • how often `/chat` injects 8K tokens of memory per turn
  • when the Haiku reranker explodes from 100K → 800K tokens/day
  • whether procedural distillation is fanning out into Sonnet calls

Architecture
------------
  • JSONL append-only ledger at ``data/memory/budget_ledger.jsonl`` —
    every `record()` call writes one line. Crash-safe replay on init.
  • In-memory rolling daily summary (``self._daily_summary``) — the
    source of truth for ``check_budget()`` (must be <1ms).
  • UTC date rollover handled inside ``record()`` and the public
    summary getters.
  • Env overrides: ``NCL_MEMORY_BUDGET_<CATEGORY>=N`` (token count)
    and ``NCL_MEMORY_BUDGET_PLATFORM_CAP=N``.

Async safety: a single ``asyncio.Lock`` guards every mutation of the
in-memory summary and every JSONL append. ``check_budget()`` does *not*
take the lock (read-only snapshot read on stable dict slots).

Token estimation: callers pass a pre-computed token count. The
recommended estimator is ``len(text) // 4`` — fast, deterministic,
within ~15 % of tiktoken on English prose. This module never calls a
tokenizer of its own.

Scope boundary
--------------
This tracker counts **prompt context** sent into LLMs (the input side).
Outbound LLM responses are tracked by ``cost_tracker.py`` in dollars.
Do not double-count. A chat turn records:
  • budget_tracker.record("chat_injection", est_tokens_of_context)
  • cost_tracker.record_cost("anthropic", $$, "chat_response")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import aiofiles

log = logging.getLogger("ncl.memory.budget_tracker")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
MEMORY_DIR = NCL_BASE / "data" / "memory"
LEDGER_FILE = MEMORY_DIR / "budget_ledger.jsonl"
SUMMARY_FILE = MEMORY_DIR / "budget_summary.json"

# ── Default daily caps (tokens) ───────────────────────────────────────
# Tuned for the current swarm (May 2026). Most assume Claude Sonnet/Haiku
# context windows of 200K. Caps trip an alert at 100 %; 80 % warns in logs.
DEFAULT_BUDGETS: dict[str, int] = {
    "chat_injection":           500_000,   # /chat prepended context, all turns/day
    "council_context":          300_000,   # Delphi-MAD session shared context
    "working_context_assembly": 200_000,   # 6am / noon / 11pm context builds
    "retrieval_rerank":         100_000,   # Haiku reranker on /memory/search/fused
    "reflection":               150_000,   # journal + memory reflection prompts
    "procedural_distill":       100_000,   # Loop 7 — chain → skill abstraction
    "narrative_summary":         50_000,   # Loop 9 — Sonnet thread summaries
}

# Platform-wide ceiling across all categories. Trips a separate alert.
PLATFORM_DAILY_CAP_TOKENS: int = int(
    os.getenv("NCL_MEMORY_BUDGET_PLATFORM_CAP", "2000000")
)


@dataclass
class BudgetEntry:
    """One row in the JSONL ledger."""
    timestamp: str
    date: str
    category: str          # one of DEFAULT_BUDGETS keys (or arbitrary if extended)
    tokens_in: int
    tokens_out: int = 0
    source: str = ""       # subsystem id, e.g. "chat:session-abc", "council:tsla"
    metadata: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))


class MemoryBudgetTracker:
    """File-backed memory/context token tracker.

    Single instance per process via :func:`get_tracker`. Thread/asyncio
    safe via an internal ``asyncio.Lock``.
    """

    def __init__(self, ledger_path: Optional[Path] = None) -> None:
        self.ledger_path = Path(ledger_path) if ledger_path else LEDGER_FILE
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.ledger_path.parent / "budget_summary.json"

        # In-memory rolling summary: category -> {tokens_in, tokens_out, calls}
        self._daily_summary: dict[str, dict[str, int]] = defaultdict(
            lambda: {"tokens_in": 0, "tokens_out": 0, "calls": 0}
        )
        self._current_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._budgets: dict[str, int] = self._load_budgets()
        self._platform_cap: int = PLATFORM_DAILY_CAP_TOKENS
        self._warned: set[str] = set()  # categories that fired the 80% log line today
        self._lock = asyncio.Lock()
        self._initialized = False

    # ── budget config ────────────────────────────────────────────────
    def _load_budgets(self) -> dict[str, int]:
        """Apply env overrides on top of DEFAULT_BUDGETS."""
        budgets: dict[str, int] = dict(DEFAULT_BUDGETS)
        for cat in DEFAULT_BUDGETS:
            env_key = f"NCL_MEMORY_BUDGET_{cat.upper()}"
            v = os.getenv(env_key)
            if v is not None:
                try:
                    budgets[cat] = int(v)
                    log.info(
                        "[MEM-BUDGET] override %s = %s tokens/day (from %s)",
                        cat, f"{int(v):,}", env_key,
                    )
                except ValueError:
                    log.warning("[MEM-BUDGET] invalid override %s=%r", env_key, v)
        return budgets

    # ── lifecycle ────────────────────────────────────────────────────
    async def initialize(self) -> None:
        """Replay today's ledger rows so cumulative totals survive restart."""
        if self._initialized:
            return
        async with self._lock:
            if self._initialized:
                return
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            await self._replay_today()
            self._initialized = True
            total = sum(s["tokens_in"] for s in self._daily_summary.values())
            log.info(
                "[MEM-BUDGET] initialized — %d categories, today=%d tokens "
                "across %d calls",
                len(self._budgets), total,
                sum(s["calls"] for s in self._daily_summary.values()),
            )

    async def _replay_today(self) -> None:
        if not self.ledger_path.exists():
            return
        today = self._current_date
        n = 0
        try:
            async with aiofiles.open(self.ledger_path, "r") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if e.get("date") != today:
                        continue
                    cat = e.get("category", "unknown")
                    bucket = self._daily_summary[cat]
                    bucket["tokens_in"] += int(e.get("tokens_in", 0) or 0)
                    bucket["tokens_out"] += int(e.get("tokens_out", 0) or 0)
                    bucket["calls"] += 1
                    n += 1
        except Exception as ex:
            log.warning("[MEM-BUDGET] replay failed: %s", ex)
        if n:
            log.info("[MEM-BUDGET] replayed %d entries for %s", n, today)

    def _check_rollover(self) -> None:
        """Reset the in-memory totals at UTC midnight. Caller holds the lock."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            log.info(
                "[MEM-BUDGET] date rollover %s -> %s. Yesterday: %d tokens "
                "across %d calls.",
                self._current_date, today,
                sum(s["tokens_in"] for s in self._daily_summary.values()),
                sum(s["calls"] for s in self._daily_summary.values()),
            )
            self._daily_summary.clear()
            self._warned.clear()
            self._current_date = today

    # ── public: record ───────────────────────────────────────────────
    async def record(
        self,
        category: str,
        tokens_in: int,
        tokens_out: int = 0,
        source: str = "",
        metadata: Optional[dict] = None,
    ) -> None:
        """Persist one entry and bump the in-memory daily summary.

        Args:
            category: usually a DEFAULT_BUDGETS key, but arbitrary strings
                are accepted (caps default to 0 = uncapped for new categories).
            tokens_in: prompt/context tokens fed *into* the LLM.
            tokens_out: optional response tokens (most callers leave at 0;
                cost_tracker covers $$ on the response side).
            source: subsystem id ("chat:session-abc", "council:tsla", ...).
            metadata: optional dict written to the JSONL row.
        """
        await self.initialize()

        now = datetime.now(timezone.utc)
        entry = BudgetEntry(
            timestamp=now.isoformat(),
            date=now.strftime("%Y-%m-%d"),
            category=category,
            tokens_in=int(max(0, tokens_in)),
            tokens_out=int(max(0, tokens_out)),
            source=str(source)[:200],
            metadata=dict(metadata or {}),
        )

        async with self._lock:
            self._check_rollover()
            bucket = self._daily_summary[category]
            bucket["tokens_in"] += entry.tokens_in
            bucket["tokens_out"] += entry.tokens_out
            bucket["calls"] += 1

            # 80% warn (logs only; the scheduler loop dispatches ntfy)
            cap = self._budgets.get(category, 0)
            if cap > 0 and bucket["tokens_in"] >= int(cap * 0.8) and category not in self._warned:
                self._warned.add(category)
                log.warning(
                    "[MEM-BUDGET] %s at %d%% of daily cap (%s / %s tokens)",
                    category,
                    int(bucket["tokens_in"] / cap * 100),
                    f"{bucket['tokens_in']:,}", f"{cap:,}",
                )

            try:
                async with aiofiles.open(self.ledger_path, "a") as f:
                    await f.write(entry.to_json() + "\n")
            except Exception as ex:
                log.error("[MEM-BUDGET] ledger append failed: %s", ex)

        log.debug(
            "[MEM-BUDGET] %s in=%d out=%d source=%s",
            category, entry.tokens_in, entry.tokens_out, source,
        )

    # ── public: check ────────────────────────────────────────────────
    async def check_budget(self, category: str, est_tokens: int) -> tuple[bool, str]:
        """Fast (<1 ms) budget gate.

        Returns ``(allowed, reason)``. ``allowed`` is False when either the
        per-category cap or the platform-wide cap would be exceeded by
        adding ``est_tokens`` to the current daily total. Caps of 0 mean
        "uncapped".

        This is intentionally lock-free — it reads dict slots that are
        only ever mutated under the lock, and Python dict reads are
        atomic. The worst-case staleness is one in-flight ``record()``.
        """
        # Lazy init from a fast path: if the tracker hasn't replayed yet,
        # we don't want to take the lock here. Treat un-initialized as a
        # zero-state allow.
        if not self._initialized:
            return True, "uninitialized"

        # Rollover check is racy here but the worst case is a stale
        # over-count, which trips the cap one minute early.
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            return True, "rollover-pending"

        est = int(max(0, est_tokens))
        bucket = self._daily_summary.get(
            category, {"tokens_in": 0, "tokens_out": 0, "calls": 0}
        )

        # Platform-wide check
        platform_total = sum(s["tokens_in"] for s in self._daily_summary.values())
        if self._platform_cap > 0 and platform_total + est > self._platform_cap:
            return False, (
                f"platform cap exceeded: {platform_total + est:,} > "
                f"{self._platform_cap:,} tokens"
            )

        # Per-category check
        cap = self._budgets.get(category, 0)
        if cap <= 0:
            return True, "uncapped"

        projected = bucket["tokens_in"] + est
        if projected > cap:
            return False, (
                f"{category} cap exceeded: {projected:,} > {cap:,} tokens"
            )
        if projected >= int(cap * 0.8):
            return True, (
                f"{category} at {int(projected / cap * 100)}% of cap"
            )
        return True, "ok"

    # ── public: summary ──────────────────────────────────────────────
    async def get_daily_summary(self) -> dict:
        """Return today's rolling summary, ready to JSON-encode."""
        await self.initialize()

        async with self._lock:
            self._check_rollover()
            by_category: dict[str, dict] = {}
            total_in = 0
            for cat, bucket in self._daily_summary.items():
                cap = self._budgets.get(cat, 0)
                pct = (bucket["tokens_in"] / cap * 100) if cap > 0 else 0.0
                by_category[cat] = {
                    "tokens_in": bucket["tokens_in"],
                    "tokens_out": bucket["tokens_out"],
                    "calls": bucket["calls"],
                    "cap": cap,
                    "pct_of_cap": round(pct, 2),
                    "blocked": (cap > 0 and bucket["tokens_in"] >= cap),
                }
                total_in += bucket["tokens_in"]

            # Surface caps that have not yet seen traffic so the UI can
            # show every category without forcing a record() first.
            for cat, cap in self._budgets.items():
                if cat not in by_category:
                    by_category[cat] = {
                        "tokens_in": 0, "tokens_out": 0, "calls": 0,
                        "cap": cap, "pct_of_cap": 0.0, "blocked": False,
                    }

            platform_pct = (
                (total_in / self._platform_cap * 100)
                if self._platform_cap > 0 else 0.0
            )

            return {
                "date": self._current_date,
                "total_tokens": total_in,
                "platform_cap": self._platform_cap,
                "platform_pct": round(platform_pct, 2),
                "by_category": by_category,
            }

    async def get_history(self, days: int = 7) -> list[dict]:
        """Aggregate the JSONL ledger into per-day summaries for the last N days.

        Reads the whole ledger — for large ledgers this could grow, but
        with a default ~few hundred entries/day and a 7-day window the
        I/O is bounded. The scheduler loop persists daily snapshots to
        ``budget_summary.json`` so consumers needing older history can
        prefer that path.
        """
        await self.initialize()
        cutoff_date = (
            datetime.now(timezone.utc) - timedelta(days=max(0, days - 1))
        ).strftime("%Y-%m-%d")

        rollup: dict[str, dict] = {}
        if not self.ledger_path.exists():
            return []

        try:
            async with aiofiles.open(self.ledger_path, "r") as f:
                async for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    date = e.get("date", "")
                    if date < cutoff_date:
                        continue
                    cat = e.get("category", "unknown")
                    day = rollup.setdefault(
                        date,
                        {"date": date, "total_tokens": 0, "by_category": {}},
                    )
                    cb = day["by_category"].setdefault(
                        cat, {"tokens_in": 0, "tokens_out": 0, "calls": 0}
                    )
                    cb["tokens_in"] += int(e.get("tokens_in", 0) or 0)
                    cb["tokens_out"] += int(e.get("tokens_out", 0) or 0)
                    cb["calls"] += 1
                    day["total_tokens"] += int(e.get("tokens_in", 0) or 0)
        except Exception as ex:
            log.warning("[MEM-BUDGET] history read failed: %s", ex)

        return sorted(rollup.values(), key=lambda d: d["date"])

    # ── persistence helper used by the scheduler loop ────────────────
    async def persist_summary_snapshot(self) -> Path:
        """Atomically write today's summary to ``budget_summary.json``.

        Used by the autonomous scheduler loop (and any operator triage
        script) to make today's state cheaply readable without having
        to scan the JSONL.
        """
        summary = await self.get_daily_summary()
        # Atomic write: temp file + os.replace (POSIX atomic on the same
        # filesystem). Avoid aiofiles for the rename because we want to
        # block on the durable move.
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(self.summary_path.parent),
            prefix=".budget_summary_", suffix=".tmp",
        )
        try:
            with os.fdopen(tmp_fd, "w") as f:
                json.dump(summary, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.summary_path)
        except Exception as ex:
            log.error("[MEM-BUDGET] snapshot persist failed: %s", ex)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return self.summary_path


# ── Singleton accessor ────────────────────────────────────────────────

_tracker_instance: Optional[MemoryBudgetTracker] = None
_tracker_lock = asyncio.Lock()


async def get_tracker() -> MemoryBudgetTracker:
    """Return (creating on first call) the per-process tracker singleton."""
    global _tracker_instance
    if _tracker_instance is None:
        async with _tracker_lock:
            if _tracker_instance is None:
                t = MemoryBudgetTracker()
                await t.initialize()
                _tracker_instance = t
    return _tracker_instance


def get_tracker_sync() -> Optional[MemoryBudgetTracker]:
    """Non-async access — only valid after `get_tracker()` has been awaited
    at least once. Returns None otherwise. Used by sync hot-paths that
    cannot await."""
    return _tracker_instance


# ── Convenience helpers ───────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Cheap token estimator: ~4 chars/token. Good enough for budget
    gating; never use for billing math."""
    if not text:
        return 0
    return max(1, len(text) // 4)


async def record(
    category: str,
    tokens_in: int,
    tokens_out: int = 0,
    source: str = "",
    metadata: Optional[dict] = None,
) -> None:
    """Module-level convenience that records via the singleton."""
    t = await get_tracker()
    await t.record(category, tokens_in, tokens_out, source, metadata)


async def check_budget(category: str, est_tokens: int) -> tuple[bool, str]:
    """Module-level convenience that checks via the singleton."""
    t = await get_tracker()
    return await t.check_budget(category, est_tokens)


# ── Scheduler loop (drop into AutonomousScheduler) ────────────────────
# The actual `_memory_budget_loop` method must live on the scheduler
# class so it can touch `self._stats`. The canonical body is documented
# in the integration spec; this module exposes the worker function so
# tests can exercise it without spinning up the scheduler.

async def run_budget_cycle(stats: Optional[dict] = None) -> dict:
    """One full budget-check tick. Returns the persisted summary.

    Steps:
      1. Read today's summary.
      2. If any per-category pct >= 100, enqueue a per-category ntfy alert.
      3. If platform pct >= 100, enqueue a platform alert.
      4. Persist the summary snapshot.
      5. Update ``stats`` (the scheduler's ``self._stats`` dict).
    """
    tracker = await get_tracker()
    summary = await tracker.get_daily_summary()
    date = summary["date"]

    # Best-effort import — the dispatcher lives in runtime.notifications.
    try:
        from ..notifications import enqueue_alert
    except Exception:  # pragma: no cover
        enqueue_alert = None  # type: ignore

    # Platform-wide alert
    if summary["platform_pct"] >= 100.0 and enqueue_alert is not None:
        try:
            enqueue_alert(
                title="NCL MEMORY BUDGET — PLATFORM CAP",
                body=(
                    f"Context spend {summary['total_tokens']:,} / "
                    f"{summary['platform_cap']:,} tokens ({summary['platform_pct']:.0f}%). "
                    f"Tracker will keep recording but consumers should back off."
                ),
                priority="5",
                tags="rotating_light,brain",
                dedup_key=f"mem-budget-platform-{date}",
                source="memory_budget_tracker",
            )
        except Exception as ex:  # pragma: no cover
            log.warning("[MEM-BUDGET] platform alert enqueue failed: %s", ex)

    # Per-category alerts
    if enqueue_alert is not None:
        for cat, info in summary["by_category"].items():
            if info["cap"] > 0 and info["pct_of_cap"] >= 100.0:
                try:
                    enqueue_alert(
                        title=f"NCL Memory Budget — {cat}",
                        body=(
                            f"{cat} used {info['tokens_in']:,} / "
                            f"{info['cap']:,} tokens ({info['pct_of_cap']:.0f}%) "
                            f"over {info['calls']} calls."
                        ),
                        priority="4",
                        tags="warning,brain",
                        dedup_key=f"mem-budget-{cat}-{date}",
                        source="memory_budget_tracker",
                    )
                except Exception as ex:  # pragma: no cover
                    log.warning("[MEM-BUDGET] %s alert enqueue failed: %s", cat, ex)

    try:
        await tracker.persist_summary_snapshot()
    except Exception as ex:
        log.warning("[MEM-BUDGET] snapshot failed: %s", ex)

    if stats is not None:
        stats["last_memory_budget_check"] = datetime.now(timezone.utc).isoformat()
        stats["last_memory_budget_total_tokens"] = summary["total_tokens"]
        stats["last_memory_budget_platform_pct"] = summary["platform_pct"]

    return summary
