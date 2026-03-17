"""Wolfram Physics Integration — Computational Universe Framework.

Implements concepts from Stephen Wolfram's "A New Kind of Science" and the
Wolfram Physics Project, adapted to the Future Predictor Council:

  1. Hypergraph State     — Agent relations as evolving hypergraph
  2. Multiway System      — Branching model predictions explored in parallel
  3. Causal Graph          — Directed dependency graph of agent actions
  4. Branchial Distance   — Divergence metric between prediction branches
  5. Computational Irreducibility Detector — Identify non-shortcuttable forecasts
  6. Ruliad Explorer       — Systematic search across configuration space
  7. Observer Projection   — Collapse multiway branches to human-interpretable view

Reference: Wolfram, S. "A Project to Find the Fundamental Theory of Physics"
           (wolframphysics.org, 2020)
"""

from __future__ import annotations

import hashlib
import itertools
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  1. HYPERGRAPH STATE — Universe as relations between elements
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HyperEdge:
    """A single hyperedge connecting multiple elements.

    In Wolfram's framework, spacetime emerges from relations between
    abstract elements.  Here each element is an agent/model/data node
    and the edge encodes their interaction.
    """

    elements: tuple[str, ...]
    relation: str = "interaction"
    weight: float = 1.0
    step: int = 0

    @property
    def arity(self) -> int:
        return len(self.elements)


class HypergraphState:
    """The system state represented as an evolving hypergraph.

    Wolfram's core insight: the universe IS the hypergraph, and physics
    emerges from simple rewriting rules applied to it.  Here we track
    agent-model-data relations and how they transform over time.
    """

    def __init__(self) -> None:
        self._edges: list[HyperEdge] = []
        self._step: int = 0
        self._history: list[list[HyperEdge]] = []

    @property
    def edges(self) -> list[HyperEdge]:
        return list(self._edges)

    @property
    def step(self) -> int:
        return self._step

    @property
    def nodes(self) -> set[str]:
        """All unique elements across active hyperedges."""
        return {e for edge in self._edges for e in edge.elements}

    @property
    def size(self) -> int:
        return len(self._edges)

    def add_edge(self, elements: tuple[str, ...], relation: str = "interaction",
                 weight: float = 1.0) -> HyperEdge:
        """Add a hyperedge.  Returns the created edge."""
        edge = HyperEdge(elements=elements, relation=relation,
                         weight=weight, step=self._step)
        self._edges.append(edge)
        return edge

    def apply_rule(self, match_relation: str, rewrite_fn: Any) -> int:
        """Apply a rewriting rule to all matching hyperedges.

        This is the fundamental operation in Wolfram's framework:
        find a pattern, replace it with the rewrite.  Returns the
        number of rewrites applied.
        """
        self._history.append(list(self._edges))
        new_edges: list[HyperEdge] = []
        rewrites = 0

        for edge in self._edges:
            if edge.relation == match_relation:
                result = rewrite_fn(edge)
                if result is not None:
                    if isinstance(result, list):
                        new_edges.extend(result)
                    else:
                        new_edges.append(result)
                    rewrites += 1
                else:
                    new_edges.append(edge)
            else:
                new_edges.append(edge)

        self._edges = new_edges
        self._step += 1
        return rewrites

    def adjacency_matrix(self) -> np.ndarray:
        """Build an adjacency matrix from hyperedge co-occurrences."""
        node_list = sorted(self.nodes)
        idx = {n: i for i, n in enumerate(node_list)}
        n = len(node_list)
        mat = np.zeros((n, n))
        for edge in self._edges:
            for a, b in itertools.combinations(edge.elements, 2):
                mat[idx[a], idx[b]] += edge.weight
                mat[idx[b], idx[a]] += edge.weight
        return mat

    def dimension_estimate(self) -> float:
        """Estimate effective dimensionality from growth rate.

        In Wolfram's framework, spatial dimension emerges from how
        the number of nodes within graph distance r grows: N(r) ~ r^d.
        We approximate d from the adjacency structure.
        """
        if len(self._edges) < 2:
            return 0.0
        mat = self.adjacency_matrix()
        n = mat.shape[0]
        if n < 3:
            return float(n - 1)
        # Use spectral dimension: ratio of eigenvalue spread
        eigenvalues = np.sort(np.abs(np.linalg.eigvalsh(mat)))
        nonzero = eigenvalues[eigenvalues > 1e-10]
        if len(nonzero) < 2:
            return 1.0
        return float(np.log(len(nonzero)) / np.log(max(nonzero[-1], 1.01)))


