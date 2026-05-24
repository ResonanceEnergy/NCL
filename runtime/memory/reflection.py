"""
Memory Reflection Loop (ACE Pattern)
======================================

Implements the Generator → Reflector → Curator pipeline for
memory quality control during consolidation.

Generator: Creates candidate memories from raw interactions
    (Already handled by Awarebot._store_to_memory and MemoryStore.create_unit)

Reflector: Evaluates candidate memories for:
    - Importance and novelty
    - Accuracy conflicts with existing memories
    - Redundancy detection
    - Quality scoring (0-1)

Curator: Makes final storage decisions:
    - Merge duplicates
    - Resolve conflicts (newer wins unless older has higher reinforcement)
    - Trigger knowledge graph updates
    - Assign or reassign memory_type and memory_tier

The Reflector runs as a lightweight batch process during hourly
consolidation. The full LLM-based reflection runs daily.
"""

import logging
import re


log = logging.getLogger("ncl.memory.reflection")


class MemoryReflector:
    """
    Evaluates memory quality and flags issues for the Curator.

    Two modes:
    - Fast (rule-based): runs every consolidation cycle (~hourly)
    - Deep (LLM-based): runs daily during low-activity window
    """

    def __init__(self):
        self._conflict_cache = {}  # content_hash -> unit_id for dedup

    async def fast_reflect(self, units: list) -> dict:
        """
        Fast rule-based reflection pass over memory units.

        Returns dict with:
            - duplicates: list of (unit_id, duplicate_of_id) pairs
            - low_quality: list of unit_ids with quality issues
            - conflicts: list of (unit_id_a, unit_id_b, reason) triples
            - quality_scores: dict of unit_id -> float (0-1)
            - stats: summary statistics
        """
        duplicates = []
        low_quality = []
        conflicts = []
        quality_scores = {}

        # Build content fingerprints for dedup
        fingerprints = {}  # fingerprint -> (unit_id, unit)

        for unit in units:
            uid = unit.unit_id
            content = unit.content.strip()

            # Quality scoring
            score = self._score_quality(unit)
            quality_scores[uid] = score

            if score < 0.3:
                low_quality.append(uid)

            # Fingerprint-based dedup (normalized first 200 chars)
            fp = self._fingerprint(content)
            if fp in fingerprints:
                existing_id, existing_unit = fingerprints[fp]
                duplicates.append((uid, existing_id))
            else:
                fingerprints[fp] = (uid, unit)

            # Conflict detection: same tags but very different importance
            # suggests contradicting assessments of the same topic
            unit_tags = set(unit.tags) if unit.tags else set()
            if len(unit_tags) >= 2:
                for other_fp_key, (other_id, other_unit_obj) in list(fingerprints.items())[:100]:
                    if other_id == uid:
                        continue
                    other_tags = set(other_unit_obj.tags) if other_unit_obj.tags else set()
                    shared_tags = unit_tags & other_tags
                    if len(shared_tags) >= 2:
                        # Same topic area — check for importance divergence
                        imp_diff = abs(unit.importance - other_unit_obj.importance)
                        if imp_diff > 40:
                            conflicts.append(
                                (
                                    uid,
                                    other_id,
                                    f"Importance divergence ({imp_diff:.0f}) on shared tags: {', '.join(sorted(shared_tags)[:3])}",  # noqa: E501
                                )
                            )

        return {
            "duplicates": duplicates,
            "low_quality": low_quality,
            "conflicts": conflicts,
            "quality_scores": quality_scores,
            "stats": {
                "total_evaluated": len(units),
                "duplicates_found": len(duplicates),
                "low_quality_found": len(low_quality),
                "conflicts_found": len(conflicts),
                "avg_quality": sum(quality_scores.values()) / max(1, len(quality_scores)),
            },
        }

    def _score_quality(self, unit) -> float:
        """
        Score memory unit quality on 0-1 scale.

        Factors:
        - Content length (too short = low quality)
        - Has tags (tagged = higher quality)
        - Has source attribution
        - Reinforcement count (accessed = valued)
        - Content structure (has sentences, not just fragments)
        """
        score = 0.5  # Base score
        content = unit.content.strip()

        # Content length
        if len(content) < 20:
            score -= 0.3
        elif len(content) > 100:
            score += 0.1
        elif len(content) > 300:
            score += 0.15

        # Has tags
        if unit.tags and len(unit.tags) > 0:
            score += 0.1
        if len(unit.tags) >= 3:
            score += 0.05

        # Source attribution
        if unit.source and unit.source != "unknown":
            score += 0.05

        # Reinforcement (has been accessed/valued)
        if unit.reinforcement_count > 0:
            score += min(0.2, unit.reinforcement_count * 0.05)

        # Content structure
        if "." in content or ":" in content:
            score += 0.05  # Has sentence structure
        if content.startswith("[") and "]" in content:
            score += 0.05  # Has source tag structure

        # Penalty for consolidation artifacts
        if "[TRUNCATED]" in content:
            score -= 0.1
        if content.count("|") > 3:
            score -= 0.1  # Over-merged content

        return max(0.0, min(1.0, score))

    def _fingerprint(self, content: str) -> str:
        """Create a normalized fingerprint for dedup."""
        import hashlib

        # Normalize: lowercase, strip whitespace, remove punctuation
        normalized = re.sub(r"[^\w\s]", "", content.lower().strip())
        # Use first 200 chars for fingerprint
        normalized = " ".join(normalized.split())[:200]
        return hashlib.md5(normalized.encode()).hexdigest()


