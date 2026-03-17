"""Tests for the Wolfram Physics integration module.

Covers:
  - HypergraphState construction, rewriting, adjacency, dimension
  - MultiwaySystem branching, merge detection, consensus
  - CausalGraph events, cones, spacelike separation, invariance
  - Branchial distance and entanglement metrics
  - Computational irreducibility detection
  - RuliadExplorer configuration search and Pareto frontier
  - Observer projection end-to-end
  - WolframPhysicsEngine unified workflow
  - WolframAgent integration via handle()
"""

from __future__ import annotations

import numpy as np
import pytest

from ncl_agency_runtime.fpc.wolfram_physics import (
    Branch,
    CausalGraph,
    HyperEdge,
    HypergraphState,
    MultiwaySystem,
    RuliadExplorer,
    WolframPhysicsEngine,
    branchial_distance,
    branchial_entanglement,
    check_irreducibility,
    observer_projection,
)

# ═══════════════════════════════════════════════════════════════
#  HyperEdge
# ═══════════════════════════════════════════════════════════════

class TestHyperEdge:
    def test_arity(self):
        edge = HyperEdge(elements=("a", "b", "c"), relation="interaction")
        assert edge.arity == 3

    def test_frozen(self):
        edge = HyperEdge(elements=("a",))
        with pytest.raises(AttributeError):
            edge.relation = "changed"  # type: ignore[misc]

    def test_defaults(self):
        edge = HyperEdge(elements=("x",))
        assert edge.weight == 1.0
        assert edge.step == 0
        assert edge.relation == "interaction"


# ═══════════════════════════════════════════════════════════════
#  HypergraphState
# ═══════════════════════════════════════════════════════════════

class TestHypergraphState:
    def test_add_edge(self):
        hg = HypergraphState()
        edge = hg.add_edge(("agent_a", "agent_b"), relation="interacts")
        assert edge.relation == "interacts"
        assert hg.size == 1
        assert hg.nodes == {"agent_a", "agent_b"}

    def test_apply_rule_rewrites(self):
        hg = HypergraphState()
        hg.add_edge(("a", "b"), relation="weak")
        hg.add_edge(("c", "d"), relation="strong")

        def upgrade(edge):
            return HyperEdge(elements=edge.elements, relation="upgraded", step=edge.step)

        count = hg.apply_rule("weak", upgrade)
        assert count == 1
        assert hg.step == 1
        relations = {e.relation for e in hg.edges}
        assert "upgraded" in relations
        assert "weak" not in relations
        assert "strong" in relations

    def test_apply_rule_returns_list(self):
        hg = HypergraphState()
        hg.add_edge(("a", "b"), relation="split")

        def split_rule(edge):
            return [
                HyperEdge(elements=(edge.elements[0],), relation="fragment"),
                HyperEdge(elements=(edge.elements[1],), relation="fragment"),
            ]

        count = hg.apply_rule("split", split_rule)
        assert count == 1
        assert hg.size == 2

    def test_adjacency_matrix(self):
        hg = HypergraphState()
        hg.add_edge(("a", "b", "c"))
        mat = hg.adjacency_matrix()
        assert mat.shape == (3, 3)
        assert mat.sum() > 0  # Has connections

    def test_dimension_estimate_empty(self):
        hg = HypergraphState()
        assert hg.dimension_estimate() == 0.0

    def test_dimension_estimate_nontrivial(self):
        hg = HypergraphState()
        for i in range(5):
            hg.add_edge((f"n{i}", f"n{i+1}", f"n{i+2}"))
        dim = hg.dimension_estimate()
        assert dim > 0.0


# ═══════════════════════════════════════════════════════════════
#  MultiwaySystem
# ═══════════════════════════════════════════════════════════════

