"""
LDE Pipeline Engine — The main orchestrator.

URL → Ingest → Extract → Analyze → Update Doctrine

This is the single entry point. Call `process_url()` and the entire
pipeline runs: transcription, insight extraction, sandbox analysis,
doctrine evolution.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from .models import TradingInsight, SandboxEntry, InsightCategory, Urgency
from .ingestor import ingest_url
from .agents import extract_insights, analyze_against_sandbox, update_doctrine
from .sandbox import LDESandbox

log = logging.getLogger("ncl.lde.engine")


class LivingDoctrineEngine:
    """
    Main LDE pipeline engine.

    Usage:
        engine = LivingDoctrineEngine()
        await engine.init()
        result = await engine.process_url("https://youtube.com/watch?v=...")
    """

    def __init__(self, data_dir: str | None = None) -> None:
        self.sandbox = LDESandbox(data_dir=data_dir)
        self._initialized = False

    async def init(self) -> None:
        """Initialize the engine and sandbox."""
        if self._initialized:
            return
        await self.sandbox.init()
        self._initialized = True
        log.info("Living Doctrine Engine initialized")

    async def process_url(self, url: str, source_type: str | None = None) -> dict[str, Any]:
        """
        Full pipeline: URL → Ingest → Extract → Analyze → Evolve Doctrine.

        Args:
            url: Any URL (YouTube, article, earnings call, etc.)
            source_type: Override auto-detected source type

        Returns:
            Pipeline result dict with insights, analysis, and doctrine changes
        """
        if not self._initialized:
            await self.init()

        pipeline_start = time.monotonic()
        log.info(f"{'='*60}")
        log.info(f"  LDE PIPELINE — Processing: {url}")
        log.info(f"{'='*60}")

        result: dict[str, Any] = {
            "url": url,
            "status": "processing",
            "stages": {},
        }

        # ── Stage 1: Ingest ──────────────────────────────────────────
        log.info("Stage 1/4: Ingesting URL...")
        stage_start = time.monotonic()

        ingestion = await ingest_url(url, source_type=source_type)
        text = ingestion.get("text", "")
        title = ingestion.get("title", "")
        method = ingestion.get("method", "unknown")
        detected_type = ingestion.get("source_type", "unknown")

        result["stages"]["ingest"] = {
            "title": title,
            "source_type": detected_type,
            "method": method,
            "text_length": len(text),
            "duration_seconds": ingestion.get("duration_seconds", "0"),
            "elapsed": round(time.monotonic() - stage_start, 1),
        }

        if not text or len(text) < 50:
            log.error(f"Ingestion failed or produced insufficient text ({len(text)} chars)")
            result["status"] = "failed"
            result["error"] = "Ingestion produced no usable text"
            return result

        log.info(f"Ingested: '{title}' ({len(text)} chars via {method})")

        # ── Stage 2: Extract Insights ─────────────────────────────────
        log.info("Stage 2/4: Extracting trading insights...")
        stage_start = time.monotonic()

        raw_insights = await extract_insights(text, url, detected_type)

        # Convert to TradingInsight models
        insights: list[TradingInsight] = []
        for raw in raw_insights:
            try:
                cat = InsightCategory(raw.get("category", "macro"))
            except ValueError:
                cat = InsightCategory.MACRO
            try:
                urg = Urgency(raw.get("urgency", "medium"))
            except ValueError:
                urg = Urgency.MEDIUM

            insights.append(TradingInsight(
                title=raw.get("title", "Untitled"),
                signal=raw.get("signal", ""),
                analysis=raw.get("analysis", ""),
                category=cat,
                confidence=float(raw.get("confidence", 5.0)),
                urgency=urg,
                tickers=raw.get("tickers", []),
                sectors=raw.get("sectors", []),
                tags=raw.get("tags", []),
                source_url=url,
                source_type=detected_type,
            ))

        # Persist insights
        await self.sandbox.save_insights(insights)

        result["stages"]["extract"] = {
            "insights_count": len(insights),
            "categories": list(set(i.category.value for i in insights)),
            "tickers_mentioned": list(set(t for i in insights for t in i.tickers)),
            "avg_confidence": round(sum(i.confidence for i in insights) / max(len(insights), 1), 1),
            "elapsed": round(time.monotonic() - stage_start, 1),
        }
        result["insights"] = [
            {"title": i.title, "category": i.category.value,
             "confidence": i.confidence, "urgency": i.urgency.value,
             "tickers": i.tickers, "signal": i.signal[:200]}
            for i in insights
        ]

        log.info(f"Extracted {len(insights)} insights")

        # ── Stage 3: Analyze Against Sandbox ──────────────────────────
        log.info("Stage 3/4: Analyzing against sandbox + doctrine...")
        stage_start = time.monotonic()

        doctrine_dict = self.sandbox.get_doctrine_dict()
        recent_history = await self.sandbox.get_recent_history(limit=5)

        analysis = await analyze_against_sandbox(
            new_insights=raw_insights,
            doctrine=doctrine_dict,
            recent_history=recent_history,
        )

        result["stages"]["analyze"] = {
            "cross_references": len(analysis.get("cross_references", [])),
            "convergence_signals": len(analysis.get("convergence_signals", [])),
            "contradictions": len(analysis.get("contradictions", [])),
            "market_bias_shift": analysis.get("market_bias_shift", "unknown"),
            "summary": analysis.get("summary", "")[:300],
            "elapsed": round(time.monotonic() - stage_start, 1),
        }
        result["analysis"] = analysis

        log.info(f"Analysis complete — bias shift: {analysis.get('market_bias_shift', '?')}")

        # ── Stage 4: Update Living Doctrine ───────────────────────────
        log.info("Stage 4/4: Updating Living Doctrine...")
        stage_start = time.monotonic()

        updates = await update_doctrine(
            doctrine=doctrine_dict,
            new_insights=raw_insights,
            analysis=analysis,
        )

        # Apply updates to the actual doctrine
        changes_summary = await self.sandbox.apply_doctrine_updates(updates)

        # Record in history
        await self.sandbox.add_history_entry(
            url=url,
            insights_count=len(insights),
            analysis_summary=analysis.get("summary", ""),
            doctrine_changes=changes_summary,
        )

        # Save sandbox entry
        entry = SandboxEntry(
            source_url=url,
            source_type=detected_type,
            insights=[i for i in insights],
            raw_transcript=text[:5000],
            analysis_output=analysis.get("summary", ""),
            doctrine_changes=changes_summary,
            metadata={"title": title, "method": method},
        )
        await self.sandbox.save_entry(entry)

        result["stages"]["doctrine_update"] = {
            "new_rules": len(updates.get("new_rules", [])),
            "updated_rules": len(updates.get("updated_rules", [])),
            "suspended_rules": len(updates.get("suspended_rules", [])),
            "new_signals": len(updates.get("new_signals", [])),
            "new_trends": len(updates.get("new_trends", [])),
            "changes_summary": changes_summary,
            "doctrine_summary": updates.get("doctrine_summary", ""),
            "elapsed": round(time.monotonic() - stage_start, 1),
        }

        # ── Pipeline Complete ─────────────────────────────────────────
        total_elapsed = round(time.monotonic() - pipeline_start, 1)
        result["status"] = "complete"
        result["total_elapsed_seconds"] = total_elapsed
        result["doctrine_stats"] = self.sandbox.get_stats()

        log.info(f"{'='*60}")
        log.info(f"  LDE PIPELINE COMPLETE — {total_elapsed}s")
        log.info(f"  Insights: {len(insights)} | Bias: {analysis.get('market_bias_shift', '?')}")
        log.info(f"  Doctrine: {changes_summary}")
        log.info(f"{'='*60}")

        return result

    def get_doctrine(self) -> dict:
        """Return the current Living Doctrine as a dict."""
        return self.sandbox.get_doctrine_dict()

    def get_stats(self) -> dict:
        """Return engine + sandbox statistics."""
        return self.sandbox.get_stats()
