"""Second Brain Knowledge Engine — Tiago Forte Framework Integration.

Implements the "Building a Second Brain" methodology as a knowledge
management and intelligence amplification layer for the Future
Predictor Council:

**PARA** — Projects / Areas / Resources / Archives
**CODE** — Capture / Organize / Distill / Express
**Progressive Summarization** — 5-layer distillation pipeline
**Intermediate Packets** — Reusable knowledge atoms
**Just-In-Time Retrieval** — Context-aware knowledge surfacing

Agent #28: CORTEX (sb) — Second Brain Knowledge Engine
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

# ── Enums ──────────────────────────────────────────────────────


class PARACategory(StrEnum):
    """PARA organizational categories."""

    PROJECTS = "projects"       # Active, time-bound goals
    AREAS = "areas"             # Ongoing responsibilities
    RESOURCES = "resources"     # Topics of interest
    ARCHIVES = "archives"       # Inactive items


class CODEStage(StrEnum):
    """CODE workflow stages."""

    CAPTURE = "capture"         # Raw information intake
    ORGANIZE = "organize"       # Sort into PARA categories
    DISTILL = "distill"         # Progressive summarization
    EXPRESS = "express"         # Share / publish / act on knowledge


class SummarizationLayer(StrEnum):
    """Progressive Summarization layers (L1-L5)."""

    L1_RAW = "layer_1_raw"             # Full source text
    L2_HIGHLIGHTED = "layer_2_highlighted"  # Bold passages
    L3_EXECUTIVE = "layer_3_executive"     # Executive summary
    L4_DISTILLED = "layer_4_distilled"     # Core insight atoms
    L5_REMIXED = "layer_5_remixed"         # Original synthesis


class PacketType(StrEnum):
    """Types of Intermediate Packets."""

    DISTILLED_NOTE = "distilled_note"       # Refined knowledge note
    OUTTAKE = "outtake"                     # Unused but valuable fragments
    WORK_IN_PROGRESS = "work_in_progress"   # Partial deliverable
    FINAL_DELIVERABLE = "final_deliverable"  # Completed output
    TEMPLATE = "template"                   # Reusable pattern
    CHECKLIST = "checklist"                 # Procedural checklist


class RetrievalMode(StrEnum):
    """Just-In-Time retrieval strategies."""

    KEYWORD = "keyword"             # Simple keyword match
    SEMANTIC = "semantic"           # Meaning-based similarity
    TEMPORAL = "temporal"           # Recency-weighted
    ASSOCIATIVE = "associative"     # Connection-graph traversal
    CONTEXTUAL = "contextual"       # Current-task context matching


class KnowledgeStatus(StrEnum):
    """Lifecycle status of knowledge items."""

    CAPTURED = "captured"           # Just ingested
    ORGANIZED = "organized"         # Placed in PARA
    DISTILLING = "distilling"       # Being summarized
    DISTILLED = "distilled"         # Summary complete
    EXPRESSED = "expressed"         # Published / acted on
    ARCHIVED = "archived"           # Moved to archives


# ── Data Contracts ─────────────────────────────────────────────


@dataclass
class KnowledgeNote:
    """Core knowledge unit in the Second Brain."""

    note_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    source: str = ""
    category: PARACategory = PARACategory.RESOURCES
    status: KnowledgeStatus = KnowledgeStatus.CAPTURED
    tags: list[str] = field(default_factory=list)
    content: dict[str, Any] = field(default_factory=dict)
    layers: dict[str, str] = field(default_factory=dict)
    connections: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    fingerprint: str = ""

    def touch(self) -> None:
        """Record an access."""
        self.access_count += 1
        self.updated_at = time.time()

    def compute_fingerprint(self) -> str:
        """Deterministic fingerprint from title + source + content keys."""
        raw = f"{self.title}|{self.source}|{sorted(self.content.keys())}"
        self.fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return self.fingerprint


@dataclass
class IntermediatePacket:
    """Reusable knowledge atom — building block for expression."""

    packet_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    packet_type: PacketType = PacketType.DISTILLED_NOTE
    title: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    source_notes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    reuse_count: int = 0
    quality_score: float = 0.0
    created_at: float = field(default_factory=time.time)

    def reuse(self) -> None:
        """Track reuse of this packet."""
        self.reuse_count += 1

    def score_quality(self) -> float:
        """Score packet quality based on reuse, sources, and completeness."""
        source_bonus = min(1.0, len(self.source_notes) * 0.2)
        reuse_bonus = min(1.0, self.reuse_count * 0.15)
        content_bonus = min(1.0, len(self.content) * 0.1)
        self.quality_score = round(
            (source_bonus + reuse_bonus + content_bonus) / 3.0, 4,
        )
        return self.quality_score


@dataclass
class RetrievalResult:
    """Result from a Just-In-Time knowledge retrieval."""

    query: str = ""
    mode: RetrievalMode = RetrievalMode.KEYWORD
    results: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)
    elapsed_ms: float = 0.0
    total_searched: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def hit_count(self) -> int:
        return len(self.results)


@dataclass
class DistillationReport:
    """Report from a progressive summarization cycle."""

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    note_id: str = ""
    layers_completed: list[str] = field(default_factory=list)
    compression_ratio: float = 0.0
    insight_density: float = 0.0
    timestamp: float = field(default_factory=time.time)


@dataclass
class ExpressionOutput:
    """Output from the Express stage of CODE."""

    output_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    format: str = "report"  # report, briefing, packet, synthesis
    source_packets: list[str] = field(default_factory=list)
    content: dict[str, Any] = field(default_factory=dict)
    audience: str = "council"
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)


# ── Knowledge Store ────────────────────────────────────────────


class KnowledgeStore:
    """PARA-organized knowledge repository.

    Stores notes across all four PARA categories with tagging,
    fingerprint-based deduplication, and lifecycle management.
    """

    def __init__(self) -> None:
        self._notes: dict[str, KnowledgeNote] = {}
        self._by_category: dict[PARACategory, list[str]] = {
            cat: [] for cat in PARACategory
        }
        self._by_tag: dict[str, list[str]] = {}
        self._fingerprints: set[str] = set()

    @property
    def total_notes(self) -> int:
        return len(self._notes)

    def ingest(
        self,
        title: str,
        source: str,
        category: PARACategory = PARACategory.RESOURCES,
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> KnowledgeNote:
        """Capture a new knowledge note with deduplication."""
        note = KnowledgeNote(
            title=title,
            source=source,
            category=category,
            content=content or {},
            tags=tags or [],
        )
        note.compute_fingerprint()

        # Dedup by fingerprint
        if note.fingerprint in self._fingerprints:
            for existing in self._notes.values():
                if existing.fingerprint == note.fingerprint:
                    existing.touch()
                    return existing

        self._notes[note.note_id] = note
        self._fingerprints.add(note.fingerprint)
        self._by_category[category].append(note.note_id)

        for tag in note.tags:
            self._by_tag.setdefault(tag, []).append(note.note_id)

        return note

    def get(self, note_id: str) -> KnowledgeNote | None:
        """Retrieve a note by ID."""
        note = self._notes.get(note_id)
        if note:
            note.touch()
        return note

    def notes_by_category(self, category: PARACategory) -> list[KnowledgeNote]:
        """Get all notes in a PARA category."""
        return [
            self._notes[nid]
            for nid in self._by_category.get(category, [])
            if nid in self._notes
        ]

    def notes_by_tag(self, tag: str) -> list[KnowledgeNote]:
        """Get all notes with a specific tag."""
        return [
            self._notes[nid]
            for nid in self._by_tag.get(tag, [])
            if nid in self._notes
        ]

    def move_category(self, note_id: str, new_category: PARACategory) -> bool:
        """Move a note between PARA categories."""
        note = self._notes.get(note_id)
        if not note:
            return False

        old_cat = note.category
        if old_cat == new_category:
            return True

        self._by_category[old_cat] = [
            nid for nid in self._by_category[old_cat] if nid != note_id
        ]
        self._by_category[new_category].append(note_id)
        note.category = new_category
        note.updated_at = time.time()
        return True

    def archive(self, note_id: str) -> bool:
        """Move a note to Archives."""
        result = self.move_category(note_id, PARACategory.ARCHIVES)
        if result:
            note = self._notes.get(note_id)
            if note:
                note.status = KnowledgeStatus.ARCHIVED
        return result

    def search(self, query: str) -> list[KnowledgeNote]:
        """Simple keyword search across note titles and tags."""
        query_lower = query.lower()
        results = []
        for note in self._notes.values():
            if query_lower in note.title.lower() or any(query_lower in tag.lower() for tag in note.tags):
                results.append(note)
        return results

    def category_stats(self) -> dict[str, int]:
        """Count of notes per PARA category."""
        return {
            cat.value: len(ids)
            for cat, ids in self._by_category.items()
        }

    def most_accessed(self, limit: int = 10) -> list[KnowledgeNote]:
        """Return most frequently accessed notes."""
        sorted_notes = sorted(
            self._notes.values(),
            key=lambda n: n.access_count,
            reverse=True,
        )
        return sorted_notes[:limit]


# ── Progressive Summarizer ─────────────────────────────────────


class ProgressiveSummarizer:
    """Implements Tiago Forte's 5-layer Progressive Summarization.

    L1: Raw — Full source text (captured as-is)
    L2: Highlighted — Key passages bolded / highlighted
    L3: Executive — Executive summary paragraph
    L4: Distilled — Core insight atoms (bullet points)
    L5: Remixed — Original synthesis combining multiple sources
    """

    LAYER_ORDER: ClassVar[list[SummarizationLayer]] = [
        SummarizationLayer.L1_RAW,
        SummarizationLayer.L2_HIGHLIGHTED,
        SummarizationLayer.L3_EXECUTIVE,
        SummarizationLayer.L4_DISTILLED,
        SummarizationLayer.L5_REMIXED,
    ]

    # Typical compression ratios per layer
    COMPRESSION_TARGETS: ClassVar[dict[str, float]] = {
        SummarizationLayer.L1_RAW: 1.0,
        SummarizationLayer.L2_HIGHLIGHTED: 0.40,
        SummarizationLayer.L3_EXECUTIVE: 0.15,
        SummarizationLayer.L4_DISTILLED: 0.05,
        SummarizationLayer.L5_REMIXED: 0.10,
    }

    def current_layer(self, note: KnowledgeNote) -> SummarizationLayer:
        """Determine the highest completed summarization layer."""
        for layer in reversed(self.LAYER_ORDER):
            if layer.value in note.layers:
                return layer
        return SummarizationLayer.L1_RAW

    def next_layer(self, note: KnowledgeNote) -> SummarizationLayer | None:
        """Determine the next layer to complete."""
        current = self.current_layer(note)
        idx = self.LAYER_ORDER.index(current)
        if idx + 1 < len(self.LAYER_ORDER):
            return self.LAYER_ORDER[idx + 1]
        return None

    def apply_layer(
        self,
        note: KnowledgeNote,
        layer: SummarizationLayer,
        text: str,
    ) -> DistillationReport:
        """Apply a summarization layer to a note."""
        note.layers[layer.value] = text
        note.status = KnowledgeStatus.DISTILLING
        note.updated_at = time.time()

        # Calculate compression ratio
        raw_len = len(note.layers.get(SummarizationLayer.L1_RAW, "")) or 1
        current_len = len(text) or 1
        ratio = round(current_len / raw_len, 4)

        completed = [
            ly.value for ly in self.LAYER_ORDER if ly.value in note.layers
        ]

        # Mark fully distilled if L4 or L5 reached
        if layer in (SummarizationLayer.L4_DISTILLED, SummarizationLayer.L5_REMIXED):
            note.status = KnowledgeStatus.DISTILLED

        return DistillationReport(
            note_id=note.note_id,
            layers_completed=completed,
            compression_ratio=ratio,
            insight_density=self._insight_density(text),
        )

    def summarize_auto(self, note: KnowledgeNote) -> DistillationReport:
        """Auto-generate the next summarization layer.

        Simulates intelligent extraction by progressively compressing.
        """
        raw_text = note.layers.get(SummarizationLayer.L1_RAW, "")
        if not raw_text:
            raw_text = str(note.content)
            note.layers[SummarizationLayer.L1_RAW] = raw_text

        target_layer = self.next_layer(note)
        if target_layer is None:
            # Already at L5 — return current state
            return DistillationReport(
                note_id=note.note_id,
                layers_completed=list(note.layers.keys()),
                compression_ratio=1.0,
                insight_density=self._insight_density(
                    note.layers.get(SummarizationLayer.L5_REMIXED, raw_text),
                ),
            )

        target_ratio = self.COMPRESSION_TARGETS[target_layer]
        target_len = max(1, int(len(raw_text) * target_ratio))

        # Simulate progressive summarization
        if target_layer == SummarizationLayer.L2_HIGHLIGHTED:
            summary = self._extract_highlights(raw_text, target_len)
        elif target_layer == SummarizationLayer.L3_EXECUTIVE:
            prev = note.layers.get(SummarizationLayer.L2_HIGHLIGHTED, raw_text)
            summary = self._build_executive(prev, target_len)
        elif target_layer == SummarizationLayer.L4_DISTILLED:
            prev = note.layers.get(SummarizationLayer.L3_EXECUTIVE, raw_text)
            summary = self._distill_insights(prev, target_len)
        else:
            prev = note.layers.get(SummarizationLayer.L4_DISTILLED, raw_text)
            summary = self._remix_synthesis(prev, target_len)

        return self.apply_layer(note, target_layer, summary)

    def _extract_highlights(self, text: str, max_len: int) -> str:
        """L2: Extract key sentences (simulate highlighting)."""
        sentences = [s.strip() for s in text.split(".") if s.strip()]
        # Take sentences with highest word count (proxy for information density)
        scored = sorted(sentences, key=len, reverse=True)
        result: list[str] = []
        total = 0
        for sent in scored:
            if total + len(sent) > max_len:
                break
            result.append(sent)
            total += len(sent)
        return ". ".join(result) + "." if result else text[:max_len]

    def _build_executive(self, text: str, max_len: int) -> str:
        """L3: Build executive summary."""
        words = text.split()
        target_words = max(1, max_len // 5)
        return " ".join(words[:target_words])

    def _distill_insights(self, text: str, max_len: int) -> str:
        """L4: Distill to core insight atoms."""
        sentences = [s.strip() for s in text.split(".") if len(s.strip()) > 10]
        atoms = [f"- {s}" for s in sentences[:5]]
        result = "\n".join(atoms)
        return result[:max_len] if len(result) > max_len else result

    def _remix_synthesis(self, text: str, max_len: int) -> str:
        """L5: Original synthesis combining insights."""
        return f"SYNTHESIS: {text[:max_len - 11]}" if len(text) > max_len - 11 else f"SYNTHESIS: {text}"

    def _insight_density(self, text: str) -> float:
        """Score information density of text (0.0 to 1.0)."""
        if not text:
            return 0.0
        words = text.split()
        if not words:
            return 0.0
        unique_words = set(w.lower() for w in words)
        # Lexical diversity as proxy for insight density
        diversity = len(unique_words) / len(words)
        # Bonus for structured content (bullets, synthesis markers)
        structure_bonus = 0.1 if any(
            marker in text for marker in ["- ", "SYNTHESIS:", "KEY:", "INSIGHT:"]
        ) else 0.0
        return min(1.0, round(diversity + structure_bonus, 4))


# ── Intermediate Packet Factory ────────────────────────────────


class PacketFactory:
    """Creates and manages Intermediate Packets — reusable knowledge atoms.

    Intermediate Packets are the "currency" of the Second Brain:
    small, self-contained units that can be recombined for any new project.
    """

    def __init__(self) -> None:
        self._packets: dict[str, IntermediatePacket] = {}
        self._by_type: dict[PacketType, list[str]] = {
            pt: [] for pt in PacketType
        }

    @property
    def total_packets(self) -> int:
        return len(self._packets)

    def create(
        self,
        packet_type: PacketType,
        title: str,
        content: dict[str, Any] | None = None,
        source_notes: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> IntermediatePacket:
        """Create a new Intermediate Packet."""
        packet = IntermediatePacket(
            packet_type=packet_type,
            title=title,
            content=content or {},
            source_notes=source_notes or [],
            tags=tags or [],
        )
        packet.score_quality()

        self._packets[packet.packet_id] = packet
        self._by_type[packet_type].append(packet.packet_id)
        return packet

    def get(self, packet_id: str) -> IntermediatePacket | None:
        return self._packets.get(packet_id)

    def by_type(self, packet_type: PacketType) -> list[IntermediatePacket]:
        """Get all packets of a type."""
        return [
            self._packets[pid]
            for pid in self._by_type.get(packet_type, [])
            if pid in self._packets
        ]

    def reuse(self, packet_id: str) -> IntermediatePacket | None:
        """Mark a packet as reused and return it."""
        packet = self._packets.get(packet_id)
        if packet:
            packet.reuse()
            packet.score_quality()
        return packet

    def top_quality(self, limit: int = 10) -> list[IntermediatePacket]:
        """Return highest quality packets."""
        scored = sorted(
            self._packets.values(),
            key=lambda p: p.quality_score,
            reverse=True,
        )
        return scored[:limit]

    def search(self, query: str) -> list[IntermediatePacket]:
        """Search packets by title and tags."""
        query_lower = query.lower()
        return [
            p for p in self._packets.values()
            if query_lower in p.title.lower()
            or any(query_lower in t.lower() for t in p.tags)
        ]

    def type_stats(self) -> dict[str, int]:
        """Count of packets per type."""
        return {
            pt.value: len(ids)
            for pt, ids in self._by_type.items()
        }


# ── Just-In-Time Retrieval Engine ──────────────────────────────


class RetrievalEngine:
    """Context-aware knowledge retrieval with multiple strategies.

    Implements Just-In-Time information access — surfacing the right
    knowledge at the right moment based on the current task context.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        factory: PacketFactory,
    ) -> None:
        self._store = store
        self._factory = factory

    def retrieve(
        self,
        query: str,
        mode: RetrievalMode = RetrievalMode.KEYWORD,
        limit: int = 10,
    ) -> RetrievalResult:
        """Execute a retrieval using the specified strategy."""
        start = time.time()

        if mode == RetrievalMode.KEYWORD:
            results, scores = self._keyword_search(query, limit)
        elif mode == RetrievalMode.TEMPORAL:
            results, scores = self._temporal_search(query, limit)
        elif mode == RetrievalMode.ASSOCIATIVE:
            results, scores = self._associative_search(query, limit)
        elif mode == RetrievalMode.CONTEXTUAL:
            results, scores = self._contextual_search(query, limit)
        else:
            # Semantic / default — fall back to keyword + boost
            results, scores = self._semantic_search(query, limit)

        elapsed = (time.time() - start) * 1000

        return RetrievalResult(
            query=query,
            mode=mode,
            results=results,
            scores=scores,
            elapsed_ms=round(elapsed, 2),
            total_searched=self._store.total_notes + self._factory.total_packets,
        )

    def _keyword_search(
        self, query: str, limit: int,
    ) -> tuple[list[str], list[float]]:
        """Simple keyword matching with relevance scoring."""
        query_lower = query.lower()
        scored: list[tuple[str, float]] = []

        for note in self._store._notes.values():
            score = 0.0
            if query_lower in note.title.lower():
                score += 0.7
            for tag in note.tags:
                if query_lower in tag.lower():
                    score += 0.2
            if score > 0:
                scored.append((note.note_id, score))

        for packet in self._factory._packets.values():
            score = 0.0
            if query_lower in packet.title.lower():
                score += 0.6
            for tag in packet.tags:
                if query_lower in tag.lower():
                    score += 0.15
            if score > 0:
                scored.append((packet.packet_id, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]
        return [item_id for item_id, _ in top], [s for _, s in top]

    def _temporal_search(
        self, query: str, limit: int,
    ) -> tuple[list[str], list[float]]:
        """Recency-weighted retrieval."""
        now = time.time()
        scored: list[tuple[str, float]] = []

        for note in self._store._notes.values():
            age = now - note.updated_at
            recency = 1.0 / (1.0 + age / 3600)  # Decay over hours
            keyword_match = 0.3 if query.lower() in note.title.lower() else 0.0
            scored.append((note.note_id, round(recency + keyword_match, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]
        return [item_id for item_id, _ in top], [s for _, s in top]

    def _associative_search(
        self, query: str, limit: int,
    ) -> tuple[list[str], list[float]]:
        """Follow connection graph from matching notes."""
        seed_notes = self._store.search(query)
        if not seed_notes:
            return [], []

        visited: set[str] = set()
        scored: list[tuple[str, float]] = []

        for note in seed_notes:
            if note.note_id not in visited:
                visited.add(note.note_id)
                scored.append((note.note_id, 1.0))

            for conn_id in note.connections:
                if conn_id not in visited:
                    visited.add(conn_id)
                    conn = self._store.get(conn_id)
                    if conn:
                        scored.append((conn_id, 0.6))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]
        return [item_id for item_id, _ in top], [s for _, s in top]

    def _contextual_search(
        self, query: str, limit: int,
    ) -> tuple[list[str], list[float]]:
        """Context-aware retrieval combining keyword + recency + access frequency."""
        now = time.time()
        scored: list[tuple[str, float]] = []

        for note in self._store._notes.values():
            keyword_score = 0.0
            if query.lower() in note.title.lower():
                keyword_score = 0.4
            elif any(query.lower() in t.lower() for t in note.tags):
                keyword_score = 0.2

            recency = 0.3 / (1.0 + (now - note.updated_at) / 3600)
            frequency = min(0.3, note.access_count * 0.03)
            total = round(keyword_score + recency + frequency, 4)
            if total > 0.05:
                scored.append((note.note_id, total))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]
        return [item_id for item_id, _ in top], [s for _, s in top]

    def _semantic_search(
        self, query: str, limit: int,
    ) -> tuple[list[str], list[float]]:
        """Simulated semantic search using character n-gram similarity."""
        query_lower = query.lower()
        scored: list[tuple[str, float]] = []

        for note in self._store._notes.values():
            sim = self._ngram_similarity(query_lower, note.title.lower())
            tag_sim = max(
                (self._ngram_similarity(query_lower, t.lower()) for t in note.tags),
                default=0.0,
            )
            total = max(sim, tag_sim)
            if total > 0.1:
                scored.append((note.note_id, round(total, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:limit]
        return [item_id for item_id, _ in top], [s for _, s in top]

    @staticmethod
    def _ngram_similarity(text_a: str, text_b: str, n: int = 3) -> float:
        """Character n-gram Jaccard similarity."""
        if not text_a or not text_b:
            return 0.0

        def ngrams(text: str) -> set[str]:
            return {text[i : i + n] for i in range(max(0, len(text) - n + 1))}

        set_a = ngrams(text_a)
        set_b = ngrams(text_b)
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a & set_b)
        union = len(set_a | set_b)
        return intersection / union if union > 0 else 0.0


# ── CODE Workflow Orchestrator ─────────────────────────────────


class CODEWorkflow:
    """Orchestrates the Capture → Organize → Distill → Express pipeline.

    Each knowledge item flows through all four stages, with each stage
    enriching the item's value and actionability.
    """

    def __init__(
        self,
        store: KnowledgeStore,
        summarizer: ProgressiveSummarizer,
        factory: PacketFactory,
    ) -> None:
        self._store = store
        self._summarizer = summarizer
        self._factory = factory
        self._pipeline_runs: int = 0

    @property
    def pipeline_runs(self) -> int:
        return self._pipeline_runs

    def capture(
        self,
        title: str,
        source: str,
        raw_text: str = "",
        content: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Stage 1: Capture — ingest raw information."""
        note = self._store.ingest(
            title=title,
            source=source,
            content=content or {},
            tags=tags or [],
        )

        # Store raw text as L1
        if raw_text:
            note.layers[SummarizationLayer.L1_RAW] = raw_text

        return {
            "stage": CODEStage.CAPTURE,
            "note_id": note.note_id,
            "title": note.title,
            "category": note.category,
            "fingerprint": note.fingerprint,
        }

    def organize(
        self,
        note_id: str,
        category: PARACategory,
        tags: list[str] | None = None,
        connections: list[str] | None = None,
    ) -> dict[str, Any]:
        """Stage 2: Organize — place into PARA and establish connections."""
        note = self._store.get(note_id)
        if not note:
            return {"stage": CODEStage.ORGANIZE, "error": "note_not_found"}

        self._store.move_category(note_id, category)
        if tags:
            for tag in tags:
                if tag not in note.tags:
                    note.tags.append(tag)
                    self._store._by_tag.setdefault(tag, []).append(note_id)

        if connections:
            for conn in connections:
                if conn not in note.connections:
                    note.connections.append(conn)

        note.status = KnowledgeStatus.ORGANIZED
        note.updated_at = time.time()

        return {
            "stage": CODEStage.ORGANIZE,
            "note_id": note_id,
            "category": category,
            "tags": note.tags,
            "connections": note.connections,
        }

    def distill(self, note_id: str) -> dict[str, Any]:
        """Stage 3: Distill — apply progressive summarization."""
        note = self._store.get(note_id)
        if not note:
            return {"stage": CODEStage.DISTILL, "error": "note_not_found"}

        report = self._summarizer.summarize_auto(note)

        return {
            "stage": CODEStage.DISTILL,
            "note_id": note_id,
            "layers_completed": report.layers_completed,
            "compression_ratio": report.compression_ratio,
            "insight_density": report.insight_density,
            "current_layer": self._summarizer.current_layer(note),
        }

    def express(
        self,
        note_ids: list[str],
        title: str = "",
        output_format: str = "report",
        audience: str = "council",
    ) -> dict[str, Any]:
        """Stage 4: Express — create and share output from distilled knowledge."""
        packets_created: list[str] = []
        source_content: list[str] = []

        for nid in note_ids:
            note = self._store.get(nid)
            if not note:
                continue

            # Get highest available layer
            best_text = ""
            for layer in reversed(ProgressiveSummarizer.LAYER_ORDER):
                if layer.value in note.layers:
                    best_text = note.layers[layer.value]
                    break

            if not best_text:
                best_text = str(note.content)

            source_content.append(best_text)

            # Create intermediate packet from note
            packet = self._factory.create(
                packet_type=PacketType.FINAL_DELIVERABLE,
                title=f"Express: {note.title}",
                content={"text": best_text, "source_note": nid},
                source_notes=[nid],
                tags=note.tags,
            )
            packets_created.append(packet.packet_id)

            note.status = KnowledgeStatus.EXPRESSED
            note.updated_at = time.time()

        output = ExpressionOutput(
            title=title or f"Synthesis of {len(note_ids)} notes",
            format=output_format,
            source_packets=packets_created,
            content={
                "sections": source_content,
                "note_count": len(note_ids),
            },
            audience=audience,
            confidence=min(1.0, 0.5 + 0.1 * len(source_content)),
        )

        return {
            "stage": CODEStage.EXPRESS,
            "output_id": output.output_id,
            "title": output.title,
            "format": output.format,
            "packets_created": len(packets_created),
            "confidence": output.confidence,
        }

    def full_pipeline(
        self,
        title: str,
        source: str,
        raw_text: str,
        category: PARACategory = PARACategory.RESOURCES,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run the full CODE pipeline: Capture → Organize → Distill → Express."""
        self._pipeline_runs += 1

        # Capture
        cap = self.capture(title, source, raw_text=raw_text, tags=tags)
        note_id = cap["note_id"]

        # Organize
        org = self.organize(note_id, category, tags=tags)

        # Distill all layers
        distill_results: list[dict[str, Any]] = []
        for _ in range(5):  # Up to 5 layers
            dist = self.distill(note_id)
            distill_results.append(dist)
            if dist.get("current_layer") == SummarizationLayer.L5_REMIXED:
                break

        # Express
        expr = self.express([note_id], title=f"Pipeline: {title}")

        return {
            "pipeline_run": self._pipeline_runs,
            "capture": cap,
            "organize": org,
            "distill_layers": len(distill_results),
            "express": expr,
            "note_id": note_id,
        }


# ── Connection Graph ───────────────────────────────────────────


class ConnectionGraph:
    """Knowledge connection graph for associative memory.

    Tracks relationships between notes, enabling serendipitous
    discovery and cross-domain insight generation.
    """

    def __init__(self) -> None:
        self._edges: dict[str, set[str]] = {}
        self._edge_weights: dict[tuple[str, str], float] = {}

    @property
    def node_count(self) -> int:
        return len(self._edges)

    @property
    def edge_count(self) -> int:
        return len(self._edge_weights)

    def connect(
        self, note_a: str, note_b: str, weight: float = 1.0,
    ) -> None:
        """Create a bidirectional connection between two notes."""
        self._edges.setdefault(note_a, set()).add(note_b)
        self._edges.setdefault(note_b, set()).add(note_a)
        key = tuple(sorted([note_a, note_b]))
        self._edge_weights[(key[0], key[1])] = weight

    def neighbors(self, note_id: str) -> list[str]:
        """Get directly connected notes."""
        return list(self._edges.get(note_id, set()))

    def weight(self, note_a: str, note_b: str) -> float:
        """Get connection weight between two notes."""
        key = tuple(sorted([note_a, note_b]))
        return self._edge_weights.get((key[0], key[1]), 0.0)

    def clusters(self) -> list[set[str]]:
        """Find connected components (knowledge clusters)."""
        visited: set[str] = set()
        components: list[set[str]] = []

        for node in self._edges:
            if node in visited:
                continue
            component: set[str] = set()
            queue = [node]
            while queue:
                current = queue.pop(0)
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                for neighbor in self._edges.get(current, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)
            components.append(component)

        return components

    def hub_score(self, note_id: str) -> float:
        """Score how "hub-like" a note is (0.0 to 1.0)."""
        connections = len(self._edges.get(note_id, set()))
        if self.node_count <= 1:
            return 0.0
        return min(1.0, connections / max(1, self.node_count - 1))

    def top_hubs(self, limit: int = 5) -> list[tuple[str, float]]:
        """Return top hub nodes by connectivity."""
        scored = [
            (nid, self.hub_score(nid))
            for nid in self._edges
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:limit]

    def path_exists(self, source: str, target: str) -> bool:
        """Check if a path exists between two notes."""
        if source not in self._edges or target not in self._edges:
            return False

        visited: set[str] = set()
        queue = [source]
        while queue:
            current = queue.pop(0)
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            for neighbor in self._edges.get(current, set()):
                if neighbor not in visited:
                    queue.append(neighbor)
        return False

    def summary(self) -> dict[str, Any]:
        """Graph summary statistics."""
        cluster_list = self.clusters()
        return {
            "nodes": self.node_count,
            "edges": self.edge_count,
            "clusters": len(cluster_list),
            "largest_cluster": max(len(c) for c in cluster_list) if cluster_list else 0,
            "top_hubs": self.top_hubs(3),
        }


# ── Second Brain Engine (Unified) ──────────────────────────────


class SecondBrainEngine:
    """Unified Second Brain — the complete Tiago Forte framework.

    Combines all components into a single knowledge management system:
    - KnowledgeStore (PARA organization)
    - ProgressiveSummarizer (5-layer distillation)
    - PacketFactory (Intermediate Packets)
    - RetrievalEngine (Just-In-Time access)
    - CODEWorkflow (Capture → Organize → Distill → Express)
    - ConnectionGraph (Associative memory)

    Agent #28: CORTEX (sb) — "Your mind's cortex, externalized."
    """

    # Tiago Forte's 12 Favorite Problems (adapted for the council)
    TWELVE_PROBLEMS: ClassVar[list[str]] = [
        "How can we predict outcomes with higher confidence?",
        "What signals are we missing in our data pipeline?",
        "How do we reduce noise and amplify true signal?",
        "What cross-domain connections reveal hidden patterns?",
        "How do we make knowledge actionable faster?",
        "What are the second-order effects we are not seeing?",
        "How do we preserve institutional knowledge across agents?",
        "What mental models drive the best predictions?",
        "How do we bridge the gap between data and wisdom?",
        "What assumptions need to be challenged right now?",
        "How can we compress learning cycles?",
        "What would a 10x improvement look like?",
    ]

    def __init__(self) -> None:
        self._store = KnowledgeStore()
        self._summarizer = ProgressiveSummarizer()
        self._factory = PacketFactory()
        self._retrieval = RetrievalEngine(self._store, self._factory)
        self._workflow = CODEWorkflow(self._store, self._summarizer, self._factory)
        self._graph = ConnectionGraph()
        self._initialized = False
        self._cycle_count = 0

    @property
    def initialized(self) -> bool:
        return self._initialized

    def initialize(self) -> None:
        """Warm up the Second Brain with foundation knowledge."""
        self._initialized = True
        self._seed_foundation()

    def _seed_foundation(self) -> None:
        """Seed the brain with foundational meta-knowledge."""
        foundations = [
            ("PARA Method", "tiago_forte", PARACategory.RESOURCES,
             "Projects are time-bound goals. Areas are ongoing responsibilities. "
             "Resources are topics of interest. Archives are inactive items."),
            ("CODE Workflow", "tiago_forte", PARACategory.RESOURCES,
             "Capture widely. Organize for actionability. Distill progressively. "
             "Express to create value."),
            ("Progressive Summarization", "tiago_forte", PARACategory.RESOURCES,
             "Layer 1: Raw notes. Layer 2: Bold key passages. Layer 3: Executive summary. "
             "Layer 4: Core insight atoms. Layer 5: Original remix."),
            ("Intermediate Packets", "tiago_forte", PARACategory.RESOURCES,
             "Break work into reusable atoms. Every project produces packets that "
             "fuel future projects. Reuse is the superpower."),
            ("Twelve Favorite Problems", "richard_feynman", PARACategory.AREAS,
             "Keep twelve open questions. Every new piece of information is tested "
             "against these problems. Serendipity emerges."),
        ]

        for title, source, category, raw_text in foundations:
            cap = self._workflow.capture(title, source, raw_text=raw_text)
            note_id = cap["note_id"]
            self._workflow.organize(note_id, category, tags=["foundation", "methodology"])

    # ── Public API ─────────────────────────────────────────────

    def capture_knowledge(
        self,
        title: str,
        source: str,
        raw_text: str = "",
        content: dict[str, Any] | None = None,
        category: PARACategory = PARACategory.RESOURCES,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ingest new knowledge into the Second Brain."""
        result = self._workflow.capture(
            title, source, raw_text=raw_text, content=content, tags=tags,
        )
        note_id = result["note_id"]
        self._workflow.organize(note_id, category, tags=tags)
        return {**result, "status": "captured"}

    def distill_note(self, note_id: str) -> dict[str, Any]:
        """Apply progressive summarization to a note."""
        result = self._workflow.distill(note_id)
        return {**result, "status": "distilled"}

    def express_knowledge(
        self,
        note_ids: list[str],
        title: str = "",
        output_format: str = "report",
    ) -> dict[str, Any]:
        """Create expressed output from distilled knowledge."""
        result = self._workflow.express(note_ids, title=title, output_format=output_format)
        return {**result, "status": "expressed"}

    def full_pipeline(
        self,
        title: str,
        source: str,
        raw_text: str,
        category: PARACategory = PARACategory.RESOURCES,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run full CODE pipeline: Capture → Organize → Distill → Express."""
        result = self._workflow.full_pipeline(title, source, raw_text, category, tags)
        return {**result, "status": "pipeline_complete"}

    def retrieve(
        self,
        query: str,
        mode: RetrievalMode = RetrievalMode.KEYWORD,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Just-In-Time knowledge retrieval."""
        result = self._retrieval.retrieve(query, mode, limit)
        return {
            "query": result.query,
            "mode": result.mode,
            "hits": result.hit_count,
            "results": result.results,
            "scores": result.scores,
            "elapsed_ms": result.elapsed_ms,
            "total_searched": result.total_searched,
            "status": "retrieved",
        }

    def create_packet(
        self,
        packet_type: PacketType,
        title: str,
        content: dict[str, Any] | None = None,
        source_notes: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create an Intermediate Packet."""
        packet = self._factory.create(
            packet_type, title, content, source_notes, tags,
        )
        return {
            "packet_id": packet.packet_id,
            "type": packet.packet_type,
            "title": packet.title,
            "quality_score": packet.quality_score,
            "status": "packet_created",
        }

    def connect_notes(
        self, note_a: str, note_b: str, weight: float = 1.0,
    ) -> dict[str, Any]:
        """Create a connection between two knowledge notes."""
        self._graph.connect(note_a, note_b, weight)

        # Also update note connections
        note_obj_a = self._store.get(note_a)
        note_obj_b = self._store.get(note_b)
        if note_obj_a and note_b not in note_obj_a.connections:
            note_obj_a.connections.append(note_b)
        if note_obj_b and note_a not in note_obj_b.connections:
            note_obj_b.connections.append(note_a)

        return {
            "connected": [note_a, note_b],
            "weight": weight,
            "graph_nodes": self._graph.node_count,
            "graph_edges": self._graph.edge_count,
            "status": "connected",
        }

    def test_against_problems(self, knowledge: str) -> dict[str, Any]:
        """Test new knowledge against the Twelve Favorite Problems."""
        matches: list[dict[str, Any]] = []
        knowledge_lower = knowledge.lower()

        for idx, problem in enumerate(self.TWELVE_PROBLEMS):
            problem_lower = problem.lower()
            # Check word overlap
            knowledge_words = set(knowledge_lower.split())
            problem_words = set(problem_lower.split())
            overlap = knowledge_words & problem_words
            # Remove common words
            common = {"how", "can", "we", "do", "the", "a", "is", "are", "what", "that"}
            meaningful_overlap = overlap - common

            if meaningful_overlap:
                relevance = min(1.0, len(meaningful_overlap) * 0.25)
                matches.append({
                    "problem_index": idx,
                    "problem": problem,
                    "matching_words": sorted(meaningful_overlap),
                    "relevance": round(relevance, 2),
                })

        return {
            "knowledge_tested": knowledge[:100],
            "problems_matched": len(matches),
            "matches": sorted(matches, key=lambda m: m["relevance"], reverse=True),
            "status": "problems_tested",
        }

    def run_cycle(self) -> dict[str, Any]:
        """Run a full Second Brain maintenance cycle.

        - Scan for un-distilled notes and advance them
        - Identify disconnected knowledge and suggest connections
        - Score packet quality
        - Generate system health metrics
        """
        self._cycle_count += 1

        # Distill undistilled notes
        distilled_count = 0
        for note in self._store._notes.values():
            if note.status in (
                KnowledgeStatus.CAPTURED,
                KnowledgeStatus.ORGANIZED,
                KnowledgeStatus.DISTILLING,
            ):
                self._summarizer.summarize_auto(note)
                distilled_count += 1

        # Score all packets
        for packet in self._factory._packets.values():
            packet.score_quality()

        # Graph health
        graph_stats = self._graph.summary()

        return {
            "cycle": self._cycle_count,
            "notes_distilled": distilled_count,
            "total_notes": self._store.total_notes,
            "total_packets": self._factory.total_packets,
            "category_stats": self._store.category_stats(),
            "packet_type_stats": self._factory.type_stats(),
            "graph": graph_stats,
            "status": "cycle_complete",
        }

    def operational_readiness(self) -> dict[str, Any]:
        """Assess operational readiness of the Second Brain."""
        category_stats = self._store.category_stats()
        total = self._store.total_notes

        # Readiness scoring
        has_projects = category_stats.get("projects", 0) > 0
        has_areas = category_stats.get("areas", 0) > 0
        has_resources = category_stats.get("resources", 0) > 0
        has_packets = self._factory.total_packets > 0
        has_connections = self._graph.edge_count > 0

        readiness_checks = {
            "initialized": self._initialized,
            "has_projects": has_projects,
            "has_areas": has_areas,
            "has_resources": has_resources,
            "has_packets": has_packets,
            "has_connections": has_connections,
        }

        score = sum(1 for v in readiness_checks.values() if v) / len(readiness_checks)

        return {
            "readiness_score": round(score, 2),
            "checks": readiness_checks,
            "total_notes": total,
            "total_packets": self._factory.total_packets,
            "graph_nodes": self._graph.node_count,
            "graph_edges": self._graph.edge_count,
            "pipeline_runs": self._workflow.pipeline_runs,
            "cycles_completed": self._cycle_count,
        }

    def score_methodology(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Score adherence to Tiago Forte's Second Brain methodology."""
        ctx = context or {}

        # PARA balance — are all categories used?
        cat_stats = self._store.category_stats()
        para_used = sum(1 for v in cat_stats.values() if v > 0)
        para_score = para_used / 4.0

        # CODE completeness — how many notes have gone through full pipeline?
        expressed_count = sum(
            1 for note in self._store._notes.values()
            if note.status == KnowledgeStatus.EXPRESSED
        )
        code_score = (
            min(1.0, expressed_count / max(1, self._store.total_notes))
            if self._store.total_notes > 0
            else 0.0
        )

        # Progressive Summarization depth
        l4_plus = sum(
            1 for note in self._store._notes.values()
            if SummarizationLayer.L4_DISTILLED in note.layers
            or SummarizationLayer.L5_REMIXED in note.layers
        )
        distill_score = (
            min(1.0, l4_plus / max(1, self._store.total_notes))
            if self._store.total_notes > 0
            else 0.0
        )

        # Intermediate Packets — reuse rate
        reused = sum(
            1 for p in self._factory._packets.values() if p.reuse_count > 0
        )
        packet_score = (
            min(1.0, reused / max(1, self._factory.total_packets))
            if self._factory.total_packets > 0
            else 0.0
        )

        # Connection density
        connection_score = min(
            1.0,
            self._graph.edge_count / max(1, self._store.total_notes),
        )

        # Context bonus (if caller provides domain hints)
        context_bonus = 0.05 if ctx.get("domain") else 0.0

        composite = round(
            (para_score + code_score + distill_score + packet_score + connection_score) / 5.0
            + context_bonus,
            4,
        )

        return {
            "para_score": round(para_score, 4),
            "code_score": round(code_score, 4),
            "distill_score": round(distill_score, 4),
            "packet_reuse_score": round(packet_score, 4),
            "connection_score": round(connection_score, 4),
            "context_bonus": context_bonus,
            "composite": min(1.0, composite),
            "status": "methodology_scored",
        }
