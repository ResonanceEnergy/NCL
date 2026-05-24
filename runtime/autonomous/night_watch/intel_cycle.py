"""
ncl-night-watch Phase 3 intelligence-correlation cycle (carved from
scheduler.py, W10C-8).

Runs 6 analysis tasks against the intel pipeline:
  I1: Cross-source correlation mining (FREE)
  I2: Coverage blind spot detection (FREE + Sonnet + Gemini dual-model)
  I3: Signal score calibration (FREE)
  I4: Prediction calibration analysis (FREE + Sonnet + Gemini dual-model)
  I5: Council topic suggestion (Sonnet + Gemini dual-model, merged with priority)
  I6: Cost optimization analysis (Sonnet + Gemini consensus)

Total cost target: ~$0.30/night (4 Sonnet + 4 Gemini calls).

This is the extracted body of what used to be
`AutonomousScheduler._night_watch_intel_cycle` defined inline in
`runtime/autonomous/scheduler.py`. The method on the scheduler is now a
thin shim that calls `run(self)` here so external callers and factories
that reference the method name still resolve.

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler.data_dir` — Path. Used to locate `intelligence/agent_signals.jsonl`,
  `predictions/`, watch-query JSON candidates, and the `night-watch/` output dir
  (which is created if absent for the I5 council-topics file).
- `scheduler.brain` — Brain instance. Reads `scheduler.brain.memory_store`
  (and its `_knowledge_graph` + `_units` attrs) plus `scheduler.brain.journal_store`.
  All accesses are getattr-guarded; missing/None tolerated.

NOTE on safety of state refs:
- `data_dir` and `brain` are both set in `Scheduler.__init__` and are stable
  for the scheduler's lifetime. The only mutation is the I5 `nw_dir.mkdir(...)`
  + aiofiles write of `council-topics-YYYY-MM-DD.json`, both inside the
  scheduler's owned output dir. Safe to call from the carved-out module.
- The `_call_sonnet_intel` / `_call_gemini` inline async helpers stay defined
  inside `run()` because they close over `api_key`, `api_headers`, `tracker`,
  and `google_api_key_intel`. Hoisting them would require threading those
  captures explicitly — byte-identical behavior took priority for this carve.

Other dependencies:
- `runtime.cost_tracker.get_tracker` — async budget tracker singleton.
- httpx, aiofiles, asyncio — same direct calls as before the carve.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import aiofiles

log = logging.getLogger("ncl.autonomous")


async def run(scheduler) -> dict:
    """
    Night Watch Phase 3 — Intelligence Correlation Cycle.

    Runs 6 analysis tasks on intelligence data:
      I1: Cross-source correlation mining (FREE)
      I2: Coverage blind spot detection (FREE + Sonnet + Gemini dual-model)
      I3: Signal score calibration (FREE)
      I4: Prediction calibration analysis (FREE + Sonnet + Gemini dual-model)
      I5: Council topic suggestion (Sonnet + Gemini dual-model, merged with priority)
      I6: Cost optimization analysis (Sonnet + Gemini consensus)

    Total cost target: ~$0.30/night (4 Sonnet + 4 Gemini calls).

    Returns:
        Dict with task results and overall stats.
    """
    import re
    import time

    import httpx

    from ...cost_tracker import get_tracker

    t0 = time.monotonic()
    report: dict = {
        "missed_correlations": 0,
        "blind_spots": [],
        "over_scored_signals": 0,
        "under_scored_signals": 0,
        "predictions_stale": 0,
        "per_model_accuracy": {},
        "council_suggestions": [],
        "cost_optimization": "",
        "total_cost_usd": 0.0,
        "duration_seconds": 0.0,
        "errors": [],
    }

    TASK_TIMEOUT = 10 * 60  # 10 minutes per task  # noqa: N806

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        report["errors"].append("No ANTHROPIC_API_KEY — skipping LLM intel tasks")
        log.warning("[NIGHT-WATCH/INTEL] No ANTHROPIC_API_KEY — LLM tasks will be skipped")

    tracker = await get_tracker()
    sonnet_model_intel = "claude-sonnet-4"
    api_headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async def _call_sonnet_intel(
        prompt: str, label: str, max_tokens: int = 1024
    ) -> tuple[str, float]:
        """Make a Sonnet call for intel analysis, return (text, cost_usd). Raises on failure."""
        if not api_key:
            raise RuntimeError("No API key")
        if not await tracker.can_spend("anthropic", 0.02):
            raise RuntimeError("Anthropic budget exceeded")
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=api_headers,
                json={
                    "model": sonnet_model_intel,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            cost = (input_tokens * 3.00 + output_tokens * 15.00) / 1_000_000
            log.info(
                "[NIGHT-WATCH/INTEL] Sonnet call '%s': %d in / %d out tokens, $%.4f",
                label,
                input_tokens,
                output_tokens,
                cost,
            )
            await tracker.record(
                "anthropic",
                cost,
                "night_watch_intel",
                f"Night Watch Intel Sonnet: {label}",
                {"model": sonnet_model_intel, "phase": "intel", "label": label},
            )
            return text, cost

    google_api_key_intel = os.environ.get("GOOGLE_API_KEY", "")

    async def _call_gemini(
        prompt: str, label: str, max_tokens: int = 1024
    ) -> tuple[str, float]:
        """Make a Gemini 2.5 Flash call, return (text, cost_usd). Raises on failure."""
        if not google_api_key_intel:
            raise RuntimeError("No GOOGLE_API_KEY")
        if not await tracker.can_spend("google", 0.005):
            raise RuntimeError("Google budget exceeded")
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                params={"key": google_api_key_intel},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": max_tokens},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError(f"Gemini returned no candidates: {list(data.keys())}")
            parts_list = candidates[0].get("content", {}).get("parts", [])
            if not parts_list:
                raise ValueError("Gemini candidate has no content parts")
            text = parts_list[0].get("text", "")
            usage_meta = data.get("usageMetadata", {})
            input_tokens = usage_meta.get("promptTokenCount", 0)
            output_tokens = usage_meta.get("candidatesTokenCount", 0)
            # Gemini 2.5 Flash: $0.15/1M input, $0.60/1M output
            cost = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000
            log.info(
                "[NIGHT-WATCH/INTEL] Gemini call '%s': %d in / %d out tokens, $%.6f",
                label,
                input_tokens,
                output_tokens,
                cost,
            )
            await tracker.record(
                "google",
                cost,
                "night_watch_intel",
                f"Night Watch Intel Gemini: {label}",
                {"model": "gemini-2.5-flash", "phase": "intel", "label": label},
            )
            return text, cost

    # Ensure output directory exists
    nw_dir = scheduler.data_dir / "night-watch"
    nw_dir.mkdir(parents=True, exist_ok=True)

    # ══════════════════════════════════════════════════════════════
    # TASK I1: Cross-Source Correlation Mining (FREE)
    # ══════════════════════════════════════════════════════════════
    try:
        log.info("[NIGHT-WATCH/INTEL] Task I1: Cross-source correlation mining...")

        signals_file = scheduler.data_dir / "intelligence" / "agent_signals.jsonl"
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        signals_by_source: dict[str, list[dict]] = defaultdict(list)

        if signals_file.exists():
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                        ts = sig.get("timestamp", "")
                        if ts >= cutoff:
                            source = sig.get("source", "unknown")
                            signals_by_source[source].append(sig)
                    except json.JSONDecodeError:
                        continue

        # Tokenize each signal's content into keyword sets
        def _tokenize_signal(sig: dict) -> set[str]:
            text = f"{sig.get('title', '')} {sig.get('content', '')} {' '.join(sig.get('tags', []))}"  # noqa: E501
            tokens = set(t.lower() for t in re.findall(r"\b[a-zA-Z0-9]{4,}\b", text))
            # Filter out very common words
            stopwords = {
                "this",
                "that",
                "with",
                "from",
                "have",
                "been",
                "will",
                "they",
                "their",
                "about",
                "would",
                "could",
                "should",
                "just",
                "more",
                "some",
                "than",
                "into",
                "when",
                "what",
                "also",
                "other",
                "were",
            }
            return tokens - stopwords

        # Build per-source keyword sets grouped by broad topic clusters
        source_keywords: dict[str, dict[str, set]] = {}  # source -> {keyword -> signal_ids}
        for source, sigs in signals_by_source.items():
            kw_map: dict[str, set] = defaultdict(set)
            for sig in sigs:
                tokens = _tokenize_signal(sig)
                sid = sig.get("signal_id", "")
                for token in tokens:
                    kw_map[token].add(sid)
            source_keywords[source] = dict(kw_map)

        # Find keywords appearing in 2+ different sources
        all_sources = list(source_keywords.keys())
        cross_source_keywords: dict[str, set[str]] = defaultdict(set)  # keyword -> sources
        for source, kw_map in source_keywords.items():
            for kw in kw_map:
                cross_source_keywords[kw].add(source)

        # Filter to multi-source keywords with >= 2 sources
        multi_source_kw = {
            kw: sources for kw, sources in cross_source_keywords.items() if len(sources) >= 2
        }

        # Cluster related keywords by co-occurrence in the same signals
        # Simple approach: group keywords that share significant overlap in source coverage
        missed_clusters: list[dict] = []
        used_keywords: set[str] = set()

        for kw, sources in sorted(multi_source_kw.items(), key=lambda x: -len(x[1])):
            if kw in used_keywords:
                continue
            # Find related keywords (appear in same sources)
            cluster = {kw}
            for other_kw, other_sources in multi_source_kw.items():
                if other_kw not in used_keywords and other_sources == sources:
                    cluster.add(other_kw)
                if len(cluster) >= 8:
                    break

            used_keywords.update(cluster)
            if len(cluster) >= 2:  # Only report clusters with multiple related keywords
                missed_clusters.append(
                    {
                        "keywords": sorted(cluster)[:8],
                        "sources": sorted(sources),
                        "source_count": len(sources),
                    }
                )

            if len(missed_clusters) >= 20:
                break

        report["missed_correlations"] = len(missed_clusters)
        log.info(
            "[NIGHT-WATCH/INTEL] Task I1: found %d missed correlation clusters across %d sources",  # noqa: E501
            len(missed_clusters),
            len(all_sources),
        )

    except asyncio.TimeoutError:
        report["errors"].append("I1: timeout")
        log.error("[NIGHT-WATCH/INTEL] Task I1 timed out")
    except Exception as e:
        report["errors"].append(f"I1: {e}")
        log.error("[NIGHT-WATCH/INTEL] Task I1 failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # TASK I2: Coverage Blind Spot Detection (FREE + 1 Haiku)
    # ══════════════════════════════════════════════════════════════
    blind_spot_analysis = ""
    try:
        log.info("[NIGHT-WATCH/INTEL] Task I2: Coverage blind spot detection...")

        # Load watch queries
        watch_topics: list[str] = []
        wq_candidates = [
            scheduler.data_dir.parent / "config" / "watch_queries.json",
            scheduler.data_dir.parent / "runtime" / "autonomous" / "watch_queries.json",
            scheduler.data_dir / "watch_queries.json",
        ]
        for wq_path in wq_candidates:
            if wq_path.exists():
                try:
                    wq_data = json.loads(wq_path.read_text())
                    for key, val in wq_data.items():
                        if key.startswith("_"):
                            continue
                        if isinstance(val, list):
                            watch_topics.extend(val)
                    break
                except Exception:
                    continue

        # If no watch config, try knowledge graph top entities
        if not watch_topics:
            memory_store = getattr(scheduler.brain, "memory_store", None)
            kg = getattr(memory_store, "_knowledge_graph", None) if memory_store else None
            if kg and hasattr(kg, "get_top_entities"):
                try:
                    top_ents = kg.get_top_entities(limit=20)
                    watch_topics = [e.get("name", "") for e in top_ents if e.get("name")]
                except Exception:
                    pass

        # Deduplicate
        watch_topics = list(dict.fromkeys(watch_topics))

        # Check signals from last 48h for coverage
        cutoff_48h = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        recent_signal_text = ""
        recent_count = 0
        if signals_file.exists():
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                        if sig.get("timestamp", "") >= cutoff_48h:
                            recent_signal_text += (
                                f" {sig.get('title', '')} {sig.get('content', '')}"
                            )
                            recent_count += 1
                    except json.JSONDecodeError:
                        continue

        recent_lower = recent_signal_text.lower()
        blind_spots: list[str] = []
        covered_topics: list[str] = []
        for topic in watch_topics:
            # Check if any significant words from the topic appear in signals
            topic_words = [w.lower() for w in topic.split() if len(w) >= 4]
            if not topic_words:
                continue
            matches = sum(1 for w in topic_words if w in recent_lower)
            coverage_ratio = matches / len(topic_words) if topic_words else 0
            if coverage_ratio < 0.3:
                blind_spots.append(topic)
            else:
                covered_topics.append(topic)

        report["blind_spots"] = blind_spots[:20]

        # Dual-model call for synthesis (Haiku + Gemini in parallel)
        if blind_spots and api_key:
            try:
                prompt = (
                    "You are an intelligence analyst for an autonomous AI brain system. "
                    "The system watches specific topics and generates signals from X/Twitter, "
                    "YouTube, Reddit, Google Trends, news, and market data.\n\n"
                    f"WATCHED TOPICS ({len(watch_topics)} total):\n"
                    + "\n".join(f"- {t}" for t in watch_topics[:30])
                    + "\n\n"
                    f"TOPICS WITH NO COVERAGE in last 48h ({len(blind_spots)}):\n"
                    + "\n".join(f"- {t}" for t in blind_spots[:15])
                    + "\n\n"
                    f"TOPICS WITH COVERAGE ({len(covered_topics)}):\n"
                    + "\n".join(f"- {t}" for t in covered_topics[:10])
                    + "\n\n"
                    f"Total signals in last 48h: {recent_count}\n\n"
                    "Given these watched topics and coverage gaps, what intelligence might "
                    "we be missing? What risks emerge from the blind spots? "
                    "Return each blind spot as a bullet point starting with '- '."
                )

                # Run both models in parallel
                haiku_task = asyncio.wait_for(
                    _call_sonnet_intel(prompt, "I2_blind_spots"), timeout=TASK_TIMEOUT
                )
                gemini_task = asyncio.wait_for(
                    _call_gemini(prompt, "I2_blind_spots"), timeout=TASK_TIMEOUT
                )
                haiku_res, gemini_res = await asyncio.gather(
                    haiku_task,
                    gemini_task,
                    return_exceptions=True,
                )

                haiku_text = ""
                gemini_text = ""

                if isinstance(haiku_res, tuple):
                    haiku_text, haiku_cost = haiku_res
                    report["total_cost_usd"] += haiku_cost
                elif isinstance(haiku_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I2 Haiku failed: %s", haiku_res)

                if isinstance(gemini_res, tuple):
                    gemini_text, gemini_cost = gemini_res
                    report["total_cost_usd"] += gemini_cost
                elif isinstance(gemini_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I2 Gemini failed: %s", gemini_res)

                # Merge blind spot bullet points (union, deduplicated)
                def _extract_bullets(text: str) -> list[str]:
                    return [
                        line.strip().lstrip("- •*").strip()
                        for line in text.split("\n")
                        if line.strip().startswith(("-", "•", "*")) and len(line.strip()) > 10
                    ]

                haiku_bullets = _extract_bullets(haiku_text)
                gemini_bullets = _extract_bullets(gemini_text)

                # Identify high-confidence bullets (flagged by both)
                haiku_kw = {b.lower()[:60] for b in haiku_bullets}  # noqa: F841
                gemini_kw = {b.lower()[:60] for b in gemini_bullets}  # noqa: F841

                merged_bullets: list[str] = []
                high_confidence: list[str] = []

                for b in haiku_bullets:
                    merged_bullets.append(b)
                    # Check if Gemini flagged something similar
                    b_words = set(b.lower().split())
                    for gb in gemini_bullets:
                        gb_words = set(gb.lower().split())
                        overlap = len(b_words & gb_words) / max(len(b_words | gb_words), 1)
                        if overlap > 0.4:
                            high_confidence.append(b)
                            break

                for b in gemini_bullets:
                    # Only add if not already covered
                    b_words = set(b.lower().split())
                    already = False
                    for mb in merged_bullets:
                        mb_words = set(mb.lower().split())
                        overlap = len(b_words & mb_words) / max(len(b_words | mb_words), 1)
                        if overlap > 0.4:
                            already = True
                            break
                    if not already:
                        merged_bullets.append(b)

                # Build combined analysis
                combined_parts: list[str] = []
                if high_confidence:
                    combined_parts.append(
                        "HIGH CONFIDENCE blind spots (flagged by both Haiku and Gemini):\n"
                        + "\n".join(f"- {b}" for b in high_confidence)
                    )
                combined_parts.append(
                    "ALL identified blind spots (merged):\n"
                    + "\n".join(f"- {b}" for b in merged_bullets)
                )
                blind_spot_analysis = "\n\n".join(combined_parts)  # noqa: F841

                log.info(
                    "[NIGHT-WATCH/INTEL] I2: Haiku found %d, Gemini found %d, "
                    "%d merged (%d high confidence)",
                    len(haiku_bullets),
                    len(gemini_bullets),
                    len(merged_bullets),
                    len(high_confidence),
                )

            except Exception as e:
                report["errors"].append(f"I2 dual-model: {e}")
                log.error("[NIGHT-WATCH/INTEL] Task I2 dual-model failed: %s", e)

        log.info(
            "[NIGHT-WATCH/INTEL] Task I2: %d blind spots out of %d watched topics",
            len(blind_spots),
            len(watch_topics),
        )

    except asyncio.TimeoutError:
        report["errors"].append("I2: timeout")
        log.error("[NIGHT-WATCH/INTEL] Task I2 timed out")
    except Exception as e:
        report["errors"].append(f"I2: {e}")
        log.error("[NIGHT-WATCH/INTEL] Task I2 failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # TASK I3: Signal Score Calibration (FREE)
    # ══════════════════════════════════════════════════════════════
    try:
        log.info("[NIGHT-WATCH/INTEL] Task I3: Signal score calibration...")

        signals_file = scheduler.data_dir / "intelligence" / "agent_signals.jsonl"
        cutoff_14d = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()

        high_signals: list[dict] = []  # scored HIGH/CRITICAL (composite > 0.7)
        low_signals: list[dict] = []  # scored LOW (composite < 0.3)

        if signals_file.exists():
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                        if sig.get("timestamp", "") < cutoff_14d:
                            continue
                        score = sig.get("composite_score", 0)
                        level = sig.get("route_level", "")
                        if score >= 0.7 or level in ("HIGH", "CRITICAL"):
                            high_signals.append(sig)
                        elif score < 0.3 or level == "LOW":
                            low_signals.append(sig)
                    except json.JSONDecodeError:
                        continue

        # Check which high signals were actually referenced in memory/journal
        memory_store = getattr(scheduler.brain, "memory_store", None)
        memory_contents: set[str] = set()
        if memory_store:
            try:
                # Get recent memory units to check for signal references
                all_units = getattr(memory_store, "_units", [])
                if hasattr(memory_store, "get_all_units"):
                    try:
                        all_units = await memory_store.get_all_units()
                    except Exception:
                        pass
                for unit in all_units:
                    content = ""
                    if isinstance(unit, dict):
                        content = unit.get("content", "")
                    elif hasattr(unit, "content"):
                        content = unit.content
                    if content:
                        memory_contents.add(content[:200].lower())
            except Exception:
                pass

        # Check journal for references
        journal_store = getattr(scheduler.brain, "journal_store", None)
        journal_contents: set[str] = set()
        if journal_store:
            try:
                recent_entries = await journal_store.get_entries(
                    date_from=(datetime.now(timezone.utc) - timedelta(days=14)).date(),
                    limit=100,
                )
                for entry in recent_entries:
                    journal_contents.add(entry.content[:200].lower())
            except Exception:
                pass

        all_ref_text = " ".join(memory_contents) + " " + " ".join(journal_contents)
        all_ref_lower = all_ref_text.lower()

        # Over-scored: HIGH signals never referenced again
        over_scored = 0
        over_scored_examples: list[str] = []
        for sig in high_signals:
            title = sig.get("title", "")[:60]
            # Check if key words from the signal title appear in memory/journal
            key_words = [w.lower() for w in title.split() if len(w) >= 5]
            if key_words:
                found = sum(1 for w in key_words if w in all_ref_lower)
                if found == 0:
                    over_scored += 1
                    if len(over_scored_examples) < 5:
                        over_scored_examples.append(
                            f"{sig.get('source', '?')}: {title} (score={sig.get('composite_score', 0):.2f})"  # noqa: E501
                        )

        # Under-scored: LOW signals that ended up being reinforced/referenced
        under_scored = 0
        under_scored_examples: list[str] = []
        for sig in low_signals[:500]:  # Cap for performance
            title = sig.get("title", "")[:60]
            key_words = [w.lower() for w in title.split() if len(w) >= 5]
            if key_words:
                found = sum(1 for w in key_words if w in all_ref_lower)
                if found >= 2:  # Multiple key words referenced
                    under_scored += 1
                    if len(under_scored_examples) < 5:
                        under_scored_examples.append(
                            f"{sig.get('source', '?')}: {title} (score={sig.get('composite_score', 0):.2f})"  # noqa: E501
                        )

        report["over_scored_signals"] = over_scored
        report["under_scored_signals"] = under_scored

        over_rate = (over_scored / max(len(high_signals), 1)) * 100
        under_rate = (under_scored / max(min(len(low_signals), 500), 1)) * 100

        log.info(
            "[NIGHT-WATCH/INTEL] Task I3: %d HIGH signals checked, %d over-scored (%.1f%%), "
            "%d LOW signals checked, %d under-scored (%.1f%%)",
            len(high_signals),
            over_scored,
            over_rate,
            min(len(low_signals), 500),
            under_scored,
            under_rate,
        )

    except asyncio.TimeoutError:
        report["errors"].append("I3: timeout")
        log.error("[NIGHT-WATCH/INTEL] Task I3 timed out")
    except Exception as e:
        report["errors"].append(f"I3: {e}")
        log.error("[NIGHT-WATCH/INTEL] Task I3 failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # TASK I4: Prediction Calibration Analysis (FREE + 1 Haiku)
    # ══════════════════════════════════════════════════════════════
    try:
        log.info("[NIGHT-WATCH/INTEL] Task I4: Prediction calibration analysis...")

        pred_dir = scheduler.data_dir / "predictions"
        cutoff_30d = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_14d_dt = datetime.now(timezone.utc) - timedelta(days=14)

        all_predictions: list[dict] = []
        if pred_dir.exists():
            for pf in sorted(pred_dir.glob("pred-*.json")):
                try:
                    # Check file age
                    mtime = datetime.fromtimestamp(pf.stat().st_mtime, tz=timezone.utc)
                    if mtime < cutoff_30d:
                        continue
                    pdata = json.loads(pf.read_text())
                    pdata["_file"] = pf.name
                    pdata["_mtime"] = mtime.isoformat()
                    all_predictions.append(pdata)
                except Exception:
                    continue

        # Read accuracy outcomes
        accuracy_outcomes: dict[str, dict] = {}  # prediction_id -> outcome
        acc_file = pred_dir / "accuracy.jsonl" if pred_dir.exists() else None
        if acc_file and acc_file.exists():
            try:
                with open(acc_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            outcome = json.loads(line)
                            pid = outcome.get("prediction_id", "")
                            if pid:
                                accuracy_outcomes[pid] = outcome
                        except json.JSONDecodeError:
                            continue
            except Exception:
                pass

        # Extract model info from consensus text and compute per-model stats
        model_predictions: dict[str, list[dict]] = defaultdict(list)  # model -> predictions
        stale_predictions: list[dict] = []

        for pred in all_predictions:
            consensus = pred.get("consensus", "")
            topic = pred.get("topic", "unknown")
            ts_str = pred.get("timestamp", pred.get("_mtime", ""))
            pred_id = pred.get("prediction_id", "")

            # Extract model names from consensus text
            models_found: list[str] = []
            # Pattern: "lead=MODEL@" or "[MODEL concurs@"
            for m in re.findall(r"lead=(\w+)@|(\w+)\s+concurs@|\[Single-model\]", consensus):
                model_name = m[0] or m[1]
                if model_name:
                    models_found.append(model_name.lower())
            if "[Single-model]" in consensus:
                # Try to detect model from context
                if "claude" in consensus.lower():
                    models_found.append("claude")
                elif "qwen" in consensus.lower():
                    models_found.append("qwen")
                elif "deepseek" in consensus.lower():
                    models_found.append("deepseek")

            if not models_found:
                models_found = ["unknown"]

            # Check for outcome
            has_outcome = pred_id in accuracy_outcomes or pred.get("outcome")
            outcome_correct = None
            if pred_id in accuracy_outcomes:
                outcome_correct = accuracy_outcomes[pred_id].get("correct")
            elif pred.get("outcome") in ("correct", "partial"):
                outcome_correct = True
            elif pred.get("outcome") == "incorrect":
                outcome_correct = False

            for model in models_found:
                model_predictions[model].append(
                    {
                        "topic": topic,
                        "confidence": pred.get("confidence", 0),
                        "has_outcome": has_outcome,
                        "correct": outcome_correct,
                    }
                )

            # Stale predictions: no outcome and older than 14 days
            if not has_outcome:
                try:
                    pred_dt = (
                        datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts_str
                        else None
                    )
                    if pred_dt and pred_dt < cutoff_14d_dt:
                        stale_predictions.append(
                            {
                                "topic": topic,
                                "timestamp": ts_str,
                                "file": pred.get("_file", ""),
                            }
                        )
                except Exception:
                    pass

        report["predictions_stale"] = len(stale_predictions)

        # Compute per-model accuracy
        per_model_accuracy: dict[str, str] = {}
        model_summary_lines: list[str] = []
        for model, preds in sorted(model_predictions.items()):
            total = len(preds)
            with_outcome = sum(1 for p in preds if p["has_outcome"])
            correct = sum(1 for p in preds if p["correct"] is True)
            if with_outcome > 0:
                acc_pct = f"{correct}/{with_outcome} ({correct/with_outcome*100:.0f}%)"
            else:
                acc_pct = f"0/{total} (no outcomes)"
            per_model_accuracy[model] = acc_pct
            model_summary_lines.append(f"{model}: {total} predictions, accuracy={acc_pct}")

        report["per_model_accuracy"] = per_model_accuracy

        # Dual-model call for model reliability assessment (Haiku + Gemini)
        if api_key and model_summary_lines:
            try:
                stale_summary = ""
                if stale_predictions:
                    stale_summary = (
                        "\n\nUNRESOLVED PREDICTIONS (older than 14 days, no outcome recorded):\n"  # noqa: E501
                        + "\n".join(
                            f"- {p['topic']} ({p.get('file', '')})"
                            for p in stale_predictions[:10]
                        )
                    )

                prompt = (
                    "You are a prediction system analyst. Review per-model accuracy data "
                    "for an AI ensemble forecasting system.\n\n"
                    "PER-MODEL STATS:\n"
                    + "\n".join(f"- {line}" for line in model_summary_lines)
                    + "\n"
                    + stale_summary
                    + "\n\n"
                    "Given these per-model accuracy rates and unresolved predictions, "
                    "which models are reliable on which topics? What calibration issues "
                    "exist? 3-5 bullet points."
                )

                # Run both models in parallel
                haiku_task = asyncio.wait_for(
                    _call_sonnet_intel(prompt, "I4_prediction_calibration"),
                    timeout=TASK_TIMEOUT,
                )
                gemini_task = asyncio.wait_for(
                    _call_gemini(prompt, "I4_prediction_calibration"), timeout=TASK_TIMEOUT
                )
                haiku_res, gemini_res = await asyncio.gather(
                    haiku_task,
                    gemini_task,
                    return_exceptions=True,
                )

                haiku_text = ""
                gemini_text = ""

                if isinstance(haiku_res, tuple):
                    haiku_text, haiku_cost = haiku_res
                    report["total_cost_usd"] += haiku_cost
                elif isinstance(haiku_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I4 Haiku failed: %s", haiku_res)

                if isinstance(gemini_res, tuple):
                    gemini_text, gemini_cost = gemini_res
                    report["total_cost_usd"] += gemini_cost
                elif isinstance(gemini_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I4 Gemini failed: %s", gemini_res)

                # Combine assessments — note disagreements
                combined_parts: list[str] = []
                if haiku_text and gemini_text:
                    combined_parts.append(f"=== Haiku Assessment ===\n{haiku_text}")
                    combined_parts.append(f"=== Gemini Assessment ===\n{gemini_text}")
                    log.info(
                        "[NIGHT-WATCH/INTEL] I4: Got assessments from both Haiku and Gemini"
                    )
                elif haiku_text:
                    combined_parts.append(haiku_text)
                elif gemini_text:
                    combined_parts.append(gemini_text)

                # Store combined calibration in report for Phase 5 synthesis
                report["prediction_calibration_analysis"] = "\n\n".join(combined_parts)

            except Exception as e:
                report["errors"].append(f"I4 dual-model: {e}")
                log.error("[NIGHT-WATCH/INTEL] Task I4 dual-model failed: %s", e)

        log.info(
            "[NIGHT-WATCH/INTEL] Task I4: %d predictions, %d models, %d stale",
            len(all_predictions),
            len(model_predictions),
            len(stale_predictions),
        )

    except asyncio.TimeoutError:
        report["errors"].append("I4: timeout")
        log.error("[NIGHT-WATCH/INTEL] Task I4 timed out")
    except Exception as e:
        report["errors"].append(f"I4: {e}")
        log.error("[NIGHT-WATCH/INTEL] Task I4 failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # TASK I5: Council Topic Suggestion (1 Haiku)
    # ══════════════════════════════════════════════════════════════
    try:
        log.info("[NIGHT-WATCH/INTEL] Task I5: Council topic suggestion...")

        suggestion_inputs: list[str] = []

        # Prediction failures
        for model, preds in model_predictions.items():
            for p in preds:
                if p["correct"] is False:
                    suggestion_inputs.append(f"PREDICTION FAILURE ({model}): {p['topic']}")

        # Coverage blind spots from I2
        for bs in report.get("blind_spots", [])[:5]:
            suggestion_inputs.append(f"COVERAGE GAP: {bs}")

        # Journal research_queue items
        journal_store = getattr(scheduler.brain, "journal_store", None)
        if journal_store:
            try:
                recent_reflections = await journal_store.get_recent_reflections(days=7)
                for ref in recent_reflections:
                    for rq in getattr(ref, "research_queue", []):
                        suggestion_inputs.append(f"RESEARCH QUEUE: {rq}")
                    for oq in getattr(ref, "open_questions", []):
                        suggestion_inputs.append(f"OPEN QUESTION: {oq}")
            except Exception:
                pass

        # High-importance signals not yet council-debated
        if signals_file.exists():
            cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            high_undebated: list[str] = []
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        sig = json.loads(line)
                        if sig.get("timestamp", "") >= cutoff_7d:
                            tags = sig.get("tags", [])
                            level = sig.get("route_level", "")
                            if level in ("HIGH", "CRITICAL") and "council_flagged" not in tags:
                                title = sig.get("title", "")[:80]
                                if title and len(high_undebated) < 10:
                                    high_undebated.append(title)
                    except json.JSONDecodeError:
                        continue
            for t in high_undebated[:5]:
                suggestion_inputs.append(f"HIGH SIGNAL (no council): {t}")

        if api_key and suggestion_inputs:
            try:
                prompt = (
                    "You are a strategic intelligence advisor for an autonomous AI brain system. "  # noqa: E501
                    "Based on the following intelligence gaps, prediction failures, research questions, "  # noqa: E501
                    "and high-importance signals, suggest the top 3 topics that would benefit from "  # noqa: E501
                    "a full council debate (multi-LLM deliberation with Claude, Grok, Gemini, GPT). "  # noqa: E501
                    "Explain why each topic matters.\n\n"
                    "INPUTS:\n"
                    + "\n".join(f"- {inp}" for inp in suggestion_inputs[:30])
                    + "\n\n"
                    "Format as:\n"
                    "1. TOPIC: [topic]\n   WHY: [reasoning]\n"
                    "2. TOPIC: [topic]\n   WHY: [reasoning]\n"
                    "3. TOPIC: [topic]\n   WHY: [reasoning]"
                )

                # Run both models in parallel
                haiku_task = asyncio.wait_for(
                    _call_sonnet_intel(prompt, "I5_council_topics"), timeout=TASK_TIMEOUT
                )
                gemini_task = asyncio.wait_for(
                    _call_gemini(prompt, "I5_council_topics"), timeout=TASK_TIMEOUT
                )
                haiku_res, gemini_res = await asyncio.gather(
                    haiku_task,
                    gemini_task,
                    return_exceptions=True,
                )

                def _parse_topics(text: str) -> list[str]:
                    topics: list[str] = []
                    for line_text in text.split("\n"):
                        line_text = line_text.strip()
                        if line_text and re.match(
                            r"^\d+\.?\s*TOPIC:", line_text, re.IGNORECASE
                        ):
                            topic_text = re.sub(
                                r"^\d+\.?\s*TOPIC:\s*", "", line_text, flags=re.IGNORECASE
                            ).strip()
                            if topic_text:
                                topics.append(topic_text)
                    if not topics:
                        for line_text in text.split("\n"):
                            line_text = line_text.strip()
                            if re.match(r"^\d+\.", line_text):
                                topics.append(line_text)
                    return topics

                haiku_topics: list[str] = []
                gemini_topics: list[str] = []
                haiku_full = ""
                gemini_full = ""

                if isinstance(haiku_res, tuple):
                    haiku_full, haiku_cost = haiku_res
                    report["total_cost_usd"] += haiku_cost
                    haiku_topics = _parse_topics(haiku_full)
                elif isinstance(haiku_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I5 Haiku failed: %s", haiku_res)

                if isinstance(gemini_res, tuple):
                    gemini_full, gemini_cost = gemini_res
                    report["total_cost_usd"] += gemini_cost
                    gemini_topics = _parse_topics(gemini_full)
                elif isinstance(gemini_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I5 Gemini failed: %s", gemini_res)

                # Merge: topics from both models get priority boost
                haiku_kw_set = {t.lower()[:50] for t in haiku_topics}  # noqa: F841
                gemini_kw_set = {t.lower()[:50] for t in gemini_topics}  # noqa: F841

                priority_topics: list[str] = []  # Both models agree
                other_topics: list[str] = []  # Only one model

                seen_lower: set[str] = set()
                for t in haiku_topics:
                    t_lower = t.lower()[:50]
                    t_words = set(t_lower.split())
                    # Check if Gemini has a similar topic
                    matched = False
                    for gt in gemini_topics:
                        gt_words = set(gt.lower()[:50].split())
                        overlap = len(t_words & gt_words) / max(len(t_words | gt_words), 1)
                        if overlap > 0.3:
                            matched = True
                            break
                    if matched:
                        priority_topics.append(t)
                    else:
                        other_topics.append(t)
                    seen_lower.add(t_lower)

                for t in gemini_topics:
                    t_lower = t.lower()[:50]
                    if t_lower not in seen_lower:
                        other_topics.append(t)
                        seen_lower.add(t_lower)

                # Priority topics first, then others
                suggestions = priority_topics + other_topics
                report["council_suggestions"] = suggestions[:5]

                log.info(
                    "[NIGHT-WATCH/INTEL] I5: Haiku suggested %d, Gemini suggested %d, "
                    "%d priority (both agree), %d total merged",
                    len(haiku_topics),
                    len(gemini_topics),
                    len(priority_topics),
                    len(suggestions),
                )

                # Save to file for daytime council scheduling
                today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                topics_file = nw_dir / f"council-topics-{today_str}.json"
                try:
                    topics_data = {
                        "date": today_str,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "suggestions": suggestions[:5],
                        "priority_topics": priority_topics,
                        "haiku_analysis": haiku_full,
                        "gemini_analysis": gemini_full,
                        "inputs_count": len(suggestion_inputs),
                    }
                    async with aiofiles.open(topics_file, "w") as f:
                        await f.write(json.dumps(topics_data, indent=2))
                    log.info("[NIGHT-WATCH/INTEL] Council topics saved to %s", topics_file)
                except Exception as e:
                    log.error("[NIGHT-WATCH/INTEL] Failed to save council topics: %s", e)

            except Exception as e:
                report["errors"].append(f"I5 dual-model: {e}")
                log.error("[NIGHT-WATCH/INTEL] Task I5 dual-model failed: %s", e)
        else:
            log.info("[NIGHT-WATCH/INTEL] Task I5: no inputs or no API key — skipping")

        log.info(
            "[NIGHT-WATCH/INTEL] Task I5: %d suggestion inputs, %d topics suggested",
            len(suggestion_inputs),
            len(report.get("council_suggestions", [])),
        )

    except asyncio.TimeoutError:
        report["errors"].append("I5: timeout")
        log.error("[NIGHT-WATCH/INTEL] Task I5 timed out")
    except Exception as e:
        report["errors"].append(f"I5: {e}")
        log.error("[NIGHT-WATCH/INTEL] Task I5 failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # TASK I6: Cost Optimization Analysis (1 Haiku)
    # ══════════════════════════════════════════════════════════════
    try:
        log.info("[NIGHT-WATCH/INTEL] Task I6: Cost optimization analysis...")

        # Get 30-day spending history
        historical = await tracker.get_historical(30)
        today_ledger = await tracker.get_full_ledger(1)

        # Build per-source daily averages
        source_daily_totals: dict[str, list[float]] = defaultdict(list)
        daily_totals: list[float] = []
        for day_summary in historical:
            by_source = day_summary.get("by_source", {})
            day_total = day_summary.get("total_usd", 0)
            daily_totals.append(day_total)
            for source, sdata in by_source.items():
                spent = sdata.get("spent_usd", 0)
                if spent > 0:
                    source_daily_totals[source].append(spent)

        # Per-category breakdown from today's ledger
        category_totals: dict[str, float] = defaultdict(float)
        source_totals_today: dict[str, float] = defaultdict(float)
        for entry in today_ledger:
            cat = entry.get("category", "unknown")
            src = entry.get("source", "unknown")
            amt = entry.get("amount_usd", 0)
            category_totals[cat] += amt
            source_totals_today[src] += amt

        # Build analysis summary for Haiku
        cost_summary_lines: list[str] = []
        cost_summary_lines.append(f"30-day history: {len(historical)} days recorded")
        if daily_totals:
            avg_daily = sum(daily_totals) / len(daily_totals)
            max_daily = max(daily_totals)
            cost_summary_lines.append(f"Daily average: ${avg_daily:.4f}, max: ${max_daily:.4f}")

            # Trend: compare last 7 days vs prior 7 days
            if len(daily_totals) >= 14:
                recent_avg = sum(daily_totals[-7:]) / 7
                prior_avg = sum(daily_totals[-14:-7]) / 7
                if prior_avg > 0:
                    change_pct = ((recent_avg - prior_avg) / prior_avg) * 100
                    trend = (
                        "INCREASING"
                        if change_pct > 10
                        else "DECREASING"
                        if change_pct < -10
                        else "STABLE"
                    )
                    cost_summary_lines.append(
                        f"Trend: {trend} ({change_pct:+.1f}% last 7d vs prior 7d)"
                    )

        cost_summary_lines.append("\nPer-source daily averages:")
        for source, amounts in sorted(source_daily_totals.items(), key=lambda x: -sum(x[1])):
            avg = sum(amounts) / max(len(amounts), 1)
            cost_summary_lines.append(f"  {source}: ${avg:.4f}/day (over {len(amounts)} days)")

        cost_summary_lines.append("\nToday's per-category spend:")
        for cat, amt in sorted(category_totals.items(), key=lambda x: -x[1]):
            cost_summary_lines.append(f"  {cat}: ${amt:.4f}")

        cost_summary_lines.append(f"\nToday's ledger entries: {len(today_ledger)}")
        cost_summary_lines.append(f"Today's total: ${sum(source_totals_today.values()):.4f}")

        if api_key:
            try:
                prompt = (
                    "You are a cost optimization analyst for an autonomous AI brain system "
                    "that uses Claude, Grok, Gemini, GPT, and local Ollama models. "
                    "Analyze this 30-day cost data and identify optimization opportunities.\n\n"
                    "COST DATA:\n" + "\n".join(cost_summary_lines) + "\n\n"
                    "Identify:\n"
                    "1. Categories where Sonnet could replace Opus (simpler tasks using expensive models)\n"  # noqa: E501
                    "2. Redundant calls (same data processed twice)\n"
                    "3. Times/patterns of highest spend\n"
                    "4. Project when daily budgets will be consistently exceeded\n\n"
                    "Give 3-5 specific, actionable recommendations. "
                    "Each recommendation as a bullet point starting with '- '."
                )

                # Run both models in parallel
                haiku_task = asyncio.wait_for(
                    _call_sonnet_intel(prompt, "I6_cost_optimization"), timeout=TASK_TIMEOUT
                )
                gemini_task = asyncio.wait_for(
                    _call_gemini(prompt, "I6_cost_optimization"), timeout=TASK_TIMEOUT
                )
                haiku_res, gemini_res = await asyncio.gather(
                    haiku_task,
                    gemini_task,
                    return_exceptions=True,
                )

                haiku_text = ""
                gemini_text = ""

                if isinstance(haiku_res, tuple):
                    haiku_text, haiku_cost = haiku_res
                    report["total_cost_usd"] += haiku_cost
                elif isinstance(haiku_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I6 Haiku failed: %s", haiku_res)

                if isinstance(gemini_res, tuple):
                    gemini_text, gemini_cost = gemini_res
                    report["total_cost_usd"] += gemini_cost
                elif isinstance(gemini_res, Exception):
                    log.warning("[NIGHT-WATCH/INTEL] I6 Gemini failed: %s", gemini_res)

                # Conservative approach: only flag optimizations both models agree on
                def _extract_recs(text: str) -> list[str]:
                    return [
                        line.strip().lstrip("- •*0123456789.").strip()
                        for line in text.split("\n")
                        if line.strip()
                        and (
                            line.strip().startswith(("-", "•", "*"))
                            or re.match(r"^\d+\.", line.strip())
                        )
                        and len(line.strip()) > 15
                    ]

                haiku_recs = _extract_recs(haiku_text)
                gemini_recs = _extract_recs(gemini_text)

                # Find recommendations both models agree on (word overlap > 30%)
                agreed_recs: list[str] = []
                haiku_only: list[str] = []

                for hr in haiku_recs:
                    hr_words = set(hr.lower().split())
                    matched = False
                    for gr in gemini_recs:
                        gr_words = set(gr.lower().split())
                        overlap = len(hr_words & gr_words) / max(len(hr_words | gr_words), 1)
                        if overlap > 0.3:
                            matched = True
                            break
                    if matched:
                        agreed_recs.append(hr)
                    else:
                        haiku_only.append(hr)

                # Build combined output — consensus first
                combined_parts: list[str] = []
                if agreed_recs:
                    combined_parts.append(
                        "CONSENSUS RECOMMENDATIONS (both Haiku and Gemini agree):\n"
                        + "\n".join(f"- {r}" for r in agreed_recs)
                    )
                if haiku_only:
                    combined_parts.append(
                        "ADDITIONAL (Haiku-only, not confirmed by Gemini):\n"
                        + "\n".join(f"- {r}" for r in haiku_only[:3])
                    )

                report["cost_optimization"] = (
                    "\n\n".join(combined_parts) if combined_parts else haiku_text or gemini_text
                )

                log.info(
                    "[NIGHT-WATCH/INTEL] I6: Haiku %d recs, Gemini %d recs, %d consensus",
                    len(haiku_recs),
                    len(gemini_recs),
                    len(agreed_recs),
                )

            except Exception as e:
                report["errors"].append(f"I6 dual-model: {e}")
                log.error("[NIGHT-WATCH/INTEL] Task I6 dual-model failed: %s", e)
        else:
            report["cost_optimization"] = "No API key — skipped LLM analysis"

        log.info(
            "[NIGHT-WATCH/INTEL] Task I6: analyzed %d days of cost history", len(historical)
        )

    except asyncio.TimeoutError:
        report["errors"].append("I6: timeout")
        log.error("[NIGHT-WATCH/INTEL] Task I6 timed out")
    except Exception as e:
        report["errors"].append(f"I6: {e}")
        log.error("[NIGHT-WATCH/INTEL] Task I6 failed: %s", e, exc_info=True)

    # ══════════════════════════════════════════════════════════════
    # WRAP-UP
    # ══════════════════════════════════════════════════════════════

    report["duration_seconds"] = round(time.monotonic() - t0, 2)

    log.info(
        "[NIGHT-WATCH/INTEL] Intel cycle complete — "
        "correlations=%d, blind_spots=%d, over_scored=%d, under_scored=%d, "
        "stale_predictions=%d, council_suggestions=%d, "
        "cost=$%.4f, duration=%.1fs, errors=%d",
        report["missed_correlations"],
        len(report["blind_spots"]),
        report["over_scored_signals"],
        report["under_scored_signals"],
        report["predictions_stale"],
        len(report["council_suggestions"]),
        report["total_cost_usd"],
        report["duration_seconds"],
        len(report["errors"]),
    )

    return report
