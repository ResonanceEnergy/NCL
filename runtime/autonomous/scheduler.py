"""
NCL Autonomous Scheduler
========================

Background task scheduler that makes NCL a true autonomous second brain.
Runs continuous loops for:

1. Intelligence Scanning (Awarebot) — X/YouTube/Reddit monitoring
2. Future Prediction — Ensemble forecasting with convergence detection
3. Council Auto-Spawn — Triggers council deliberation on high-signal events
4. Memory Consolidation — Periodic merge and decay processing
5. AAC War Room Sync — Pulls market regime data from AAC forecasters
6. MWP Workspace Health — Monitors pipeline stage health

All intervals are configurable via ncl.yaml or environment variables.
"""

import asyncio
import fcntl
import json
import logging
import os
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles

from ..ncl_brain.models import InsightSignal
from ..governance.emergency_stop import EMERGENCY_STOP_EVENT
from .signal_processor import SignalProcessor
from ..journal.store import JournalStore
from ..journal.reflection_engine import ReflectionEngine, ContextAwareTips
from ..awarebot.agent import Awarebot
from ..memory.working_context import DailyContextWindow

log = logging.getLogger("ncl.autonomous")


def _json_safe(obj: Any) -> Any:
    """Fallback for json.dumps(default=...). Handles sets, datetimes, Pydantic, Path."""
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    return str(obj)


