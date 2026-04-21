"""NCL Intelligence Engine — orchestrates collection, analysis, and brief generation.

This is the brain of NCL's intelligence system. It:
1. Runs all collectors in parallel
2. Correlates signals across sources
3. Clusters signals into sectors/themes
4. Uses LLM to synthesize executive summaries
5. Produces structured IntelBrief objects
6. Persists briefs and tracks prediction accuracy

Replaces the old scanner → static-score → memory-dump pipeline
with real analysis that produces decision-quality intelligence.
"""

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiofiles
import httpx

from .models import (
    IntelBrief,
    IntelSignal,
    SocialSignal,
    SectorSnapshot,
    SignalDirection,
    SourceType,
)
from .collectors import (
    GoogleTrendsCollector,
    PolymarketCollector,
    NewsCollector,
    CryptoMarketCollector,
    RedditCollector,
)

log = logging.getLogger("ncl.intelligence.engine")


# ═══════════════════════════════════════════════════════════════════════════
# SIGNAL CORRELATOR
# ═══════════════════════════════════════════════════════════════════════════


class SignalCorrelator:
    """
    Groups signals by theme/sector, detects cross-source convergence,
    and ranks by combined importance.
    """

    # Keywords → sector mapping
    SECTOR_KEYWORDS = {
        "crypto": [
            "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
            "defi", "solana", "web3", "nft", "token", "stablecoin", "altcoin",
        ],
        "ai_tech": [
            "ai", "artificial intelligence", "llm", "openai", "anthropic",
            "claude", "gpt", "machine learning", "deepmind", "agi",
            "chatgpt", "gemini ai", "nvidia ai",
        ],
        "macro": [
            "fed", "federal reserve", "inflation", "interest rate", "gdp",
            "recession", "employment", "treasury", "bond", "cpi",
            "tariff", "trade war", "debt ceiling", "yield curve",
            "unemployment", "central bank",
        ],
        "politics": [
            "election", "president", "congress", "senate", "regulation",
            "policy", "government", "democrat", "republican", "trump",
            "biden", "vote", "legislation", "supreme court",
            "war", "ceasefire", "ukraine", "russia", "china", "israel",
            "nato", "sanctions", "hezbollah", "hamas", "iran", "military",
            "geopolit",
        ],
        "markets": [
            "stock", "s&p", "nasdaq", "dow", "equity", "trading",
            "options", "call flow", "put flow", "unusual whales",
            "earnings", "ipo", "merger", "acquisition",
        ],
        "tech": [
            "apple", "google", "microsoft", "amazon", "meta", "tesla",
            "spacex", "semiconductor", "chip", "iphone", "startup",
            "software", "saas", "cloud computing",
        ],
        "entertainment": [
            "movie", "film", "oscars", "emmy", "grammy", "album",
            "eurovision", "gta", "game release", "box office",
            "streaming", "netflix", "disney", "tv show", "celebrity",
            "music award",
        ],
        "sports": [
            "sport", "nba", "nfl", "mlb", "nhl", "soccer", "football",
            "world cup", "fifa", "olympics", "f1", "ufc", "boxing",
            "playoffs", "championship", "super bowl", "premier league",
            "champions league", "grand slam",
        ],
        "energy": [
            "oil", "gas", "energy", "solar", "nuclear", "opec",
            "renewable", "petroleum", "lng",
        ],
        "gaming": ["game", "gaming", "indie", "steam", "unity", "unreal"],
        "music": ["music", "production", "audio", "streaming", "dubforge"],
        "climate": [
            "climate", "weather", "hurricane", "earthquake", "wildfire",
            "temperature", "carbon", "renewable energy",
        ],
    }

    def correlate(self, signals: list[IntelSignal]) -> list[SectorSnapshot]:
        """Group signals into sector snapshots with cross-source scoring."""
        sector_signals: dict[str, list[IntelSignal]] = defaultdict(list)

        for signal in signals:
            # Use explicit category first
            if signal.category and signal.category != "general":
                sector_signals[signal.category].append(signal)
                continue

            # Fall back to keyword matching
            text = (signal.title + " " + signal.content + " " + " ".join(signal.tags)).lower()
            matched = False
            for sector, keywords in self.SECTOR_KEYWORDS.items():
                if any(kw in text for kw in keywords):
                    sector_signals[sector].append(signal)
                    matched = True
                    break
            if not matched:
                sector_signals["other"].append(signal)

        # Build snapshots
        snapshots = []
        for sector, sigs in sector_signals.items():
            if not sigs:
                continue

            # Compute aggregate direction
            direction_votes = defaultdict(float)
            total_confidence = 0.0
            for sig in sigs:
                weight = sig.importance_score() * sig.confidence
                direction_votes[sig.direction] += weight
                total_confidence += sig.confidence

            avg_confidence = total_confidence / len(sigs) if sigs else 0.0

            # Pick dominant direction
            if direction_votes:
                dominant = max(direction_votes, key=direction_votes.get)
            else:
                dominant = SignalDirection.NEUTRAL

            # Cross-source bonus: signals from multiple sources on same theme = higher confidence
            source_types = set(s.source for s in sigs)
            cross_source_count = len(source_types)
            if cross_source_count >= 3:
                avg_confidence = min(1.0, avg_confidence * 1.3)
            elif cross_source_count >= 2:
                avg_confidence = min(1.0, avg_confidence * 1.15)

            # Sort by importance for top signals
            ranked = sorted(sigs, key=lambda s: s.importance_score(), reverse=True)

            # Build summary from top signals
            top_3 = ranked[:3]
            summary_parts = [s.title for s in top_3 if s.title]
            summary = " | ".join(summary_parts)

            snapshots.append(SectorSnapshot(
                sector=sector,
                direction=dominant,
                signal_count=len(sigs),
                avg_confidence=round(avg_confidence, 3),
                top_signals=ranked[:5],
                summary=summary[:300],
            ))

        # Sort sectors by signal count * confidence
        snapshots.sort(key=lambda s: s.signal_count * s.avg_confidence, reverse=True)
        return snapshots