class TestMultiwaySystem:
    def test_add_branch(self):
        ms = MultiwaySystem()
        b = ms.add_branch("model_a", np.array([1.0, 2.0, 3.0]), confidence=0.9)
        assert b.source == "model_a"
        assert ms.branch_count == 1

    def test_evolve(self):
        ms = MultiwaySystem()
        count = ms.evolve([
            ("model_a", np.array([1.0, 2.0, 3.0]), 0.9),
            ("model_b", np.array([1.1, 2.1, 3.1]), 0.8),
        ])
        assert count == 2
        assert ms.branch_count == 2

    def test_consensus_prediction(self):
        ms = MultiwaySystem()
        ms.add_branch("a", np.array([10.0, 20.0, 30.0]), confidence=1.0)
        ms.add_branch("b", np.array([12.0, 22.0, 32.0]), confidence=1.0)
        consensus = ms.consensus_prediction()
        assert consensus is not None
        assert len(consensus) == 3
        np.testing.assert_allclose(consensus, [11.0, 21.0, 31.0], atol=0.01)

    def test_consensus_empty(self):
        ms = MultiwaySystem()
        assert ms.consensus_prediction() is None

    def test_consensus_weighted(self):
        ms = MultiwaySystem()
        ms.add_branch("a", np.array([10.0, 20.0]), confidence=3.0)
        ms.add_branch("b", np.array([20.0, 40.0]), confidence=1.0)
        consensus = ms.consensus_prediction()
        assert consensus is not None
        # Weighted: (10*3/4 + 20*1/4) = 12.5, (20*3/4 + 40*1/4) = 25
        np.testing.assert_allclose(consensus, [12.5, 25.0], atol=0.01)

    def test_merge_detection(self):
        ms = MultiwaySystem()
        # Two nearly identical branches should merge
        preds = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        ms.evolve([
            ("a", preds, 1.0),
            ("b", preds + 0.001, 1.0),  # Almost identical
        ])
        bg = ms.branchial_graph()
        assert len(bg["merges"]) > 0

    def test_branchial_graph(self):
        ms = MultiwaySystem()
        ms.add_branch("a", np.array([1.0, 2.0, 3.0]))
        ms.add_branch("b", np.array([5.0, 6.0, 7.0]))
        bg = ms.branchial_graph()
        assert len(bg["nodes"]) == 2
        assert len(bg["edges"]) == 1

    def test_branch_fingerprint(self):
        b1 = Branch("b1", "model", np.array([1.0, 2.0]))
        b2 = Branch("b2", "model", np.array([1.0, 2.0]))
        b3 = Branch("b3", "model", np.array([1.0, 3.0]))
        assert b1.fingerprint == b2.fingerprint
        assert b1.fingerprint != b3.fingerprint


# ═══════════════════════════════════════════════════════════════
#  CausalGraph
# ═══════════════════════════════════════════════════════════════

class TestCausalGraph:
    def test_add_event(self):
        cg = CausalGraph()
        node = cg.add_event("ds", "data_validated")
        assert node.agent == "ds"
        assert len(cg.nodes) == 1

    def test_causal_chain(self):
        cg = CausalGraph()
        e1 = cg.add_event("ds", "validated")
        e2 = cg.add_event("be", "forecast", causes=[e1.node_id])
        e3 = cg.add_event("mc", "decided", causes=[e2.node_id])
        assert len(cg.links) == 2
        cone = cg.causal_cone(e3.node_id)
        assert e1.node_id in cone
        assert e2.node_id in cone

    def test_future_cone(self):
        cg = CausalGraph()
        e1 = cg.add_event("ds", "validated")
        e2 = cg.add_event("be", "forecast", causes=[e1.node_id])
        e3 = cg.add_event("mc", "decided", causes=[e2.node_id])
        future = cg.future_cone(e1.node_id)
        assert e2.node_id in future
        assert e3.node_id in future

    def test_spacelike_separation(self):
        cg = CausalGraph()
        e1 = cg.add_event("ds", "validated")
        e2 = cg.add_event("xe", "explained")  # No causal link to e1
        assert cg.spacelike_separated(e1.node_id, e2.node_id)

    def test_not_spacelike_if_linked(self):
        cg = CausalGraph()
        e1 = cg.add_event("ds", "validated")
        e2 = cg.add_event("be", "forecast", causes=[e1.node_id])
        assert not cg.spacelike_separated(e1.node_id, e2.node_id)

    def test_causal_invariance_high(self):
        cg = CausalGraph()
        # Independent parallel events → high invariance
        cg.add_event("a", "x")
        cg.add_event("b", "y")
        cg.add_event("c", "z")
        score = cg.causal_invariance_score()
        assert score == 1.0  # No links → perfectly invariant

    def test_causal_invariance_chain(self):
        cg = CausalGraph()
        e1 = cg.add_event("a", "x")
        e2 = cg.add_event("b", "y", causes=[e1.node_id])
        cg.add_event("c", "z", causes=[e2.node_id])
        score = cg.causal_invariance_score()
        # Fully sequential chain → invariance could be < 1 depending on
        # link structure. Main thing is it returns a valid float.
        assert 0.0 <= score <= 1.0

    def test_to_dict(self):
        cg = CausalGraph()
        e1 = cg.add_event("ds", "validated")
        cg.add_event("be", "forecast", causes=[e1.node_id])
        d = cg.to_dict()
        assert len(d["nodes"]) == 2
        assert len(d["links"]) == 1
        assert "causal_invariance" in d

    def test_empty_cone(self):
        cg = CausalGraph()
        assert cg.causal_cone("nonexistent") == set()
        assert cg.future_cone("nonexistent") == set()


