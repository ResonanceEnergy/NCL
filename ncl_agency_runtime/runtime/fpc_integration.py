"""FPC ↔ NCL Daemon Integration — Bidirectional Feedback Bridge.

Wires the Future Predictor Council into the NCL Autonomous Daemon's
PDCA cycle. This creates the continuous intelligence → prediction →
learning feedback loop that connects all platform scrapers through
NCL's cognitive core.

Architecture:
    ┌─────────────────────────────────────────────────┐
    │              NCL AUTONOMOUS DAEMON               │
    │                                                  │
    │   ┌─ PLAN ─────────────────────────────────┐    │
    │   │  Gap Analyzer + FPC Intelligence Scan   │    │
    │   └─────────────────┬───────────────────────┘    │
    │                     │                            │
    │   ┌─ DO ────────────▼───────────────────────┐    │
    │   │  Run FPC Feedback Cycle                 │    │
    │   │  ├─ Collect from all platform scrapers  │    │
    │   │  ├─ Aggregate & normalize signals       │    │
    │   │  ├─ Detect cross-platform trends        │    │
    │   │  ├─ Generate predictions via Council     │    │
    │   │  └─ Verify past predictions             │    │
    │   └─────────────────┬───────────────────────┘    │
    │                     │                            │
    │   ┌─ CHECK ─────────▼───────────────────────┐    │
    │   │  Prediction accuracy → adjust weights   │    │
    │   │  Platform coverage → identify blind spots│    │
    │   └─────────────────┬───────────────────────┘    │
    │                     │                            │
    │   ┌─ ACT ───────────▼───────────────────────┐    │
    │   │  Feed insights back to NCL memory       │    │
    │   │  Update scraper priorities              │    │
    │   │  Journal everything for compounding     │    │
    │   └─────────────────────────────────────────┘    │
    └─────────────────────────────────────────────────┘

NCC Triad Routing:
    - Predictions → NCL Brain (cognitive augmentation)
    - Market trends → AAC Bank (financial intelligence)
    - Platform signals → BRS (agent dispatch)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("ncl.fpc_integration")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_FPC_ROOT = _REPO_ROOT / "ncl_agency_runtime" / "fpc"


# ── Dataclasses ─────────────────────────────────────────────────


@dataclass
class FPCCycleResult:
    """Result from one FPC intelligence cycle within the daemon."""

    cycle_id: str
    timestamp: str
    platforms_scraped: list[str]
    signals_collected: int
    trends_detected: int
    predictions_made: int
    predictions_verified: int
    accuracy_rate: float
    top_trends: list[str]
    platform_priorities: dict[str, float]
    domain_priorities: dict[str, float]
    learning_notes: list[str]
    duration_s: float = 0.0
    errors: list[str] = field(default_factory=list)


@dataclass
class IntelligenceReport:
    """Summary report fed back to NCL Brain memory."""

    report_id: str
    timestamp: str
    executive_summary: str
    active_trends: list[dict[str, Any]]
    predictions: list[dict[str, Any]]
    platform_coverage: dict[str, int]
    accuracy_metrics: dict[str, Any]
    recommended_actions: list[str]


# ── Platform Scraper Orchestrator ───────────────────────────────


class PlatformOrchestrator:
    """Coordinate all platform intelligence scrapers."""

    def __init__(self) -> None:
        self._scrapers_available: dict[str, bool] = {}
        self._last_errors: dict[str, str] = {}

    def run_all_scrapers(self) -> dict[str, Any]:
        """Execute all available platform scrapers and return results."""
        results: dict[str, Any] = {}
        platforms_scraped: list[str] = []
        errors: list[str] = []

        # GitHub
        try:
            from ncl_agency_runtime.fpc.github_intelligence import GitHubIntelligence
            gh = GitHubIntelligence()
            digest = gh.collect()
            results["github"] = {"signals": len(digest.signals), "status": "ok"}
            platforms_scraped.append("github")
        except Exception as exc:
            errors.append(f"GitHub: {exc}")
            logger.debug("GitHub scraper failed: %s", exc)

        # Reddit
        try:
            from ncl_agency_runtime.fpc.reddit_intelligence import RedditIntelligence
            reddit = RedditIntelligence()
            reddit_digest = reddit.collect()
            results["reddit"] = {"posts": len(reddit_digest.posts), "status": "ok"}
            platforms_scraped.append("reddit")
        except Exception as exc:
            errors.append(f"Reddit: {exc}")
            logger.debug("Reddit scraper failed: %s", exc)

        # Substack
        try:
            from ncl_agency_runtime.fpc.substack_intelligence import SubstackIntelligence
            ss = SubstackIntelligence()
            ss_digest = ss.collect()
            results["substack"] = {"articles": len(ss_digest.articles), "status": "ok"}
            platforms_scraped.append("substack")
        except Exception as exc:
            errors.append(f"Substack: {exc}")
            logger.debug("Substack scraper failed: %s", exc)

        # Google Trends
        try:
            from ncl_agency_runtime.fpc.google_trends_intelligence import GoogleTrendsIntelligence
            gt = GoogleTrendsIntelligence()
            gt_digest = gt.collect()
            results["google_trends"] = {"signals": len(gt_digest.signals), "status": "ok"}
            platforms_scraped.append("google_trends")
        except Exception as exc:
            errors.append(f"Google Trends: {exc}")
            logger.debug("Google Trends scraper failed: %s", exc)

        # TikTok
        try:
            from ncl_agency_runtime.fpc.tiktok_intelligence import TikTokIntelligence
            tt = TikTokIntelligence()
            tt_digest = tt.collect()
            results["tiktok"] = {"signals": len(tt_digest.signals), "status": "ok"}
            platforms_scraped.append("tiktok")
        except Exception as exc:
            errors.append(f"TikTok: {exc}")
            logger.debug("TikTok scraper failed: %s", exc)

        # Instagram
        try:
            from ncl_agency_runtime.fpc.instagram_intelligence import InstagramIntelligence
            ig = InstagramIntelligence()
            ig_digest = ig.collect()
            results["instagram"] = {"signals": len(ig_digest.signals), "status": "ok"}
            platforms_scraped.append("instagram")
        except Exception as exc:
            errors.append(f"Instagram: {exc}")
            logger.debug("Instagram scraper failed: %s", exc)

        # X/Twitter
        try:
            from ncl_agency_runtime.fpc.x_intelligence import XFeedScraper
            xscraper = XFeedScraper()
            result = xscraper.collect_and_process()
            results["x_twitter"] = {"scraped": result.get("total_scraped", 0), "status": "ok"}
            platforms_scraped.append("x_twitter")
        except Exception as exc:
            errors.append(f"X/Twitter: {exc}")
            logger.debug("X/Twitter scraper failed: %s", exc)

        # YouTube (existing)
        try:
            from ncl_agency_runtime.fpc.youtube_intelligence import YouTubeIntelligenceEngine
            yt = YouTubeIntelligenceEngine()
            report = yt.tracker.trend_report()
            results["youtube"] = {"tracked_tools": report.get("total_tools_tracked", 0), "status": "ok"}
            platforms_scraped.append("youtube")
        except Exception as exc:
            errors.append(f"YouTube: {exc}")
            logger.debug("YouTube scraper failed: %s", exc)

        return {
            "platforms_scraped": platforms_scraped,
            "results": results,
            "errors": errors,
        }


# ── FPC Daemon Handler ─────────────────────────────────────────


class FPCDaemonHandler:
    """Handles FPC intelligence tasks within the autonomous daemon.

    Plugs into the daemon's TaskExecutor via the 'fpc_intelligence' category.
    Each daemon PDCA cycle can include FPC intelligence gathering,
    trend detection, and prediction generation.
    """

    def __init__(self, repo_root: Path | None = None):
        self._repo_root = repo_root or _REPO_ROOT
        self._orchestrator = PlatformOrchestrator()
        self._last_cycle_result: FPCCycleResult | None = None

    async def handle_fpc_task(self, task: Any) -> dict[str, Any]:
        """Handle an FPC intelligence task from the daemon."""
        task_type = getattr(task, "description", "").lower()

        if "full_cycle" in task_type or "intelligence" in task_type:
            return await self._run_full_intelligence_cycle()
        if "scrape" in task_type or "collect" in task_type:
            return self._run_scraper_pass()
        if "predict" in task_type or "trend" in task_type:
            return await self._run_prediction_cycle()
        if "verify" in task_type or "accuracy" in task_type:
            return self._run_verification()

        # Default: full cycle
        return await self._run_full_intelligence_cycle()

    async def _run_full_intelligence_cycle(self) -> dict[str, Any]:
        """Execute a complete FPC intelligence cycle."""
        start = time.time()
        errors: list[str] = []

        # Step 1: Run all platform scrapers
        scraper_results = self._orchestrator.run_all_scrapers()

        # Step 2: Run the prediction feedback loop
        feedback_result: dict[str, Any] = {}
        try:
            from ncl_agency_runtime.fpc.prediction_feedback_loop import (
                PredictionFeedbackLoop,
            )
            loop = PredictionFeedbackLoop(data_dir=_FPC_ROOT / "data")
            report = loop.run_cycle()
            feedback_result = {
                "signals": report.signals_collected,
                "trends": report.trends_detected,
                "predictions": report.predictions_made,
                "verified": report.predictions_verified,
                "accuracy": report.accuracy_rate,
                "top_trends": report.top_trends[:5],
            }
            priorities = loop.get_priorities()
        except Exception as exc:
            errors.append(f"Feedback loop: {exc}")
            logger.warning("FPC feedback loop failed: %s", exc)
            feedback_result = {"error": str(exc)}
            priorities = {"platform_priorities": {}, "domain_priorities": {}}

        # Step 3: Build cycle result
        cycle_result = FPCCycleResult(
            cycle_id=f"FPC-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}",
            timestamp=datetime.now(UTC).isoformat(),
            platforms_scraped=scraper_results.get("platforms_scraped", []),
            signals_collected=feedback_result.get("signals", 0),
            trends_detected=feedback_result.get("trends", 0),
            predictions_made=feedback_result.get("predictions", 0),
            predictions_verified=feedback_result.get("verified", 0),
            accuracy_rate=feedback_result.get("accuracy", 0.0),
            top_trends=feedback_result.get("top_trends", []),
            platform_priorities=priorities.get("platform_priorities", {}),
            domain_priorities=priorities.get("domain_priorities", {}),
            learning_notes=[
                f"Scraped {len(scraper_results.get('platforms_scraped', []))} platforms",
                f"Detected {feedback_result.get('trends', 0)} cross-platform trends",
            ],
            duration_s=round(time.time() - start, 2),
            errors=errors + scraper_results.get("errors", []),
        )

        self._last_cycle_result = cycle_result

        # Step 4: Persist intelligence report for NCL Brain
        self._persist_intelligence_report(cycle_result)

        return {
            "action": "fpc_full_intelligence_cycle",
            "status": "completed",
            "cycle_id": cycle_result.cycle_id,
            "platforms_scraped": cycle_result.platforms_scraped,
            "signals": cycle_result.signals_collected,
            "trends": cycle_result.trends_detected,
            "predictions": cycle_result.predictions_made,
            "accuracy": cycle_result.accuracy_rate,
            "top_trends": cycle_result.top_trends,
            "duration_s": cycle_result.duration_s,
            "errors": cycle_result.errors,
        }

    def _run_scraper_pass(self) -> dict[str, Any]:
        """Run just the platform scrapers without prediction."""
        results = self._orchestrator.run_all_scrapers()
        return {
            "action": "fpc_scraper_pass",
            "status": "completed",
            **results,
        }

    async def _run_prediction_cycle(self) -> dict[str, Any]:
        """Run just the prediction feedback loop."""
        try:
            from ncl_agency_runtime.fpc.prediction_feedback_loop import (
                PredictionFeedbackLoop,
            )
            loop = PredictionFeedbackLoop(data_dir=_FPC_ROOT / "data")
            report = loop.run_cycle()
            return {
                "action": "fpc_prediction_cycle",
                "status": "completed",
                "signals": report.signals_collected,
                "trends": report.trends_detected,
                "predictions": report.predictions_made,
                "accuracy": report.accuracy_rate,
                "top_trends": report.top_trends[:10],
            }
        except Exception as exc:
            return {"action": "fpc_prediction_cycle", "status": "error", "error": str(exc)}

    def _run_verification(self) -> dict[str, Any]:
        """Verify past predictions against current data."""
        try:
            from ncl_agency_runtime.fpc.prediction_feedback_loop import (
                PredictionTracker,
            )
            tracker = PredictionTracker(data_dir=_FPC_ROOT / "data" / "predictions")
            report = tracker.accuracy_report()
            return {"action": "fpc_verification", "status": "completed", **report}
        except Exception as exc:
            return {"action": "fpc_verification", "status": "error", "error": str(exc)}

    def _persist_intelligence_report(self, result: FPCCycleResult) -> None:
        """Write intelligence report for NCL Brain consumption."""
        report_dir = _FPC_ROOT / "data" / "ncl_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"intel_report_{datetime.now(UTC).strftime('%Y%m%d')}.json"
        try:
            report = IntelligenceReport(
                report_id=result.cycle_id,
                timestamp=result.timestamp,
                executive_summary=(
                    f"FPC Intelligence Cycle: {result.signals_collected} signals from "
                    f"{len(result.platforms_scraped)} platforms, "
                    f"{result.trends_detected} trends detected, "
                    f"{result.predictions_made} predictions generated. "
                    f"Accuracy: {result.accuracy_rate:.1%}"
                ),
                active_trends=[{"topic": t} for t in result.top_trends],
                predictions=[],
                platform_coverage={p: 1 for p in result.platforms_scraped},
                accuracy_metrics={"rate": result.accuracy_rate},
                recommended_actions=result.learning_notes,
            )
            report_file.write_text(
                json.dumps(asdict(report), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to persist intelligence report: %s", exc)


# ── Gap Scanner Extension ───────────────────────────────────────


def scan_fpc_health(repo_root: Path) -> list[dict[str, Any]]:
    """Additional gap scanner for FPC intelligence coverage.

    Plug this into the daemon's GapAnalyzer to detect intelligence gaps.
    """
    gaps: list[dict[str, Any]] = []
    fpc_root = repo_root / "ncl_agency_runtime" / "fpc"

    if not fpc_root.exists():
        gaps.append({
            "category": "fpc_intelligence",
            "severity": "high",
            "description": "Future Predictor Council directory not found",
            "source": "fpc_health",
        })
        return gaps

    # Check for platform scraper modules
    expected_scrapers = [
        "github_intelligence.py",
        "reddit_intelligence.py",
        "substack_intelligence.py",
        "google_trends_intelligence.py",
        "tiktok_intelligence.py",
        "instagram_intelligence.py",
        "x_intelligence.py",
        "youtube_intelligence.py",
    ]
    for scraper in expected_scrapers:
        if not (fpc_root / scraper).exists():
            gaps.append({
                "category": "fpc_intelligence",
                "severity": "normal",
                "description": f"Missing platform scraper: {scraper}",
                "source": "fpc_health",
            })

    # Check for prediction data
    pred_dir = fpc_root / "data" / "predictions"
    if not pred_dir.exists() or not list(pred_dir.glob("*.json")):
        gaps.append({
            "category": "fpc_intelligence",
            "severity": "low",
            "description": "No prediction data found — FPC feedback loop not yet run",
            "source": "fpc_health",
        })

    # Check for stale intelligence (no data in last 24h)
    cache_dirs = ["github_cache", "reddit_cache", "substack_cache",
                  "gtrends_cache", "tiktok_cache", "instagram_cache", "x_cache"]
    data_dir = fpc_root / "data"
    stale_platforms: list[str] = []
    for cache_name in cache_dirs:
        cache_dir = data_dir / cache_name
        if cache_dir.exists():
            files = sorted(cache_dir.glob("*.json"))
            if not files:
                stale_platforms.append(cache_name.replace("_cache", ""))
        else:
            stale_platforms.append(cache_name.replace("_cache", ""))

    if stale_platforms:
        gaps.append({
            "category": "fpc_intelligence",
            "severity": "normal",
            "description": f"No cached data for platforms: {', '.join(stale_platforms)}",
            "source": "fpc_health",
        })

    return gaps


# ── Scheduled Task Generator ────────────────────────────────────


def generate_fpc_scheduled_tasks() -> list[dict[str, Any]]:
    """Generate scheduled FPC tasks for the daemon's task generator.

    Returns task dicts that can be converted to AutonomousTask.
    """
    return [
        {
            "title": "FPC Full Intelligence Cycle",
            "description": "Run full_cycle FPC intelligence gathering, trend detection, and prediction",
            "category": "fpc_intelligence",
            "priority": "normal",
            "tags": ["fpc", "intelligence", "scheduled"],
        },
    ]
