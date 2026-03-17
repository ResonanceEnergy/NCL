"""Tests for the Second Brain Knowledge Engine (Agent #28 — CORTEX).

Covers all components:
- PARACategory / CODEStage / SummarizationLayer / PacketType / RetrievalMode / KnowledgeStatus enums
- KnowledgeNote / IntermediatePacket / RetrievalResult / DistillationReport / ExpressionOutput data contracts
- KnowledgeStore (PARA organization, dedup, search, archive, stats)
- ProgressiveSummarizer (5-layer distillation pipeline)
- PacketFactory (intermediate packets, quality scoring, reuse)
- RetrievalEngine (5 retrieval strategies)
- CODEWorkflow (full pipeline orchestration)
- ConnectionGraph (associative memory, clusters, hubs)
- SecondBrainEngine (unified API, methodology scoring, operational readiness)
- CortexAgent integration (#28 in expansion pack)
- Event system integration (6 new EventTypes)
- Agent roster integration (28 total agents)
"""

from __future__ import annotations

# ── Enum Tests ─────────────────────────────────────────────────


class TestPARACategory:
    def test_all_categories(self):
        from ncl_agency_runtime.fpc.second_brain import PARACategory
        assert len(PARACategory) == 4
        assert set(PARACategory) == {
            PARACategory.PROJECTS,
            PARACategory.AREAS,
            PARACategory.RESOURCES,
            PARACategory.ARCHIVES,
        }

    def test_values(self):
        from ncl_agency_runtime.fpc.second_brain import PARACategory
        assert PARACategory.PROJECTS == "projects"
        assert PARACategory.AREAS == "areas"
        assert PARACategory.RESOURCES == "resources"
        assert PARACategory.ARCHIVES == "archives"


class TestCODEStage:
    def test_all_stages(self):
        from ncl_agency_runtime.fpc.second_brain import CODEStage
        assert len(CODEStage) == 4
        assert set(CODEStage) == {
            CODEStage.CAPTURE,
            CODEStage.ORGANIZE,
            CODEStage.DISTILL,
            CODEStage.EXPRESS,
        }


class TestSummarizationLayer:
    def test_five_layers(self):
        from ncl_agency_runtime.fpc.second_brain import SummarizationLayer
        assert len(SummarizationLayer) == 5

    def test_layer_order(self):
        from ncl_agency_runtime.fpc.second_brain import SummarizationLayer
        layers = list(SummarizationLayer)
        assert layers[0] == SummarizationLayer.L1_RAW
        assert layers[-1] == SummarizationLayer.L5_REMIXED


class TestPacketType:
    def test_all_types(self):
        from ncl_agency_runtime.fpc.second_brain import PacketType
        assert len(PacketType) == 6
        assert PacketType.DISTILLED_NOTE == "distilled_note"
        assert PacketType.FINAL_DELIVERABLE == "final_deliverable"