# ═══════════════════════════════════════════════════════════════════════════
# INTELLIGENCE ENGINE
# ═══════════════════════════════════════════════════════════════════════════


class IntelligenceEngine:
    """
    Main intelligence engine — coordinates all collectors and produces briefs.

    Usage:
        engine = IntelligenceEngine(config)
        await engine.initialize()
        brief = await engine.generate_brief()
        print(brief.to_text())
    """

    def __init__(self, config: Any = None):
        """
        Initialize with NCL config.

        Args:
            config: NCL Settings object (for API keys, intervals, etc.)
        """
        self.config = config

        # Collectors
        self._trends = GoogleTrendsCollector()
        self._polymarket = PolymarketCollector()
        self._news = NewsCollector(
            gnews_api_key=getattr(config, "gnews_api_key", None) if config else None,
            newsapi_key=getattr(config, "newsapi_key", None) if config else None,
        )
        self._crypto = CryptoMarketCollector()
        self._reddit = RedditCollector()  # Uses full tiered system: T1+T2+T3 rotating

        # Analysis
        self._correlator = SignalCorrelator()

        # Persistence
        self._data_dir = Path(getattr(config, "data_dir", "~/NCL/data")).expanduser()
        self._briefs_dir = self._data_dir / "intelligence"
        self._briefs_dir.mkdir(parents=True, exist_ok=True)
        self._briefs_file = self._briefs_dir / "briefs.jsonl"
        self._signals_file = self._briefs_dir / "signals.jsonl"

        # LLM client for synthesis
        self._llm_client = httpx.AsyncClient(timeout=60.0)
        self._anthropic_key = getattr(config, "anthropic_api_key", "") if config else ""
        self._anthropic_base = getattr(config, "anthropic_base_url", "https://api.anthropic.com") if config else "https://api.anthropic.com"
        self._ollama_host = getattr(config, "ollama_host", "localhost:11434") if config else "localhost:11434"

        # Watch queries (what NCL cares about)
        self._watch_topics = [
            "AI automation",
            "crypto regulation",
            "prediction markets",
            "algorithmic trading",
            "indie game development",
            "AI music production",
        ]

        # Stats
        self._stats = {
            "briefs_generated": 0,
            "total_signals_collected": 0,
            "last_brief": None,
            "last_collection": None,
            "errors": 0,
        }

    async def initialize(self) -> None:
        """Initialize engine and load watch topics from config."""
        # Load custom watch topics if available
        topics_file = Path(getattr(self.config, "config_dir", "~/NCL/config")).expanduser() / "watch_topics.json"
        if topics_file.exists():
            try:
                with open(topics_file) as f:
                    data = json.load(f)
                    self._watch_topics = data.get("topics", self._watch_topics)
            except Exception:
                pass

        log.info(f"Intelligence Engine initialized — watching {len(self._watch_topics)} topics")

    # ─── COLLECTION ─────────────────────────────────────────────────────

    async def collect_all_signals(self) -> list[IntelSignal]:
        """
        Run all collectors in parallel, return combined signal list.

        This is the raw intelligence gathering phase.
        """
        log.info("Starting intelligence collection sweep...")

        # Run all collectors concurrently
        results = await asyncio.gather(
            self._collect_trends(),
            self._collect_polymarket(),
            self._collect_news(),
            self._collect_crypto(),
            self._collect_reddit(),
            return_exceptions=True,
        )

        all_signals: list[IntelSignal] = []
        source_names = ["trends", "polymarket", "news", "crypto", "reddit"]

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.error(f"Collector {source_names[i]} failed: {result}")
                self._stats["errors"] += 1
            elif isinstance(result, list):
                all_signals.extend(result)
                log.info(f"  {source_names[i]}: {len(result)} signals")

        self._stats["total_signals_collected"] += len(all_signals)
        self._stats["last_collection"] = datetime.now(timezone.utc).isoformat()

        log.info(f"Collection complete: {len(all_signals)} total signals")

        # Persist raw signals
        await self._persist_signals(all_signals)

        return all_signals

    async def _collect_trends(self) -> list[IntelSignal]:
        """Collect from Google Trends."""
        signals: list[IntelSignal] = []
        try:
            daily = await self._trends.collect_daily_trends()
            signals.extend(daily)
        except Exception as e:
            log.warning(f"Google Trends daily failed: {e}")

        try:
            interest = await self._trends.collect_interest(self._watch_topics[:5])
            signals.extend(interest)
        except Exception as e:
            log.warning(f"Google Trends interest failed: {e}")

        return signals

    async def _collect_polymarket(self) -> list[IntelSignal]:
        """Collect from Polymarket."""
        signals: list[IntelSignal] = []
        try:
            trending = await self._polymarket.collect_trending_markets(limit=25)
            signals.extend(trending)
        except Exception as e:
            log.warning(f"Polymarket trending failed: {e}")

        try:
            specific = await self._polymarket.collect_specific_markets(self._watch_topics[:5])
            signals.extend(specific)
        except Exception as e:
            log.warning(f"Polymarket specific failed: {e}")

        return signals

    async def _collect_news(self) -> list[IntelSignal]:
        """Collect from news sources."""
        signals: list[IntelSignal] = []
        try:
            headlines = await self._news.collect_top_headlines()
            signals.extend(headlines)
        except Exception as e:
            log.warning(f"News headlines failed: {e}")

        # Topic-specific news
        for topic in self._watch_topics[:3]:
            try:
                topic_news = await self._news.collect_topic_news(topic)
                signals.extend(topic_news)
            except Exception:
                pass

        return signals

    async def _collect_crypto(self) -> list[IntelSignal]:
        """Collect crypto market data."""
        signals: list[IntelSignal] = []
        try:
            overview = await self._crypto.collect_market_overview()
            signals.extend(overview)
        except Exception as e:
            log.warning(f"Crypto overview failed: {e}")

        try:
            trending = await self._crypto.collect_trending()
            signals.extend(trending)
        except Exception as e:
            log.warning(f"Crypto trending failed: {e}")

        try:
            global_metrics = await self._crypto.collect_global_metrics()
            signals.extend(global_metrics)
        except Exception as e:
            log.warning(f"Crypto global failed: {e}")

        return signals

    async def _collect_reddit(self) -> list[IntelSignal]:
        """Collect retail sentiment from r/wallstreetbets and r/Superstonk."""
        signals: list[IntelSignal] = []
        try:
            reddit_signals = await self._reddit.collect_all()
            signals.extend(reddit_signals)
        except Exception as e:
            log.warning(f"Reddit collection failed: {e}")

        # Cross-subreddit ticker heatmap for intelligence summary
        try:
            ticker_subs = ["wallstreetbets", "options", "Shortsqueeze", "pennystocks", "Superstonk"]
            merged_tickers: dict[str, int] = {}
            for sub in ticker_subs:
                try:
                    sub_tickers = await self._reddit.collect_ticker_mentions(sub, limit=50)
                    for ticker, count in sub_tickers.items():
                        merged_tickers[ticker] = merged_tickers.get(ticker, 0) + count
                except Exception:
                    pass  # Skip failed sub, continue with others

            if merged_tickers:
                sorted_tickers = sorted(merged_tickers.items(), key=lambda x: x[1], reverse=True)
                top_10 = sorted_tickers[:10]
                ticker_summary = ", ".join(f"${t}: {c}" for t, c in top_10)
                signals.append(SocialSignal(
                    source=SourceType.REDDIT,
                    category="retail_ticker_heat",
                    title=f"Reddit Ticker Heatmap: {', '.join(f'${t}' for t, _ in top_10[:5])}",
                    content=f"Top Reddit ticker mentions across {len(ticker_subs)} subs: {ticker_summary}",
                    platform="reddit",
                    engagement=sum(c for _, c in top_10),
                    sentiment=0.0,
                    value=float(top_10[0][1]) if top_10 else 0,
                    direction=SignalDirection.EMERGING,
                    confidence=0.65,
                    tags=["reddit", "ticker_heat", "cross_sub"] + [f"ticker:{t.lower()}" for t, _ in top_10[:5]],
                    metadata={"ticker_counts": dict(sorted_tickers[:20]), "subs_scanned": ticker_subs},
                ))
        except Exception as e:
            log.warning(f"Reddit ticker scan failed: {e}")

        return signals

    # ─── ANALYSIS & SYNTHESIS ───────────────────────────────────────────

    async def generate_brief(self, brief_type: str = "daily") -> IntelBrief:
        """
        Full intelligence pipeline:
        1. Collect all signals
        2. Correlate into sectors
        3. Extract predictions and trends
        4. Generate executive summary via LLM
        5. Package into IntelBrief
        """
        log.info(f"Generating {brief_type} intelligence brief...")

        # 1. Collect
        signals = await self.collect_all_signals()

        # 2. Correlate into sectors
        sectors = self._correlator.correlate(signals)

        # 3. Extract top signals (ranked by importance)
        ranked_signals = sorted(signals, key=lambda s: s.importance_score(), reverse=True)
        top_signals = ranked_signals[:20]

        # 4. Extract predictions (Polymarket signals) — deduplicated by question
        predictions = []
        seen_questions: set[str] = set()
        for sig in signals:
            if sig.source == SourceType.POLYMARKET and hasattr(sig, "market_question"):
                q = sig.title.strip()
                if q in seen_questions:
                    continue
                seen_questions.add(q)
                predictions.append({
                    "question": q,
                    "probability": sig.value or 0.5,
                    "volume": sig.volume or 0,
                    "direction": sig.direction.value,
                })
        predictions.sort(key=lambda p: p.get("volume", 0), reverse=True)

        # 5. Extract trending items
        trending = []
        for sig in signals:
            if sig.source == SourceType.GOOGLE_TRENDS:
                trending.append({
                    "term": sig.title,
                    "score": sig.value or 0,
                    "change_pct": sig.change_pct,
                    "direction": sig.direction.value,
                })
            elif sig.source == SourceType.CRYPTO and sig.direction == SignalDirection.EMERGING:
                trending.append({
                    "term": sig.title,
                    "score": sig.value or 0,
                    "direction": "emerging",
                })

        # 6. Market movements (crypto + options)
        market_movements = []
        for sig in signals:
            if sig.source == SourceType.CRYPTO and hasattr(sig, "symbol") and sig.change_pct is not None:
                market_movements.append({
                    "symbol": getattr(sig, "symbol", sig.title),
                    "price": getattr(sig, "current_price", sig.value or 0),
                    "change_pct": sig.change_pct,
                    "volume": sig.volume or 0,
                })
        market_movements.sort(key=lambda m: abs(m.get("change_pct", 0)), reverse=True)

        # 7. Risk alerts — filter out noise (low-volume sports matchups, etc.)
        risk_alerts = []
        seen_risk_titles: set[str] = set()
        for sig in ranked_signals[:30]:
            if sig.direction in (SignalDirection.BEARISH, SignalDirection.CONTRACTING):
                if sig.importance_score() > 50:
                    # Skip low-volume or sports noise
                    if sig.category in ("sports", "entertainment"):
                        continue
                    if sig.volume is not None and sig.volume < 1000:
                        continue
                    title_key = sig.title.strip()
                    if title_key in seen_risk_titles:
                        continue
                    seen_risk_titles.add(title_key)
                    risk_alerts.append(f"{sig.title}: {sig.content[:100]}")

        # 8. Source counts
        source_counts: dict[str, int] = defaultdict(int)
        for sig in signals:
            source_counts[sig.source.value] += 1

        # 9. LLM executive summary
        executive_summary = await self._generate_executive_summary(
            sectors, top_signals, predictions, market_movements
        )

        # Build brief
        brief = IntelBrief(
            brief_type=brief_type,
            executive_summary=executive_summary,
            sectors=sectors[:8],
            top_signals=top_signals[:15],
            predictions=predictions[:10],
            trending=trending[:10],
            market_movements=market_movements[:10],
            risk_alerts=risk_alerts[:5],
            source_counts=dict(source_counts),
            total_signals_processed=len(signals),
        )

        # Persist brief
        await self._persist_brief(brief)

        self._stats["briefs_generated"] += 1
        self._stats["last_brief"] = datetime.now(timezone.utc).isoformat()

        log.info(f"Brief generated: {len(signals)} signals → {len(sectors)} sectors, "
                 f"{len(predictions)} predictions, {len(risk_alerts)} risk alerts")

        return brief

    async def _generate_executive_summary(
        self,
        sectors: list[SectorSnapshot],
        top_signals: list[IntelSignal],
        predictions: list[dict],
        market_movements: list[dict],
    ) -> str:
        """
        Use LLM to generate a concise executive summary.

        Falls back to template-based summary if LLM unavailable.
        """
        # Build context for LLM
        context_parts = []

        if sectors:
            sector_text = "\n".join(
                f"- {s.sector}: {s.direction.value}, {s.signal_count} signals, conf={s.avg_confidence:.0%}"
                for s in sectors[:6]
            )
            context_parts.append(f"SECTORS:\n{sector_text}")

        if market_movements:
            moves = "\n".join(
                f"- {m['symbol']}: ${m.get('price', 0):,.2f} ({m.get('change_pct', 0):+.1f}%)"
                for m in market_movements[:8]
            )
            context_parts.append(f"MARKET MOVEMENTS:\n{moves}")

        if predictions:
            preds = "\n".join(
                f"- {p['question'][:60]}: {p.get('probability', 0):.0%}"
                for p in predictions[:5]
            )
            context_parts.append(f"PREDICTION MARKETS:\n{preds}")

        if top_signals:
            top = "\n".join(
                f"- [{s.source.value}] {s.title}: {s.content[:80]}"
                for s in top_signals[:5]
            )
            context_parts.append(f"TOP SIGNALS:\n{top}")

        context = "\n\n".join(context_parts)

        prompt = f"""You are NCL, an intelligence analyst for NARTIX operations.
Given today's intelligence signals, write a 3-4 sentence executive summary highlighting:
1. The most important development or trend
2. Key market movements worth watching
3. Any emerging opportunities or risks

Be specific and actionable. No fluff. Reference actual data points.

TODAY'S INTELLIGENCE:
{context}

EXECUTIVE SUMMARY:"""

        # Try Claude first
        if self._anthropic_key:
            try:
                resp = await self._llm_client.post(
                    f"{self._anthropic_base}/v1/messages",
                    headers={
                        "x-api-key": self._anthropic_key,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 300,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["content"][0]["text"].strip()
            except Exception as e:
                log.warning(f"Claude summary generation failed: {e}")

        # Try Ollama fallback
        try:
            resp = await self._llm_client.post(
                f"http://{self._ollama_host}/api/generate",
                json={"model": "qwen3:32b", "prompt": prompt, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("response", "")[:500].strip()
        except Exception:
            pass

        # Template fallback
        return self._template_summary(sectors, market_movements, predictions)

    def _template_summary(
        self,
        sectors: list[SectorSnapshot],
        market_movements: list[dict],
        predictions: list[dict],
    ) -> str:
        """Generate a template-based summary when LLM is unavailable."""
        parts = []

        if sectors:
            top = sectors[0]
            parts.append(
                f"The {top.sector} sector shows {top.direction.value} signals "
                f"across {top.signal_count} data points (confidence: {top.avg_confidence:.0%})."
            )

        if market_movements:
            biggest = market_movements[0]
            parts.append(
                f"Largest move: {biggest['symbol']} at "
                f"${biggest.get('price', 0):,.2f} ({biggest.get('change_pct', 0):+.1f}%)."
            )

        if predictions:
            top_pred = predictions[0]
            parts.append(
                f"Top prediction market: \"{top_pred['question'][:50]}\" "
                f"at {top_pred.get('probability', 0):.0%} probability."
            )

        return " ".join(parts) if parts else "Intelligence collection complete. No significant signals detected."

    # ─── PERSISTENCE ────────────────────────────────────────────────────

    async def _persist_signals(self, signals: list[IntelSignal]) -> None:
        """Append signals to JSONL file."""
        try:
            async with aiofiles.open(self._signals_file, "a") as f:
                for sig in signals:
                    await f.write(sig.model_dump_json() + "\n")
        except Exception as e:
            log.warning(f"Failed to persist signals: {e}")

    async def _persist_brief(self, brief: IntelBrief) -> None:
        """Persist brief to JSONL and save latest as standalone JSON."""
        try:
            # Append to history
            async with aiofiles.open(self._briefs_file, "a") as f:
                await f.write(brief.model_dump_json() + "\n")

            # Save latest brief as standalone file
            latest_file = self._briefs_dir / "latest_brief.json"
            async with aiofiles.open(latest_file, "w") as f:
                await f.write(brief.model_dump_json(indent=2))

            # Save text version
            text_file = self._briefs_dir / "latest_brief.txt"
            async with aiofiles.open(text_file, "w") as f:
                await f.write(brief.to_text())

            log.info(f"Brief persisted to {self._briefs_dir}")

        except Exception as e:
            log.warning(f"Failed to persist brief: {e}")

    # ─── STATUS & CLEANUP ───────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return engine statistics."""
        return {
            **self._stats,
            "watch_topics": self._watch_topics,
            "briefs_dir": str(self._briefs_dir),
        }

    async def get_latest_brief(self) -> Optional[IntelBrief]:
        """Load the most recent brief from disk."""
        latest_file = self._briefs_dir / "latest_brief.json"
        if not latest_file.exists():
            return None
        try:
            async with aiofiles.open(latest_file, "r") as f:
                data = json.loads(await f.read())
                return IntelBrief(**data)
        except Exception:
            return None

    async def close(self) -> None:
        """Close all collectors and HTTP clients."""
        await asyncio.gather(
            self._trends.close(),
            self._polymarket.close(),
            self._news.close(),
            self._crypto.close(),
            self._llm_client.aclose(),
            return_exceptions=True,
        )
