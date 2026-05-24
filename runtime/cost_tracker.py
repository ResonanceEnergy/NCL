"""
NCL Cost Tracker — File-backed, per-source budget enforcement.

Replaces the dead Paperclip integration with a real, crash-safe cost
ledger that survives restarts. Every API call that costs money should
call `record()` — the tracker enforces daily per-source budgets with
hard stops and emits warnings at 80%.

Architecture:
  - JSONL append-only log: `data/costs/cost_ledger.jsonl`
  - Daily summary cache: `data/costs/daily_summary.json`
  - Budget config: loaded from config.py defaults, overridable via .env

Thread-safe via asyncio.Lock. Singleton via `get_tracker()`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from .config import flags


log = logging.getLogger("ncl.cost_tracker")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))
COST_DIR = NCL_BASE / "data" / "costs"
LEDGER_FILE = COST_DIR / "cost_ledger.jsonl"
DAILY_SUMMARY_FILE = COST_DIR / "daily_summary.json"

# ── SQLite double-write feature flag (Wave 2 persistence migration) ───
# When NCL_COST_LEDGER_SQLITE=true, every record() call ALSO writes to
# the SQLite cost_ledger table. The JSONL write remains the source of
# truth — SQLite failures NEVER block the JSONL append. Default OFF
# until we've double-written for ~1 week and confirmed the counts match.
#
# W10B-1 (2026-05-24): the per-call env check + lazy import + warn-once
# logic that used to live inline here is now owned by DoubleWriteHook
# (runtime.persistence.double_write). The module-level constant below
# is kept for back-compat (tests + diagnostics still read it) but the
# hot path no longer consults it — DoubleWriteHook.enabled() reads
# NCL_COST_LEDGER_SQLITE fresh on every call.
SQLITE_DOUBLE_WRITE = flags.cost_ledger_sqlite()

# ── Default daily budget caps (in USD) ────────────────────────────────
# Override via environment: NCL_BUDGET_X=5.00, NCL_BUDGET_ANTHROPIC=10.00, etc.
#
# 2026-05-23 COST EMERGENCY rebalance:
#   Brain hit $29/day (145% over $20 platform cap). Old per-source sum was
#   $23, which exceeded platform $20 — the math was broken by construction.
#   New defaults SUM to exactly $20.00 and scale-to-fit the platform cap
#   with explicit reservations. Anthropic dominates because Sonnet 4 powers
#   async_writer enrichment + chat + council chair + memory scoring.
DEFAULT_DAILY_BUDGETS: dict[str, float] = {
    "anthropic": 12.00,  # Claude — chair, async_writer, /chat, scoring
    # (lowered 15→12 to fit platform $20)
    "openai": 2.00,  # GPT-4o — council member + Whisper
    "xai": 2.00,  # Grok — council member + fallback
    "google": 1.00,  # Gemini — council member (lowered 2→1)
    "perplexity": 1.00,  # Sonar Pro — council member (lowered 2→1)
    "cohere": 1.00,  # Cohere Rerank 3.5 cross-encoder for FusedRetriever
    "others": 1.00,  # Catch-all reservation for unknown / new paid sources
    # ── Free / subscription / token-disabled sources (do not contribute) ──
    "x_twitter": 0.00,  # ON HOLD — subscription expired, 402 (May 19)
    "gnews": 0.00,  # NewsAPI free tier
    "unusual_whales": 0.00,  # Subscription — no per-call cost
    "coingecko": 0.00,  # Free tier
    "polymarket": 0.00,  # Free
    "google_trends": 0.00,  # Free
    "ollama": 0.00,  # Local — free
    "youtube_data": 0.00,  # Free tier (quota-based)
    "reddit": 0.00,  # Free (RSS + public API)
    "ytc": 0.00,  # No own pool — bills against anthropic/xai
}
# Sum of paid sources = 12 + 2 + 2 + 1 + 1 + 1 + 1 = $20.00 (= platform cap)

# Hard platform-wide daily cap (all sources combined)
PLATFORM_DAILY_CAP: float = float(os.getenv("NCL_BUDGET_PLATFORM_CAP", "20.00"))

# Producer-side admission soft-block threshold (fraction of source cap).
# Below 100% (hard block) — gives upstream callers a chance to back off
# *before* they make the request and burn money racing the drainer.
ADMISSION_SOFT_BLOCK_PCT: float = float(os.getenv("NCL_COST_ADMISSION_PCT", "0.80"))


# ── Startup invariant assertion ──────────────────────────────────────
# If per-source caps sum greater than platform cap, the platform cap will
# silently override and individual sources won't see their full budget.
# Log a loud warning so this gets caught at boot.
def _assert_budget_invariant() -> None:
    paid_sum = sum(v for v in DEFAULT_DAILY_BUDGETS.values() if v > 0)
    if paid_sum > PLATFORM_DAILY_CAP:
        log.warning(
            "[COST] BUDGET INVARIANT VIOLATED: per-source sum $%.2f > platform cap $%.2f. "
            "Platform cap will throttle individual sources before they hit their nominal limit.",
            paid_sum,
            PLATFORM_DAILY_CAP,
        )
    else:
        log.info(
            "[COST] Budget invariant OK: per-source sum $%.2f <= platform cap $%.2f",
            paid_sum,
            PLATFORM_DAILY_CAP,
        )


_assert_budget_invariant()

# Known cost rates per API (USD per unit)
# These are approximate — used for estimation when exact cost isn't provided
COST_RATES: dict[str, dict] = {
    "x_twitter": {
        "tweet_read": 0.01,  # ~$0.01 per tweet read (Basic tier)
        "user_lookup": 0.005,
    },
    "anthropic": {
        "input_1k_tokens": 0.003,  # Claude 3.5 Sonnet
        "output_1k_tokens": 0.015,
        "council_run_est": 0.25,  # Estimated per council run
    },
    "xai": {
        "input_1k_tokens": 0.005,  # Grok
        "output_1k_tokens": 0.015,
        "council_run_est": 0.10,
    },
    "openai": {
        "whisper_per_minute": 0.006,
    },
    # Perplexity (Sonar family) — added Wave-8 2026-05-24.
    # NOTE: flat baseline rate ($1/M tok in/out) is a *floor* — real cost
    # varies by model: sonar-pro ≈ $5/M tok in/out + per-request search fees,
    # sonar ≈ $1/M tok. Refine per-model if/when council adopts sonar-pro
    # heavily. The platform $20/day cap is no longer the only gate — the
    # per-source NCL_BUDGET_PERPLEXITY ($1.00 default) now hard-stops at cap.
    "perplexity": {
        "input_1k_tokens": 0.001,  # $1/M tok baseline (sonar)
        "output_1k_tokens": 0.001,  # $1/M tok baseline (sonar)
        "council_run_est": 0.05,  # Estimated per council member turn
    },
}


class CostTracker:
    """
    File-backed cost tracker with per-source daily budget enforcement.

    Usage:
        tracker = await get_tracker()

        # Check before making an expensive call
        if not await tracker.can_spend("anthropic", 0.25):
            log.warning("Anthropic daily budget exceeded — skipping")
            return

        # Record after the call succeeds
        await tracker.record("anthropic", 0.25, "council_run", "Council session abc123")
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._daily_totals: dict[str, float] = defaultdict(float)  # source -> USD today
        self._daily_counts: dict[str, int] = defaultdict(int)  # source -> call count today
        self._current_date: str = ""  # YYYY-MM-DD
        self._budgets: dict[str, float] = {}
        self._warned_sources: set[str] = set()  # Sources that hit 80% warning today
        self._initialized = False
        # SQLite double-write side-channel. Lazily initialized so the
        # tracker still works if persistence/ isn't importable in some env.
        self._sqlite_store = None  # type: ignore[assignment]
        self._sqlite_warned: bool = False
        # Eager-load budgets so callers can introspect `tracker.budgets` /
        # `tracker.platform_cap` before async initialize() runs (smoke tests).
        self._load_budgets()

    @property
    def budgets(self) -> dict[str, float]:
        """Public view of currently-loaded per-source daily caps."""
        return dict(self._budgets)

    @property
    def platform_cap(self) -> float:
        """Public view of the platform-wide daily cap."""
        return PLATFORM_DAILY_CAP

    async def initialize(self) -> None:
        """Load budgets and replay today's ledger entries."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            COST_DIR.mkdir(parents=True, exist_ok=True)
            self._load_budgets()
            self._current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await self._replay_today()
            self._initialized = True

            log.info(
                "[COST] Tracker initialized — %d sources configured, "
                "today's spend: $%.4f across %d calls",
                len(self._budgets),
                sum(self._daily_totals.values()),
                sum(self._daily_counts.values()),
            )

    def _load_budgets(self) -> None:
        """Load budget caps from defaults + environment overrides."""
        self._budgets = dict(DEFAULT_DAILY_BUDGETS)
        for source, default in DEFAULT_DAILY_BUDGETS.items():
            env_key = f"NCL_BUDGET_{source.upper()}"
            env_val = os.getenv(env_key)
            if env_val is not None:
                try:
                    self._budgets[source] = float(env_val)
                    log.info(
                        f"[COST] Budget override: {source} = ${float(env_val):.2f}/day (from {env_key})"  # noqa: E501
                    )
                except ValueError:
                    log.warning(
                        f"[COST] Invalid budget override {env_key}={env_val}, using default ${default:.2f}"  # noqa: E501
                    )

    async def _replay_today(self) -> None:
        """Replay today's JSONL entries to rebuild daily totals after restart."""
        if not LEDGER_FILE.exists():
            return

        today = self._current_date
        count = 0
        try:
            with open(LEDGER_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("date") == today:
                            source = entry.get("source", "unknown")
                            amount = entry.get("amount_usd", 0.0)
                            self._daily_totals[source] += amount
                            self._daily_counts[source] += 1
                            count += 1
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning(f"[COST] Error replaying ledger: {e}")

        if count > 0:
            log.info(f"[COST] Replayed {count} entries for {today}")

    def _check_date_rollover(self) -> None:
        """Reset daily totals at midnight UTC."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._current_date:
            log.info(
                f"[COST] Date rollover {self._current_date} → {today}. "
                f"Yesterday's total: ${sum(self._daily_totals.values()):.4f}"
            )
            # Save yesterday's summary before reset
            self._save_daily_summary()
            self._daily_totals.clear()
            self._daily_counts.clear()
            self._warned_sources.clear()
            self._current_date = today

    async def can_spend(self, source: str, estimated_usd: float = 0.0) -> bool:
        """
        Check if a source has budget remaining for the estimated cost.

        Returns True if:
          - Source has no budget cap (budget == 0.0, meaning unlimited/free)
          - Source has budget remaining after the estimated cost

        Returns False if spending would exceed the daily budget or platform cap.
        """
        await self.initialize()

        async with self._lock:
            self._check_date_rollover()

            # Platform-wide cap check
            platform_total = sum(self._daily_totals.values())
            if platform_total + estimated_usd > PLATFORM_DAILY_CAP:
                msg = (
                    f"🛑 PLATFORM CAP HIT — Total spend ${platform_total:.2f} "
                    f"exceeds ${PLATFORM_DAILY_CAP:.2f}/day. ALL paid calls blocked."
                )
                log.warning(f"[COST] {msg}")
                if "_platform" not in self._warned_sources:
                    self._warned_sources.add("_platform")
                    asyncio.get_event_loop().create_task(
                        self._send_budget_notification(msg, priority="5")
                    )
                return False

            budget = self._budgets.get(source, 0.0)
            if budget <= 0.0:
                return True  # No cap (free source or unlimited)

            current = self._daily_totals.get(source, 0.0)

            # 80% warning
            if current >= budget * 0.8 and source not in self._warned_sources:
                self._warned_sources.add(source)
                warn_msg = (
                    f"⚠️ {source} at {current/budget*100:.0f}% of daily budget "
                    f"(${current:.4f} / ${budget:.2f})"
                )
                log.warning(f"[COST] {warn_msg}")
                asyncio.get_event_loop().create_task(
                    self._send_budget_notification(warn_msg, priority="4")
                )

            if current + estimated_usd > budget:
                msg = (
                    f"🛑 {source} BUDGET HIT — "
                    f"${current:.4f} / ${budget:.2f} daily cap. Calls blocked."
                )
                log.warning(f"[COST] {msg}")
                # Send push notification on first hit
                cap_key = f"_cap_{source}"
                if cap_key not in self._warned_sources:
                    self._warned_sources.add(cap_key)
                    asyncio.get_event_loop().create_task(
                        self._send_budget_notification(msg, priority="5")
                    )
                return False

            return True

    async def can_admit(self, source: str, est_cost_usd: float = 0.0) -> bool:
        """
        Producer-side admission control — returns False at SOFT threshold
        (default 80% of source cap), before the hard 100% block.

        Use this in upstream callers (Awarebot scoring, async_writer
        enrichment, council pre-checks) to back off *before* the call
        is made. `can_spend()` remains the hard 100% gate that the
        record path uses.

        Returns:
            True   — under soft threshold, OK to admit the request
            False  — above soft threshold OR platform cap, caller should back off
        """
        await self.initialize()

        async with self._lock:
            self._check_date_rollover()

            # Platform cap remains the hard outer ring — same rule as can_spend
            platform_total = sum(self._daily_totals.values())
            if platform_total + est_cost_usd > PLATFORM_DAILY_CAP:
                return False

            budget = self._budgets.get(source, 0.0)
            if budget <= 0.0:
                return True  # No cap (free source) — admit

            current = self._daily_totals.get(source, 0.0)
            soft_threshold = budget * ADMISSION_SOFT_BLOCK_PCT
            return (current + est_cost_usd) <= soft_threshold

    async def _send_budget_notification(self, message: str, priority: str = "4") -> None:
        """Send push notification for budget warnings/caps.

        Args:
            message: Alert text
            priority: ntfy priority — "4" for 80% warning, "5" for hard cap
        """
        # Preferred path: enqueue via centralized AlertDispatcher (rate limited + deduped).
        # Falls back to direct HTTP POST if the dispatcher import fails (test envs, etc.).
        try:
            from .notifications import enqueue_alert  # local import to avoid cycles

            tags = (
                "rotating_light,money_with_wings" if priority == "5" else "warning,money_with_wings"
            )
            safe_title = "NCL COST ALERT" if priority == "5" else "NCL Cost Warning"
            # Dedup at the cost layer: one warn + one cap per source per day handled by
            # _warned_sources; here we add a short cooldown so even repeated invocations
            # within the same minute coalesce.
            dedup = f"cost:{priority}:{message[:40]}"
            enqueue_alert(
                title=safe_title,
                body=message,
                priority=priority,
                tags=tags,
                dedup_key=dedup,
                source="cost_tracker",
            )
            log.info(f"[COST] ntfy alert enqueued (priority={priority}): {message[:60]}")
            return
        except Exception as enq_err:
            log.warning(
                f"[COST] AlertDispatcher unavailable, falling back to direct POST: {enq_err}"
            )

        try:
            import httpx

            # Fallback: direct ntfy
            ntfy_topic = os.getenv("NTFY_TOPIC", "ncl-natrix-intel-7x9k")
            ntfy_server = os.getenv("NTFY_SERVER", "https://ntfy.sh")
            if ntfy_topic:
                tags = (
                    "rotating_light,money_with_wings"
                    if priority == "5"
                    else "warning,money_with_wings"
                )
                safe_title = "NCL COST ALERT" if priority == "5" else "NCL Cost Warning"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        f"{ntfy_server}/{ntfy_topic}",
                        content=message.encode("utf-8"),
                        headers={
                            "Content-Type": "text/plain; charset=utf-8",
                            "Title": safe_title,
                            "Priority": priority,
                            "Tags": tags,
                        },
                    )
                log.info(f"[COST] ntfy push sent (priority={priority}): {message[:60]}")
                return

            # Try Pushover
            pushover_token = os.getenv("PUSHOVER_APP_TOKEN")
            pushover_user = os.getenv("PUSHOVER_USER_KEY")
            if pushover_token and pushover_user:
                pushover_priority = 2 if priority == "5" else 1
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(
                        "https://api.pushover.net/1/messages.json",
                        data={
                            "token": pushover_token,
                            "user": pushover_user,
                            "title": "NCL Cost Alert",
                            "message": message,
                            "priority": pushover_priority,
                        },
                    )
                log.info(f"[COST] Push notification sent via Pushover: {message[:60]}")
                return

            log.info(
                f"[COST] No push service configured — budget alert logged only: {message[:80]}"
            )

        except Exception as e:
            log.warning(f"[COST] Failed to send budget notification: {e}")

    async def record(
        self,
        source: str,
        amount_usd: float,
        category: str,
        detail: str = "",
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Record a cost event to the JSONL ledger and update daily totals.

        Args:
            source: API provider (e.g., "anthropic", "x_twitter", "xai")
            amount_usd: Cost in USD
            category: What the money bought (e.g., "council_run", "tweet_search", "whisper")
            detail: Human-readable description
            metadata: Optional dict with extra info (model, tokens, etc.)
        """
        await self.initialize()

        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "source": source,
            "amount_usd": round(amount_usd, 6),
            "category": category,
            "detail": detail[:200],
        }
        if metadata:
            entry["metadata"] = metadata

        async with self._lock:
            self._check_date_rollover()
            self._daily_totals[source] += amount_usd
            self._daily_counts[source] += 1

            # Append to JSONL (crash-safe — append-only)
            try:
                COST_DIR.mkdir(parents=True, exist_ok=True)
                with open(LEDGER_FILE, "a") as f:
                    f.write(json.dumps(entry) + "\n")
            except Exception as e:
                log.error(f"[COST] Failed to write ledger: {e}")

        # SQLite double-write side-channel (Wave 2 migration; refactored
        # under W10B-1 to use the unified DoubleWriteHook). The hook
        # owns the env-flag check + lazy store import + warn-once
        # semantics. The call is outside the JSONL lock branch + NEVER
        # raises — a SQLite outage cannot block cost recording.
        await self._sqlite_hook().try_write(entry)

        log.debug(f"[COST] {source}/{category}: ${amount_usd:.4f} — {detail[:60]}")

    # ── SQLite side-channel ──────────────────────────────────────────

    async def _ensure_sqlite_store(self):
        """
        Lazy import + init the SqliteStore. Returns None if the module
        is unavailable (test env etc.) — callers are expected to handle.
        """
        if self._sqlite_store is not None:
            return self._sqlite_store
        try:
            from .persistence import get_store  # local import to avoid cycles
        except Exception as e:
            log.warning(f"[COST] persistence module not importable: {e}")
            return None
        self._sqlite_store = await get_store()
        return self._sqlite_store

    # W10B-1: row mapping for the DoubleWriteHook. Mapping still mirrors
    # scripts/migrate_cost_ledger_to_sqlite.py exactly so a migrated row
    # and a live-double-written row are bit-identical.
    @staticmethod
    def _build_cost_row(entry: dict):
        metadata = entry.get("metadata") or {}
        if entry.get("detail"):
            metadata.setdefault("detail", entry["detail"])

        model = metadata.get("model") if isinstance(metadata, dict) else None
        input_tokens = metadata.get("input_tokens") if isinstance(metadata, dict) else None
        output_tokens = metadata.get("output_tokens") if isinstance(metadata, dict) else None
        est = metadata.get("est_cost_usd") if isinstance(metadata, dict) else None

        return (
            entry.get("timestamp"),
            entry.get("date"),
            entry.get("source"),
            model,
            entry.get("category"),
            est,
            float(entry.get("amount_usd", 0.0)),
            int(input_tokens) if input_tokens is not None else None,
            int(output_tokens) if output_tokens is not None else None,
            json.dumps(metadata, separators=(",", ":")) if metadata else None,
        )

    def _sqlite_hook(self):
        """Lazily build (and cache) the DoubleWriteHook for cost_ledger.

        Constructed on first use so the persistence module import only
        runs when the tracker is actually invoked — keeps test
        environments that never touch cost recording free of the
        runtime.persistence dependency.
        """
        hook = getattr(self, "_cost_hook", None)
        if hook is not None:
            return hook
        from .persistence import DoubleWriteHook

        hook = DoubleWriteHook[dict](
            env_flag="NCL_COST_LEDGER_SQLITE",
            table="cost_ledger",
            columns=(
                "ts", "date_utc", "source", "model", "purpose",
                "est_cost_usd", "actual_cost_usd",
                "input_tokens", "output_tokens", "metadata",
            ),
            build_row=CostTracker._build_cost_row,
            conflict_strategy="ignore",
            log_prefix="[COST]",
        )
        self._cost_hook = hook
        return hook

    async def query_today_by_source_sqlite(self) -> dict[str, dict]:
        """
        SQL-aggregation replacement for the in-memory daily rollup.

        Not wired into the live rollup yet — exposed so an admin /
        diagnostic endpoint can verify SQLite totals match the in-memory
        totals during the double-write window.

        Returns:
            { source: { "calls": int, "spent_usd": float } }
            Empty dict if SQLite is not enabled or initialization fails.
        """
        store = await self._ensure_sqlite_store()
        if store is None:
            return {}

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = await store.fetch_all(
            """
            SELECT source,
                   COUNT(*)               AS calls,
                   SUM(actual_cost_usd)   AS spent_usd
              FROM cost_ledger
             WHERE date_utc = ?
          GROUP BY source
            """,
            (today,),
        )
        return {
            r["source"]: {"calls": int(r["calls"]), "spent_usd": float(r["spent_usd"] or 0.0)}
            for r in rows
        }

    async def get_daily_summary(self) -> dict:
        """Return today's cost summary by source."""
        await self.initialize()

        async with self._lock:
            self._check_date_rollover()
            sources = {}
            for source in set(list(self._daily_totals.keys()) + list(self._budgets.keys())):
                spent = self._daily_totals.get(source, 0.0)
                budget = self._budgets.get(source, 0.0)
                calls = self._daily_counts.get(source, 0)
                sources[source] = {
                    "spent_usd": round(spent, 6),
                    "budget_usd": budget,
                    "calls": calls,
                    "remaining_usd": round(max(0, budget - spent), 6) if budget > 0 else None,
                    "pct_used": round(spent / budget * 100, 1) if budget > 0 else 0.0,
                    "blocked": spent >= budget if budget > 0 else False,
                }

            return {
                "date": self._current_date,
                "total_spent_usd": round(sum(self._daily_totals.values()), 6),
                "total_calls": sum(self._daily_counts.values()),
                "sources": sources,
            }

    async def get_historical(self, days: int = 30) -> list[dict]:
        """Read the daily summary history for the last N days."""
        await self.initialize()

        if not DAILY_SUMMARY_FILE.exists():
            return []

        try:
            data = json.loads(DAILY_SUMMARY_FILE.read_text())
            history = data.get("history", [])
            return history[-days:]
        except Exception:
            return []

    async def get_full_ledger(self, days: int = 7) -> list[dict]:
        """Read raw ledger entries for the last N days."""
        await self.initialize()

        if not LEDGER_FILE.exists():
            return []

        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        entries = []
        try:
            with open(LEDGER_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if entry.get("date", "") >= cutoff_date:
                            entries.append(entry)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            log.warning(f"[COST] Error reading ledger: {e}")

        return entries

    def _save_daily_summary(self) -> None:
        """Save the completed day's summary to the history file."""
        if not self._daily_totals:
            return

        summary = {
            "date": self._current_date,
            "total_usd": round(sum(self._daily_totals.values()), 6),
            "total_calls": sum(self._daily_counts.values()),
            "by_source": {
                source: {
                    "spent_usd": round(amount, 6),
                    "calls": self._daily_counts.get(source, 0),
                }
                for source, amount in self._daily_totals.items()
            },
        }

        try:
            history_data = {"history": []}
            if DAILY_SUMMARY_FILE.exists():
                history_data = json.loads(DAILY_SUMMARY_FILE.read_text())

            history = history_data.get("history", [])
            history.append(summary)
            # Keep last 90 days
            history = history[-90:]
            history_data["history"] = history

            COST_DIR.mkdir(parents=True, exist_ok=True)
            DAILY_SUMMARY_FILE.write_text(json.dumps(history_data, indent=2))
        except Exception as e:
            log.error(f"[COST] Failed to save daily summary: {e}")


# ── Singleton ─────────────────────────────────────────────────────────

_tracker_instance: Optional[CostTracker] = None
_tracker_lock = asyncio.Lock()


async def get_tracker() -> CostTracker:
    """Get or create the singleton CostTracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CostTracker()
        await _tracker_instance.initialize()
    return _tracker_instance


# ── Convenience helpers ───────────────────────────────────────────────


async def check_budget(source: str, estimated_usd: float = 0.01, *, soft: bool = True) -> bool:
    """
    Quick check: can this source afford another call?

    Args:
        source: API provider key (e.g., "anthropic", "xai")
        estimated_usd: Estimated cost of the upcoming call
        soft: If True (default), apply producer-side admission control
              at 80% of the source cap (caller backs off early).
              If False, only the hard 100% cap is checked.
    """
    tracker = await get_tracker()
    if soft:
        # Soft-block first — admission control gives callers a chance to
        # gracefully degrade before the hard cap blocks them entirely.
        if not await tracker.can_admit(source, estimated_usd):
            return False
    return await tracker.can_spend(source, estimated_usd)


async def record_cost(
    source: str,
    amount_usd: float,
    category: str,
    detail: str = "",
    **metadata,
) -> None:
    """Quick record: log a cost event."""
    tracker = await get_tracker()
    await tracker.record(source, amount_usd, category, detail, metadata or None)
