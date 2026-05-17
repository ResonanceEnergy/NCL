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
        self._working_context = None  # Initialized by _working_context_loop (W6 fix)
        self._journal_store: Optional[JournalStore] = None  # Initialized in start()
        self._reflection_engine = None

        # Council trigger threshold (importance score 0-100)
        self.council_trigger_threshold = 75.0
        # Minimum signals needed before auto-spawning a council
        self.council_min_signals = 3

        # Unified Signal Processor — central routing hub for all loops
        self.signal_processor = SignalProcessor(
            memory_store=brain.memory_store,
            working_context=None,  # Set later when WC loop initializes
            signal_buffer=self._signal_buffer,
            signal_lock=self._signal_lock,
            data_dir=self.data_dir,
        )

        # ── Unified Awarebot Agent ─────────────────────────────────────
        # Replaces: scanner_loop, intel_collection_loop, intel_brief_loop,
        # prediction_loop, morning_brief_loop, weekly_strategy_loop
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
                working_context=None,  # Set later by _working_context_loop
                journal_store=None,  # Set below after JournalStore init
            )
            log.info("  Awarebot agent: ACTIVE (unified intelligence pipeline)")
        except Exception as e:
            log.error(f"  Awarebot agent: FAILED to initialize: {e}")
            self.awarebot = None

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

        # Journal system
        try:
            self._journal_store = JournalStore(
                data_dir=str(self.data_dir),
                memory_store=self.brain.memory_store if self.brain else None,
                working_context=None,  # Set when WC loop initializes
            )
            self._reflection_engine = ReflectionEngine(self._journal_store)
            # Wire journal store into Awarebot for cross-referencing
            if self.awarebot:
                self.awarebot.journal_store = self._journal_store
            self._tasks.append(
                asyncio.create_task(self._journal_reflection_loop(), name="ncl-journal-reflection")
            )
            log.info("  Journal reflection loop: 10pm ET daily")
        except ImportError:
            log.warning("Journal module not available — reflection loop disabled")

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

    # ─── LOOP 1: Social Intelligence Scanner (X + YouTube) ─────

    async def _scanner_loop(self) -> None:
        """
        Scan X and YouTube for intelligence signals via Awarebot.

        UNIFIED PIPELINE: All signals flow through the same path as
        Loop 8 (Intel Collection) — memory store, signals JSONL,
        working context, and prediction buffer. No separate storage.

        Reddit is handled exclusively by Loop 8's RedditCollector
        to avoid duplicate scanning.

        Per-platform intervals: X scans at x_scan_interval (5 min),
        YouTube at youtube_scan_interval (10 min). Each platform
        tracks its own last-run time independently.
        """
        await asyncio.sleep(5)

        last_x_scan = datetime.min.replace(tzinfo=timezone.utc)
        last_yt_scan = datetime.min.replace(tzinfo=timezone.utc)
        # Tick every 60s and check if each platform is due
        tick_interval = 60

        while not self._stop_event.is_set():
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[SCANNER] Emergency stop active — halting loop")
                break

            try:
                now = datetime.now(timezone.utc)
                all_signals = []
                platforms_scanned = []

                # ── X (Twitter) ──────────────────────────────────
                x_due = (now - last_x_scan).total_seconds() >= self.config.x_scan_interval
                if x_due:
                    try:
                        x_signals: list = []
                        for q in self._get_watch_queries("x"):
                            try:
                                x_signals.extend(await self.brain.scanner.scan_x(q, max_results=25))
                            except Exception as ie:
                                log.warning(f"[SCANNER] X query '{q}' failed: {ie}")
                        all_signals.extend(x_signals)
                        last_x_scan = now
                        platforms_scanned.append(f"X:{len(x_signals)}")
                    except Exception as e:
                        log.warning(f"[SCANNER] X scan failed: {e}")

                # ── YouTube ──────────────────────────────────────
                yt_due = (now - last_yt_scan).total_seconds() >= self.config.youtube_scan_interval
                if yt_due:
                    try:
                        yt_signals: list = []
                        for q in self._get_watch_queries("youtube"):
                            try:
                                yt_signals.extend(await self.brain.scanner.scan_youtube(q, max_results=10))
                            except Exception as ie:
                                log.warning(f"[SCANNER] YouTube query '{q}' failed: {ie}")
                        all_signals.extend(yt_signals)
                        last_yt_scan = now
                        platforms_scanned.append(f"YT:{len(yt_signals)}")
                    except Exception as e:
                        log.warning(f"[SCANNER] YouTube scan failed: {e}")

                # ── UNIFIED SIGNAL PROCESSING (via SignalProcessor) ─
                if all_signals:
                    result = await self.signal_processor.process_signals(
                        signals=all_signals,
                        source_label="scanner",
                        push_alerts=True,
                    )

                    self._stats["high_signals_detected"] += result.get("stored_memory", 0)

                    await self._log_autonomous_event("scan_complete", {
                        "total_signals": len(all_signals),
                        "stored_memory": result.get("stored_memory", 0),
                        "injected_wc": result.get("injected_wc", 0),
                        "fed_predictor": result.get("fed_predictor", 0),
                        "platforms": ", ".join(platforms_scanned),
                    })

                    log.info(f"[SCANNER] {', '.join(platforms_scanned)} — "
                             f"processed {result.get('processed', 0)} via SignalProcessor")

                if platforms_scanned:
                    self._stats["scans_completed"] += 1
                    self._stats["last_scan"] = now.isoformat()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[SCANNER] Loop error: {e}", exc_info=True)

            # Tick every 60s; break immediately if stop is signaled
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=tick_interval
                )
                break
            except asyncio.TimeoutError:
                pass

    # ─── LOOP 2: Future Prediction ─────────────────────────────

    async def _prediction_loop(self) -> None:
        """
        Run ensemble predictions on accumulated intelligence signals.

        Pulls from signal buffer, runs multi-model forecasting with
        convergence detection. If convergence is detected with high
        confidence, stores prediction in memory and may trigger council.
        """
        # Wait for first scan cycle to populate signals
        await asyncio.sleep(self.config.x_scan_interval + 30)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[PREDICTOR] Emergency stop active — halting loop")
                break
            try:
                # Snapshot signal buffer WITHOUT clearing — only clear after success (#38)
                async with self._signal_lock:
                    signals = list(self._signal_buffer)
                    # DON'T clear yet — cleared below only on successful prediction

                if not signals:
                    log.debug("[PREDICTOR] No signals to process, sleeping...")
                    await asyncio.sleep(self.config.prediction_interval)
                    continue

                log.info(f"[PREDICTOR] Processing {len(signals)} signals...")

                # Convert raw signal dicts to InsightSignal objects for FuturePredictor
                import uuid as _uuid
                insight_signals = []
                for sig in signals:
                    try:
                        importance = sig.get("importance", 50.0)
                        insight_signals.append(InsightSignal(
                            signal_id=str(_uuid.uuid4()),
                            content=sig.get("content", ""),
                            source_platform=sig.get("source", "unknown"),
                            importance_score=min(100.0, max(0.0, importance)),
                            relevance=min(1.0, importance / 100.0),
                            novelty=0.5,
                            actionability=0.5,
                            source_authority=0.5,
                            time_sensitivity=0.5,
                            tags=sig.get("tags", []),
                        ))
                    except Exception:
                        continue  # Skip malformed signals

                if not insight_signals:
                    log.debug("[PREDICTOR] No valid InsightSignals after conversion")
                    await asyncio.sleep(self.config.prediction_interval)
                    continue

                # Determine prediction topic from most common tags
                all_tags = [t for sig in insight_signals for t in sig.tags]
                topic = max(set(all_tags), key=all_tags.count) if all_tags else "general_intelligence"

                # Run FuturePredictor ensemble with real signals
                try:
                    prediction = await self.brain.predictor.predict(
                        signals=insight_signals, topic=topic
                    )

                    if prediction:
                        # Store prediction in memory using correct method
                        await self.brain.memory_store.create_unit(
                            content=(
                                f"Autonomous prediction on '{topic}': "
                                f"{prediction.consensus_prediction or 'inconclusive'}"
                            ),
                            source="autonomous:predictor",
                            importance=min(100.0, prediction.confidence * 100),
                            tags=["prediction", "autonomous", "ensemble", topic],
                        )

                        log.info(f"[PREDICTOR] Prediction complete — "
                                 f"confidence={prediction.confidence:.2f}, "
                                 f"convergence={len(prediction.convergence_signals) > 0}")

                        # Persist prediction to disk for FirstStrike access
                        try:
                            pred_dir = Path(os.getenv("NCL_DATA", str(Path.home() / "NCL" / "data"))) / "predictions"
                            pred_dir.mkdir(parents=True, exist_ok=True)
                            pred_file = pred_dir / f"pred-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
                            pred_data = {
                                "topic": topic,
                                "consensus": prediction.consensus_prediction,
                                "confidence": prediction.confidence,
                                "convergence": prediction.convergence_signals if prediction.convergence_signals else [],
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "signal_count": len(insight_signals),
                            }
                            pred_file.write_text(json.dumps(pred_data, indent=2, default=_json_safe))
                        except Exception as disk_err:
                            log.warning(f"[PREDICTOR] Disk persistence failed: {disk_err}")

                        # Push high-confidence predictions to FirstStrike
                        if prediction.confidence >= 0.6:
                            try:
                                from ..strike_point_orchestrator import notify_natrix
                                await notify_natrix(
                                    f"Prediction [{topic}]: {prediction.consensus_prediction or 'inconclusive'}\n"
                                    f"Confidence: {prediction.confidence:.0%}\n"
                                    f"Signals analyzed: {len(insight_signals)}",
                                    title="NCL Prediction Alert",
                                    priority=-1,
                                )
                            except Exception:
                                pass

                        # If high-confidence convergence, flag for council consideration
                        if prediction.convergence_signals and prediction.confidence >= 0.8:
                            await self._flag_for_council(
                                trigger="high_confidence_prediction",
                                data={
                                    "topic": topic,
                                    "consensus": prediction.consensus_prediction,
                                    "confidence": prediction.confidence,
                                    "convergence": prediction.convergence_signals,
                                },
                                importance=prediction.confidence * 100,
                            )

                    # Prediction succeeded — now safe to drain the signals we processed.
                    # Use popleft() instead of clear() so any signals that arrived
                    # during the prediction run (appended to the right of the deque)
                    # are preserved for the next cycle. (#38)
                    async with self._signal_lock:
                        for _ in range(min(len(signals), len(self._signal_buffer))):
                            self._signal_buffer.popleft()

                except Exception as e:
                    log.error(
                        f"[PREDICTOR] Prediction failed, signals preserved for retry: {e}",
                        exc_info=True,
                    )

                self._stats["predictions_run"] += 1
                self._stats["last_prediction"] = datetime.now(timezone.utc).isoformat()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[PREDICTOR] Loop error: {e}", exc_info=True)

            await asyncio.sleep(self.config.prediction_interval)

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

                # Run full consolidation: decay + prune + cluster + merge
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
    # ─── Intelligence Engine Loops ────────────────────────────

    async def _intel_collection_loop(self) -> None:
        """
        Periodic signal collection from all intelligence sources.

        Runs more frequently than brief generation — collects raw signals
        from Google Trends, Polymarket, news, crypto markets and persists them.
        High-importance signals (>80) trigger immediate push alerts.
        """
        # Initial delay — let other loops warm up first
        await asyncio.sleep(60)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[INTEL-COLLECT] Emergency stop active — halting loop")
                break
            try:
                log.info("[INTEL-COLLECT] Starting signal collection sweep...")
                signals = await self.intelligence_engine.collect_all_signals()

                # Cache for brief loop — avoids re-collecting from APIs (C3 fix)
                self._last_collected_signals = signals

                self._stats["intel_collections_run"] += 1
                self._stats["last_intel_collection"] = datetime.now(timezone.utc).isoformat()

                # Route ALL signals through the unified SignalProcessor
                # This handles: prediction buffer, memory, JSONL, WC, push alerts
                result = await self.signal_processor.process_signals(
                    signals=signals,
                    source_label="intel",
                    push_alerts=True,
                )

                self._stats["intel_alerts_pushed"] += result.get("pushed_alerts", 0)

                await self._log_autonomous_event("intel_collection", {
                    "total_signals": len(signals),
                    "processed": result.get("processed", 0),
                    "fed_predictor": result.get("fed_predictor", 0),
                    "stored_memory": result.get("stored_memory", 0),
                    "injected_wc": result.get("injected_wc", 0),
                    "pushed_alerts": result.get("pushed_alerts", 0),
                    "sources": {s.source.value for s in signals} if signals else set(),
                })

                log.info(f"[INTEL-COLLECT] {len(signals)} signals → "
                         f"SignalProcessor routed {result.get('processed', 0)}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[INTEL-COLLECT] Collection error: {e}", exc_info=True)

            await asyncio.sleep(self.config.intelligence_collection_interval)

    async def _intel_brief_loop(self) -> None:
        """
        Periodic intelligence brief generation and iPhone push delivery.

        Generates a full synthesized brief (with LLM executive summary),
        pushes a structured notification to NATRIX's iPhone via Pushover,
        and writes a FirstStrike-compatible notification file with action buttons.
        """
        # Initial delay — let collection run at least once first
        await asyncio.sleep(self.config.intelligence_collection_interval + 30)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[INTEL-BRIEF] Emergency stop active — halting loop")
                break
            try:
                log.info("[INTEL-BRIEF] Generating scheduled intelligence brief...")

                # Pass cached signals from last collection (C3 fix: avoids
                # redundant API calls — collection loop already gathered them)
                cached_signals = getattr(self, "_last_collected_signals", None)
                brief = await self.intelligence_engine.generate_brief(
                    brief_type="daily", signals=cached_signals
                )

                self._stats["intel_briefs_generated"] += 1
                self._stats["last_intel_brief"] = datetime.now(timezone.utc).isoformat()

                # Push to iPhone via Pushover + FirstStrike notification file
                try:
                    from ..strike_point_orchestrator import notify_intelligence_brief
                    pushed = await notify_intelligence_brief(brief.model_dump())
                    if pushed:
                        log.info(f"[INTEL-BRIEF] Brief pushed to iPhone: {brief.brief_id}")
                    else:
                        log.info(f"[INTEL-BRIEF] Brief saved (no Pushover configured): {brief.brief_id}")
                except ImportError:
                    log.warning("[INTEL-BRIEF] Could not import notification functions")
                    pushed = False

                # Auto-escalate if risk alerts exceed threshold
                if len(brief.risk_alerts) >= 3:
                    log.warning(f"[INTEL-BRIEF] {len(brief.risk_alerts)} risk alerts — "
                                f"consider auto-escalating to STRIKE-POINT")
                    await self._log_autonomous_event("intel_risk_threshold", {
                        "risk_alerts": brief.risk_alerts,
                        "brief_id": brief.brief_id,
                    })

                await self._log_autonomous_event("intel_brief_generated", {
                    "brief_id": brief.brief_id,
                    "total_signals": brief.total_signals_processed,
                    "sectors": len(brief.sectors),
                    "risk_alerts": len(brief.risk_alerts),
                    "pushed": pushed,
                })

                log.info(f"[INTEL-BRIEF] Brief {brief.brief_id} — "
                         f"{brief.total_signals_processed} signals, "
                         f"{len(brief.sectors)} sectors, "
                         f"{len(brief.risk_alerts)} risk alerts")

                # Trigger working context refresh so new signals surface immediately
                if hasattr(self, "_working_context") and self._working_context:
                    try:
                        ctx = await self._working_context.refresh()
                        log.info(f"[INTEL-BRIEF] Working context refreshed after brief: "
                                 f"{len(ctx.items)} items")
                    except Exception as wc_err:
                        log.debug(f"[INTEL-BRIEF] Working context refresh skipped: {wc_err}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[INTEL-BRIEF] Brief generation error: {e}", exc_info=True)

            await asyncio.sleep(self.config.intelligence_brief_interval)

    # ─── LOOP 10: Morning Brief (6am daily) ─────────────────────────

    async def _morning_brief_loop(self) -> None:
        """
        Daily morning brief at 6am ET.

        Generates 3 research topics from current intelligence,
        pushes to NATRIX's iPhone, and tracks research progress.
        Runs once per day at the configured morning hour.
        """
        import pytz
        from datetime import time as dt_time

        morning_hour = int(os.environ.get("NCL_MORNING_BRIEF_HOUR", "6"))
        tz = pytz.timezone(os.environ.get("NCL_TIMEZONE", "America/New_York"))
        last_run_date = None

        log.info(f"[MORNING-BRIEF] Loop started — will fire at {morning_hour}:00 {tz}")

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[MORNING-BRIEF] Emergency stop active — halting loop")
                break
            try:
                now = datetime.now(tz)
                today = now.date()

                # Only run once per day, at the morning hour
                if now.hour >= morning_hour and last_run_date != today:
                    last_run_date = today
                    log.info(f"[MORNING-BRIEF] Generating morning brief for {today}")

                    try:
                        # Call the morning brief endpoint logic directly
                        # Pass cached signals if available (C3 fix)
                        cached_signals = getattr(self, "_last_collected_signals", None)
                        brief = await self.intelligence_engine.generate_brief(
                            brief_type="daily", signals=cached_signals
                        )

                        # Build topic context
                        top_signals_ctx = "\n".join(
                            f"- [{s.source.value}] {s.title}: {s.content[:150]}"
                            for s in brief.top_signals[:15]
                        )
                        sectors_ctx = "\n".join(
                            f"- {s.sector}: {s.direction.value}, {s.signal_count} signals"
                            for s in brief.sectors[:8]
                        )

                        topics_text = (
                            f"Morning Intelligence — {today}\n\n"
                            f"EXECUTIVE SUMMARY:\n{brief.executive_summary or 'No summary available'}\n\n"
                            f"TOP SIGNALS:\n{top_signals_ctx}\n\n"
                            f"Sectors: {sectors_ctx}"
                        )

                        # Save morning brief file
                        morning_dir = Path(os.getenv("NCL_DATA", str(Path.home() / "NCL" / "data"))) / "morning_briefs"
                        morning_dir.mkdir(parents=True, exist_ok=True)
                        date_str = today.isoformat()
                        brief_data = {
                            "date": date_str,
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "brief_id": brief.brief_id,
                            "total_signals": brief.total_signals_processed,
                            "topics": topics_text,
                            "executive_summary": brief.executive_summary,
                            "risk_alerts": brief.risk_alerts,
                            "status": "pending",
                            "progress": [],
                        }
                        # Inject working context summary into morning brief
                        working_ctx_summary = ""
                        if hasattr(self, "_working_context") and self._working_context:
                            try:
                                wc = self._working_context.get_current()
                                if wc and wc.items:
                                    top_items = wc.items[:5]
                                    working_ctx_summary = "\n\nWORKING CONTEXT (top items):\n" + "\n".join(
                                        f"- [{i.category}] {i.content[:120]}" for i in top_items
                                    )
                                    brief_data["working_context"] = {
                                        "items": len(wc.items),
                                        "themes": wc.themes[:10],
                                        "pinned": len(wc.pinned_ids),
                                    }
                            except Exception as wc_err:
                                log.debug(f"[MORNING-BRIEF] Working context injection skipped: {wc_err}")

                        brief_path = morning_dir / f"morning-{date_str}.json"
                        brief_path.write_text(json.dumps(brief_data, indent=2, default=str))

                        # Push notification (with working context if available)
                        try:
                            from ..strike_point_orchestrator import notify_natrix
                            push_msg = (
                                f"Good morning NATRIX.\n\n{brief.executive_summary or ''}\n\n"
                                f"Signals processed: {brief.total_signals_processed}\n"
                                f"Risk alerts: {len(brief.risk_alerts)}"
                                f"{working_ctx_summary}"
                            )
                            await notify_natrix(
                                push_msg,
                                title="NCL Morning Brief",
                                priority=0,
                            )
                            log.info(f"[MORNING-BRIEF] Pushed to iPhone")
                        except Exception as push_err:
                            log.warning(f"[MORNING-BRIEF] Push notification failed: {push_err}")

                        self._stats["morning_briefs_generated"] = self._stats.get("morning_briefs_generated", 0) + 1
                        self._stats["last_morning_brief"] = datetime.now(timezone.utc).isoformat()

                        await self._log_autonomous_event("morning_brief_generated", {
                            "date": date_str,
                            "brief_id": brief.brief_id,
                            "total_signals": brief.total_signals_processed,
                        })

                    except Exception as gen_err:
                        log.error(f"[MORNING-BRIEF] Generation failed: {gen_err}", exc_info=True)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[MORNING-BRIEF] Loop error: {e}", exc_info=True)

            # Check every 5 minutes
            await asyncio.sleep(300)

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
        """
        import pytz
        from ..memory.working_context import DailyContextWindow

        tz = pytz.timezone(os.environ.get("NCL_TIMEZONE", "America/New_York"))
        morning_hour = int(os.environ.get("NCL_WORKING_CTX_HOUR", "6"))
        midday_hour = 12
        eod_hour = 23

        # Initialize the working context window
        self._working_context = DailyContextWindow(
            data_dir=self.data_dir,
            memory_store=self.brain.memory_store,
        )
        # Wire into the unified signal processor so all loops can inject
        self.signal_processor.working_context = self._working_context
        if self._journal_store:
            self._journal_store.working_context = self._working_context

        last_assembly_date = None
        last_midday_date = None
        last_eod_date = None

        # Initial assembly on startup
        await asyncio.sleep(30)
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

    # ─── LOOP 11: Weekly Strategy Review ────────────────────────────

    async def _weekly_strategy_loop(self) -> None:
        """
        Weekly strategy review brief (#37).

        Generates a weekly intelligence brief via the intelligence engine
        and pushes it to iPhone via the same notify_intelligence_brief
        path used by _intel_brief_loop.

        Schedule: first run after a 24h warm-up delay (lets other loops
        stabilise), then repeats every 7 days (604 800 s).
        """
        # 24-hour initial delay so other loops can warm up first
        await asyncio.sleep(24 * 3600)

        while self._running:
            if EMERGENCY_STOP_EVENT.is_set():
                log.critical("[WEEKLY-STRATEGY] Emergency stop active — halting loop")
                break
            try:
                log.info("[WEEKLY-STRATEGY] Generating weekly strategy review brief...")

                brief = await self.intelligence_engine.generate_brief(brief_type="weekly")

                log.info(
                    f"[WEEKLY-STRATEGY] Brief {brief.brief_id} generated — "
                    f"{brief.total_signals_processed} signals, "
                    f"{len(brief.sectors)} sectors"
                )

                # Push to iPhone via the same path as the daily intel brief
                try:
                    from ..strike_point_orchestrator import notify_intelligence_brief
                    pushed = await notify_intelligence_brief(brief.model_dump())
                    if pushed:
                        log.info(f"[WEEKLY-STRATEGY] Brief pushed to iPhone: {brief.brief_id}")
                    else:
                        log.info(
                            f"[WEEKLY-STRATEGY] Brief saved (no Pushover configured): "
                            f"{brief.brief_id}"
                        )
                except ImportError:
                    log.warning("[WEEKLY-STRATEGY] Could not import notification functions")

                await self._log_autonomous_event("weekly_strategy_review", {
                    "brief_id": brief.brief_id,
                    "total_signals": brief.total_signals_processed,
                    "sectors": len(brief.sectors),
                    "risk_alerts": len(brief.risk_alerts),
                })

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[WEEKLY-STRATEGY] Loop error: {e}", exc_info=True)

            # Run every 7 days
            await asyncio.sleep(7 * 24 * 3600)

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