# ═══════════════════════════════════════════════════════════════
#  Branchial Distance & Entanglement
# ═══════════════════════════════════════════════════════════════

class TestBranchialDistance:
    def test_identical_branches(self):
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        assert branchial_distance(a, a) == 0.0

    def test_different_branches(self):
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        b = np.array([5.0, 3.0, 1.0, 4.0, 2.0])  # Different shape/trend
        dist = branchial_distance(a, b)
        assert 0.0 < dist <= 1.0

    def test_different_lengths(self):
        a = np.array([1.0, 2.0])
        b = np.array([1.0, 2.0, 3.0])
        assert branchial_distance(a, b) == 1.0

    def test_empty_arrays(self):
        assert branchial_distance(np.array([]), np.array([])) == 1.0

    def test_symmetry(self):
        a = np.array([1.0, 3.0, 5.0, 7.0])
        b = np.array([2.0, 4.0, 6.0, 8.0])
        assert branchial_distance(a, b) == pytest.approx(branchial_distance(b, a))


class TestBranchialEntanglement:
    def test_single_branch(self):
        assert branchial_entanglement([np.array([1.0, 2.0])]) == 1.0

    def test_identical_branches(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        ent = branchial_entanglement([a, a, a])
        assert ent == 1.0

    def test_divergent_branches(self):
        rng = np.random.default_rng(42)
        branches = [rng.normal(0, 1, 30) for _ in range(5)]
        ent = branchial_entanglement(branches)
        # Random branches should have moderate-to-low entanglement
        assert 0.0 <= ent <= 1.0

    def test_no_branches(self):
        assert branchial_entanglement([]) == 1.0


# ═══════════════════════════════════════════════════════════════
#  Computational Irreducibility
# ═══════════════════════════════════════════════════════════════

class TestIrreducibility:
    def test_linear_series_is_reducible(self):
        # Perfectly linear → shortcuts should work great
        series = np.arange(50, dtype=float)
        result = check_irreducibility(series, shortcut_horizon=7)
        assert not result.is_irreducible
        assert result.reducibility_score > 0.5

    def test_random_series_is_irreducible(self):
        rng = np.random.default_rng(42)
        series = rng.normal(0, 10, 100)
        result = check_irreducibility(series, shortcut_horizon=7)
        assert result.is_irreducible
        assert result.full_compute_needed

    def test_insufficient_data(self):
        series = np.array([1.0, 2.0, 3.0])
        result = check_irreducibility(series, shortcut_horizon=7)
        assert result.is_irreducible
        assert result.method == "insufficient_data"

    def test_result_fields(self):
        series = np.arange(50, dtype=float)
        result = check_irreducibility(series)
        assert isinstance(result.is_irreducible, bool)
        assert 0.0 <= result.reducibility_score <= 1.0
        assert result.shortcut_error >= 0.0
        assert isinstance(result.full_compute_needed, bool)
        assert result.method != ""
        assert result.detail != ""

    def test_constant_series(self):
        # Constant → maximally reducible (last-value repeat is perfect)
        series = np.ones(50) * 42.0
        result = check_irreducibility(series, shortcut_horizon=7)
        assert not result.is_irreducible


# ═══════════════════════════════════════════════════════════════
#  RuliadExplorer
# ═══════════════════════════════════════════════════════════════

class TestRuliadExplorer:
    def test_explore_and_best(self):
        re = RuliadExplorer()
        re.explore({"lr": 0.01}, score=0.5)
        re.explore({"lr": 0.001}, score=0.3)
        re.explore({"lr": 0.1}, score=0.8)
        assert re.explored_count == 3
        assert re.best_config is not None
        assert re.best_config.score == 0.3

    def test_generate_configs(self):
        re = RuliadExplorer()
        configs = re.generate_configs(
            {"model": "patchtst"},
            {"lr": [0.01, 0.001], "batch": [32, 64]},
        )
        assert len(configs) == 4
        assert all(c["model"] == "patchtst" for c in configs)

    def test_pareto_frontier(self):
        re = RuliadExplorer()
        re.explore({"a": 1}, score=0.5, entanglement=0.3)
        re.explore({"a": 2}, score=0.3, entanglement=0.2)
        re.explore({"a": 3}, score=0.8, entanglement=0.9)
        frontier = re.pareto_frontier()
        assert len(frontier) >= 1

    def test_summary_empty(self):
        re = RuliadExplorer()
        s = re.summary()
        assert s["explored_count"] == 0
        assert s["best_score"] is None

    def test_summary_populated(self):
        re = RuliadExplorer()
        re.explore({"x": 1}, score=0.4)
        s = re.summary()
        assert s["explored_count"] == 1
        assert s["best_score"] == 0.4


# ═══════════════════════════════════════════════════════════════
#  Observer Projection
# ═══════════════════════════════════════════════════════════════

class TestObserverProjection:
    def test_high_consensus(self):
        ms = MultiwaySystem()
        ms.add_branch("a", np.array([10.0, 20.0, 30.0]), confidence=1.0)
        ms.add_branch("b", np.array([10.1, 20.1, 30.1]), confidence=1.0)
        result = observer_projection(ms)
        assert result["interpretation"] == "high_consensus"
        assert result["confidence"] == "strong"
        assert result["branch_count"] == 2
        assert len(result["consensus_forecast"]) == 3

    def test_divergent_futures(self):
        ms = MultiwaySystem()
        ms.add_branch("a", np.arange(30, dtype=float), confidence=1.0)
        ms.add_branch("b", np.arange(30, 0, -1, dtype=float), confidence=1.0)
        result = observer_projection(ms)
        # These two branches are very different
        assert result["entanglement"] < 0.8

    def test_with_causal_graph(self):
        ms = MultiwaySystem()
        ms.add_branch("a", np.array([1.0, 2.0, 3.0]))
        cg = CausalGraph()
        cg.add_event("ds", "validated")
        result = observer_projection(ms, cg)
        assert "causal_invariance" in result
        assert "causal_events" in result


# ═══════════════════════════════════════════════════════════════
#  WolframPhysicsEngine
# ═══════════════════════════════════════════════════════════════

class TestWolframPhysicsEngine:
    def test_initialize(self):
        engine = WolframPhysicsEngine()
        result = engine.initialize(["mc", "ds", "be"])
        assert result["status"] == "initialized"
        assert result["nodes"] > 0
        assert result["edges"] > 0

    def test_record_action(self):
        engine = WolframPhysicsEngine()
        node = engine.record_action("ds", "data_validated")
        assert node.agent == "ds"

    def test_add_prediction_branch(self):
        engine = WolframPhysicsEngine()
        branch = engine.add_prediction_branch("model_a", np.array([1.0, 2.0]))
        assert branch.source == "model_a"

    def test_check_irreducibility(self):
        engine = WolframPhysicsEngine()
        series = np.arange(50, dtype=float)
        result = engine.check_irreducibility(series)
        assert isinstance(result.is_irreducible, bool)

    def test_observe(self):
        engine = WolframPhysicsEngine()
        engine.initialize(["mc", "ds"])
        engine.add_prediction_branch("a", np.array([1.0, 2.0, 3.0]))
        engine.record_action("ds", "validated")
        result = engine.observe()
        assert "consensus_forecast" in result
        assert "hypergraph" in result
        assert "ruliad" in result

    def test_full_state(self):
        engine = WolframPhysicsEngine()
        engine.initialize(["mc", "ds"])
        state = engine.full_state()
        assert "hypergraph" in state
        assert "multiway" in state
        assert "causal" in state
        assert "ruliad" in state

    def test_full_workflow(self):
        """End-to-end: init → predict → causal → observe."""
        engine = WolframPhysicsEngine()
        engine.initialize(["mc", "ds", "be", "cs"])

        # Add prediction branches from multiple models
        engine.add_prediction_branch("statsforecast", np.arange(30, dtype=float) * 1.1)
        engine.add_prediction_branch("patchtst", np.arange(30, dtype=float) * 1.15)
        engine.add_prediction_branch("chronos", np.arange(30, dtype=float) * 1.05)

        # Build causal chain
        e1 = engine.record_action("ds", "data_ingested")
        e2 = engine.record_action("be", "forecast_run", [e1.node_id])
        e3 = engine.record_action("cs", "causal_estimated", [e1.node_id])
        engine.record_action("mc", "council_decided", [e2.node_id, e3.node_id])

        # Observe
        result = engine.observe()
        assert len(result["consensus_forecast"]) == 30
        assert result["hypergraph"]["nodes"] > 0
        assert result["entanglement"] > 0.5  # Similar linear forecasts


# ═══════════════════════════════════════════════════════════════
#  WolframAgent (via expansion.py)
# ═══════════════════════════════════════════════════════════════

class TestWolframAgent:
    @pytest.fixture()
    def agent(self):
        from ncl_agency_runtime.fpc.agents.expansion import WolframAgent
        return WolframAgent()

    @pytest.fixture()
    def task(self):
        from ncl_agency_runtime.fpc.agents.orchestrator import Task
        return Task(id="wolfram-test", agent_codename="wp", description="test")

    def test_observe_action(self, agent, task):
        result = agent.handle(task, {"payload": {"action": "observe"}})
        assert result["status"] == "wolfram_observed"
        assert "_agent" in result
        assert result["_agent"] == "wp"

    def test_initialize_action(self, agent, task):
        result = agent.handle(task, {"payload": {"action": "initialize", "agents": ["mc", "ds"]}})
        assert result["status"] == "wolfram_initialized"
        assert result["nodes"] > 0

    def test_irreducibility_check(self, agent, task):
        series = list(range(50))
        result = agent.handle(task, {"payload": {"action": "irreducibility_check", "series": series}})
        assert result["status"] == "irreducibility_tested"
        assert "is_irreducible" in result

    def test_multiway_action(self, agent, task):
        result = agent.handle(task, {"payload": {"action": "multiway"}})
        assert result["status"] == "multiway_computed"
        assert result["branch_count"] == 3  # Default branches

    def test_default_observe(self, agent, task):
        result = agent.handle(task, {"payload": {}})
        assert result["status"] == "wolfram_observed"

    def test_in_expansion_registry(self):
        from ncl_agency_runtime.fpc.agents.expansion import EXPANSION_STUBS
        assert "wp" in EXPANSION_STUBS
        assert EXPANSION_STUBS["wp"].callsign == "WOLFRAM"


# ═══════════════════════════════════════════════════════════════
#  Agent Roster Integration
# ═══════════════════════════════════════════════════════════════

class TestRosterIntegration:
    def test_wolfram_in_all_agents(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS, CALLSIGN_MAP
        codenames = [a.codename for a in ALL_AGENTS]
        assert "wp" in codenames
        assert CALLSIGN_MAP["wp"] == "WOLFRAM"

    def test_21_agents_total(self):
        from ncl_agency_runtime.fpc.agents import ALL_AGENTS
        assert len(ALL_AGENTS) == 31

    def test_wolfram_event_types(self):
        from ncl_agency_runtime.fpc.agents.events import EventType
        assert EventType.WOLFRAM_BRANCH == "wolfram.branch"
        assert EventType.WOLFRAM_MERGE == "wolfram.merge"
        assert EventType.WOLFRAM_IRREDUCIBILITY == "wolfram.irreducibility"
        assert EventType.WOLFRAM_OBSERVE == "wolfram.observe"
