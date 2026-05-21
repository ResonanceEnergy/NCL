"""
In-Memory Knowledge Graph
===========================

Stores entity-relationship-entity triples extracted from memory units.
Uses NetworkX for graph operations (traversal, community detection,
shortest path). Persisted to JSONL for durability.

This is the lightweight first step — when the graph exceeds ~50K edges,
migrate to Neo4j/Graphiti.

Graph structure:
    - Nodes: entities (people, companies, tickers, concepts)
    - Edges: relationships with predicate, timestamp, source_unit_id, weight
    - Node attributes: entity_type, first_seen, last_seen, mention_count
    - Edge attributes: predicate, timestamps[], weight, source_units[]
"""

import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Any

log = logging.getLogger("ncl.memory.knowledge_graph")


class KnowledgeGraph:
    """
    In-memory knowledge graph backed by NetworkX with JSONL persistence.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser() / "memory" / "knowledge_graph"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.nodes_file = self.data_dir / "nodes.jsonl"
        self.edges_file = self.data_dir / "edges.jsonl"
        self._graph = None  # Lazy init
        self._lock = asyncio.Lock()

    def _ensure_graph(self):
        """Lazily initialize NetworkX graph."""
        if self._graph is not None:
            return True
        try:
            import networkx as nx
            self._nx = nx
            self._graph = nx.DiGraph()
            self._load_from_disk()
            log.info(f"Knowledge graph initialized: {self._graph.number_of_nodes()} nodes, {self._graph.number_of_edges()} edges")
            return True
        except ImportError:
            log.info("networkx not installed — knowledge graph disabled. Install with: pip install networkx")
            return False
        except Exception as e:
            log.warning(f"Knowledge graph init failed: {e}")
            return False

    def _load_from_disk(self):
        """Load persisted nodes and edges from JSONL files."""
        # Load nodes
        if self.nodes_file.exists():
            try:
                with open(self.nodes_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            node_id = data.pop("node_id")
                            self._graph.add_node(node_id, **data)
                        except (json.JSONDecodeError, KeyError):
                            continue
            except Exception as e:
                log.warning(f"Failed to load nodes: {e}")

        # Load edges
        if self.edges_file.exists():
            try:
                with open(self.edges_file, "r") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                            src = data.pop("source")
                            tgt = data.pop("target")
                            self._graph.add_edge(src, tgt, **data)
                        except (json.JSONDecodeError, KeyError):
                            continue
            except Exception as e:
                log.warning(f"Failed to load edges: {e}")

    async def _persist_to_disk(self):
        """Atomically persist graph to JSONL files."""
        if not self._graph:
            return
        try:
            # Persist nodes
            tmp_nodes = str(self.nodes_file) + ".tmp"
            with open(tmp_nodes, "w") as f:
                for node_id, attrs in self._graph.nodes(data=True):
                    record = {"node_id": node_id, **attrs}
                    f.write(json.dumps(record, default=str) + "\n")
            os.replace(tmp_nodes, str(self.nodes_file))

            # Persist edges
            tmp_edges = str(self.edges_file) + ".tmp"
            with open(tmp_edges, "w") as f:
                for src, tgt, attrs in self._graph.edges(data=True):
                    record = {"source": src, "target": tgt, **attrs}
                    f.write(json.dumps(record, default=str) + "\n")
            os.replace(tmp_edges, str(self.edges_file))
        except Exception as e:
            log.error(f"Failed to persist knowledge graph: {e}")
            # Cleanup temp files
            for tmp in [str(self.nodes_file) + ".tmp", str(self.edges_file) + ".tmp"]:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    async def add_entities(self, entities: list[str], source_unit_id: str = "") -> int:
        """
        Add entity nodes to the graph. Updates mention_count if entity exists.

        Returns number of new entities added.
        """
        if not self._ensure_graph():
            return 0

        added = 0
        now = datetime.now(timezone.utc).isoformat()

        async with self._lock:
            for entity in entities:
                if not entity or len(entity) < 2:
                    continue
                entity = entity.strip()

                if self._graph.has_node(entity):
                    # Update existing node
                    self._graph.nodes[entity]["mention_count"] = self._graph.nodes[entity].get("mention_count", 0) + 1
                    self._graph.nodes[entity]["last_seen"] = now
                    if source_unit_id:
                        sources = self._graph.nodes[entity].get("source_units", [])
                        if source_unit_id not in sources:
                            sources.append(source_unit_id)
                            self._graph.nodes[entity]["source_units"] = sources[-20:]  # Cap at 20
                else:
                    # Add new node
                    self._graph.add_node(entity,
                        entity_type=self._infer_entity_type(entity),
                        first_seen=now,
                        last_seen=now,
                        mention_count=1,
                        source_units=[source_unit_id] if source_unit_id else [],
                    )
                    added += 1

            await self._persist_to_disk()

        return added

    async def add_relationships(self, relationships: list[dict], source_unit_id: str = "") -> int:
        """
        Add relationship edges to the graph.

        Each relationship: {"subject": str, "predicate": str, "object": str}
        Merges with existing edges (increments weight, appends timestamp).

        Returns number of new edges added.
        """
        if not self._ensure_graph():
            return 0

        added = 0
        now = datetime.now(timezone.utc).isoformat()

        async with self._lock:
            for rel in relationships:
                subject = rel.get("subject", "").strip()
                predicate = rel.get("predicate", "RELATED_TO").strip()
                obj = rel.get("object", "").strip()

                if not subject or not obj or len(subject) < 2 or len(obj) < 2:
                    continue

                # Ensure nodes exist
                for entity in [subject, obj]:
                    if not self._graph.has_node(entity):
                        self._graph.add_node(entity,
                            entity_type=self._infer_entity_type(entity),
                            first_seen=now,
                            last_seen=now,
                            mention_count=1,
                            source_units=[source_unit_id] if source_unit_id else [],
                        )

                # Add or update edge
                if self._graph.has_edge(subject, obj):
                    edge = self._graph.edges[subject, obj]
                    edge["weight"] = edge.get("weight", 1) + 1
                    timestamps = edge.get("timestamps", [])
                    timestamps.append(now)
                    edge["timestamps"] = timestamps[-10:]  # Keep last 10
                    if source_unit_id:
                        sources = edge.get("source_units", [])
                        if source_unit_id not in sources:
                            sources.append(source_unit_id)
                            edge["source_units"] = sources[-10:]
                else:
                    self._graph.add_edge(subject, obj,
                        predicate=predicate,
                        weight=1,
                        first_seen=now,
                        timestamps=[now],
                        source_units=[source_unit_id] if source_unit_id else [],
                    )
                    added += 1

            await self._persist_to_disk()

        return added

    async def query_entity(self, entity: str, depth: int = 1) -> dict:
        """
        Get an entity and its neighborhood up to given depth.

        Returns dict with entity info, incoming/outgoing relationships,
        and related entities.
        """
        if not self._ensure_graph() or not self._graph.has_node(entity):
            return {"found": False, "entity": entity}

        node_data = dict(self._graph.nodes[entity])

        # Get edges
        outgoing = []
        for _, target, data in self._graph.out_edges(entity, data=True):
            outgoing.append({
                "target": target,
                "predicate": data.get("predicate", "RELATED_TO"),
                "weight": data.get("weight", 1),
            })

        incoming = []
        for source, _, data in self._graph.in_edges(entity, data=True):
            incoming.append({
                "source": source,
                "predicate": data.get("predicate", "RELATED_TO"),
                "weight": data.get("weight", 1),
            })

        # Get N-hop neighbors if depth > 1
        neighbors = set()
        if depth > 1:
            try:
                ego = self._nx.ego_graph(self._graph, entity, radius=depth, undirected=True)
                neighbors = set(ego.nodes()) - {entity}
            except Exception:
                pass

        return {
            "found": True,
            "entity": entity,
            "attributes": node_data,
            "outgoing": sorted(outgoing, key=lambda x: x["weight"], reverse=True),
            "incoming": sorted(incoming, key=lambda x: x["weight"], reverse=True),
            "neighbors": sorted(neighbors)[:50] if neighbors else [],
        }

    async def find_path(self, source: str, target: str) -> Optional[list[str]]:
        """Find shortest path between two entities."""
        if not self._ensure_graph():
            return None
        try:
            path = self._nx.shortest_path(self._graph, source, target)
            return path
        except (self._nx.NetworkXNoPath, self._nx.NodeNotFound):
            return None

    async def get_top_entities(self, n: int = 20) -> list[dict]:
        """Get top entities by mention count."""
        if not self._ensure_graph():
            return []

        entities = []
        for node_id, data in self._graph.nodes(data=True):
            entities.append({
                "entity": node_id,
                "mention_count": data.get("mention_count", 0),
                "entity_type": data.get("entity_type", "unknown"),
                "last_seen": data.get("last_seen", ""),
                "connections": self._graph.degree(node_id),
            })

        entities.sort(key=lambda x: x["mention_count"], reverse=True)
        return entities[:n]

    async def stats(self) -> dict:
        """Return graph statistics."""
        if not self._ensure_graph():
            return {"status": "disabled", "nodes": 0, "edges": 0}

        return {
            "status": "active",
            "nodes": self._graph.number_of_nodes(),
            "edges": self._graph.number_of_edges(),
            "density": round(self._nx.density(self._graph), 4) if self._graph.number_of_nodes() > 1 else 0,
            "components": self._nx.number_weakly_connected_components(self._graph) if self._graph.number_of_nodes() > 0 else 0,
        }

    async def prune_stale(self, days: int = 90) -> dict:
        """Remove nodes not seen in N days and edges with weight 1 older than N days."""
        if not self._ensure_graph():
            return {"pruned_nodes": 0, "pruned_edges": 0}

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        pruned_nodes = 0
        pruned_edges = 0

        async with self._lock:
            # Prune edges
            edges_to_remove = []
            for src, tgt, data in self._graph.edges(data=True):
                if data.get("weight", 1) <= 1:
                    last_ts = data.get("timestamps", [""])[- 1] if data.get("timestamps") else data.get("first_seen", "")
                    if last_ts and last_ts < cutoff:
                        edges_to_remove.append((src, tgt))

            for src, tgt in edges_to_remove:
                self._graph.remove_edge(src, tgt)
                pruned_edges += 1

            # Prune isolated nodes not seen recently
            nodes_to_remove = []
            for node_id, data in self._graph.nodes(data=True):
                if self._graph.degree(node_id) == 0:
                    last_seen = data.get("last_seen", "")
                    if last_seen and last_seen < cutoff:
                        nodes_to_remove.append(node_id)

            for node_id in nodes_to_remove:
                self._graph.remove_node(node_id)
                pruned_nodes += 1

            if pruned_nodes > 0 or pruned_edges > 0:
                await self._persist_to_disk()

        return {"pruned_nodes": pruned_nodes, "pruned_edges": pruned_edges}

    @staticmethod
    def _infer_entity_type(entity: str) -> str:
        """Infer entity type from name pattern."""
        if entity.startswith("$"):
            return "ticker"
        if entity.startswith("#"):
            return "hashtag"
        if "." in entity and not entity.endswith("."):
            return "domain"
        if entity[0].isupper() and " " in entity:
            return "person_or_org"
        return "concept"