# ═══════════════════════════════════════════════════════════════════
#  2. MULTIWAY SYSTEM — All possible rule applications explored
# ═══════════════════════════════════════════════════════════════════

@dataclass
class Branch:
    """A single branch in the multiway system.

    Each branch represents one possible evolution of predictions —
    one model with one configuration producing one forecast path.
    """

    branch_id: str
    source: str                         # Model/strategy name
    predictions: np.ndarray             # Forecast values
    confidence: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None

    @property
    def fingerprint(self) -> str:
        """Content hash for dedup and merge detection."""
        h = hashlib.sha256(self.predictions.tobytes())
        h.update(self.source.encode())
        return h.hexdigest()[:12]


class MultiwaySystem:
    """Explores all branching prediction paths simultaneously.

    Wolfram's multiway system applies ALL possible rules at each step,
    creating a branching graph of states.  Here, each model strategy
    produces a "branch" of predictions, and we track how they merge
    and diverge over time — this IS the quantum-like superposition
    of possible forecasting futures.
    """

    def __init__(self) -> None:
        self._branches: dict[str, Branch] = {}
        self._merge_events: list[dict[str, Any]] = []
        self._step: int = 0

    @property
    def branches(self) -> list[Branch]:
        return list(self._branches.values())

    @property
    def branch_count(self) -> int:
        return len(self._branches)

    def add_branch(self, source: str, predictions: np.ndarray,
                   confidence: float = 1.0,
                   parent_id: str | None = None,
                   **meta: Any) -> Branch:
        """Add a new prediction branch from a model/strategy."""
        bid = f"b_{self._step}_{source}_{len(self._branches)}"
        branch = Branch(
            branch_id=bid,
            source=source,
            predictions=np.asarray(predictions, dtype=float),
            confidence=confidence,
            meta=meta,
            parent_id=parent_id,
        )
        self._branches[bid] = branch
        return branch

    def evolve(self, new_branches: list[tuple[str, np.ndarray, float]]) -> int:
        """Advance one step: add branches from latest model runs.

        Returns the number of new branches created.
        """
        self._step += 1
        count = 0
        for source, preds, conf in new_branches:
            self.add_branch(source, preds, conf)
            count += 1
        self._detect_merges()
        return count

    def _detect_merges(self) -> None:
        """Identify when branches converge (predictions agree)."""
        branch_list = self.branches
        for i, a in enumerate(branch_list):
            for b in branch_list[i + 1:]:
                if len(a.predictions) == len(b.predictions):
                    dist = branchial_distance(a.predictions, b.predictions)
                    if dist < 0.05:
                        self._merge_events.append({
                            "step": self._step,
                            "branch_a": a.branch_id,
                            "branch_b": b.branch_id,
                            "distance": dist,
                        })

    def consensus_prediction(self) -> np.ndarray | None:
        """Weighted average across all branches (observer projection).

        This is the "classical" outcome — what a computationally bounded
        observer perceives when they can't track individual branches.
        """
        if not self._branches:
            return None
        # Stack all branches of same length, weight by confidence
        by_len: dict[int, list[Branch]] = {}
        for b in self._branches.values():
            by_len.setdefault(len(b.predictions), []).append(b)
        # Use the most common length
        if not by_len:
            return None
        target_len = max(by_len, key=lambda k: len(by_len[k]))
        branches = by_len[target_len]
        weights = np.array([b.confidence for b in branches])
        weights = weights / weights.sum()
        stacked = np.column_stack([b.predictions for b in branches])
        result: np.ndarray = (stacked * weights).sum(axis=1)
        return result

    def branchial_graph(self) -> dict[str, Any]:
        """Build the branchial graph — connections in prediction space.

        Branchial space is orthogonal to causal space.  Two branches
        that are "close" in branchial space produce similar predictions;
        far apart means divergent possible futures.
        """
        branch_list = self.branches
        nodes = [{"id": b.branch_id, "source": b.source, "confidence": b.confidence}
                 for b in branch_list]
        edges = []
        for i, a in enumerate(branch_list):
            for b in branch_list[i + 1:]:
                if len(a.predictions) == len(b.predictions):
                    dist = branchial_distance(a.predictions, b.predictions)
                    edges.append({
                        "from": a.branch_id,
                        "to": b.branch_id,
                        "branchial_distance": round(dist, 4),
                    })
        return {"nodes": nodes, "edges": edges, "merges": self._merge_events}


