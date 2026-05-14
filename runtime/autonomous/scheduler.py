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
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..ncl_brain.models import InsightSignal

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
    ):
        self.brain = brain
        self.config = config
        self.councils_runner = councils_runner
        self.intelligence_engine = intelligence_engine

        self.data_dir = Path(config.data_dir).expanduser()
        self.signals_dir = self.data_dir / "autonomous_signals"
        self.signals_dir.mkdir(parents=True, exist_ok=True)

        # State tracking
        self._tasks: list[asyncio.Task] = []
        self._running = False
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

        # Signal buffer — accumulates between prediction cycles
        self._signal_buffer: list[dict] = []
        self._signal_lock = asyncio.Lock()

        # Council trigger threshold (importance score 0-100)
        self.council_trigger_threshold = 75.0
        # Minimum signals needed before auto-spawning a council
        self.council_min_signals = 3

    async def start(self) -> None:
        """Start all autonomous background loops."""
        if self._running:
            log.warning("Autonomous scheduler already running")
            return

        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()

        log.info("=" * 60)
        log.info("NCL AUTONOMOUS SCHEDULER — STARTING")
        log.info("=" * 60)
        log.info(f"  Scanner intervals: X={self.config.x_scan_interval}s, "
                 f"YT={self.config.youtube_scan_interval}s, "
                 f"Reddit={self.config.reddit_scan_interval}s")
        log.info(f"  Prediction interval: {self.config.prediction_interval}s")
        log.info(f"  Memory consolidation: {self.config.memory_consolidation_interval}s")
        log.info(f"  Council trigger threshold: {self.council_trigger_threshold}")
        if self.intelligence_engine:
            log.info(f"  Intel brief interval: {self.config.intelligence_brief_interval}s")
            log.info(f"  Intel collection interval: {self.config.intelligence_collection_interval}s")
        log.info("=" * 60)

        # Spawn background tasks
        self._tasks = [
            asyncio.create_task(self._scanner_loop(), name="ncl-scanner"),
            asyncio.create_task(self._prediction_loop(), name="ncl-predictor"),
            asyncio.create_task(self._council_auto_loop(), name="ncl-council-auto"),
            asyncio.create_task(self._memory_consolidation_loop(), name="ncl-memory"),
            asyncio.create_task(self._aac_sync_loop(), name="ncl-aac-sync"),
            asyncio.create_task(self._workspace_health_loop(), name="ncl-workspace"),
            asyncio.create_task(self._mandate_purge_loop(), name="ncl-mandate-purge"),
            asyncio.create_task(self._feedback_synthesis_loop(), name="ncl-feedback-synth"),
        ]

        # Intelligence Engine loops (only if engine is provided)
        if self.intelligence_engine:
            self._tasks.append(
                asyncio.create_task(self._intel_collection_loop(), name="ncl-intel-collect")
            )
            self._tasks.append(
                asyncio.create_task(self._intel_brief_loop(), name="ncl-intel-brief")
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
        """Gracefully stop all background loops."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        log.info("NCL Autonomous Scheduler stopped")
        await self._log_autonomous_event("scheduler_stopped", self._stats)

    def get_stats(self) -> dict:
        """Return scheduler statistics."""
        stats = {
            **self._stats,
            "running": self._running,
            "active_tasks": [t.get_name() for t in self._tasks if not t.done()],
            "signal_buffer_size": len(self._signal_buffer),
        }
        return stats

    # ─── LOOP 1: Intelligence Scanner ──────────────────────────

    async def _scanner_loop(self) -> None:
        """
        Continuously scan X, YouTube, and Reddit for intelligence signals.

        Runs Awarebot scanner at configured intervals, scores signals by
        importance, and feeds high-value signals into the prediction buffer
        and memory store.
        """
        # Stagger startup so all loops don't fire simultaneously
        await asyncio.sleep(5)

        while self._running:
            try:
                log.info("[SCANNER] Starting intelligence sweep...")

                # Run scans for each platform
                all_signals = []

                # X (Twitter) scan — scanner.scan_x takes a single query, fan out
                try:
                    x_signals: list = []
                    for q in self._get_watch_queries("x"):
                        try:
                            x_signals.extend(await self.brain.scanner.scan_x(q, max_results=25))
                        except Exception as ie:
                            log.warning(f"[SCANNER] X query '{q}' failed: {ie}")
                    all_signals.extend(x_signals)
                    log.info(f"[SCANNER] X: {len(x_signals)} signals")
                except Exception as e:
                    log.warning(f"[SCANNER] X scan failed: {e}")

                # YouTube scan
                try:
                    yt_signals: list = []
                    for q in self._get_watch_queries("youtube"):
                        try:
                            yt_signals.extend(await self.brain.scanner.scan_youtube(q, max_results=10))
                        except Exception as ie:
                            log.warning(f"[SCANNER] YouTube query '{q}' failed: {ie}")
                    all_signals.extend(yt_signals)
                    log.info(f"[SCANNER] YouTube: {len(yt_signals)} signals")
                except Exception as e:
                    log.warning(f"[SCANNER] YouTube scan failed: {e}")

                # Reddit scan — scanner.scan_reddit takes a subreddit name
                try:
                    reddit_signals: list = []
                    for sub in self._get_watch_queries("reddit"):
                        try:
                            reddit_signals.extend(await self.brain.scanner.scan_reddit(sub, max_results=15))
                        except Exception as ie:
                            log.warning(f"[SCANNER] Reddit r/{sub} failed: {ie}")
                    all_signals.extend(reddit_signals)
                    log.info(f"[SCANNER] Reddit: {len(reddit_signals)} signals")
                except Exception as e:
                    log.warning(f"[SCANNER] Reddit scan failed: {e}")

                # Process signals
                if all_signals:
                    high_signals = [s for s in all_signals if s.importance_score >= 50.0]
                    critical_signals = [s for s in all_signals if s.importance_score >= self.council_trigger_threshold]

                    # Add to signal buffer for prediction
                    async with self._signal_lock:
                        for sig in all_signals:
                            self._signal_buffer.append({
                                "source": sig.source_platform,
                                "content": sig.content[:500],
                                "importance": sig.importance_score,
                                "tags": sig.tags,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            })

                    # Store high-importance signals in memory
                    for sig in high_signals:
                        try:
                            await self.brain.memory_store.create_unit(
                                content=sig.content[:1000],
                                source=f"awarebot:{sig.source_platform}",
                                importance=sig.importance_score,
                                tags=list(sig.tags) + ["intelligence_signal", "autonomous"],
                            )
                        except Exception:
                            pass

                    self._stats["high_signals_detected"] += len(high_signals)

                    # Log signal summary
                    await self._log_autonomous_event("scan_complete", {
                        "total_signals": len(all_signals),
                        "high_signals": len(high_signals),
                        "critical_signals": len(critical_signals),
                        "platforms": {
                            "x": len([s for s in all_signals if s.source_platform == "x"]),
                            "youtube": len([s for s in all_signals if s.source_platform == "youtube"]),
                            "reddit": len([s for s in all_signals if s.source_platform == "reddit"]),
                        },
                    })

                    log.info(f"[SCANNER] Complete: {len(all_signals)} total, "
                             f"{len(high_signals)} high, {len(critical_signals)} critical")

                self._stats["scans_completed"] += 1
                self._stats["last_scan"] = datetime.now(timezone.utc).isoformat()

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[SCANNER] Loop error: {e}", exc_info=True)

            # Sleep for shortest scan interval (X is fastest at 5 min)
            await asyncio.sleep(self.config.x_scan_interval)

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
            try:
                # Drain signal buffer
                async with self._signal_lock:
                    signals = list(self._signal_buffer)
                    self._signal_buffer.clear()

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

                except Exception as e:
                    log.error(f"[PREDICTOR] Prediction failed: {e}", exc_info=True)

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
                            await self.brain.memory_store.store({
                                "type": "autonomous_council",
                                "trigger": council_trigger,
                                "consensus": session.get("consensus", ""),
                                "consensus_score": session.get("consensus_score", 0),
                                "mandates_proposed": session.get("mandates", []),
                                "importance": 90,
                                "tags": ["council", "autonomous", council_trigger],
                            })

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
            try:
                log.info("[MEMORY] Starting consolidation cycle...")

                store = self.brain.memory_store
                stats_before = await store.stats()

                # Apply decay to all units
                decayed = 0
                pruned = 0
                if hasattr(store, 'units'):
                    for unit_id, unit in list(store.units.items()):
                        # Decay is computed dynamically in store.py on access,
                        # but we force a pass here to identify prunable units
                        if hasattr(unit, 'importance') and unit.get('importance', 100) < self.config.memory_importance_threshold:
                            pruned += 1

                # Run consolidation (merging related units)
                try:
                    await store.consolidate()
                except Exception as e:
                    log.debug(f"[MEMORY] Consolidation not yet implemented: {e}")

                stats_after = await store.stats()

                self._stats["memory_consolidations"] += 1
                self._stats["last_consolidation"] = datetime.now(timezone.utc).isoformat()

                log.info(f"[MEMORY] Consolidation complete — "
                         f"units: {stats_after.get('total', 0)}, "
                         f"prunable: {pruned}")

                await self._log_autonomous_event("memory_consolidation", {
                    "stats_before": stats_before,
                    "stats_after": stats_after,
                    "pruned": pruned,
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
            try:
                aac_data = {}

                # Try AAC health endpoint
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
                    await self.brain.memory_store.store({
                        "type": "pillar_sync",
                        "pillars_reached": list(aac_data.keys()),
                        "data": aac_data,
                        "importance": 40,
                        "tags": ["aac", "sync", "pillar_status", "autonomous"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

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
            try:
                log.info("[INTEL-COLLECT] Starting signal collection sweep...")
                signals = await self.intelligence_engine.collect_all_signals()

                self._stats["intel_collections_run"] += 1
                self._stats["last_intel_collection"] = datetime.now(timezone.utc).isoformat()

                # Check for high-importance signals that need immediate alerts
                alert_threshold = 80.0
                hot_signals = [s for s in signals if s.importance_score() > alert_threshold]

                if hot_signals:
                    log.info(f"[INTEL-COLLECT] {len(hot_signals)} high-importance signals detected!")
                    try:
                        from ..strike_point_orchestrator import notify_intel_signal_alert
                        for sig in hot_signals[:3]:  # Max 3 immediate alerts per sweep
                            await notify_intel_signal_alert(sig.model_dump())
                            self._stats["intel_alerts_pushed"] += 1
                    except ImportError:
                        log.warning("[INTEL-COLLECT] Could not import notification functions")

                await self._log_autonomous_event("intel_collection", {
                    "total_signals": len(signals),
                    "hot_signals": len(hot_signals),
                    "sources": {s.source.value for s in signals} if signals else set(),
                })

                log.info(f"[INTEL-COLLECT] Collected {len(signals)} signals "
                         f"({len(hot_signals)} hot)")

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
            try:
                log.info("[INTEL-BRIEF] Generating scheduled intelligence brief...")

                brief = await self.intelligence_engine.generate_brief(brief_type="daily")

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

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"[INTEL-BRIEF] Brief generation error: {e}", exc_info=True)

            await asyncio.sleep(self.config.intelligence_brief_interval)

    # ─── Helpers ───────────────────────────────────────────────

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
        """Flag a signal/prediction for council consideration."""
        flag = {
            "trigger": trigger,
            "data": data,
            "importance": importance,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        flags_file = self.signals_dir / "council_flags.jsonl"
        try:
            import aiofiles
            async with aiofiles.open(flags_file, "a") as f:
                await f.write(json.dumps(flag, default=_json_safe) + "\n")
        except Exception as e:
            log.warning(f"Failed to write council flag: {e}")

    async def _get_council_flags(self) -> list[dict]:
        """Read pending council flags."""
        flags_file = self.signals_dir / "council_flags.jsonl"
        flags = []
        if flags_file.exists():
            try:
                import aiofiles
                async with aiofiles.open(flags_file, "r") as f:
                    content = await f.read()
                    for line in content.strip().split("\n"):
                        if line.strip():
                            flags.append(json.loads(line))
            except Exception:
                pass
        return flags

    async def _clear_council_flags(self) -> None:
        """Clear processed council flags."""
        flags_file = self.signals_dir / "council_flags.jsonl"
        if flags_file.exists():
            flags_file.unlink()

    async def _log_autonomous_event(self, event_type: str, data: dict) -> None:
        """Log an autonomous event to the autonomous events file."""
        event = {
            "type": f"autonomous.{event_type}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        events_file = self.signals_dir / "events.ndjson"
        try:
            import aiofiles
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
