"""
LDE Sandbox + Living Doctrine Persistence.

The Sandbox is the persistent current-affairs state — it holds all prior
insights, analyses, and the Living Doctrine JSON. Every new URL updates
both the sandbox (vector + JSONL) and the doctrine (structured JSON).

Storage:
    ~/dev/NCL/data/lde/
    ├── LIVING_DOCTRINE.json       # The doctrine itself
    ├── sandbox_entries.jsonl       # All sandbox entries (append-only)
    ├── insights.jsonl              # All extracted insights (append-only)
    └── vector_sandbox/             # ChromaDB/TF-IDF vector index
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import aiofiles

from .models import (
    DoctrineRule,
    DoctrineSignal,
    InsightCategory,
    LivingDoctrine,
    RiskThreshold,
    RuleStatus,
    SandboxEntry,
    TradingInsight,
    TrendMonitor,
)


log = logging.getLogger("ncl.lde.sandbox")

NCL_BASE = Path(os.getenv("NCL_BASE", str(Path.home() / "dev" / "NCL")))


class LDESandbox:
    """
    Persistent sandbox for the Living Doctrine Engine.

    Manages doctrine state, sandbox entries, insight history,
    and vector indexing.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir else NCL_BASE / "data" / "lde"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.doctrine_file = self.data_dir / "LIVING_DOCTRINE.json"
        self.sandbox_file = self.data_dir / "sandbox_entries.jsonl"
        self.insights_file = self.data_dir / "insights.jsonl"

        self._doctrine: LivingDoctrine | None = None
        self._vector_store = None

    async def init(self) -> None:
        """Initialize sandbox — load doctrine and vector store."""
        self._doctrine = self._load_doctrine()

        # Try to initialize vector store — use the shared singleton so
        # we don't open a second chromadb.PersistentClient against the
        # same on-disk store (see vector_store_singleton.py docstring
        # for the 2026-05-24 deadlock incident this prevents).
        try:
            from ..councils.shared.vector_store_singleton import get_council_vector_store

            self._vector_store = await get_council_vector_store(self.data_dir)
            log.info(f"LDE vector store: {self._vector_store._backend}")
        except Exception as e:
            log.warning(f"Vector store init failed (will use doctrine-only mode): {e}")

    def _load_doctrine(self) -> LivingDoctrine:
        """Load or create the Living Doctrine."""
        if self.doctrine_file.exists():
            try:
                raw = json.loads(self.doctrine_file.read_text())
                doctrine = LivingDoctrine(**raw)
                log.info(
                    f"Doctrine loaded: v{doctrine.version}, "
                    f"{doctrine.urls_processed} URLs processed, "
                    f"{len(doctrine.core_rules)} rules"
                )
                return doctrine
            except Exception as e:
                log.warning(f"Failed to load doctrine, creating fresh: {e}")

        doctrine = LivingDoctrine()
        self._save_doctrine(doctrine)
        log.info("Fresh Living Doctrine created")
        return doctrine

    def _save_doctrine(self, doctrine: LivingDoctrine) -> None:
        """Persist doctrine to disk."""
        doctrine.last_updated = datetime.now(timezone.utc)
        self.doctrine_file.write_text(
            doctrine.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @property
    def doctrine(self) -> LivingDoctrine:
        if not self._doctrine:
            self._doctrine = self._load_doctrine()
        return self._doctrine

    def get_doctrine_dict(self) -> dict:
        """Return doctrine as a plain dict (for passing to agents)."""
        return json.loads(self.doctrine.model_dump_json())

    async def save_entry(self, entry: SandboxEntry) -> None:
        """Append a sandbox entry to the JSONL log."""
        async with aiofiles.open(self.sandbox_file, "a") as f:
            await f.write(entry.model_dump_json() + "\n")

    async def save_insights(self, insights: list[TradingInsight]) -> None:
        """Append insights to the insights JSONL log."""
        async with aiofiles.open(self.insights_file, "a") as f:
            for insight in insights:
                await f.write(insight.model_dump_json() + "\n")

        # Also index in vector store
        if self._vector_store:
            for insight in insights:
                try:
                    text = f"{insight.title}. {insight.signal}. {insight.analysis}"
                    if insight.tickers:
                        text += " " + " ".join(insight.tickers)
                    if insight.tags:
                        text += " " + " ".join(insight.tags)

                    await self._vector_store.index_document(
                        doc_id=insight.insight_id,
                        text=text,
                        metadata={
                            "type": "trading_insight",
                            "category": insight.category.value,
                            "confidence": insight.confidence,
                            "urgency": insight.urgency.value,
                            "source_url": insight.source_url,
                            "tickers": ",".join(insight.tickers),
                        },
                    )
                except Exception as e:
                    log.warning(f"Vector index failed for insight: {e}")

    async def apply_doctrine_updates(self, updates: dict) -> str:
        """
        Apply structured updates from the Doctrine Guardian to the doctrine.

        Returns summary of changes made.
        """
        doctrine = self.doctrine
        changes: list[str] = []

        # New rules
        for rule_data in updates.get("new_rules", []):
            try:
                cat = InsightCategory(rule_data.get("category", "macro"))
            except ValueError:
                cat = InsightCategory.MACRO

            rule = DoctrineRule(
                title=rule_data.get("title", "Untitled"),
                description=rule_data.get("description", ""),
                category=cat,
                strength=float(rule_data.get("strength", 5.0)),
                tickers=rule_data.get("tickers", []),
                action=rule_data.get("action", ""),
            )
            if rule_data.get("expires_at"):
                try:
                    rule.expires_at = datetime.fromisoformat(rule_data["expires_at"])
                except (ValueError, TypeError):
                    pass

            doctrine.core_rules.append(rule)
            changes.append(f"+ Rule: {rule.title}")

        # Updated rules
        for update in updates.get("updated_rules", []):
            rule_id = update.get("rule_id", "")
            rule_changes = update.get("changes", {})
            for rule in doctrine.core_rules:
                if rule.rule_id == rule_id:
                    for key, val in rule_changes.items():
                        if hasattr(rule, key):
                            setattr(rule, key, val)
                    rule.updated_at = datetime.now(timezone.utc)
                    changes.append(f"~ Rule updated: {rule.title}")
                    break

        # Suspended rules
        for suspension in updates.get("suspended_rules", []):
            rule_id = suspension.get("rule_id", "")
            for rule in doctrine.core_rules:
                if rule.rule_id == rule_id:
                    rule.status = RuleStatus.SUSPENDED
                    changes.append(f"- Rule suspended: {rule.title}")
                    break

        # New signals
        for sig_data in updates.get("new_signals", []):
            try:
                cat = InsightCategory(sig_data.get("category", "macro"))
            except ValueError:
                cat = InsightCategory.MACRO

            signal = DoctrineSignal(
                name=sig_data.get("name", "Untitled"),
                description=sig_data.get("description", ""),
                category=cat,
                direction=sig_data.get("direction", "neutral"),
                strength=float(sig_data.get("strength", 5.0)),
                tickers=sig_data.get("tickers", []),
            )
            doctrine.active_signals.append(signal)
            changes.append(f"+ Signal: {signal.name} ({signal.direction})")

        # New trends
        for trend_data in updates.get("new_trends", []):
            try:
                cat = InsightCategory(trend_data.get("category", "macro"))
            except ValueError:
                cat = InsightCategory.MACRO

            trend = TrendMonitor(
                name=trend_data.get("name", "Untitled"),
                description=trend_data.get("description", ""),
                category=cat,
                direction=trend_data.get("direction", "emerging"),
                confidence=float(trend_data.get("confidence", 5.0)),
                tickers=trend_data.get("tickers", []),
                sectors=trend_data.get("sectors", []),
                watch_triggers=trend_data.get("watch_triggers", []),
            )
            doctrine.monitored_trends.append(trend)
            changes.append(f"+ Trend: {trend.name} ({trend.direction})")

        # Risk threshold updates
        for rt_data in updates.get("risk_threshold_updates", []):
            rt = RiskThreshold(
                name=rt_data.get("name", ""),
                category=rt_data.get("category", ""),
                current_level=float(rt_data.get("current_level", 5.0)),
                alert_level=float(rt_data.get("alert_level", 7.0)),
                description=rt_data.get("description", ""),
            )
            # Update existing or add new
            found = False
            for i, existing in enumerate(doctrine.risk_thresholds):
                if existing.name == rt.name:
                    doctrine.risk_thresholds[i] = rt
                    found = True
                    changes.append(f"~ Risk threshold: {rt.name} → {rt.current_level}")
                    break
            if not found:
                doctrine.risk_thresholds.append(rt)
                changes.append(f"+ Risk threshold: {rt.name}")

        # Top-level updates
        if "market_bias" in updates:
            doctrine.market_bias = updates["market_bias"]
        if "confidence_score" in updates:
            doctrine.confidence_score = float(updates["confidence_score"])
        if "top_tickers" in updates:
            doctrine.top_tickers = updates["top_tickers"]

        # Save
        self._save_doctrine(doctrine)

        summary = f"{len(changes)} changes applied"
        if changes:
            summary += ": " + "; ".join(changes[:5])
            if len(changes) > 5:
                summary += f" (+{len(changes) - 5} more)"

        log.info(f"Doctrine updated: {summary}")
        return summary

    async def add_history_entry(
        self,
        url: str,
        insights_count: int,
        analysis_summary: str,
        doctrine_changes: str,
    ) -> None:
        """Add an entry to the doctrine's evolution history."""
        doctrine = self.doctrine
        doctrine.urls_processed += 1
        doctrine.total_insights_extracted += insights_count

        doctrine.history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "url": url,
                "insights_extracted": insights_count,
                "analysis_summary": analysis_summary[:500],
                "doctrine_changes": doctrine_changes[:500],
            }
        )

        # Keep history manageable (last 200 entries in full, summarize older)
        if len(doctrine.history) > 200:
            doctrine.history = doctrine.history[-200:]

        self._save_doctrine(doctrine)

    async def get_recent_history(self, limit: int = 10) -> list[dict]:
        """Get recent sandbox entries."""
        entries: list[dict] = []
        if not self.sandbox_file.exists():
            return entries

        try:
            async with aiofiles.open(self.sandbox_file, "r") as f:
                lines = await f.readlines()
            for line in lines[-limit:]:
                if line.strip():
                    entries.append(json.loads(line))
        except Exception as e:
            log.warning(f"Failed to read sandbox history: {e}")

        return entries

    async def search_insights(self, query: str, top_k: int = 10) -> list[dict]:
        """Search the vector store for relevant prior insights."""
        if not self._vector_store:
            return []

        try:
            results = await self._vector_store.query(query, top_k=top_k)
            return [r.to_dict() for r in results]
        except Exception as e:
            log.warning(f"Vector search failed: {e}")
            return []

    def get_stats(self) -> dict:
        """Return sandbox statistics."""
        doctrine = self.doctrine
        return {
            "urls_processed": doctrine.urls_processed,
            "total_insights": doctrine.total_insights_extracted,
            "active_rules": len([r for r in doctrine.core_rules if r.status == RuleStatus.ACTIVE]),
            "suspended_rules": len(
                [r for r in doctrine.core_rules if r.status == RuleStatus.SUSPENDED]
            ),
            "active_signals": len(doctrine.active_signals),
            "monitored_trends": len(doctrine.monitored_trends),
            "risk_thresholds": len(doctrine.risk_thresholds),
            "market_bias": doctrine.market_bias,
            "confidence_score": doctrine.confidence_score,
            "top_tickers": doctrine.top_tickers,
            "doctrine_version": doctrine.version,
            "last_updated": doctrine.last_updated.isoformat(),
            "vector_store": self._vector_store.get_stats() if self._vector_store else None,
        }