class AutonomousScheduler:
    """
    Background task scheduler for NCL autonomous operations.

    Spawns asyncio tasks on startup that run indefinitely,
    performing intelligence gathering, prediction, and council
    deliberation without requiring pump prompts from NATRIX.
    """

    def __init__(
        self,
        brain,  # NCLBrain instance
        config,  # Settings instance
        councils_runner=None,  # councils.runner module (optional)
        intelligence_engine=None,  # IntelligenceEngine instance (optional)
        emergency_stop=None,  # EmergencyStop instance (optional)
    ):
        self.brain = brain
        self.config = config
        self.councils_runner = councils_runner
        self.intelligence_engine = intelligence_engine
        self.emergency_stop = emergency_stop  # EmergencyStop instance

        self.data_dir = Path(config.data_dir).expanduser()
        self.signals_dir = self.data_dir / "autonomous_signals"
        self.signals_dir.mkdir(parents=True, exist_ok=True)

        # State tracking
        self._tasks: list[asyncio.Task] = []
        # _stop_event must be created before the _running property is accessed.
        # Starts as "set" (stopped state); start() clears it.
        self._stop_event: asyncio.Event = asyncio.Event()
        self._stop_event.set()  # initially stopped
        self._stats = {
            "scans_completed": 0,
            "predictions_run": 0,
            "councils_auto_spawned": 0,
            "memory_consolidations": 0,
            "aac_syncs": 0,
            "high_signals_detected": 0,
            "started_at": None,
            "last_scan": None,
            "last_prediction": None,
            "last_council": None,
            "last_consolidation": None,
            "last_aac_sync": None,
            "intel_briefs_generated": 0,
            "intel_collections_run": 0,
            "intel_alerts_pushed": 0,
            "last_intel_brief": None,
            "last_intel_collection": None,
        }

        # Signal buffer — bounded deque to prevent unbounded accumulation
        # Capped at 1000 entries; oldest signals are dropped automatically
        self._signal_buffer: deque[dict] = deque(maxlen=1000)
        self._signal_lock = asyncio.Lock()
        self._last_collected_signals: list | None = None  # Cached for brief loop (C3 fix)
        self._working_context = None  # Initialized eagerly in start()
        self._journal_store: Optional[JournalStore] = None  # Initialized in start()
        self._reflection_engine = None

        # Council trigger threshold (importance score 0-100)
        self.council_trigger_threshold = 75.0
        # Minimum signals needed before auto-spawning a council
        self.council_min_signals = 3

        # Unified Signal Processor — central routing hub for all loops
        self.signal_processor = SignalProcessor(
            memory_store=brain.memory_store,
            working_context=None,  # Set in start() before tasks spawn
            signal_buffer=self._signal_buffer,
            signal_lock=self._signal_lock,
            data_dir=self.data_dir,
        )

        # ── Unified Awarebot Agent ─────────────────────────────────────
        # Awarebot runs its own event loop, handling all intelligence
        # scanning, predictions, briefs, and collection in one agent.
        self.awarebot: Optional[Awarebot] = None

    @property
    def _running(self) -> bool:
        """Derived from _stop_event for backward compat — True when NOT stopped."""
        return not self._stop_event.is_set()

    async def start(self) -> None:
        """Start all autonomous background loops."""
        if not self._stop_event.is_set() and self._tasks:
            log.warning("Autonomous scheduler already running")
            return

        self._stop_event.clear()
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()

        log.info("=" * 60)
        log.info("NCL AUTONOMOUS SCHEDULER — STARTING")
        log.info("=" * 60)
        log.info(f"  Scanner intervals: X={self.config.x_scan_interval}s, "
                 f"YT={self.config.youtube_scan_interval}s")
        log.info(f"  Prediction interval: {self.config.prediction_interval}s")
        log.info(f"  Memory consolidation: {self.config.memory_consolidation_interval}s")
        log.info(f"  Council trigger threshold: {self.council_trigger_threshold}")
        if self.intelligence_engine:
            log.info(f"  Intel brief interval: {self.config.intelligence_brief_interval}s")
            log.info(f"  Intel collection interval: {self.config.intelligence_collection_interval}s")
        log.info(f"  Working context: 6am assembly, noon refresh, 11pm EOD")
        log.info(f"  Journal reflection: 10pm ET daily")
        log.info("=" * 60)

        # ── Initialize Working Context Window (eager) ────────────────
        # Must be created before Awarebot/JournalStore so they can
        # reference it immediately.  Eliminates the 30-second 503 window
        # that occurred when DailyContextWindow lived in the background loop.
        try:
            self._working_context = DailyContextWindow(
                data_dir=self.data_dir,
                memory_store=self.brain.memory_store,
            )
            self.signal_processor.working_context = self._working_context
            log.info("  Working context window: INITIALIZED (eager)")
        except Exception as e:
            log.error(f"  Working context window: FAILED to initialize: {e}", exc_info=True)
            # _working_context stays None; endpoints will 503 but scheduler won't crash

        # ── Initialize Awarebot Agent ─────────────────────────────────
        # Awarebot unifies: scanner, collectors, signal processor,
        # predictions, briefs, context management, journal processing.
        try:
            self.awarebot = Awarebot(
                config=self.config,
                scanner=getattr(self.brain, "scanner", None),
                predictor=getattr(self.brain, "predictor", None),
                intelligence_engine=self.intelligence_engine,
                memory_store=self.brain.memory_store if self.brain else None,
                working_context=self._working_context,
                journal_store=None,  # Set below after JournalStore init
            )
            log.info("  Awarebot agent: ACTIVE (unified intelligence pipeline)")
        except Exception as e:
            log.error(f"  Awarebot agent: FAILED to initialize: {e}")
            self.awarebot = None

        # Journal system
        try:
            self._journal_store = JournalStore(
                data_dir=str(self.data_dir),
                memory_store=self.brain.memory_store if self.brain else None,
                working_context=self._working_context,
            )
            self._reflection_engine = ReflectionEngine(self._journal_store)
            # Wire journal store into Awarebot for cross-referencing
            if self.awarebot:
                self.awarebot.journal_store = self._journal_store
            log.info("  Journal reflection loop: 10pm ET daily")
        except ImportError:
            log.warning("Journal module not available — reflection loop disabled")

        # Spawn background tasks
        self._tasks = [
            asyncio.create_task(self._council_auto_loop(), name="ncl-council-auto"),
            asyncio.create_task(self._memory_consolidation_loop(), name="ncl-memory"),
            asyncio.create_task(self._aac_sync_loop(), name="ncl-aac-sync"),
            asyncio.create_task(self._workspace_health_loop(), name="ncl-workspace"),
            asyncio.create_task(self._mandate_purge_loop(), name="ncl-mandate-purge"),
            asyncio.create_task(self._feedback_synthesis_loop(), name="ncl-feedback-synth"),
            asyncio.create_task(self._heartbeat_loop(), name="ncl-heartbeat"),
            asyncio.create_task(self._working_context_loop(), name="ncl-working-ctx"),
        ]

        # Awarebot runs its own event loop (replaces scanner, intel, brief, prediction loops)
        if self.awarebot:
            self._tasks.append(
                asyncio.create_task(self.awarebot.run(), name="ncl-awarebot-agent")
            )

        # Journal reflection task (needs _journal_store to exist)
        if self._journal_store and self._reflection_engine:
            self._tasks.append(
                asyncio.create_task(self._journal_reflection_loop(), name="ncl-journal-reflection")
            )

        # Attach a done-callback to every task so a silent crash (unobserved
        # task exception) gets logged instead of disappearing.
        def _task_done(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                log.error(
                    f"[SCHEDULER] task '{task.get_name()}' DIED: "
                    f"{type(exc).__name__}: {exc!r}",
                    exc_info=exc,
                )
        for t in self._tasks:
            t.add_done_callback(_task_done)
        await self._log_autonomous_event("scheduler_started", {
            "loops": [t.get_name() for t in self._tasks],
            "config": {
                "x_scan_interval": self.config.x_scan_interval,
                "youtube_scan_interval": self.config.youtube_scan_interval,
                "reddit_scan_interval": self.config.reddit_scan_interval,
                "prediction_interval": self.config.prediction_interval,
                "memory_consolidation_interval": self.config.memory_consolidation_interval,
                "council_trigger_threshold": self.council_trigger_threshold,
            },
        })

    async def stop(self) -> None:
        """Gracefully stop all background loops.

        Sets _stop_event so loops break cleanly (the _running property
        derives from _stop_event — no separate flag to desync).
        Cancels all asyncio tasks and waits for them to finish.
        """
        log.warning("[SCHEDULER] stop() called — cancelling %d tasks", len(self._tasks))
        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("[SCHEDULER] All tasks stopped")
        await self._log_autonomous_event("scheduler_stopped", self._stats)

    def _emergency_stop_active(self) -> bool:
        """Return True if the emergency stop kill switch is engaged.

        Delegates solely to EMERGENCY_STOP_EVENT (the single source of truth)
        so all loops—regardless of which check style they use—see the same state.
        The EmergencyStop instance is kept for activation/deactivation calls only.
        """
        return EMERGENCY_STOP_EVENT.is_set()

    def get_stats(self) -> dict:
        """Return scheduler statistics."""
        stats = {
            **self._stats,
            "running": self._running,
            "active_tasks": [t.get_name() for t in self._tasks if not t.done()],
            "signal_buffer_size": len(self._signal_buffer),
            "signal_processor": self.signal_processor.get_stats(),
        }
        if self.awarebot:
            stats["awarebot"] = self.awarebot.get_stats()
        if self._journal_store:
            stats["journal"] = self._journal_store.get_stats()
        return stats

    # ─── LOOP 3: Council Auto-Spawn ────────────────────────────

    async def _council_auto_loop(self) -> None:
        """
        Monitor for conditions that warrant autonomous council deliberation.

        Triggers a council session when:
        - Multiple high-importance signals converge on a theme
        - Prediction ensemble detects convergence with high confidence
        - A critical signal exceeds the council trigger threshold
        - Scheduled strategic review interval is reached

        Councils run autonomously but mandates still require NATRIX approval.
        """
        # Strategic review interval (4 hours default)
        strategic_review_interval = 4 * 3600
        last_strategic_review = datetime.now(timezone.utc)

        # Wait for initial data gathering
        await asyncio.sleep(self.config.prediction_interval + 60)

        while self._running:
            # Halt council spawning on emergency stop
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[COUNCIL-AUTO] Emergency stop active — halting loop")
                break

            try:
                now = datetime.now(timezone.utc)
                council_needed = False
                council_prompt = ""
                council_trigger = ""

                # Check 1: Pending council flags from prediction/scanner
                council_flags = await self._get_council_flags()
                if len(council_flags) >= self.council_min_signals:
                    council_needed = True
                    council_trigger = "accumulated_signals"
                    themes = set()
                    for flag in council_flags:
                        themes.update(flag.get("data", {}).get("tags", []))
                    council_prompt = (
                        f"AUTONOMOUS COUNCIL — {len(council_flags)} high-priority signals detected. "
                        f"Themes: {', '.join(list(themes)[:10])}. "
                        f"Analyze these converging signals, assess implications for NARTIX operations, "
                        f"and recommend strategic actions or mandate adjustments."
                    )

                # Check 2: Scheduled strategic review
                elif (now - last_strategic_review).total_seconds() >= strategic_review_interval:
                    council_needed = True
                    council_trigger = "strategic_review"
                    council_prompt = (
                        "SCHEDULED STRATEGIC REVIEW — Conduct a periodic assessment of: "
                        "1) Active mandate progress and blockers, "
                        "2) Intelligence signals and emerging opportunities, "
                        "3) Resource allocation and budget status, "
                        "4) Risk factors and mitigation strategies. "
                        "Produce recommendations for NATRIX review."
                    )
                    last_strategic_review = now

                if council_needed:
                    log.info(f"[COUNCIL-AUTO] Spawning autonomous council: {council_trigger}")
                    try:
                        # Create a synthetic pump prompt for the council
                        session = await self.brain.council_engine.spawn_council(
                            prompt=council_prompt,
                            context={
                                "trigger": council_trigger,
                                "autonomous": True,
                                "signal_count": len(council_flags) if council_flags else 0,
                                "timestamp": now.isoformat(),
                            },
                        )

                        if session:
                            # Store council output in memory
                            await self.brain.memory_store.create_unit(
                                content=(
                                    f"Autonomous council ({council_trigger}): "
                                    f"{session.get('consensus', '')[:500]}"
                                ),
                                source=f"autonomous:council:{council_trigger}",
                                importance=90.0,
                                tags=["council", "autonomous", council_trigger],
                            )

                            # Clear processed flags
                            await self._clear_council_flags()

                            self._stats["councils_auto_spawned"] += 1
                            self._stats["last_council"] = now.isoformat()

                            log.info(f"[COUNCIL-AUTO] Session complete — "
                                     f"consensus={session.get('consensus_score', 0):.0f}%")

                            await self._log_autonomous_event("council_auto_spawned", {
                                "trigger": council_trigger,
                                "consensus_score": session.get("consensus_score", 0),
                                "mandates_proposed": len(session.get("mandates", [])),
                            })

                    except Exception as e:
                        log.error(f"[COUNCIL-AUTO] Council spawn failed: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[COUNCIL-AUTO] Loop error: {e}", exc_info=True)

            # Check every 5 minutes
            await asyncio.sleep(300)

    # ─── LOOP 4: Memory Consolidation ──────────────────────────

    async def _memory_consolidation_loop(self) -> None:
        """
        Periodic memory maintenance: decay, consolidation, and cleanup.

        - Applies exponential decay to all memory units
        - Consolidates related units (merge duplicates)
        - Prunes units below importance threshold
        - Computes and logs memory statistics
        """
        await asyncio.sleep(60)  # Brief startup delay

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[MEMORY] Emergency stop active — halting loop")
                break
            try:
                log.info("[MEMORY] Starting consolidation cycle...")

                store = self.brain.memory_store
                stats_before = await store.stats()

                # Enhanced consolidation with reflection loop
                try:
                    if hasattr(self.brain.memory_store, 'consolidate_v2'):
                        consolidation_result = await self.brain.memory_store.consolidate_v2()
                    else:
                        consolidation_result = await self.brain.memory_store.consolidate()
                except Exception as e:
                    log.warning(f"consolidate_v2 failed, using basic: {e}")
                    consolidation_result = await store.consolidate()

                stats_after = await store.stats()

                self._stats["memory_consolidations"] += 1
                self._stats["last_consolidation"] = datetime.now(timezone.utc).isoformat()

                pruned = consolidation_result.get("pruned", 0)
                merged = consolidation_result.get("merged", 0)
                log.info(f"[MEMORY] Consolidation complete — "
                         f"before: {consolidation_result.get('total_before', 0)}, "
                         f"after: {consolidation_result.get('total_after', 0)}, "
                         f"pruned: {pruned}, merged: {merged}")

                await self._log_autonomous_event("memory_consolidation", {
                    "stats_before": stats_before,
                    "stats_after": stats_after,
                    "consolidation": consolidation_result,
                })

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[MEMORY] Consolidation error: {e}", exc_info=True)

            await asyncio.sleep(self.config.memory_consolidation_interval)

    # ─── LOOP 5: AAC War Room Sync ─────────────────────────────

    async def _aac_sync_loop(self) -> None:
        """
        Pull market regime data from AAC forecasters.

        Queries AAC's health endpoint and market data APIs to sync:
        - Current market regime classification
        - Crypto regime signals (8 formulas)
        - Stock opportunity rankings
        - Prediction market positions
        - P&L and risk metrics

        Stores as memory units for council access.
        """
        await asyncio.sleep(120)  # Wait for services to stabilize

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[AAC-SYNC] Emergency stop active — halting loop")
                break
            try:
                aac_data = {}

                # Try AAC health endpoint.
                # json.loads() is called on the event loop after each to_thread()
                # HTTP call completes. These are small health/status responses
                # (typically <10 KB) so parsing on the event loop is acceptable;
                # wrapping in a second to_thread() would add overhead without
                # meaningful benefit.
                try:
                    aac_health = await asyncio.to_thread(
                        self._http_get, "http://localhost:8080/health"
                    )
                    if aac_health:
                        aac_data["health"] = json.loads(aac_health)
                except Exception:
                    pass

                # Try AAC War Room URL if configured
                war_room_url = self.config.aac_war_room_url
                if war_room_url:
                    try:
                        regime_data = await asyncio.to_thread(
                            self._http_get, f"{war_room_url}/regime"
                        )
                        if regime_data:
                            aac_data["market_regime"] = json.loads(regime_data)
                    except Exception:
                        pass

                    try:
                        positions_data = await asyncio.to_thread(
                            self._http_get, f"{war_room_url}/positions"
                        )
                        if positions_data:
                            aac_data["positions"] = json.loads(positions_data)
                    except Exception:
                        pass

                # Try NCC Master for execution status
                try:
                    ncc_health = await asyncio.to_thread(
                        self._http_get, "http://localhost:8765/health"
                    )
                    if ncc_health:
                        aac_data["ncc_status"] = json.loads(ncc_health)
                except Exception:
                    pass

                # Try BRS Dashboard for revenue metrics
                try:
                    brs_data = await asyncio.to_thread(
                        self._http_get, "http://localhost:8000/matrix/sitrep"
                    )
                    if brs_data:
                        aac_data["brs_sitrep"] = json.loads(brs_data)
                except Exception:
                    pass

                if aac_data:
                    # Store pillar sync data in memory
                    await self.brain.memory_store.create_unit(
                        content=(
                            f"Pillar sync: reached {list(aac_data.keys())} at "
                            f"{datetime.now(timezone.utc).isoformat()}"
                        ),
                        source="autonomous:aac_sync",
                        importance=40.0,
                        tags=["aac", "sync", "pillar_status", "autonomous"],
                    )

                    self._stats["aac_syncs"] += 1
                    self._stats["last_aac_sync"] = datetime.now(timezone.utc).isoformat()

                    log.info(f"[AAC-SYNC] Pillar sync complete — "
                             f"reached: {list(aac_data.keys())}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[AAC-SYNC] Sync error: {e}", exc_info=True)

            # Sync every 15 minutes
            await asyncio.sleep(900)

    # ─── LOOP 6: Workspace Health ──────────────────────────────

    async def _workspace_health_loop(self) -> None:
        """
        Monitor MWP workspace pipeline health.

        Checks each workspace stage for:
        - Stale artifacts (stuck in processing)
        - Empty stages (pipeline blockage)
        - Output accumulation (review backlog)
        """
        await asyncio.sleep(180)

        while self._running:
            try:
                workspaces = [
                    "mandate-generation", "research-pipeline",
                    "intelligence-scan", "memory-processing",
                    "feedback-synthesis",
                ]
                base = Path(self.config.data_dir).expanduser().parent / "workspaces"
                health = {}

                for ws in workspaces:
                    ws_path = base / ws / "stages"
                    if ws_path.exists():
                        stages = {}
                        for stage_dir in sorted(ws_path.iterdir()):
                            if stage_dir.is_dir():
                                artifacts = list(stage_dir.glob("*"))
                                stages[stage_dir.name] = {
                                    "artifact_count": len(artifacts),
                                    "newest": max(
                                        (f.stat().st_mtime for f in artifacts), default=0
                                    ),
                                }
                        health[ws] = stages

                if health:
                    await self._log_autonomous_event("workspace_health", health)
                    log.debug(f"[WORKSPACE] Health check: {len(health)} workspaces monitored")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[WORKSPACE] Health check error: {e}", exc_info=True)

            # Check every 30 minutes
            await asyncio.sleep(1800)
    # ─── LOOP 7: Mandate State Hygiene ───────────────────────────

    async def _mandate_purge_loop(self) -> None:
        """
        Periodically purge stale mandates to prevent state explosion.

        Background: in May 2026 a watcher bug let pending_approval mandates
        accumulate to 22,388 entries before discovery. This loop ensures any
        future leak self-heals within hours instead of months.

        Targets:
          - cancelled / completed older than 30 days  → hard delete
          - pending_approval older than 7 days        → hard delete (orphans)
        """
        # Defer first run so we don't compete with startup
        await asyncio.sleep(600)

        from ..ncl_brain.models import MandateStatus
        from datetime import datetime as _dt, timezone as _tz

        purge_specs = [
            (MandateStatus.CANCELLED, 30 * 24),
            (MandateStatus.COMPLETED, 30 * 24),
            (MandateStatus.PENDING_APPROVAL, 7 * 24),
        ]

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[PURGE] Emergency stop active — halting loop")
                break
            try:
                purged_total = 0
                async with self.brain._mandates_lock:
                    now_ts = _dt.now(_tz.utc).timestamp()
                    for status, max_age_h in purge_specs:
                        cutoff = now_ts - (max_age_h * 3600)
                        victims = [
                            mid for mid, m in self.brain.mandates.items()
                            if m.status == status and m.created_at.timestamp() < cutoff
                        ]
                        for mid in victims:
                            self.brain.mandates.pop(mid, None)
                        if victims:
                            log.info(
                                f"[PURGE] Removed {len(victims)} {status.value} mandates "
                                f"older than {max_age_h}h"
                            )
                            purged_total += len(victims)
                    if purged_total > 0:
                        await self.brain._persist_mandates_unlocked()

                # Health alarm: if total mandates exploded, log loud
                total = len(self.brain.mandates)
                if total > 1000:
                    log.error(
                        f"[PURGE] Mandate count high: {total} — possible state"
                        f" leak. Inspect mandates.json."
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[PURGE] loop error: {e}", exc_info=True)

            # Run every 6 hours
            await asyncio.sleep(6 * 3600)

    # ─── LOOP 8: Feedback Synthesis ───────────────────────────

    async def _feedback_synthesis_loop(self) -> None:
        """
        Consume pillar feedback reports → produce synthesis notes.

        Reads from feedback-synthesis/{ncc,brs,aac}-reports/, validates each
        report against FeedbackReport schema, moves processed → .consumed/,
        invalid → .quarantine/, and writes interpreted SynthesisNote into
        feedback-synthesis/synthesis/ for downstream council/mandate review.
        """
        # Loud entry log so we can prove the task was scheduled even if a later
        # step throws. (Previous silent-failure mode: import-after-warmup raised
        # under launchd's process environment and the task died with no trace.)
        log.info("[FEEDBACK] loop task spawned, warming up 15s...")
        try:
            await asyncio.sleep(15)  # short warmup so brain finishes other init
        except asyncio.CancelledError:
            raise

        # All imports + path resolution wrapped so any failure logs visibly
        # instead of dying as an unobserved task exception.
        try:
            import os
            from ..feedback.scanner import FeedbackScanner

            env_override = os.environ.get("NCL_FEEDBACK_DIR")
            candidates: list[Path] = []
            if env_override:
                candidates.append(Path(env_override).expanduser())
            # cwd is the launchd WorkingDirectory (NCL repo root) — preferred
            candidates.append(Path.cwd() / "feedback-synthesis")
            candidates.append(self.brain.data_dir.parent / "feedback-synthesis")

            def _is_real_feedback_root(p: Path) -> bool:
                return p.exists() and any(
                    (p / sub).exists()
                    for sub in ("aac-reports", "brs-reports", "ncc-reports")
                )

            base = next((c for c in candidates if _is_real_feedback_root(c)), None)
            if base is None:
                log.warning(
                    f"[FEEDBACK] no valid feedback-synthesis dir "
                    f"(tried: {[str(c) for c in candidates]}) — loop will idle"
                )
                base = candidates[0]
            else:
                log.info(f"[FEEDBACK] watching {base} (cwd={Path.cwd()})")

            scanner = FeedbackScanner(base_dir=base)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception(
                f"[FEEDBACK] init failed; loop dying: {type(e).__name__}: {e!r}"
            )
            return

        log.info("[FEEDBACK] loop entering scan cycle (interval=300s)")
        ticks = 0
        while self._running:
            ticks += 1
            try:
                if base.exists():
                    note = scanner.scan_once()
                    if note:
                        log.info(
                            f"[FEEDBACK] tick {ticks}: {note.reports_consumed} "
                            f"reports → {note.synthesis_id}"
                        )
                        await self._apply_synthesis_to_mandates(note)
                    elif ticks % 12 == 1:  # once per hour, prove we're alive
                        log.info(f"[FEEDBACK] tick {ticks}: no new reports")
                else:
                    log.warning(f"[FEEDBACK] base dir vanished: {base}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception(
                    f"[FEEDBACK] tick {ticks} error: {type(e).__name__}: {e!r}"
                )

            try:
                await asyncio.sleep(300)
            except asyncio.CancelledError:
                raise

    async def _apply_synthesis_to_mandates(self, note) -> None:
        """
        Convert a SynthesisNote into PENDING_APPROVAL mandate proposals.

        Authority chain: feedback is interpreted → drafted as mandate proposals
        → NATRIX must approve before dispatch. We do NOT create ACTIVE mandates
        from feedback automatically — that would let downstream pillars steer
        their own next directives, violating the chain of command.

        Heuristics:
          - Each open blocker → one proposal targeting the reporting pillar
            with priority 7 (high). Title prefix: "RESOLVE: ".
          - Each suggested_adjustment → one proposal at priority 5.
        """
        from ..ncl_brain.models import PillarType, MandateStatus

        # Map pillar string → enum
        pillar_lookup = {p.name: p for p in PillarType}

        proposals: list[tuple[PillarType, int, str, str]] = []

        for blocker in note.open_blockers:
            pillar_str = blocker.get("pillar", "")
            pillar = pillar_lookup.get(pillar_str)
            if not pillar:
                continue
            blk = blocker.get("blocker", "").strip()
            if not blk:
                continue
            mid = blocker.get("mandate_id", "") or "unattributed"
            proposals.append((
                pillar,
                7,
                f"RESOLVE: {blk[:80]}",
                f"Blocker reported by {pillar_str} (source mandate: {mid}). "
                f"Synthesis note {note.synthesis_id}. Resolve and report back.",
            ))

        for adj in note.suggested_adjustments:
            adj_clean = (adj or "").strip()
            if not adj_clean:
                continue
            # Default to NCC for adjustments without explicit pillar tagging;
            # NCC owns execution and can re-route if needed.
            proposals.append((
                PillarType.NCC,
                5,
                f"FEEDBACK: {adj_clean[:80]}",
                f"Pillar-suggested adjustment from synthesis {note.synthesis_id}: "
                f"{adj_clean}",
            ))

        if not proposals:
            return

        created = 0
        for pillar, priority, title, objective in proposals:
            try:
                m = await self.brain.create_mandate(
                    pillar=pillar,
                    priority=priority,
                    title=title,
                    objective=objective,
                    success_criteria=[
                        f"Source synthesis: {note.synthesis_id}",
                        "NATRIX review and approval required",
                    ],
                    status=MandateStatus.PENDING_APPROVAL,
                )
                created += 1
                log.info(
                    f"[FEEDBACK] proposal created: {m.mandate_id} → {pillar.value} "
                    f"P{priority}: {title}"
                )
            except Exception as e:
                log.error(
                    f"[FEEDBACK] failed to create proposal for {pillar.value}: "
                    f"{type(e).__name__}: {e!r}"
                )

        log.info(
            f"[FEEDBACK] synthesis {note.synthesis_id} → {created}/{len(proposals)} "
            f"PENDING_APPROVAL mandates queued"
        )
    # ─── LOOP: Journal Reflection (10pm ET daily) ────────────────────

    async def _journal_reflection_loop(self) -> None:
        """
        Daily journal reflection — synthesizes the day's entries with intel
        and working context into actionable patterns and research queues.

        Runs at 10pm ET (22:00). Generates reflection, extracts tips,
        detects cross-entry patterns, and pushes summary to iPhone.
        """
        try:
            import pytz
            tz = pytz.timezone("US/Eastern")
        except ImportError:
            from datetime import timezone as tz_mod
            tz = tz_mod(timedelta(hours=-5))

        reflection_hour = 22  # 10pm ET
        last_run_date = None

        # Initial delay — let other loops warm up
        await asyncio.sleep(120)

        log.info(f"[JOURNAL] Reflection loop started — will fire at {reflection_hour}:00 ET")

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[JOURNAL] Emergency stop active — halting loop")
                break
            try:
                now = datetime.now(tz)
                today = now.date()

                if now.hour >= reflection_hour and last_run_date != today:
                    last_run_date = today
                    log.info(f"[JOURNAL] Generating daily reflection for {today}")

                    try:
                        # Gather intel context
                        intel_brief_data = None
                        if self.intelligence_engine:
                            try:
                                latest = await self.intelligence_engine.get_latest_brief()
                                if latest:
                                    intel_brief_data = latest.model_dump()
                            except Exception:
                                pass

                        # Gather working context
                        wc_data = None
                        if self._working_context:
                            try:
                                wc_data = self._working_context.get_current()
                            except Exception:
                                pass

                        # Generate reflection
                        reflection = await self._reflection_engine.generate_daily_reflection(
                            intel_brief=intel_brief_data,
                            working_context=wc_data,
                        )

                        self._stats["journal_reflections_generated"] = self._stats.get("journal_reflections_generated", 0) + 1
                        self._stats["last_journal_reflection"] = datetime.now(timezone.utc).isoformat()

                        # Push summary to iPhone
                        try:
                            from ..strike_point_orchestrator import notify_intelligence_brief
                            summary_text = (
                                f"Daily Reflection — {today}\n\n"
                                f"{reflection.summary}\n\n"
                            )
                            if reflection.patterns_noticed:
                                summary_text += "Patterns: " + ", ".join(reflection.patterns_noticed[:3]) + "\n"
                            if reflection.tomorrow_focus:
                                summary_text += "Tomorrow: " + ", ".join(reflection.tomorrow_focus[:3]) + "\n"

                            await notify_intelligence_brief({
                                "brief_type": "journal_reflection",
                                "executive_summary": summary_text,
                                "brief_id": reflection.reflection_id,
                            })
                            log.info(f"[JOURNAL] Reflection pushed to iPhone: {reflection.reflection_id}")
                        except ImportError:
                            log.debug("[JOURNAL] Push notification not available")
                        except Exception as e:
                            log.warning(f"[JOURNAL] Push failed: {e}")

                        await self._log_autonomous_event("journal_reflection", {
                            "entries_count": reflection.entries_count,
                            "patterns": len(reflection.patterns_noticed),
                            "research_topics": len(reflection.research_queue),
                            "date": str(today),
                        })

                        log.info(f"[JOURNAL] Reflection complete: {reflection.entries_count} entries → "
                                 f"{len(reflection.patterns_noticed)} patterns, "
                                 f"{len(reflection.research_queue)} research topics")

                    except Exception as e:
                        log.error(f"[JOURNAL] Reflection generation failed: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[JOURNAL] Loop error: {e}", exc_info=True)

            await asyncio.sleep(300)  # Check every 5 minutes

    # ─── LOOP 10: Working Context Window ─────────────────────────────

    async def _working_context_loop(self) -> None:
        """
        Daily Working Context Window — assembles a curated high-salience
        memory context each morning, refreshes mid-day, and runs EOD
        promote/demote at midnight.

        Schedule:
          6am ET  → Full assembly (pull memory, councils, signals, mandates)
          noon ET → Mid-day refresh (re-score, pull new high-priority items)
          11pm ET → End-of-day promote/demote cycle

        NOTE: DailyContextWindow is initialized eagerly in start() so the
        /memory/working-context endpoint is available immediately after
        restart (no 30-second 503 window).
        """
        import pytz

        if not self._working_context:
            log.error("[WORKING-CTX] DailyContextWindow not initialized — loop exiting")
            return

        tz = pytz.timezone(os.environ.get("NCL_TIMEZONE", "America/New_York"))
        morning_hour = int(os.environ.get("NCL_WORKING_CTX_HOUR", "6"))
        midday_hour = 12
        eod_hour = 23

        last_assembly_date = None
        last_midday_date = None
        last_eod_date = None

        # Initial assembly on startup — no delay; object already exists
        try:
            ctx = await self._working_context.assemble()
            last_assembly_date = datetime.now(tz).date()
            log.info(f"[WORKING-CTX] Initial assembly: {len(ctx.items)} items")
        except Exception as e:
            log.error(f"[WORKING-CTX] Initial assembly failed: {e}", exc_info=True)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[WORKING-CTX] Emergency stop active — halting loop")
                break

            try:
                now = datetime.now(tz)
                today = now.date()

                # Morning assembly (6am)
                if now.hour >= morning_hour and last_assembly_date != today:
                    last_assembly_date = today
                    log.info(f"[WORKING-CTX] Morning assembly for {today}")
                    try:
                        ctx = await self._working_context.assemble()
                        self._stats["working_ctx_assemblies"] = self._stats.get("working_ctx_assemblies", 0) + 1
                        self._stats["last_working_ctx"] = datetime.now(timezone.utc).isoformat()

                        await self._log_autonomous_event("working_context_assembled", {
                            "date": str(today),
                            "items": len(ctx.items),
                            "themes": ctx.themes[:10],
                            "stats": ctx.stats,
                        })
                    except Exception as e:
                        log.error(f"[WORKING-CTX] Morning assembly failed: {e}", exc_info=True)

                # Mid-day refresh (noon)
                elif now.hour >= midday_hour and last_midday_date != today:
                    last_midday_date = today
                    log.info("[WORKING-CTX] Mid-day refresh")
                    try:
                        ctx = await self._working_context.refresh()
                        log.info(f"[WORKING-CTX] Refreshed: {len(ctx.items)} items")
                    except Exception as e:
                        log.error(f"[WORKING-CTX] Mid-day refresh failed: {e}", exc_info=True)

                # End-of-day promote/demote (11pm)
                elif now.hour >= eod_hour and last_eod_date != today:
                    last_eod_date = today
                    log.info("[WORKING-CTX] End-of-day cycle")
                    try:
                        eod_stats = await self._working_context.end_of_day()
                        log.info(f"[WORKING-CTX] EOD: {eod_stats}")
                        await self._log_autonomous_event("working_context_eod", eod_stats)
                    except Exception as e:
                        log.error(f"[WORKING-CTX] EOD cycle failed: {e}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[WORKING-CTX] Loop error: {e}", exc_info=True)

            # Check every 5 minutes
            await asyncio.sleep(300)

    # ─── Helpers ───────────────────────────────────────────────

    # ─── LOOP 9: Heartbeat ──────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Log a heartbeat every 60 seconds so operators can verify the scheduler
        is alive without checking individual loop stats."""
        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[HEARTBEAT] Emergency stop active — halting loop")
                break
            try:
                active = [t.get_name() for t in self._tasks if not t.done()]
                log.info(
                    "[SCHEDULER][HEARTBEAT] alive — active_tasks=%d signal_buffer=%d "
                    "scans=%d predictions=%d councils=%d",
                    len(active),
                    len(self._signal_buffer),
                    self._stats["scans_completed"],
                    self._stats["predictions_run"],
                    self._stats["councils_auto_spawned"],
                )
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("[HEARTBEAT] error: %s", e, exc_info=True)

            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

    def _get_watch_queries(self, platform: str) -> list[str]:
        """
        Get intelligence watch queries for a platform.

        Loads from config or uses defaults aligned with active mandates.
        """
        # Load custom queries from config file if available
        queries_file = Path(self.config.config_dir).expanduser() / "watch_queries.json"
        if queries_file.exists():
            try:
                with open(queries_file) as f:
                    queries = json.load(f)
                    return queries.get(platform, [])
            except Exception:
                pass

        # Default queries aligned with NARTIX mandate priorities
        defaults = {
            "x": [
                "AI automation business",
                "algorithmic trading crypto",
                "indie game development",
                "AI music production",
                "prediction markets Polymarket",
            ],
            "youtube": [
                "AI business automation 2026",
                "crypto trading strategies",
                "game development indie",
                "AI tools for developers",
            ],
            "reddit": [
                "artificial intelligence business",
                "cryptocurrency trading",
                "gamedev indie",
                "AI music generation",
            ],
        }
        return defaults.get(platform, [])

    async def _flag_for_council(self, trigger: str, data: dict, importance: float) -> None:
        """Flag a signal/prediction for council consideration.

        Uses file locking to prevent TOCTOU races with concurrent readers.
        """
        flag = {
            "trigger": trigger,
            "data": data,
            "importance": importance,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        flags_file = self.signals_dir / "council_flags.jsonl"
        try:
            line = json.dumps(flag, default=_json_safe) + "\n"

            def _locked_append() -> None:
                with open(flags_file, "a") as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        f.write(line)
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            await asyncio.to_thread(_locked_append)
        except Exception as e:
            log.warning(f"Failed to write council flag: {e}")

    async def _get_council_flags(self) -> list[dict]:
        """Read pending council flags with file locking to avoid TOCTOU races."""
        flags_file = self.signals_dir / "council_flags.jsonl"
        flags = []
        try:
            fd = await asyncio.to_thread(
                lambda: open(flags_file, "r")
            )
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
                content = fd.read()
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                for line in content.strip().split("\n"):
                    if line.strip():
                        flags.append(json.loads(line))
            finally:
                fd.close()
        except (FileNotFoundError, OSError):
            pass
        return flags

    async def _clear_council_flags(self) -> None:
        """Clear processed council flags atomically.

        Renames the file to a .processing sentinel before unlinking so that
        a concurrent writer appending to council_flags.jsonl at the same moment
        will not see a partially-deleted file. The rename is atomic on POSIX
        filesystems; the subsequent unlink is then safe to fail silently.
        """
        flags_file = self.signals_dir / "council_flags.jsonl"
        if flags_file.exists():
            processing = self.signals_dir / "council_flags.jsonl.processing"
            try:
                flags_file.rename(processing)
            except OSError as e:
                log.warning(f"[COUNCIL-AUTO] Failed to rename flags file for atomic clear: {e}")
                return
            try:
                processing.unlink()
            except OSError as e:
                log.warning(f"[COUNCIL-AUTO] Failed to unlink processing flags file: {e}")

    async def _log_autonomous_event(self, event_type: str, data: dict) -> None:
        """Log an autonomous event to the autonomous events file."""
        event = {
            "type": f"autonomous.{event_type}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        events_file = self.signals_dir / "events.ndjson"
        try:
            async with aiofiles.open(events_file, "a") as f:
                await f.write(json.dumps(event, default=_json_safe) + "\n")
        except Exception as e:
            log.warning(f"Failed to log autonomous event: {e}")

    def _http_get(self, url: str, timeout: int = 5) -> Optional[str]:
        """Synchronous HTTP GET (run via asyncio.to_thread)."""
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status < 400:
                    return resp.read().decode("utf-8")
        except Exception:
            return None
        return None
