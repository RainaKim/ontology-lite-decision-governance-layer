"""
In-memory graph repository — development / test implementation.

Implements BaseGraphRepository with plain Python dicts and lists.
No external dependencies.  Not persistent across restarts.

Use this instead of Neo4jGraphRepository when:
  - Running unit tests (no Neo4j required)
  - Local dev without a Docker instance running
  - Integration tests that don't exercise the graph backend directly
"""

from __future__ import annotations

from typing import Optional

from app.graph.base import BaseGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import DecisionGraph, Edge, Node
from app.ontology.node_types import NodeType


class InMemoryGraphRepository(BaseGraphRepository):
    """
    Simple dict-backed implementation of BaseGraphRepository.

    Storage
    -------
    _nodes  — dict[node_id, Node]  (keyed by node.id)
    _edges  — list[Edge]
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self.__adjacency_cache: dict[str, list[Edge]] | None = None
        self.__adjacency_dirty: bool = True

    @property
    def _adjacency(self) -> dict[str, list[Edge]]:
        """Lazily built adjacency index: node_id -> list of edges."""
        if self.__adjacency_cache is None or self.__adjacency_dirty:
            index: dict[str, list[Edge]] = {}
            for edge in self._edges:
                index.setdefault(edge.from_node, []).append(edge)
                index.setdefault(edge.to_node, []).append(edge)
            self.__adjacency_cache = index
            self.__adjacency_dirty = False
        return self.__adjacency_cache

    # ------------------------------------------------------------------
    # Schema init (no-op — nothing to seed in memory)
    # ------------------------------------------------------------------

    async def initialize(self, company_id: str) -> None:
        """No-op.  In-memory store needs no schema setup."""

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def write_node(self, node: Node, company_id: str) -> None:
        """Upsert a node by ID (last write wins)."""
        self._nodes[node.id] = node

    async def write_edge(self, edge: Edge, company_id: str) -> None:
        """Append an edge.  Does not deduplicate."""
        self._edges.append(edge)
        self.__adjacency_dirty = True

    async def write_graph(self, graph: DecisionGraph, company_id: str) -> None:
        """Write all nodes then all edges."""
        for node in graph.nodes:
            await self.write_node(node, company_id)
        for edge in graph.edges:
            await self.write_edge(edge, company_id)

    # ------------------------------------------------------------------
    # Read: governance context (BFS traversal)
    # ------------------------------------------------------------------

    async def get_governance_context(
        self,
        decision_id: str,
        depth: int = 2,
    ) -> dict:
        """BFS up to *depth* hops from *decision_id*."""
        if decision_id not in self._nodes:
            return {
                "decision": None,
                "actors": [],
                "policies": [],
                "risks": [],
                "edges": [],
                "metadata": {"error": "Decision not found"},
            }

        visited_ids: set[str] = set()
        visited_edges: list[Edge] = []
        seen_edge_keys: set[tuple] = set()
        frontier: set[str] = {decision_id}
        adjacency = self._adjacency

        for _ in range(depth):
            next_frontier: set[str] = set()
            for node_id in frontier:
                visited_ids.add(node_id)
                for edge in adjacency.get(node_id, []):
                    edge_key = (edge.from_node, edge.predicate, edge.to_node)
                    if edge.from_node == node_id and edge.to_node not in visited_ids:
                        next_frontier.add(edge.to_node)
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            visited_edges.append(edge)
                    elif edge.to_node == node_id and edge.from_node not in visited_ids:
                        next_frontier.add(edge.from_node)
                        if edge_key not in seen_edge_keys:
                            seen_edge_keys.add(edge_key)
                            visited_edges.append(edge)
            frontier = next_frontier
            if not frontier:
                break

        visited_ids.update(frontier)

        decision_node = self._nodes.get(decision_id)
        neighbours = [
            self._nodes[nid]
            for nid in visited_ids
            if nid != decision_id and nid in self._nodes
        ]

        return {
            "decision": decision_node,
            "actors": [n for n in neighbours if n.type == NodeType.ACTOR],
            "policies": [n for n in neighbours if n.type == NodeType.RULE],
            "risks": [n for n in neighbours if n.type == NodeType.RISK],
            "edges": visited_edges,
            "metadata": {
                "traversal_depth": depth,
                "node_count": len(visited_ids),
                "edge_count": len(visited_edges),
            },
        }

    # ------------------------------------------------------------------
    # Read: single node
    # ------------------------------------------------------------------

    async def get_node(self, node_id: str, company_id: str) -> Optional[dict]:
        """Return a node's property dict, or None if not found."""
        node = self._nodes.get(node_id)
        if node is None:
            return None
        return {"id": node.id, "label": node.label, "node_type": node.type, **node.properties}

    # ------------------------------------------------------------------
    # Read: Cypher (not supported)
    # ------------------------------------------------------------------

    async def cypher_read(
        self,
        query: str,
        params: Optional[dict] = None,
        company_id: str = "default",
    ) -> list[dict]:
        """Not supported by the in-memory backend."""
        raise NotImplementedError(
            "cypher_read is only available on Neo4jGraphRepository. "
            "Use InMemoryGraphRepository for unit tests that don't need Cypher."
        )

    # ------------------------------------------------------------------
    # Read: all node IDs (for global edge resolution)
    # ------------------------------------------------------------------

    async def get_all_node_ids(self, company_id: str) -> dict[str, str]:
        """
        Return semantic_id_suffix → full_node_id for all stored nodes.

        Filters to nodes whose ID starts with the given company_id prefix.
        """
        result: dict[str, str] = {}
        prefix = f"{company_id}:"
        for node_id in self._nodes:
            if node_id.startswith(prefix):
                # node ID format: {company_id}:{type}:{semantic_id}
                parts = node_id.split(":")
                if len(parts) >= 3:
                    semantic_suffix = parts[-1].lower()
                    result[semantic_suffix] = node_id
        return result

    # ------------------------------------------------------------------
    # Read: vector search (not supported)
    # ------------------------------------------------------------------

    async def vector_search(
        self,
        embedding: list[float],
        top_k: int = 5,
        company_id: str = "default",
        label: str = "Chunk",
        index_name: str = "chunk_embeddings",
    ) -> list[dict]:
        """Not supported by the in-memory backend."""
        raise NotImplementedError(
            "vector_search is only available on Neo4jGraphRepository."
        )

    # ------------------------------------------------------------------
    # Graph RAG query methods (Step 8c)
    # ------------------------------------------------------------------

    async def get_all_rules(self, company_id: str) -> list[dict]:
        """Return all Rule nodes with GOVERNED_BY goals and REQUIRES_APPROVAL_FROM actors."""
        prefix = f"{company_id}:"
        rule_nodes = [
            n for n in self._nodes.values()
            if n.type == NodeType.RULE and n.id.startswith(prefix)
        ]
        results = []
        for rule in rule_nodes:
            goals = []
            approvers = []
            for edge in self._edges:
                if edge.from_node == rule.id:
                    pred = edge.predicate if isinstance(edge.predicate, str) else edge.predicate
                    target = self._nodes.get(edge.to_node)
                    if pred == EdgePredicate.GOVERNED_BY.value and target:
                        goals.append({"id": target.id, "label": target.label})
                    elif pred == EdgePredicate.REQUIRES_APPROVAL_FROM.value and target:
                        approvers.append({"id": target.id, "label": target.label})
            results.append({
                "rule_id": rule.id,
                "label": rule.label,
                "properties": rule.properties,
                "goals": goals,
                "approvers": approvers,
            })
        return results

    async def get_approval_chain_for_rules(
        self, rule_ids: list[str], company_id: str
    ) -> list[dict]:
        """Traverse REQUIRES_APPROVAL_FROM + ESCALATES_TO edges."""
        results = []
        for rule_id in rule_ids:
            # Find REQUIRES_APPROVAL_FROM edges from this rule
            for edge in self._edges:
                pred = edge.predicate if isinstance(edge.predicate, str) else edge.predicate
                if (
                    edge.from_node == rule_id
                    and pred == EdgePredicate.REQUIRES_APPROVAL_FROM.value
                ):
                    actor = self._nodes.get(edge.to_node)
                    if not actor:
                        continue
                    # Traverse ESCALATES_TO chain (up to 3 hops)
                    escalation = []
                    current_id = actor.id
                    for _ in range(3):
                        found_next = False
                        for e2 in self._edges:
                            p2 = e2.predicate if isinstance(e2.predicate, str) else e2.predicate
                            if (
                                e2.from_node == current_id
                                and p2 == EdgePredicate.ESCALATES_TO.value
                            ):
                                higher = self._nodes.get(e2.to_node)
                                if higher and higher.label not in escalation:
                                    escalation.append(higher.label)
                                    current_id = higher.id
                                    found_next = True
                                    break
                        if not found_next:
                            break
                    results.append({
                        "rule_id": rule_id,
                        "actor_id": actor.id,
                        "actor_label": actor.label,
                        "escalation_chain": escalation,
                    })
        return results

    async def get_goal_conflicts(
        self, goal_ids: list[str], company_id: str
    ) -> list[dict]:
        """Find CONFLICTS_WITH edges between the given goals."""
        results = []
        seen = set()
        for edge in self._edges:
            pred = edge.predicate if isinstance(edge.predicate, str) else edge.predicate
            if pred == EdgePredicate.CONFLICTS_WITH.value:
                g1_id = edge.from_node
                g2_id = edge.to_node
                if g1_id in goal_ids or g2_id in goal_ids:
                    # Normalize order for dedup
                    key = tuple(sorted([g1_id, g2_id]))
                    if key not in seen:
                        seen.add(key)
                        g1 = self._nodes.get(g1_id)
                        g2 = self._nodes.get(g2_id)
                        results.append({
                            "goal1_id": key[0],
                            "goal2_id": key[1],
                            "goal1_label": g1.label if g1 else key[0],
                            "goal2_label": g2.label if g2 else key[1],
                            "conflict_label": "",
                        })
        return results

    async def get_gaps_for_rules(
        self, rule_ids: list[str], company_id: str
    ) -> list[dict]:
        """Find HAS_GAP edges from triggered rules."""
        results = []
        for edge in self._edges:
            pred = edge.predicate if isinstance(edge.predicate, str) else edge.predicate
            if (
                pred == EdgePredicate.HAS_GAP.value
                and edge.from_node in rule_ids
            ):
                gap = self._nodes.get(edge.to_node)
                if gap:
                    results.append({
                        "rule_id": edge.from_node,
                        "gap_id": gap.id,
                        "gap_label": gap.label,
                        "gap_properties": gap.properties,
                    })
        return results

    async def search_similar_decisions(
        self,
        decision_embedding: list[float],
        company_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Not supported by the in-memory backend (no vector index)."""
        raise NotImplementedError(
            "search_similar_decisions is only available on Neo4jGraphRepository."
        )

    async def safe_cypher_read(
        self,
        query: str,
        params: Optional[dict] = None,
        company_id: str = "default",
        result_limit: int = 50,
    ) -> list[dict]:
        """Not supported by the in-memory backend."""
        raise NotImplementedError(
            "safe_cypher_read is only available on Neo4jGraphRepository. "
            "Use InMemoryGraphRepository for unit tests that don't need Cypher."
        )

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    def get_nodes_by_type(self, node_type: NodeType) -> list[Node]:
        """Return all nodes of the given type (test helper)."""
        type_val = node_type.value if hasattr(node_type, "value") else node_type
        return [n for n in self._nodes.values() if n.type == type_val]

    def get_edges_by_predicate(self, predicate: EdgePredicate) -> list[Edge]:
        """Return all edges with the given predicate (test helper)."""
        pred_val = predicate.value if hasattr(predicate, "value") else predicate
        return [e for e in self._edges if e.predicate == pred_val]

    async def clear(self) -> None:
        """Reset store to empty (test helper)."""
        self._nodes.clear()
        self._edges.clear()
        self.__adjacency_cache = None
        self.__adjacency_dirty = True
