"""
ncl-night-watch Phase 2 memory maintenance cycle (carved from scheduler.py, W10C-7).

Runs 6 sequential maintenance tasks on the memory store:
  M1: Semantic duplicate detection (FREE — offloaded to ncl-dedup-scan loop)
  M2: Deep re-scoring of unscored units (Sonnet, ~$0.50)
  M3: Entity backfill for entity-less units (Sonnet, ~$0.30)
  M4: Stale fact detection via LLM (Sonnet + Gemini dual-model, ~$0.05)
  M5: Knowledge graph maintenance (FREE)
  M6: Entity normalization (Sonnet + Gemini consensus, ~$0.01)

NEVER deletes memory units — all operations are additive or re-scoring.

This is the extracted body of what used to be
`AutonomousScheduler._night_watch_memory_cycle` defined inline in
`runtime/autonomous/scheduler.py`. The method on the scheduler is now a
thin shim that calls `run(self)` here so external callers and factories
that reference the method name still resolve.

Scheduler attributes touched (passed in as `scheduler`):
- `scheduler.brain` — Brain instance. Reads `scheduler.brain.memory_store`
  for `_load_all_units`, `_acquire_write`, `_release_write`, `_rewrite_units`,
  and the optional `_knowledge_graph` attribute. Falls back to
  `scheduler.brain.knowledge_graph` if the memory-store-attached one is
  missing. Tolerates `None`.
- `scheduler._stats` — dict. Reads `last_dedup_scan_merged_24h`,
  `last_dedup_scan`, `last_dedup_scan_candidates`, and
  `last_dedup_scan_dupes_found` for the M1 offload report. Read-only.

NOTE on safety of state refs:
- `brain` and `_stats` are both initialized in `Scheduler.__init__` and
  are stable for the scheduler's lifetime. `_stats` is a dict mutated
  by other loops; we only read four specific keys here, so no
  cross-loop write races to worry about. Memory store mutations go
  through its own writer-preference lock. Safe to call from the
  carved-out module.
- The two `_m4_haiku` / `_m4_gemini` and `_m6_haiku` / `_m6_gemini`
  inline async helpers stay defined inside `run()` because they close
  over `api_key`, `google_api_key`, and (M6) `google_api_key_m6`.
  Hoisting them would require threading those captures explicitly —
  byte-identical behavior took priority for this carve.

Other dependencies:
- `runtime.cost_tracker.get_tracker` — async budget tracker singleton.
- `runtime.memory.entity_extractor.extract_entities_and_relationships`
- `runtime.memory.importance_scorer.llm_importance_score` + `rule_based_score`
- httpx, asyncio — same direct calls as before the carve.
"""

from __future__ import annotations  # noqa: I001

import asyncio
import json
import logging
import os

log = logging.getLogger("ncl.autonomous")