# ═══════════════════════════════════════════════════════════════════
#  3. CAUSAL GRAPH — Directed dependencies between events
# ═══════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CausalNode:
    """A node in the causal graph — an event that happened."""

    node_id: str
    agent: str
    action: str
    ts: float = 0.0


@dataclass(frozen=True)
class CausalLink:
    """A directed causal edge: cause → effect."""

    cause: str      # node_id
    effect: str     # node_id
    strength: float = 1.0


class CausalGraph:
    """Wolfram-style causal graph of agent actions.

    In Wolfram's framework, the causal graph encodes which events
    can influence which other events.  Causal invariance — the
    property that the causal graph is the same regardless of
    evaluation order — is what gives rise to relativistic spacetime.

    Here we use it to understand information flow between agents.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, CausalNode] = {}
        self._links: list[CausalLink] = []

    @property
    def nodes(self) -> list[CausalNode]:
        return list(self._nodes.values())

    @property
    def links(self) -> list[CausalLink]:
        return list(self._links)

    def add_event(self, agent: str, action: str,
                  causes: list[str] | None = None,
                  ts: float | None = None) -> CausalNode:
        """Record an agent action with its causal parents."""
        node_id = f"c_{agent}_{len(self._nodes)}"
        node = CausalNode(
            node_id=node_id,
            agent=agent,
            action=action,
            ts=ts or time.time(),
        )
        self._nodes[node_id] = node
        for parent_id in (causes or []):
            if parent_id in self._nodes:
                self._links.append(CausalLink(cause=parent_id, effect=node_id))
        return node

    def causal_cone(self, node_id: str) -> set[str]:
        """Past light cone — all events that could have influenced this one."""
        if node_id not in self._nodes:
            return set()
        cone: set[str] = set()
        frontier = {node_id}
        while frontier:
            current = frontier.pop()
            for link in self._links:
                if link.effect == current and link.cause not in cone:
                    cone.add(link.cause)
                    frontier.add(link.cause)
        return cone

    def future_cone(self, node_id: str) -> set[str]:
        """Future light cone — all events this one could influence."""
        if node_id not in self._nodes:
            return set()
        cone: set[str] = set()
        frontier = {node_id}
        while frontier:
            current = frontier.pop()
            for link in self._links:
                if link.cause == current and link.effect not in cone:
                    cone.add(link.effect)
                    frontier.add(link.effect)
        return cone

    def spacelike_separated(self, a: str, b: str) -> bool:
        """True if a and b are causally independent (spacelike separation).

        Two events are spacelike-separated if neither is in the other's
        causal cone — they cannot have influenced each other.
        """
        return b not in self.causal_cone(a) and a not in self.causal_cone(b) and \
               b not in self.future_cone(a) and a not in self.future_cone(b)

    def causal_invariance_score(self) -> float:
        """Measure how order-independent the causal structure is.

        In Wolfram's framework, causal invariance is the deep property
        that makes the system behave like relativistic spacetime.
        Score of 1.0 = perfectly invariant.
        """
        if len(self._links) < 2:
            return 1.0
        # Count how many pairs of links could be reordered
        # without changing the causal structure
        reorderable = 0
        total_pairs = 0
        link_list = self._links
        for i, la in enumerate(link_list):
            for lb in link_list[i + 1:]:
                total_pairs += 1
                # Two links are reorderable if they don't share endpoints
                if (la.cause != lb.effect and lb.cause != la.effect and
                        la.cause != lb.cause and la.effect != lb.effect):
                    reorderable += 1
        return reorderable / total_pairs if total_pairs > 0 else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [{"id": n.node_id, "agent": n.agent, "action": n.action, "ts": n.ts}
                      for n in self._nodes.values()],
            "links": [{"cause": lk.cause, "effect": lk.effect, "strength": lk.strength}
                      for lk in self._links],
            "causal_invariance": round(self.causal_invariance_score(), 4),
        }


# ═══════════════════════════════════════════════════════════════════
#  4. BRANCHIAL DISTANCE — Divergence between prediction branches
# ═══════════════════════════════════════════════════════════════════

def branchial_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Compute the branchial distance between two prediction branches.

    In Wolfram's framework, branchial distance measures how "far apart"
    two branches are in the multiway graph.  Close branches will merge;
    distant ones represent genuinely different possible futures.

    We use normalized RMSE + Jensen-Shannon divergence as a combined
    metric that captures both magnitude and distributional differences.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if len(a) != len(b) or len(a) == 0:
        return 1.0

    # RMSE component (normalized by range)
    val_range = max(np.ptp(np.concatenate([a, b])), 1e-10)
    rmse = float(np.sqrt(np.mean((a - b) ** 2)) / val_range)

    # Shape component (cosine distance of differenced series)
    da = np.diff(a) if len(a) > 1 else np.array([0.0])
    db = np.diff(b) if len(b) > 1 else np.array([0.0])
    dot = np.dot(da, db)
    norms = np.linalg.norm(da) * np.linalg.norm(db)
    cosine = 1.0 - (dot / max(norms, 1e-10))

    # Combined: geometric mean of magnitude and shape divergence
    return float(min(math.sqrt(rmse * max(cosine, 0.0)), 1.0))


def branchial_entanglement(branches: list[np.ndarray]) -> float:
    """Measure the total entanglement across all branches.

    High entanglement = models agree (branches clustered in branchial
    space).  Low entanglement = divergent futures, high uncertainty.

    Returns 0.0 (fully divergent) to 1.0 (fully entangled/consensus).
    """
    if len(branches) < 2:
        return 1.0
    # Average pairwise branchial distance
    distances = []
    for i, a in enumerate(branches):
        for b in branches[i + 1:]:
            if len(a) == len(b):
                distances.append(branchial_distance(a, b))
    if not distances:
        return 1.0
    avg_dist = float(np.mean(distances))
    return float(max(0.0, 1.0 - avg_dist))


# ═══════════════════════════════════════════════════════════════════
#  5. COMPUTATIONAL IRREDUCIBILITY DETECTOR
# ═══════════════════════════════════════════════════════════════════

@dataclass
class IrreducibilityResult:
    """Result of a computational irreducibility test."""

    is_irreducible: bool
    reducibility_score: float       # 0.0 = fully irreducible, 1.0 = fully reducible
    shortcut_error: float           # Error when trying to shortcut
    full_compute_needed: bool
    method: str = ""
    detail: str = ""


def check_irreducibility(series: np.ndarray, shortcut_horizon: int = 7) -> IrreducibilityResult:
    """Test whether a forecast is computationally irreducible.

    Wolfram's Principle of Computational Irreducibility: many processes
    cannot be predicted faster than by running them.  We test this by
    comparing simple extrapolation (the "shortcut") against the actual
    series — if the shortcut fails badly, the series is irreducible
    and we MUST run the full model council.

    This saves compute: reducible series don't need the full pipeline.
    """
    series = np.asarray(series, dtype=float)
    n = len(series)
    if n < shortcut_horizon + 5:
        return IrreducibilityResult(
            is_irreducible=True,
            reducibility_score=0.0,
            shortcut_error=1.0,
            full_compute_needed=True,
            method="insufficient_data",
            detail=f"Need at least {shortcut_horizon + 5} points, got {n}",
        )

    # Split into train and "future" (which we actually know)
    train = series[:-shortcut_horizon]
    actual = series[-shortcut_horizon:]

    # Shortcut 1: Linear extrapolation (simplest possible prediction)
    x = np.arange(len(train))
    coeffs = np.polyfit(x, train, 1)
    x_future = np.arange(len(train), len(train) + shortcut_horizon)
    linear_pred = np.polyval(coeffs, x_future)
    linear_error = float(np.sqrt(np.mean((actual - linear_pred) ** 2)))

    # Shortcut 2: Last-value repeat (naive)
    naive_pred = np.full(shortcut_horizon, train[-1])
    naive_error = float(np.sqrt(np.mean((actual - naive_pred) ** 2)))

    # Shortcut 3: Seasonal naive (if enough data)
    if len(train) >= shortcut_horizon * 2:
        seasonal_pred = train[-shortcut_horizon:]
        seasonal_error = float(np.sqrt(np.mean((actual - seasonal_pred) ** 2)))
    else:
        seasonal_error = naive_error

    best_shortcut_error = min(linear_error, naive_error, seasonal_error)

    # Normalize by series scale
    scale = max(float(np.std(series)), 1e-10)
    normalized_error = best_shortcut_error / scale

    # Decision: if shortcuts can approximate well, it's reducible
    is_irreducible = normalized_error > 0.5
    reducibility = float(max(0.0, 1.0 - normalized_error))

    if normalized_error < 0.2:
        method = "highly_reducible"
        detail = "Simple heuristics approximate well — skip full pipeline"
    elif normalized_error < 0.5:
        method = "partially_reducible"
        detail = "Some structure capturable by shortcuts — lightweight models may suffice"
    else:
        method = "computationally_irreducible"
        detail = "No shortcut works — full model council required (Wolfram CI)"

    return IrreducibilityResult(
        is_irreducible=is_irreducible,
        reducibility_score=round(reducibility, 4),
        shortcut_error=round(normalized_error, 4),
        full_compute_needed=is_irreducible,
        method=method,
        detail=detail,
    )


# ═══════════════════════════════════════════════════════════════════
#  6. RULIAD EXPLORER — Search the space of all possible rules
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RuliadPoint:
    """A single point in the ruliad — one configuration of the system."""

    config: dict[str, Any]
    score: float
    branch_count: int = 0
    entanglement: float = 0.0


class RuliadExplorer:
    """Systematically explore the space of possible configurations.

    The Ruliad is Wolfram's concept of the entangled limit of all
    possible computations.  Every formal system, every possible rule,
    exists somewhere in the ruliad.  We explore a finite slice of it
    by varying model configs, ensemble weights, and horizons.
    """

    def __init__(self) -> None:
        self._explored: list[RuliadPoint] = []
        self._best: RuliadPoint | None = None

    @property
    def explored_count(self) -> int:
        return len(self._explored)

    @property
    def best_config(self) -> RuliadPoint | None:
        return self._best

    def explore(self, config: dict[str, Any], score: float,
                branch_count: int = 0, entanglement: float = 0.0) -> RuliadPoint:
        """Record one explored configuration in the ruliad."""
        point = RuliadPoint(
            config=config,
            score=score,
            branch_count=branch_count,
            entanglement=entanglement,
        )
        self._explored.append(point)
        if self._best is None or score < self._best.score:
            self._best = point
        return point

    def generate_configs(self, base_config: dict[str, Any],
                         variations: dict[str, list[Any]]) -> list[dict[str, Any]]:
        """Generate configuration grid from base + variations.

        Each combination is a point in the ruliad to explore.
        """
        keys = list(variations.keys())
        values = list(variations.values())
        configs = []
        for combo in itertools.product(*values):
            cfg = dict(base_config)
            for k, v in zip(keys, combo, strict=True):
                cfg[k] = v
            configs.append(cfg)
        return configs

    def pareto_frontier(self) -> list[RuliadPoint]:
        """Return the Pareto-optimal configs (score vs entanglement)."""
        if not self._explored:
            return []
        # Sort by score ascending
        sorted_points = sorted(self._explored, key=lambda p: p.score)
        frontier = [sorted_points[0]]
        best_entanglement = sorted_points[0].entanglement
        for p in sorted_points[1:]:
            if p.entanglement > best_entanglement:
                frontier.append(p)
                best_entanglement = p.entanglement
        return frontier

    def summary(self) -> dict[str, Any]:
        scores = [p.score for p in self._explored]
        return {
            "explored_count": len(self._explored),
            "best_score": round(min(scores), 4) if scores else None,
            "worst_score": round(max(scores), 4) if scores else None,
            "mean_score": round(float(np.mean(scores)), 4) if scores else None,
            "pareto_size": len(self.pareto_frontier()),
            "best_config": self._best.config if self._best else None,
        }


# ═══════════════════════════════════════════════════════════════════
#  7. OBSERVER PROJECTION — Collapse branches to classical view
# ═══════════════════════════════════════════════════════════════════

def observer_projection(multiway: MultiwaySystem,
                        causal: CausalGraph | None = None) -> dict[str, Any]:
    """Project the multiway system into an observer's reference frame.

    Wolfram's Observer Theory: observers are computationally bounded
    entities that sample the ruliad.  They can't see individual branches;
    they see a "classical" average weighted by confidence.

    This is the function that turns the full quantum-like multiway
    state into a single actionable forecast.
    """
    consensus = multiway.consensus_prediction()
    bg = multiway.branchial_graph()

    # Compute entanglement across branches
    preds = [b.predictions for b in multiway.branches]
    entanglement = branchial_entanglement(preds) if len(preds) >= 2 else 1.0

    result: dict[str, Any] = {
        "consensus_forecast": consensus.tolist() if consensus is not None else [],
        "branch_count": multiway.branch_count,
        "entanglement": round(entanglement, 4),
        "merge_events": len(bg.get("merges", [])),
        "branchial_graph_edges": len(bg.get("edges", [])),
        "observation_step": multiway._step,
    }

    # Add causal structure if available
    if causal:
        ci = causal.causal_invariance_score()
        result["causal_invariance"] = round(ci, 4)
        result["causal_events"] = len(causal.nodes)

    # Interpretation
    if entanglement > 0.8:
        result["interpretation"] = "high_consensus"
        result["confidence"] = "strong"
    elif entanglement > 0.5:
        result["interpretation"] = "moderate_agreement"
        result["confidence"] = "moderate"
    else:
        result["interpretation"] = "divergent_futures"
        result["confidence"] = "low — models disagree significantly"

    return result


# ═══════════════════════════════════════════════════════════════════
#  INTEGRATION — Unified Wolfram Physics Engine
# ═══════════════════════════════════════════════════════════════════

class WolframPhysicsEngine:
    """Unified engine integrating all Wolfram Physics concepts.

    Ties together hypergraph state, multiway branching, causal graphs,
    irreducibility detection, and ruliad exploration into a single
    coherent framework for the Future Predictor Council.
    """

    def __init__(self) -> None:
        self.hypergraph = HypergraphState()
        self.multiway = MultiwaySystem()
        self.causal = CausalGraph()
        self.ruliad = RuliadExplorer()
        self._initialized = False

    def initialize(self, agent_codenames: list[str],
                   data_sources: list[str] | None = None) -> dict[str, Any]:
        """Initialize the physics engine with agent topology.

        Creates the initial hypergraph connecting agents and data sources.
        """
        # Build initial hypergraph: each agent connected to data
        sources = data_sources or ["panel_data"]
        for agent in agent_codenames:
            for source in sources:
                self.hypergraph.add_edge(
                    (agent, source),
                    relation="reads",
                )
        # Connect orchestrator to all agents
        if "mc" in agent_codenames:
            for agent in agent_codenames:
                if agent != "mc":
                    self.hypergraph.add_edge(
                        ("mc", agent),
                        relation="orchestrates",
                    )

        self._initialized = True
        return {
            "status": "initialized",
            "nodes": len(self.hypergraph.nodes),
            "edges": self.hypergraph.size,
            "dimension": round(self.hypergraph.dimension_estimate(), 2),
        }

    def record_action(self, agent: str, action: str,
                      caused_by: list[str] | None = None) -> CausalNode:
        """Record an agent action in the causal graph."""
        return self.causal.add_event(agent, action, caused_by)

    def add_prediction_branch(self, model: str, predictions: np.ndarray,
                              confidence: float = 1.0) -> Branch:
        """Add a model's predictions as a multiway branch."""
        return self.multiway.add_branch(model, predictions, confidence)

    def check_irreducibility(self, series: np.ndarray,
                             horizon: int = 7) -> IrreducibilityResult:
        """Test if the series is computationally irreducible."""
        return check_irreducibility(series, horizon)

    def observe(self) -> dict[str, Any]:
        """Observer projection — collapse everything to a single view."""
        projection = observer_projection(self.multiway, self.causal)
        projection["hypergraph"] = {
            "nodes": len(self.hypergraph.nodes),
            "edges": self.hypergraph.size,
            "step": self.hypergraph.step,
            "dimension": round(self.hypergraph.dimension_estimate(), 2),
        }
        projection["ruliad"] = self.ruliad.summary()
        return projection

    def full_state(self) -> dict[str, Any]:
        """Complete system state for debugging/inspection."""
        return {
            "hypergraph": {
                "nodes": sorted(self.hypergraph.nodes),
                "edge_count": self.hypergraph.size,
                "step": self.hypergraph.step,
                "dimension": round(self.hypergraph.dimension_estimate(), 2),
            },
            "multiway": {
                "branch_count": self.multiway.branch_count,
                "branchial_graph": self.multiway.branchial_graph(),
            },
            "causal": self.causal.to_dict(),
            "ruliad": self.ruliad.summary(),
        }