class TestRetrievalMode:
    def test_all_modes(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        assert len(RetrievalMode) == 5
        assert RetrievalMode.KEYWORD == "keyword"
        assert RetrievalMode.CONTEXTUAL == "contextual"


class TestKnowledgeStatus:
    def test_all_statuses(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStatus
        assert len(KnowledgeStatus) == 6
        assert KnowledgeStatus.CAPTURED == "captured"
        assert KnowledgeStatus.ARCHIVED == "archived"


# ── Data Contract Tests ────────────────────────────────────────


class TestKnowledgeNote:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            KnowledgeStatus,
            PARACategory,
        )
        note = KnowledgeNote()
        assert note.note_id
        assert note.category == PARACategory.RESOURCES
        assert note.status == KnowledgeStatus.CAPTURED
        assert note.access_count == 0

    def test_touch(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeNote
        note = KnowledgeNote()
        assert note.access_count == 0
        note.touch()
        assert note.access_count == 1
        note.touch()
        assert note.access_count == 2

    def test_fingerprint(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeNote
        note = KnowledgeNote(title="Test", source="unit_test")
        fp = note.compute_fingerprint()
        assert len(fp) == 16
        assert note.fingerprint == fp
        # Same input → same fingerprint
        note2 = KnowledgeNote(title="Test", source="unit_test")
        assert note2.compute_fingerprint() == fp

    def test_different_fingerprints(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeNote
        n1 = KnowledgeNote(title="Alpha", source="src_a")
        n2 = KnowledgeNote(title="Beta", source="src_b")
        assert n1.compute_fingerprint() != n2.compute_fingerprint()


class TestIntermediatePacket:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.second_brain import (
            IntermediatePacket,
            PacketType,
        )
        pkt = IntermediatePacket()
        assert pkt.packet_type == PacketType.DISTILLED_NOTE
        assert pkt.reuse_count == 0
        assert pkt.quality_score == 0.0

    def test_reuse(self):
        from ncl_agency_runtime.fpc.second_brain import IntermediatePacket
        pkt = IntermediatePacket()
        pkt.reuse()
        assert pkt.reuse_count == 1
        pkt.reuse()
        assert pkt.reuse_count == 2

    def test_quality_score(self):
        from ncl_agency_runtime.fpc.second_brain import IntermediatePacket
        pkt = IntermediatePacket(
            source_notes=["n1", "n2", "n3"],
            content={"key": "val"},
        )
        pkt.reuse_count = 3
        score = pkt.score_quality()
        assert 0.0 < score <= 1.0
        assert pkt.quality_score == score


class TestRetrievalResult:
    def test_hit_count(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalResult
        rr = RetrievalResult(results=["a", "b", "c"])
        assert rr.hit_count == 3

    def test_empty(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalResult
        rr = RetrievalResult()
        assert rr.hit_count == 0


class TestDistillationReport:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.second_brain import DistillationReport
        dr = DistillationReport()
        assert dr.report_id
        assert dr.compression_ratio == 0.0


class TestExpressionOutput:
    def test_defaults(self):
        from ncl_agency_runtime.fpc.second_brain import ExpressionOutput
        eo = ExpressionOutput()
        assert eo.format == "report"
        assert eo.audience == "council"
        assert eo.confidence == 0.5


# ── KnowledgeStore Tests ───────────────────────────────────────


class TestKnowledgeStore:
    def test_ingest(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        note = store.ingest("Test Note", "unit_test", tags=["alpha"])
        assert store.total_notes == 1
        assert note.title == "Test Note"
        assert note.fingerprint

    def test_deduplication(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        n1 = store.ingest("Same Title", "same_source")
        n2 = store.ingest("Same Title", "same_source")
        assert store.total_notes == 1
        assert n1.note_id == n2.note_id
        assert n2.access_count >= 1  # Touch increments

    def test_get(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        note = store.ingest("Findme", "src")
        found = store.get(note.note_id)
        assert found is not None
        assert found.title == "Findme"

    def test_get_missing(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        assert store.get("nonexistent") is None

    def test_notes_by_category(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PARACategory,
        )
        store = KnowledgeStore()
        store.ingest("P1", "src", category=PARACategory.PROJECTS)
        store.ingest("P2", "src", category=PARACategory.PROJECTS)
        store.ingest("A1", "src", category=PARACategory.AREAS)
        assert len(store.notes_by_category(PARACategory.PROJECTS)) == 2
        assert len(store.notes_by_category(PARACategory.AREAS)) == 1

    def test_notes_by_tag(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        store.ingest("Tagged", "src", tags=["important", "review"])
        store.ingest("Other", "src", tags=["review"])
        assert len(store.notes_by_tag("review")) == 2
        assert len(store.notes_by_tag("important")) == 1

    def test_move_category(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PARACategory,
        )
        store = KnowledgeStore()
        note = store.ingest("Move Me", "src", category=PARACategory.RESOURCES)
        assert store.move_category(note.note_id, PARACategory.PROJECTS)
        assert note.category == PARACategory.PROJECTS
        assert len(store.notes_by_category(PARACategory.PROJECTS)) == 1
        assert len(store.notes_by_category(PARACategory.RESOURCES)) == 0

    def test_move_category_nonexistent(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PARACategory,
        )
        store = KnowledgeStore()
        assert not store.move_category("fake_id", PARACategory.PROJECTS)

    def test_archive(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStatus,
            KnowledgeStore,
            PARACategory,
        )
        store = KnowledgeStore()
        note = store.ingest("Archive Me", "src")
        assert store.archive(note.note_id)
        assert note.category == PARACategory.ARCHIVES
        assert note.status == KnowledgeStatus.ARCHIVED

    def test_search(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        store.ingest("Machine Learning Basics", "book", tags=["ml"])
        store.ingest("Deep Learning Advanced", "paper", tags=["dl"])
        store.ingest("Cooking Recipes", "web")
        results = store.search("learning")
        assert len(results) == 2

    def test_search_by_tag(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        store.ingest("Note1", "src", tags=["quantum"])
        results = store.search("quantum")
        assert len(results) == 1

    def test_category_stats(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PARACategory,
        )
        store = KnowledgeStore()
        store.ingest("P1", "s", category=PARACategory.PROJECTS)
        store.ingest("R1", "s", category=PARACategory.RESOURCES)
        store.ingest("R2", "s2", category=PARACategory.RESOURCES)
        stats = store.category_stats()
        assert stats["projects"] == 1
        assert stats["resources"] == 2
        assert stats["areas"] == 0

    def test_most_accessed(self):
        from ncl_agency_runtime.fpc.second_brain import KnowledgeStore
        store = KnowledgeStore()
        n1 = store.ingest("Popular", "s")
        store.ingest("Unpopular", "s2")
        for _ in range(5):
            store.get(n1.note_id)
        top = store.most_accessed(limit=1)
        assert len(top) == 1
        assert top[0].note_id == n1.note_id


# ── ProgressiveSummarizer Tests ────────────────────────────────


class TestProgressiveSummarizer:
    def test_current_layer_empty(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote()
        assert ps.current_layer(note) == SummarizationLayer.L1_RAW

    def test_next_layer(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote()
        note.layers[SummarizationLayer.L1_RAW] = "raw text"
        assert ps.next_layer(note) == SummarizationLayer.L2_HIGHLIGHTED

    def test_next_layer_fully_summarized(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote()
        for layer in SummarizationLayer:
            note.layers[layer.value] = f"text for {layer}"
        assert ps.next_layer(note) is None

    def test_apply_layer(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            KnowledgeStatus,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote()
        note.layers[SummarizationLayer.L1_RAW] = "Full raw text here with many details about the topic."
        report = ps.apply_layer(note, SummarizationLayer.L2_HIGHLIGHTED, "Key passages highlighted.")
        assert SummarizationLayer.L2_HIGHLIGHTED in note.layers
        assert note.status == KnowledgeStatus.DISTILLING
        assert report.compression_ratio > 0

    def test_apply_l4_marks_distilled(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            KnowledgeStatus,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote()
        note.layers[SummarizationLayer.L1_RAW] = "raw text for testing"
        ps.apply_layer(note, SummarizationLayer.L4_DISTILLED, "- Core insight")
        assert note.status == KnowledgeStatus.DISTILLED

    def test_summarize_auto(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote(content={"text": "Long text with multiple points."})
        note.layers[SummarizationLayer.L1_RAW] = (
            "This is a long document about machine learning. "
            "It covers supervised and unsupervised techniques. "
            "Neural networks are particularly effective for pattern recognition. "
            "Deep learning has revolutionized computer vision and NLP. "
            "Transfer learning reduces the need for labeled data."
        )
        report = ps.summarize_auto(note)
        assert report.note_id == note.note_id
        assert len(report.layers_completed) > 0

    def test_summarize_auto_seeds_l1(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote(content={"data": "some content"})
        # No L1_RAW — should auto-seed from content
        ps.summarize_auto(note)
        assert SummarizationLayer.L1_RAW in note.layers

    def test_full_summarization_pipeline(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeNote,
            ProgressiveSummarizer,
            SummarizationLayer,
        )
        ps = ProgressiveSummarizer()
        note = KnowledgeNote()
        note.layers[SummarizationLayer.L1_RAW] = (
            "Quantum computing leverages quantum mechanical phenomena. "
            "Superposition allows qubits to exist in multiple states. "
            "Entanglement enables correlated measurements across distance. "
            "Quantum algorithms like Shor's can factor large numbers. "
            "Grover's algorithm provides quadratic speedup for search."
        )
        for _ in range(4):
            ps.summarize_auto(note)
        # Should have progressed through layers
        assert len(note.layers) >= 4

    def test_insight_density(self):
        from ncl_agency_runtime.fpc.second_brain import ProgressiveSummarizer
        ps = ProgressiveSummarizer()
        assert ps._insight_density("") == 0.0
        density = ps._insight_density("- Core insight about prediction. KEY: accuracy matters.")
        assert density > 0.0

    def test_compression_targets(self):
        from ncl_agency_runtime.fpc.second_brain import ProgressiveSummarizer
        assert len(ProgressiveSummarizer.COMPRESSION_TARGETS) == 5
        assert ProgressiveSummarizer.COMPRESSION_TARGETS["layer_1_raw"] == 1.0


# ── PacketFactory Tests ────────────────────────────────────────


class TestPacketFactory:
    def test_create(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        pkt = factory.create(PacketType.DISTILLED_NOTE, "Test Packet")
        assert factory.total_packets == 1
        assert pkt.title == "Test Packet"

    def test_get(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        pkt = factory.create(PacketType.TEMPLATE, "Template")
        found = factory.get(pkt.packet_id)
        assert found is not None
        assert found.title == "Template"

    def test_get_missing(self):
        from ncl_agency_runtime.fpc.second_brain import PacketFactory
        factory = PacketFactory()
        assert factory.get("nonexistent") is None

    def test_by_type(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        factory.create(PacketType.CHECKLIST, "CL1")
        factory.create(PacketType.CHECKLIST, "CL2")
        factory.create(PacketType.TEMPLATE, "T1")
        checklists = factory.by_type(PacketType.CHECKLIST)
        assert len(checklists) == 2

    def test_reuse_tracking(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        pkt = factory.create(PacketType.OUTTAKE, "Reusable")
        factory.reuse(pkt.packet_id)
        factory.reuse(pkt.packet_id)
        assert pkt.reuse_count == 2
        assert pkt.quality_score > 0

    def test_reuse_nonexistent(self):
        from ncl_agency_runtime.fpc.second_brain import PacketFactory
        factory = PacketFactory()
        assert factory.reuse("fake_id") is None

    def test_top_quality(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        factory.create(PacketType.DISTILLED_NOTE, "Low", source_notes=["n1"])
        p2 = factory.create(
            PacketType.FINAL_DELIVERABLE, "High",
            source_notes=["n1", "n2", "n3", "n4", "n5"],
            content={"a": 1, "b": 2},
        )
        for _ in range(5):
            factory.reuse(p2.packet_id)
        top = factory.top_quality(limit=1)
        assert len(top) == 1
        assert top[0].packet_id == p2.packet_id

    def test_search(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        factory.create(PacketType.DISTILLED_NOTE, "ML Insights", tags=["ml"])
        factory.create(PacketType.TEMPLATE, "Report Template", tags=["reporting"])
        results = factory.search("ml")
        assert len(results) == 1

    def test_type_stats(self):
        from ncl_agency_runtime.fpc.second_brain import (
            PacketFactory,
            PacketType,
        )
        factory = PacketFactory()
        factory.create(PacketType.DISTILLED_NOTE, "DN1")
        factory.create(PacketType.DISTILLED_NOTE, "DN2")
        factory.create(PacketType.CHECKLIST, "CL1")
        stats = factory.type_stats()
        assert stats["distilled_note"] == 2
        assert stats["checklist"] == 1


# ── RetrievalEngine Tests ─────────────────────────────────────


class TestRetrievalEngine:
    def _make_engine(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PacketFactory,
            RetrievalEngine,
        )
        store = KnowledgeStore()
        factory = PacketFactory()
        store.ingest("Machine Learning Fundamentals", "textbook", tags=["ml", "ai"])
        store.ingest("Deep Learning for NLP", "paper", tags=["dl", "nlp"])
        store.ingest("Quantum Computing Overview", "lecture", tags=["quantum"])
        return RetrievalEngine(store, factory)

    def test_keyword_retrieval(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        engine = self._make_engine()
        result = engine.retrieve("Machine", mode=RetrievalMode.KEYWORD)
        assert result.hit_count >= 1
        assert result.elapsed_ms >= 0

    def test_temporal_retrieval(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        engine = self._make_engine()
        result = engine.retrieve("learning", mode=RetrievalMode.TEMPORAL)
        assert result.mode == RetrievalMode.TEMPORAL
        # All notes are recent, so all should have some recency score
        assert result.total_searched >= 3

    def test_associative_retrieval(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PacketFactory,
            RetrievalEngine,
            RetrievalMode,
        )
        store = KnowledgeStore()
        factory = PacketFactory()
        n1 = store.ingest("Hub Note", "src", tags=["hub"])
        n2 = store.ingest("Connected Note", "src")
        n1.connections.append(n2.note_id)
        engine = RetrievalEngine(store, factory)
        result = engine.retrieve("Hub", mode=RetrievalMode.ASSOCIATIVE)
        assert result.hit_count >= 1

    def test_contextual_retrieval(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        engine = self._make_engine()
        result = engine.retrieve("quantum", mode=RetrievalMode.CONTEXTUAL)
        assert result.hit_count >= 1

    def test_semantic_retrieval(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        engine = self._make_engine()
        result = engine.retrieve("Machine", mode=RetrievalMode.SEMANTIC)
        assert result.mode == RetrievalMode.SEMANTIC

    def test_empty_associative(self):
        from ncl_agency_runtime.fpc.second_brain import (
            KnowledgeStore,
            PacketFactory,
            RetrievalEngine,
            RetrievalMode,
        )
        store = KnowledgeStore()
        factory = PacketFactory()
        engine = RetrievalEngine(store, factory)
        result = engine.retrieve("nothing", mode=RetrievalMode.ASSOCIATIVE)
        assert result.hit_count == 0

    def test_ngram_similarity(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalEngine
        sim = RetrievalEngine._ngram_similarity("hello", "hello")
        assert sim == 1.0
        sim2 = RetrievalEngine._ngram_similarity("hello", "world")
        assert sim2 < 1.0
        sim3 = RetrievalEngine._ngram_similarity("", "")
        assert sim3 == 0.0


# ── CODEWorkflow Tests ─────────────────────────────────────────


class TestCODEWorkflow:
    def _make_workflow(self):
        from ncl_agency_runtime.fpc.second_brain import (
            CODEWorkflow,
            KnowledgeStore,
            PacketFactory,
            ProgressiveSummarizer,
        )
        store = KnowledgeStore()
        summarizer = ProgressiveSummarizer()
        factory = PacketFactory()
        return CODEWorkflow(store, summarizer, factory), store

    def test_capture(self):
        from ncl_agency_runtime.fpc.second_brain import CODEStage
        wf, store = self._make_workflow()
        result = wf.capture("Test", "src", raw_text="Some raw text.")
        assert result["stage"] == CODEStage.CAPTURE
        assert result["note_id"]
        assert store.total_notes == 1

    def test_organize(self):
        from ncl_agency_runtime.fpc.second_brain import CODEStage, PARACategory
        wf, _ = self._make_workflow()
        cap = wf.capture("Organize Me", "src")
        result = wf.organize(cap["note_id"], PARACategory.PROJECTS, tags=["urgent"])
        assert result["stage"] == CODEStage.ORGANIZE
        assert result["category"] == PARACategory.PROJECTS
        assert "urgent" in result["tags"]

    def test_organize_nonexistent(self):
        from ncl_agency_runtime.fpc.second_brain import PARACategory
        wf, _ = self._make_workflow()
        result = wf.organize("fake_id", PARACategory.PROJECTS)
        assert result.get("error") == "note_not_found"

    def test_distill(self):
        from ncl_agency_runtime.fpc.second_brain import (
            CODEStage,
        )
        wf, _ = self._make_workflow()
        cap = wf.capture(
            "Distill Me", "src",
            raw_text="This is a long text about various topics that need summarization. " * 10,
        )
        result = wf.distill(cap["note_id"])
        assert result["stage"] == CODEStage.DISTILL
        assert len(result["layers_completed"]) > 0

    def test_distill_nonexistent(self):
        wf, _ = self._make_workflow()
        result = wf.distill("fake_id")
        assert result.get("error") == "note_not_found"

    def test_express(self):
        from ncl_agency_runtime.fpc.second_brain import CODEStage
        wf, _ = self._make_workflow()
        cap = wf.capture("Express Me", "src", raw_text="Key insight here.")
        result = wf.express([cap["note_id"]], title="My Report")
        assert result["stage"] == CODEStage.EXPRESS
        assert result["packets_created"] == 1
        assert result["title"] == "My Report"

    def test_full_pipeline(self):
        wf, _store = self._make_workflow()
        result = wf.full_pipeline(
            "Full Pipeline Test", "unit_test",
            raw_text="Detailed content for the full pipeline test. " * 10,
            tags=["test"],
        )
        assert result["pipeline_run"] == 1
        assert result["note_id"]
        assert result["distill_layers"] >= 1
        assert wf.pipeline_runs == 1

    def test_multiple_pipelines(self):
        wf, _ = self._make_workflow()
        wf.full_pipeline("P1", "s", "Text one. " * 5)
        wf.full_pipeline("P2", "s2", "Text two. " * 5)
        assert wf.pipeline_runs == 2


# ── ConnectionGraph Tests ──────────────────────────────────────


class TestConnectionGraph:
    def test_connect(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("a", "b", 0.8)
        assert graph.node_count == 2
        assert graph.edge_count == 1

    def test_bidirectional(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("a", "b")
        assert "b" in graph.neighbors("a")
        assert "a" in graph.neighbors("b")

    def test_weight(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("x", "y", 0.75)
        assert graph.weight("x", "y") == 0.75
        assert graph.weight("y", "x") == 0.75  # Bidirectional
        assert graph.weight("x", "z") == 0.0   # Nonexistent

    def test_clusters(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("a", "b")
        graph.connect("b", "c")
        graph.connect("x", "y")
        clusters = graph.clusters()
        assert len(clusters) == 2
        sizes = sorted(len(c) for c in clusters)
        assert sizes == [2, 3]

    def test_hub_score(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("hub", "a")
        graph.connect("hub", "b")
        graph.connect("hub", "c")
        assert graph.hub_score("hub") > graph.hub_score("a")

    def test_top_hubs(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("hub", "a")
        graph.connect("hub", "b")
        graph.connect("a", "c")
        top = graph.top_hubs(limit=1)
        assert len(top) == 1
        assert top[0][0] == "hub"

    def test_path_exists(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("a", "b")
        graph.connect("b", "c")
        assert graph.path_exists("a", "c")
        assert not graph.path_exists("a", "d")

    def test_path_missing_nodes(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        assert not graph.path_exists("x", "y")

    def test_summary(self):
        from ncl_agency_runtime.fpc.second_brain import ConnectionGraph
        graph = ConnectionGraph()
        graph.connect("a", "b")
        graph.connect("c", "d")
        summary = graph.summary()
        assert summary["nodes"] == 4
        assert summary["edges"] == 2
        assert summary["clusters"] == 2


# ── SecondBrainEngine Tests ────────────────────────────────────


class TestSecondBrainEngine:
    def _make_engine(self):
        from ncl_agency_runtime.fpc.second_brain import SecondBrainEngine
        engine = SecondBrainEngine()
        engine.initialize()
        return engine

    def test_initialization(self):
        engine = self._make_engine()
        assert engine.initialized
        # Foundation notes seeded
        assert engine._store.total_notes >= 5

    def test_twelve_problems(self):
        from ncl_agency_runtime.fpc.second_brain import SecondBrainEngine
        assert len(SecondBrainEngine.TWELVE_PROBLEMS) == 12

    def test_capture_knowledge(self):
        engine = self._make_engine()
        result = engine.capture_knowledge("AI Trends 2025", "report", raw_text="AI is advancing rapidly.")
        assert result["status"] == "captured"
        assert result["note_id"]

    def test_distill_note(self):
        engine = self._make_engine()
        cap = engine.capture_knowledge(
            "Distillation Test", "src",
            raw_text="Long text about quantum computing and machine learning fusion. " * 10,
        )
        result = engine.distill_note(cap["note_id"])
        assert result["status"] == "distilled"

    def test_express_knowledge(self):
        engine = self._make_engine()
        cap = engine.capture_knowledge("Express Test", "src", raw_text="Key finding here.")
        result = engine.express_knowledge([cap["note_id"]], title="Report")
        assert result["status"] == "expressed"
        assert result["packets_created"] >= 1

    def test_full_pipeline(self):
        engine = self._make_engine()
        result = engine.full_pipeline(
            "Pipeline Test", "unit_test",
            "Comprehensive analysis of market trends in AI. " * 10,
        )
        assert result["status"] == "pipeline_complete"
        assert result["note_id"]

    def test_retrieve_keyword(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        engine = self._make_engine()
        engine.capture_knowledge("Findable Note", "src", tags=["searchable"])
        result = engine.retrieve("Findable", mode=RetrievalMode.KEYWORD)
        assert result["status"] == "retrieved"
        assert result["hits"] >= 1

    def test_retrieve_temporal(self):
        from ncl_agency_runtime.fpc.second_brain import RetrievalMode
        engine = self._make_engine()
        result = engine.retrieve("PARA", mode=RetrievalMode.TEMPORAL)
        assert result["status"] == "retrieved"

    def test_create_packet(self):
        from ncl_agency_runtime.fpc.second_brain import PacketType
        engine = self._make_engine()
        result = engine.create_packet(
            PacketType.TEMPLATE, "My Template",
            content={"structure": "intro + body + conclusion"},
        )
        assert result["status"] == "packet_created"
        assert result["packet_id"]

    def test_connect_notes(self):
        engine = self._make_engine()
        n1 = engine.capture_knowledge("Note A", "src")
        n2 = engine.capture_knowledge("Note B", "src2")
        result = engine.connect_notes(n1["note_id"], n2["note_id"], 0.9)
        assert result["status"] == "connected"
        assert result["graph_edges"] == 1

    def test_test_against_problems(self):
        engine = self._make_engine()
        result = engine.test_against_problems(
            "predictions with higher confidence using cross-domain patterns"
        )
        assert result["status"] == "problems_tested"
        assert result["problems_matched"] >= 1

    def test_run_cycle(self):
        engine = self._make_engine()
        engine.capture_knowledge("Cycle Test", "src", raw_text="Some content.")
        result = engine.run_cycle()
        assert result["status"] == "cycle_complete"
        assert result["cycle"] == 1

    def test_operational_readiness(self):
        engine = self._make_engine()
        result = engine.operational_readiness()
        assert result["readiness_score"] > 0
        assert "checks" in result

    def test_score_methodology(self):
        engine = self._make_engine()
        result = engine.score_methodology()
        assert result["status"] == "methodology_scored"
        assert "composite" in result
        assert 0.0 <= result["composite"] <= 1.0

    def test_score_methodology_with_context(self):
        engine = self._make_engine()
        result = engine.score_methodology({"domain": "forecasting"})
        assert result["context_bonus"] == 0.05

    def test_pipeline_then_retrieve(self):
        """End-to-end: pipeline knowledge then retrieve it."""
        engine = self._make_engine()
        engine.full_pipeline(
            "Prediction Accuracy Research", "academic_paper",
            "Research shows that ensemble methods improve prediction accuracy by 23%. "
            "Cross-validation reduces overfitting. Feature engineering is crucial.",
            tags=["prediction", "accuracy"],
        )
        result = engine.retrieve("prediction")
        assert result["hits"] >= 1


# ── CortexAgent Integration Tests ──────────────────────────────


class TestCortexAgentIntegration:
    def _make_agent(self):
        from ncl_agency_runtime.fpc.agents.expansion import CortexAgent
        return CortexAgent()

    def _make_task(self):
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        return Task(id="test-cortex-001", agent_codename="sb", description="test second brain")

    def test_agent_identity(self):
        agent = self._make_agent()
        assert agent.codename == "sb"
        assert agent.callsign == "CORTEX"

    def test_handle_returns_metadata(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {"action": "readiness"}})
        assert result["_agent"] == "sb"
        assert result["_callsign"] == "CORTEX"
        assert "_elapsed_s" in result

    def test_capture_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {
            "action": "capture",
            "title": "Market Analysis",
            "source": "report",
            "raw_text": "Markets are trending upward.",
            "tags": ["markets"],
        }})
        assert result["status"] == "knowledge_captured"

    def test_distill_action(self):
        agent = self._make_agent()
        task = self._make_task()
        # First capture
        cap = agent.handle(task, {"payload": {
            "action": "pipeline",
            "title": "Distill Target",
            "source": "src",
            "raw_text": "Content for distillation testing purposes. " * 10,
        }})
        assert cap["status"] == "pipeline_complete"

    def test_retrieve_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {
            "action": "retrieve",
            "query": "PARA",
            "mode": "keyword",
        }})
        assert result["status"] == "knowledge_retrieved"

    def test_packet_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {
            "action": "packet",
            "packet_type": "template",
            "title": "Analysis Template",
        }})
        assert result["status"] == "packet_created"

    def test_problems_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {
            "action": "problems",
            "knowledge": "predict outcomes with higher confidence",
        }})
        assert result["status"] == "problems_tested"

    def test_cycle_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {"action": "cycle"}})
        assert result["status"] == "cycle_complete"

    def test_methodology_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {"action": "methodology"}})
        assert result["status"] == "methodology_scored"

    def test_readiness_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {"action": "readiness"}})
        assert result["status"] == "readiness_checked"

    def test_default_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {}})
        # Default action is "capture" which falls to operational readiness
        assert result["status"] == "knowledge_captured"

    def test_connect_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {
            "action": "connect",
            "note_a": "some_id",
            "note_b": "other_id",
            "weight": 0.8,
        }})
        assert result["status"] == "notes_connected"

    def test_express_action(self):
        agent = self._make_agent()
        task = self._make_task()
        result = agent.handle(task, {"payload": {
            "action": "express",
            "note_ids": [],
            "title": "Empty Expression",
        }})
        assert result["status"] == "knowledge_expressed"


# ── Event System Integration ───────────────────────────────────


class TestSecondBrainEvents:
    def test_brain_event_types_exist(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert hasattr(EventType, "BRAIN_CAPTURE")
        assert hasattr(EventType, "BRAIN_ORGANIZE")
        assert hasattr(EventType, "BRAIN_DISTILL")
        assert hasattr(EventType, "BRAIN_EXPRESS")
        assert hasattr(EventType, "BRAIN_RETRIEVE")
        assert hasattr(EventType, "BRAIN_CYCLE")

    def test_brain_event_values(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.BRAIN_CAPTURE == "brain.capture"
        assert EventType.BRAIN_ORGANIZE == "brain.organize"
        assert EventType.BRAIN_DISTILL == "brain.distill"
        assert EventType.BRAIN_EXPRESS == "brain.express"
        assert EventType.BRAIN_RETRIEVE == "brain.retrieve"
        assert EventType.BRAIN_CYCLE == "brain.cycle"

    def test_total_event_types(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        # 13 core + 4 Wolfram + 10 Triad + 8 Unit8200 + 5 GeoPol + 6 Brain + 6 Brief = 52
        assert len(EventType) == 71

    def test_event_creation_with_brain_type(self):
        from ncl_agency_runtime.fpc.agents.events import Event, EventType
        evt = Event(
            detail_type=EventType.BRAIN_CAPTURE,
            source="agent.CORTEX",
            payload={"title": "Test", "note_id": "abc123"},
        )
        assert evt.detail_type == EventType.BRAIN_CAPTURE
        assert evt.source == "agent.CORTEX"


# ── Agent Roster Integration ──────────────────────────────────


class TestSecondBrainRosterIntegration:
    def test_cortex_in_expansion_pack(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        codenames = [a.codename for a in EXPANSION_PACK]
        assert "sb" in codenames

    def test_cortex_in_all_agents(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        codenames = [a.codename for a in ALL_AGENTS]
        assert "sb" in codenames

    def test_expansion_pack_count(self):
        from ncl_agency_runtime.fpc.agents import EXPANSION_PACK
        assert len(EXPANSION_PACK) == 21

    def test_all_agents_count(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_cortex_role_details(self):
        from ncl_agency_runtime.fpc.agents import get_agent
        agent = get_agent("sb")
        assert agent is not None
        assert agent.callsign == "CORTEX"
        assert agent.name == "Second Brain Knowledge Engine"

    def test_cortex_by_callsign(self):
        from ncl_agency_runtime.fpc.agents import get_agent_by_callsign
        agent = get_agent_by_callsign("CORTEX")
        assert agent is not None
        assert agent.codename == "sb"

    def test_callsign_map(self):
        from ncl_agency_runtime.fpc.agents import CALLSIGN_MAP
        assert CALLSIGN_MAP["sb"] == "CORTEX"

    def test_expansion_stubs_includes_cortex(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert "sb" in EXPANSION_STUBS
        assert len(EXPANSION_STUBS) == 21