class MemoryCurator:
    """
    Makes final storage decisions based on Reflector output.

    Actions:
    - merge_duplicates: Combine duplicate units, keeping higher-quality version
    - prune_low_quality: Remove units below quality threshold
    - promote_tier: Move high-value SML units to LML
    - demote_tier: Move decayed LML units to SML
    - update_types: Reassign memory_type based on content analysis
    """

    def __init__(self, knowledge_graph=None):
        self.knowledge_graph = knowledge_graph

    async def curate(self, units: list, reflection: dict) -> dict:
        """
        Apply curation decisions based on reflection output.

        Returns dict with:
            - merged: list of (surviving_id, merged_ids)
            - pruned: list of pruned unit_ids
            - promoted: list of unit_ids promoted LML
            - demoted: list of unit_ids demoted to SML
            - kg_updates: number of knowledge graph updates
        """
        merged = []
        pruned = []
        promoted = []
        demoted = []
        kg_updates = 0

        quality_scores = reflection.get("quality_scores", {})
        duplicates = reflection.get("duplicates", [])
        low_quality = reflection.get("low_quality", [])

        # Index units by ID
        units_by_id = {u.unit_id: u for u in units}
        merged_away = set()  # IDs that got merged into another

        # 1. Handle duplicates: keep higher quality version
        for dup_id, original_id in duplicates:
            if dup_id in merged_away or original_id in merged_away:
                continue

            dup = units_by_id.get(dup_id)
            original = units_by_id.get(original_id)
            if not dup or not original:
                continue

            # Keep the one with higher quality score
            dup_score = quality_scores.get(dup_id, 0.5)
            orig_score = quality_scores.get(original_id, 0.5)

            if dup_score > orig_score:
                # Keep dup, merge original into it
                survivor, victim = dup, original
            else:
                survivor, victim = original, dup

            # Merge: boost importance, combine tags, add to consolidated_from
            survivor.importance = min(100.0, max(survivor.importance, victim.importance) * 1.05)
            survivor.tags = list(set(survivor.tags + victim.tags))[:20]
            survivor.reinforcement_count += victim.reinforcement_count

            if hasattr(survivor, "consolidated_from"):
                survivor.consolidated_from.append(victim.unit_id)

            merged.append((survivor.unit_id, [victim.unit_id]))
            merged_away.add(victim.unit_id)

        # 2. Prune very low quality (below 0.2) that haven't been reinforced
        for uid in low_quality:
            if uid in merged_away:
                continue
            unit = units_by_id.get(uid)
            if not unit:
                continue
            q = quality_scores.get(uid, 0.5)
            if q < 0.2 and unit.reinforcement_count == 0 and unit.importance < 20:
                pruned.append(uid)
                merged_away.add(uid)

        # 3. Tier promotion/demotion
        for unit in units:
            if unit.unit_id in merged_away:
                continue

            tier = getattr(unit, "memory_tier", "SML")
            q = quality_scores.get(unit.unit_id, 0.5)

            # Promote SML -> LML: high quality + high importance + reinforced
            if (
                tier == "SML"
                and q >= 0.7
                and unit.importance >= 60
                and unit.reinforcement_count >= 2
            ):
                unit.memory_tier = "LML"
                unit.decay_rate = 0.999  # Slow decay
                promoted.append(unit.unit_id)

            # Demote LML -> SML: decayed below threshold
            elif tier == "LML" and unit.importance < 20 and q < 0.4:
                unit.memory_tier = "SML"
                unit.decay_rate = 0.95  # Fast decay
                demoted.append(unit.unit_id)

        # 4. Knowledge graph updates (if available)
        if self.knowledge_graph:
            for unit in units:
                if unit.unit_id in merged_away:
                    continue
                entities = getattr(unit, "entities", [])
                relationships = getattr(unit, "relationships", [])
                if entities:
                    await self.knowledge_graph.add_entities(entities, unit.unit_id)
                    kg_updates += len(entities)
                if relationships:
                    await self.knowledge_graph.add_relationships(relationships, unit.unit_id)
                    kg_updates += len(relationships)

        # 5. Set reflection_quality on all surviving units
        for unit in units:
            if unit.unit_id not in merged_away and hasattr(unit, "reflection_quality"):
                unit.reflection_quality = quality_scores.get(unit.unit_id)

        return {
            "merged": merged,
            "pruned": pruned,
            "promoted": promoted,
            "demoted": demoted,
            "kg_updates": kg_updates,
            "stats": {
                "total_input": len(units),
                "merged_count": len(merged),
                "pruned_count": len(pruned),
                "promoted_count": len(promoted),
                "demoted_count": len(demoted),
                "surviving": len(units) - len(merged_away),
            },
        }
