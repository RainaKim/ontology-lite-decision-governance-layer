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
        frontier: set[str] = {decision_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for node_id in frontier:
                visited_ids.add(node_id)
                for edge in self._edges:
                    if edge.from_node == node_id and edge.to_node not in visited_ids:
                        next_frontier.add(edge.to_node)
                        visited_edges.append(edge)
                    elif edge.to_node == node_id and edge.from_node not in visited_ids:
                        next_frontier.add(edge.from_node)
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