async def run(scheduler) -> dict:
    """
    Night Watch Phase 2 — Memory Maintenance Cycle.

    Runs 6 sequential maintenance tasks on the memory store:
      M1: Semantic duplicate detection (FREE)
      M2: Deep re-scoring of unscored units (Sonnet, ~$0.50)
      M3: Entity backfill for entity-less units (Sonnet, ~$0.30)
      M4: Stale fact detection via LLM (Sonnet + Gemini dual-model, ~$0.05)
      M5: Knowledge graph maintenance (FREE)
      M6: Entity normalization (Sonnet + Gemini consensus, ~$0.01)

    NEVER deletes memory units — all operations are additive or re-scoring.

    Returns:
        Dict with task results and overall stats.
    """
    import re
    import time

    import httpx

    from ...cost_tracker import get_tracker
    from ...memory.entity_extractor import (
        extract_entities_and_relationships,
    )
    from ...memory.importance_scorer import llm_importance_score, rule_based_score

    t0 = time.monotonic()
    report = {
        "duplicates_found": 0,
        "units_rescored": 0,
        "entities_extracted": 0,
        "stale_facts_found": 0,
        "kg_stats": {"nodes": 0, "edges": 0, "components": 0},
        "normalizations": 0,
        "total_cost_usd": 0.0,
        "duration_seconds": 0.0,
        "errors": [],
    }

    TASK_TIMEOUT = 30 * 60  # 30 minutes per task  # noqa: N806

    memory_store = getattr(scheduler.brain, "memory_store", None)
    if not memory_store:
        report["errors"].append("Memory store not available")
        report["duration_seconds"] = time.monotonic() - t0
        return report

    knowledge_graph = getattr(memory_store, "_knowledge_graph", None)
    if knowledge_graph is None:
        knowledge_graph = getattr(scheduler.brain, "knowledge_graph", None)

    tracker = await get_tracker()
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    log.info("[NIGHT-WATCH/MEMORY] Starting memory maintenance cycle")

    # ══════════════════════════════════════════════════════════════
    # Task M1: Semantic Duplicate Detection — OFFLOADED (2026-05-22)
    # ══════════════════════════════════════════════════════════════
    # M1's in-line implementation was wedging Night Watch:
    #   - scoped to ALL units (9.7K-strong) instead of the change frontier
    #   - counted every pair twice (both A→B and B→A queries fired)
    #   - last cycle reported 11,521 dupes among 9,710 units (i.e. each
    #     pair counted 2-3x) and timed out at 30 minutes
    # Now lives in its own loop: `ncl-dedup-scan` (6h, 500-newest window,
    # 200-merge cap). We just report the 24h rolling merge count here.
    try:
        merged_24h = int(scheduler._stats.get("last_dedup_scan_merged_24h", 0) or 0)
        last_scan = scheduler._stats.get("last_dedup_scan")
        last_candidates = int(scheduler._stats.get("last_dedup_scan_candidates", 0) or 0)
        last_dupes = int(scheduler._stats.get("last_dedup_scan_dupes_found", 0) or 0)
        report["duplicates_found"] = merged_24h  # backwards-compat key
        report["dedup_scan_merged_24h"] = merged_24h
        report["dedup_scan_last_run"] = last_scan
        report["dedup_scan_last_candidates"] = last_candidates
        report["dedup_scan_last_dupes"] = last_dupes
        log.info(
            "[NIGHT-WATCH/MEMORY] Task M1 (offloaded): dedicated ncl-dedup-scan "
            "loop merged %d units in last 24h (last cycle: %s, candidates=%d, "
            "pairs=%d)",
            merged_24h,
            last_scan or "never",
            last_candidates,
            last_dupes,
        )
    except Exception as e:
        log.error("[NIGHT-WATCH/MEMORY] Task M1 offload report failed: %s", e)
        report["errors"].append(f"M1: {e}")

    # ══════════════════════════════════════════════════════════════
    # Task M2: Deep Re-scoring (uses memory scorer - Sonnet, ~$1.80)
    # ══════════════════════════════════════════════════════════════
    try:
        task_t0 = time.monotonic()
        log.info("[NIGHT-WATCH/MEMORY] Task M2: Deep re-scoring of unscored units")

        if not api_key:
            log.info("[NIGHT-WATCH/MEMORY] M2 skipped — no ANTHROPIC_API_KEY")
        else:
            units = await memory_store._load_all_units()

            # Find units with no LLM importance score
            unscored = [u for u in units if u.llm_importance_score is None]
            # Limit to 200 per night
            unscored = unscored[:200]
            log.info(
                "[NIGHT-WATCH/MEMORY] M2: %d unscored units found (capped at 200)",
                len(unscored),
            )

            rescored_count = 0
            m2_cost = 0.0
            batch_size = 50
            units_by_id = {u.unit_id: u for u in units}

            for batch_start in range(0, len(unscored), batch_size):
                if time.monotonic() - task_t0 > TASK_TIMEOUT:
                    log.warning("[NIGHT-WATCH/MEMORY] M2 timeout — aborting")
                    break

                # Budget check before each batch
                if not await tracker.can_spend("anthropic", 0.02):
                    log.warning("[NIGHT-WATCH/MEMORY] M2 budget exceeded — stopping")
                    break

                batch = unscored[batch_start : batch_start + batch_size]
                for unit in batch:
                    try:
                        llm_score = await llm_importance_score(
                            unit.content,
                            unit.source,
                            unit.tags,
                            timeout=10.0,
                        )
                        if llm_score is not None:
                            # Compute hybrid score: 70% LLM + 30% rule
                            rule_score = rule_based_score(unit.content, unit.source, unit.tags)
                            hybrid = (llm_score * 10 * 0.7) + (rule_score * 10 * 0.3)
                            hybrid = max(0.0, min(100.0, hybrid))

                            unit.llm_importance_score = llm_score
                            unit.importance = hybrid
                            units_by_id[unit.unit_id] = unit
                            rescored_count += 1

                            # Estimate per-call cost (Sonnet: $3.00/1M in, $15.00/1M out)
                            est_cost = 0.0016  # ~300 in + 50 out tokens typical
                            m2_cost += est_cost

                    except Exception as e:
                        log.debug("[NIGHT-WATCH/MEMORY] M2 scoring error: %s", e)
                        continue

            # Persist re-scored units
            if rescored_count > 0:
                await memory_store._acquire_write()
                try:
                    all_units = list(units_by_id.values())
                    await memory_store._rewrite_units(all_units)
                finally:
                    memory_store._release_write()

                # Record cost
                await tracker.record(
                    "anthropic",
                    m2_cost,
                    "night_watch_memory",
                    f"deep re-scoring {rescored_count} units",
                )
                report["total_cost_usd"] += m2_cost

            report["units_rescored"] = rescored_count
            log.info(
                "[NIGHT-WATCH/MEMORY] Task M2: re-scored %d units, cost $%.4f",
                rescored_count,
                m2_cost,
            )

    except Exception as e:
        log.error("[NIGHT-WATCH/MEMORY] Task M2 failed: %s", e)
        report["errors"].append(f"M2: {e}")

    # ══════════════════════════════════════════════════════════════
    # Task M3: Entity Backfill (Sonnet, ~$1.20)
    # ══════════════════════════════════════════════════════════════
    try:
        task_t0 = time.monotonic()
        log.info("[NIGHT-WATCH/MEMORY] Task M3: Entity backfill")

        units = await memory_store._load_all_units()

        # Find units with importance >= 40 and no entities
        needs_entities = [u for u in units if u.importance >= 40.0 and not u.entities]
        needs_entities = needs_entities[:100]  # Limit to 100 per night
        log.info(
            "[NIGHT-WATCH/MEMORY] M3: %d entity-less units found (capped at 100)",
            len(needs_entities),
        )

        entities_extracted = 0
        m3_cost = 0.0
        modified_ids: set[str] = set()

        for unit in needs_entities:
            if time.monotonic() - task_t0 > TASK_TIMEOUT:
                log.warning("[NIGHT-WATCH/MEMORY] M3 timeout — aborting")
                break

            try:
                # Always do fast extraction (FREE)
                use_llm = unit.importance >= 60.0 and bool(api_key)

                if use_llm:
                    if not await tracker.can_spend("anthropic", 0.002):
                        use_llm = False  # Fall back to regex-only

                extraction = await extract_entities_and_relationships(
                    unit.content,
                    unit.source,
                    use_llm=use_llm,
                )

                new_entities = extraction.get("entities", [])
                new_relationships = extraction.get("relationships", [])

                if new_entities:
                    unit.entities = new_entities
                    unit.relationships = new_relationships
                    entities_extracted += 1
                    modified_ids.add(unit.unit_id)

                    # Add to knowledge graph
                    if knowledge_graph:
                        await knowledge_graph.add_entities(new_entities, unit.unit_id)
                        if new_relationships:
                            await knowledge_graph.add_relationships(
                                new_relationships, unit.unit_id
                            )

                    if use_llm:
                        est_cost = 0.001
                        m3_cost += est_cost

            except Exception as e:
                log.debug(
                    "[NIGHT-WATCH/MEMORY] M3 extraction error for %s: %s", unit.unit_id[:8], e
                )
                continue

        # Persist modified units
        if modified_ids:
            await memory_store._acquire_write()
            try:
                all_units = await memory_store._load_all_units()
                units_by_id = {u.unit_id: u for u in all_units}
                # Update modified units in place
                for unit in needs_entities:
                    if unit.unit_id in modified_ids:
                        units_by_id[unit.unit_id] = unit
                await memory_store._rewrite_units(list(units_by_id.values()))
            finally:
                memory_store._release_write()

            if m3_cost > 0:
                await tracker.record(
                    "anthropic",
                    m3_cost,
                    "night_watch_memory",
                    f"entity backfill {entities_extracted} units",
                )
                report["total_cost_usd"] += m3_cost

        report["entities_extracted"] = entities_extracted
        log.info(
            "[NIGHT-WATCH/MEMORY] Task M3: extracted entities for %d units, cost $%.4f",
            entities_extracted,
            m3_cost,
        )

    except Exception as e:
        log.error("[NIGHT-WATCH/MEMORY] Task M3 failed: %s", e)
        report["errors"].append(f"M3: {e}")

    # ══════════════════════════════════════════════════════════════
    # Task M4: Stale Fact Detection (HAIKU + GEMINI, ~$0.02)
    # ══════════════════════════════════════════════════════════════
    try:
        task_t0 = time.monotonic()
        log.info("[NIGHT-WATCH/MEMORY] Task M4: Stale fact detection (dual-model)")

        google_api_key = os.environ.get("GOOGLE_API_KEY", "")

        if not api_key or not knowledge_graph:
            log.info("[NIGHT-WATCH/MEMORY] M4 skipped — no API key or knowledge graph")
        else:
            units = await memory_store._load_all_units()

            # Load semantic and decision type units
            fact_units = [
                u
                for u in units
                if getattr(u, "memory_type", "episodic") in ("semantic", "decision")
            ]

            # Group by shared entities from the knowledge graph
            entity_to_units: dict[str, list] = {}
            for unit in fact_units:
                for entity in unit.entities:
                    entity_to_units.setdefault(entity, []).append(unit)

            # Find clusters with 3+ units
            clusters: list[tuple[str, list]] = [
                (entity, unit_list)
                for entity, unit_list in entity_to_units.items()
                if len(unit_list) >= 3
            ]
            clusters = clusters[:30]  # Limit to 30 clusters per night

            stale_facts_found = 0
            m4_cost = 0.0
            m4_haiku_finds = 0
            m4_gemini_finds = 0

            for entity, cluster_units in clusters:
                if time.monotonic() - task_t0 > TASK_TIMEOUT:
                    log.warning("[NIGHT-WATCH/MEMORY] M4 timeout — aborting")
                    break

                if not await tracker.can_spend("anthropic", 0.001):
                    log.warning("[NIGHT-WATCH/MEMORY] M4 budget exceeded — stopping")
                    break

                # Build prompt with unit contents
                unit_texts = []
                for i, u in enumerate(cluster_units[:10]):  # Cap at 10 per cluster
                    unit_texts.append(
                        f"[{i+1}] (created {u.created_at.strftime('%Y-%m-%d')}, "
                        f"importance {u.importance:.0f}): {u.content[:300]}"
                    )

                prompt = (
                    f"These memory units reference '{entity}'. "
                    "Identify any contradictions or outdated facts. "
                    'Respond with JSON: {{"contradictions": [{{"units": [i,j], '
                    '"description": "..."}}, ...], "count": N}}\n'
                    'If no contradictions, respond: {{"contradictions": [], "count": 0}}\n\n'
                    + "\n".join(unit_texts)
                )

                # --- Haiku call ---
                async def _m4_haiku(p: str) -> list[dict]:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                        resp = await client.post(
                            "https://api.anthropic.com/v1/messages",
                            headers={
                                "x-api-key": api_key,
                                "anthropic-version": "2023-06-01",
                                "content-type": "application/json",
                            },
                            json={
                                "model": "claude-sonnet-4",
                                "max_tokens": 300,
                                "messages": [{"role": "user", "content": p}],
                            },
                        )
                        if resp.status_code != 200:
                            return []
                        data = resp.json()
                        usage = data.get("usage", {})
                        input_t = usage.get("input_tokens", 0)
                        output_t = usage.get("output_tokens", 0)
                        cost = (input_t * 3.00 + output_t * 15.00) / 1_000_000
                        return [
                            {"_cost": cost, "_source": "sonnet"}
                        ] + _m4_parse_contradictions(data["content"][0]["text"])

                # --- Gemini call ---
                async def _m4_gemini(p: str) -> list[dict]:
                    if not google_api_key:
                        return []
                    if not await tracker.can_spend("google", 0.001):
                        return []
                    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                        resp = await client.post(
                            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                            params={"key": google_api_key},
                            json={
                                "contents": [{"parts": [{"text": p}]}],
                                "generationConfig": {"maxOutputTokens": 300},
                            },
                        )
                        if resp.status_code != 200:
                            return []
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if not candidates:
                            return []
                        parts_list = candidates[0].get("content", {}).get("parts", [])
                        if not parts_list:
                            return []
                        text = parts_list[0].get("text", "")
                        usage_meta = data.get("usageMetadata", {})
                        input_t = usage_meta.get("promptTokenCount", 0)
                        output_t = usage_meta.get("candidatesTokenCount", 0)
                        cost = (input_t * 0.15 + output_t * 0.60) / 1_000_000
                        return [
                            {"_cost": cost, "_source": "gemini"}
                        ] + _m4_parse_contradictions(text)

                def _m4_parse_contradictions(text: str) -> list[dict]:
                    text = re.sub(r"```json\s*", "", text)
                    text = re.sub(r"```\s*", "", text)
                    try:
                        parsed = json.loads(text.strip())
                        return parsed.get("contradictions", [])
                    except (json.JSONDecodeError, ValueError):
                        return []

                try:
                    # Run Haiku and Gemini in parallel
                    haiku_result, gemini_result = await asyncio.gather(
                        _m4_haiku(prompt),
                        _m4_gemini(prompt),
                        return_exceptions=True,
                    )

                    # Process Haiku results
                    haiku_contradictions: list[dict] = []
                    haiku_cost = 0.0
                    if isinstance(haiku_result, list) and haiku_result:
                        meta = haiku_result[0]
                        if isinstance(meta, dict) and "_cost" in meta:
                            haiku_cost = meta["_cost"]
                            haiku_contradictions = haiku_result[1:]

                    # Process Gemini results
                    gemini_contradictions: list[dict] = []
                    gemini_cost = 0.0
                    if isinstance(gemini_result, list) and gemini_result:
                        meta = gemini_result[0]
                        if isinstance(meta, dict) and "_cost" in meta:
                            gemini_cost = meta["_cost"]
                            gemini_contradictions = gemini_result[1:]

                    # Combine: union of findings from either model
                    combined_descriptions: set[str] = set()
                    combined_count = 0
                    for c in haiku_contradictions:
                        desc = c.get("description", "")
                        if desc and desc not in combined_descriptions:
                            combined_descriptions.add(desc)
                            combined_count += 1
                    for c in gemini_contradictions:
                        desc = c.get("description", "")
                        if desc and desc not in combined_descriptions:
                            combined_descriptions.add(desc)
                            combined_count += 1

                    m4_haiku_finds += len(haiku_contradictions)
                    m4_gemini_finds += len(gemini_contradictions)
                    stale_facts_found += combined_count

                    # Track costs and record to tracker
                    if haiku_cost > 0:
                        await tracker.record(
                            "anthropic",
                            haiku_cost,
                            "night_watch_memory",
                            f"M4 stale fact detection (Haiku) entity='{entity}'",
                        )
                    if gemini_cost > 0:
                        await tracker.record(
                            "google",
                            gemini_cost,
                            "night_watch_memory",
                            f"M4 stale fact detection (Gemini) entity='{entity}'",
                        )
                    m4_cost += haiku_cost + gemini_cost

                    if combined_count > 0:
                        log.info(
                            "[NIGHT-WATCH/MEMORY] M4: entity '%s' — Haiku=%d, Gemini=%d, combined=%d contradictions",  # noqa: E501
                            entity,
                            len(haiku_contradictions),
                            len(gemini_contradictions),
                            combined_count,
                        )

                except Exception as e:
                    log.debug(
                        "[NIGHT-WATCH/MEMORY] M4 dual-model call error for '%s': %s", entity, e
                    )
                    continue

            # Record costs per source (tracked inline per cluster, just add to report)
            if m4_cost > 0:
                report["total_cost_usd"] += m4_cost

            report["stale_facts_found"] = stale_facts_found
            log.info(
                "[NIGHT-WATCH/MEMORY] Task M4: Haiku found %d issues, Gemini found %d issues, "
                "%d combined across %d clusters, cost $%.4f",
                m4_haiku_finds,
                m4_gemini_finds,
                stale_facts_found,
                len(clusters),
                m4_cost,
            )

    except Exception as e:
        log.error("[NIGHT-WATCH/MEMORY] Task M4 failed: %s", e)
        report["errors"].append(f"M4: {e}")

    # ══════════════════════════════════════════════════════════════
    # Task M5: Knowledge Graph Maintenance (FREE)
    # ══════════════════════════════════════════════════════════════
    try:
        task_t0 = time.monotonic()
        log.info("[NIGHT-WATCH/MEMORY] Task M5: Knowledge graph maintenance")

        if not knowledge_graph:
            log.info("[NIGHT-WATCH/MEMORY] M5 skipped — no knowledge graph")
        else:
            # Prune stale nodes/edges (not seen in 90 days)
            prune_result = await knowledge_graph.prune_stale(90)
            log.info(
                "[NIGHT-WATCH/MEMORY] M5 prune: %d nodes, %d edges removed",
                prune_result.get("pruned_nodes", 0),
                prune_result.get("pruned_edges", 0),
            )

            # Graph structure analysis using NetworkX
            if knowledge_graph._ensure_graph():
                import networkx as nx

                g = knowledge_graph._graph

                total_nodes = g.number_of_nodes()
                total_edges = g.number_of_edges()

                # Weakly connected components
                if total_nodes > 0:
                    components = list(nx.weakly_connected_components(g))
                    num_components = len(components)
                    largest_component = max(len(c) for c in components) if components else 0
                    isolated = sum(1 for n in g.nodes() if g.degree(n) == 0)
                else:
                    num_components = 0
                    largest_component = 0
                    isolated = 0

                report["kg_stats"] = {
                    "nodes": total_nodes,
                    "edges": total_edges,
                    "components": num_components,
                    "largest_component": largest_component,
                    "isolated_nodes": isolated,
                    "pruned_nodes": prune_result.get("pruned_nodes", 0),
                    "pruned_edges": prune_result.get("pruned_edges", 0),
                }

                # Find potential missing connections: entity pairs that
                # share 3+ neighbors but have no direct edge
                potential_links: list[str] = []
                if total_nodes > 0 and total_nodes < 5000:
                    undirected = g.to_undirected()
                    nodes_list = list(g.nodes())
                    # Only check top entities by degree to limit compute
                    top_nodes = sorted(
                        nodes_list,
                        key=lambda n: g.degree(n),
                        reverse=True,
                    )[:100]

                    checked = set()
                    for n1 in top_nodes:
                        if time.monotonic() - task_t0 > TASK_TIMEOUT:
                            break
                        neighbors_1 = set(undirected.neighbors(n1))
                        for n2 in top_nodes:
                            if n1 >= n2 or (n1, n2) in checked:
                                continue
                            checked.add((n1, n2))
                            if g.has_edge(n1, n2) or g.has_edge(n2, n1):
                                continue
                            neighbors_2 = set(undirected.neighbors(n2))
                            shared = neighbors_1 & neighbors_2
                            if len(shared) >= 3:
                                potential_links.append(
                                    f"{n1} <-> {n2} (share {len(shared)} neighbors)"
                                )

                if potential_links:
                    log.info(
                        "[NIGHT-WATCH/MEMORY] M5: %d potential missing connections found",
                        len(potential_links),
                    )
                    for pl in potential_links[:5]:
                        log.info("[NIGHT-WATCH/MEMORY] M5 potential link: %s", pl)

                log.info(
                    "[NIGHT-WATCH/MEMORY] Task M5: nodes=%d, edges=%d, components=%d, "
                    "largest=%d, isolated=%d",
                    total_nodes,
                    total_edges,
                    num_components,
                    largest_component,
                    isolated,
                )

    except Exception as e:
        log.error("[NIGHT-WATCH/MEMORY] Task M5 failed: %s", e)
        report["errors"].append(f"M5: {e}")

    # ══════════════════════════════════════════════════════════════
    # Task M6: Entity Normalization (HAIKU, ~$0.001)
    # ══════════════════════════════════════════════════════════════
    try:
        task_t0 = time.monotonic()
        log.info("[NIGHT-WATCH/MEMORY] Task M6: Entity normalization")

        if not knowledge_graph or not knowledge_graph._ensure_graph():
            log.info("[NIGHT-WATCH/MEMORY] M6 skipped — no knowledge graph")
        else:
            # Get top entities
            top_entities = await knowledge_graph.get_top_entities(100)
            entity_names = [e["entity"] for e in top_entities]

            # Simple heuristic: find candidate pairs that may be the same entity
            candidate_pairs: list[tuple[str, str]] = []
            for i, name_a in enumerate(entity_names):
                for name_b in entity_names[i + 1 :]:
                    # Strip $ prefix for comparison
                    clean_a = name_a.lstrip("$").lower()
                    clean_b = name_b.lstrip("$").lower()

                    # Skip if identical after cleaning
                    if clean_a == clean_b and name_a != name_b:
                        candidate_pairs.append((name_a, name_b))
                        continue

                    # Check if one is a substring of the other (min length 3)
                    if len(clean_a) >= 3 and len(clean_b) >= 3:
                        if clean_a in clean_b or clean_b in clean_a:
                            candidate_pairs.append((name_a, name_b))
                            continue

                    # Common ticker-to-name mappings
                    ticker_map = {
                        "aapl": "apple",
                        "goog": "google",
                        "googl": "google",
                        "msft": "microsoft",
                        "amzn": "amazon",
                        "tsla": "tesla",
                        "meta": "facebook",
                        "nvda": "nvidia",
                        "nflx": "netflix",
                        "spy": "s&p 500",
                        "qqq": "nasdaq",
                    }
                    if clean_a in ticker_map and ticker_map[clean_a] in clean_b:
                        candidate_pairs.append((name_a, name_b))
                    elif clean_b in ticker_map and ticker_map[clean_b] in clean_a:
                        candidate_pairs.append((name_a, name_b))

            normalizations = 0
            m6_cost = 0.0

            if candidate_pairs:
                log.info(
                    "[NIGHT-WATCH/MEMORY] M6: %d candidate pairs found for normalization",
                    len(candidate_pairs),
                )

                # For unambiguous pairs (exact match after cleanup), add directly
                unambiguous: list[tuple[str, str]] = []
                ambiguous: list[tuple[str, str]] = []

                for a, b in candidate_pairs:
                    clean_a = a.lstrip("$").lower().strip()
                    clean_b = b.lstrip("$").lower().strip()
                    if clean_a == clean_b:
                        unambiguous.append((a, b))
                    else:
                        ambiguous.append((a, b))

                # Add SAME_AS edges for unambiguous pairs
                for a, b in unambiguous:
                    await knowledge_graph.add_relationships(
                        [{"subject": a, "predicate": "SAME_AS", "object": b}]
                    )
                    normalizations += 1

                # For ambiguous pairs, use Haiku AND Gemini — only confirm if BOTH agree
                if ambiguous and api_key:
                    google_api_key_m6 = os.environ.get("GOOGLE_API_KEY", "")
                    if await tracker.can_spend("anthropic", 0.001):
                        pairs_text = "\n".join(
                            f'  {i+1}. "{a}" vs "{b}"'
                            for i, (a, b) in enumerate(ambiguous[:30])
                        )
                        prompt = (
                            "These entity pairs may refer to the same real-world entity. "
                            "For each pair, respond YES if they are the same, NO if different.\n"  # noqa: E501
                            'Respond with JSON: {{"results": [true/false, ...]}}\n\n'
                            + pairs_text
                        )

                        def _m6_parse_results(text: str) -> list[bool]:
                            text = re.sub(r"```json\s*", "", text)
                            text = re.sub(r"```\s*", "", text)
                            try:
                                parsed = json.loads(text.strip())
                                return parsed.get("results", [])
                            except (json.JSONDecodeError, ValueError):
                                return []

                        async def _m6_haiku(p: str) -> tuple[list[bool], float]:
                            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                                resp = await client.post(
                                    "https://api.anthropic.com/v1/messages",
                                    headers={
                                        "x-api-key": api_key,
                                        "anthropic-version": "2023-06-01",
                                        "content-type": "application/json",
                                    },
                                    json={
                                        "model": "claude-sonnet-4",
                                        "max_tokens": 200,
                                        "messages": [{"role": "user", "content": p}],
                                    },
                                )
                                if resp.status_code != 200:
                                    return [], 0.0
                                data = resp.json()
                                usage = data.get("usage", {})
                                input_t = usage.get("input_tokens", 0)
                                output_t = usage.get("output_tokens", 0)
                                cost = (input_t * 3.00 + output_t * 15.00) / 1_000_000
                                return _m6_parse_results(data["content"][0]["text"]), cost

                        async def _m6_gemini(p: str) -> tuple[list[bool], float]:
                            if not google_api_key_m6:
                                return [], 0.0
                            if not await tracker.can_spend("google", 0.001):
                                return [], 0.0
                            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
                                resp = await client.post(
                                    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
                                    params={"key": google_api_key_m6},
                                    json={
                                        "contents": [{"parts": [{"text": p}]}],
                                        "generationConfig": {"maxOutputTokens": 200},
                                    },
                                )
                                if resp.status_code != 200:
                                    return [], 0.0
                                data = resp.json()
                                candidates = data.get("candidates", [])
                                if not candidates:
                                    return [], 0.0
                                parts_list = candidates[0].get("content", {}).get("parts", [])
                                if not parts_list:
                                    return [], 0.0
                                text = parts_list[0].get("text", "")
                                usage_meta = data.get("usageMetadata", {})
                                input_t = usage_meta.get("promptTokenCount", 0)
                                output_t = usage_meta.get("candidatesTokenCount", 0)
                                cost = (input_t * 0.15 + output_t * 0.60) / 1_000_000
                                return _m6_parse_results(text), cost

                        try:
                            haiku_res, gemini_res = await asyncio.gather(
                                _m6_haiku(prompt),
                                _m6_gemini(prompt),
                                return_exceptions=True,
                            )

                            haiku_results: list[bool] = []
                            haiku_cost_m6 = 0.0
                            if isinstance(haiku_res, tuple):
                                haiku_results, haiku_cost_m6 = haiku_res

                            gemini_results: list[bool] = []
                            gemini_cost_m6 = 0.0
                            if isinstance(gemini_res, tuple):
                                gemini_results, gemini_cost_m6 = gemini_res

                            m6_cost += haiku_cost_m6 + gemini_cost_m6

                            # Consensus: only confirm if BOTH models agree
                            agreed = 0
                            disagreed = 0
                            for idx in range(min(len(ambiguous), len(haiku_results))):
                                haiku_says = (
                                    haiku_results[idx] if idx < len(haiku_results) else None
                                )
                                gemini_says = (
                                    gemini_results[idx] if idx < len(gemini_results) else None
                                )

                                if haiku_says is True and gemini_says is True:
                                    # Both agree it's the same entity
                                    a, b = ambiguous[idx]
                                    await knowledge_graph.add_relationships(
                                        [{"subject": a, "predicate": "SAME_AS", "object": b}]
                                    )
                                    normalizations += 1
                                    agreed += 1
                                elif haiku_says is True and gemini_says is not True:
                                    # Haiku-only (no Gemini or disagreement) — fall back to Haiku  # noqa: E501
                                    if gemini_says is None:
                                        a, b = ambiguous[idx]
                                        await knowledge_graph.add_relationships(
                                            [
                                                {
                                                    "subject": a,
                                                    "predicate": "SAME_AS",
                                                    "object": b,
                                                }
                                            ]
                                        )
                                        normalizations += 1
                                    else:
                                        disagreed += 1
                                elif haiku_says is not None and gemini_says is not None:
                                    if haiku_says != gemini_says:
                                        disagreed += 1

                            log.info(
                                "[NIGHT-WATCH/MEMORY] M6: %d pairs agreed, %d disagreed",
                                agreed,
                                disagreed,
                            )

                        except Exception as e:
                            log.debug("[NIGHT-WATCH/MEMORY] M6 dual-model call error: %s", e)

                    if m6_cost > 0:
                        if haiku_cost_m6 > 0:
                            await tracker.record(
                                "anthropic",
                                haiku_cost_m6,
                                "night_watch_memory",
                                f"entity normalization (Haiku) {normalizations} pairs",
                            )
                        if gemini_cost_m6 > 0:
                            await tracker.record(
                                "google",
                                gemini_cost_m6,
                                "night_watch_memory",
                                f"entity normalization (Gemini) {normalizations} pairs",
                            )
                        report["total_cost_usd"] += m6_cost

            report["normalizations"] = normalizations
            log.info(
                "[NIGHT-WATCH/MEMORY] Task M6: %d normalizations, cost $%.4f",
                normalizations,
                m6_cost,
            )

    except Exception as e:
        log.error("[NIGHT-WATCH/MEMORY] Task M6 failed: %s", e)
        report["errors"].append(f"M6: {e}")

    # ══════════════════════════════════════════════════════════════
    # Final report
    # ══════════════════════════════════════════════════════════════
    report["duration_seconds"] = round(time.monotonic() - t0, 2)

    log.info(
        "[NIGHT-WATCH/MEMORY] Memory cycle complete — "
        "duplicates=%d, rescored=%d, entities=%d, stale=%d, "
        "normalizations=%d, cost=$%.4f, duration=%.1fs, errors=%d",
        report["duplicates_found"],
        report["units_rescored"],
        report["entities_extracted"],
        report["stale_facts_found"],
        report["normalizations"],
        report["total_cost_usd"],
        report["duration_seconds"],
        len(report["errors"]),
    )

    return report
