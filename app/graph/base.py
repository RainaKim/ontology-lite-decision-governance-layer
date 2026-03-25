"""
BaseGraphRepository — abstract async interface for graph storage.

All implementations (Neo4j, in-memory) must satisfy this contract.
The validation pipeline and graph reasoning module depend only on this interface,
never on a concrete implementation.

Return types:
  get_governance_context  returns a dict of Node / Edge objects so callers
                          can access .id, .label, .type, .properties, .predicate
                          without knowing the storage backend.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.ontology.models import DecisionGraph, Edge, Node


class BaseGraphRepository(ABC):
    """
    Abstract async repository for the governance graph.

    Implementations
    ---------------
    Neo4jGraphRepository   — production, multi-tenant, vector search
    InMemoryGraphRepository — tests / local dev without a Neo4j instance
    """

    # ------------------------------------------------------------------
    # Schema init
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialize(self, company_id: str) -> None:
        """
        Seed the schema layer (constraints, indexes, MetaClass nodes) for a
        company database.  Idempotent — safe to call on every startup.
        """

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    @abstractmethod
    async def write_node(self, node: Node, company_id: str) -> None:
        """
        Persist a single node.

        Uses MERGE for domain-layer nodes, CREATE for instance-layer nodes,
        MERGE-on-content-hash for Chunk nodes.
        """

    @abstractmethod
    async def write_edge(self, edge: Edge, company_id: str) -> None:
        """Persist a typed relationship.  Always MERGE (idempotent)."""

    @abstractmethod
    async def write_graph(self, graph: DecisionGraph, company_id: str) -> None:
        """
        Persist a complete DecisionGraph (all nodes then all edges) in a single
        operation.  Atomic at the session level for Neo4j.
        """

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_governance_context(
        self,
        decision_id: str,
        depth: int = 2,
    ) -> dict:
        """
        Return a 2-hop governance subgraph rooted at *decision_id*.

        Return shape
        ------------
        {
            "decision":  Node | None,
            "actors":    list[Node],   # NodeType.ACTOR within depth
            "policies":  list[Node],   # NodeType.RULE within depth
            "risks":     list[Node],   # NodeType.RISK within depth
            "edges":     list[Edge],
            "metadata": {
                "traversal_depth": int,
                "node_count":      int,
                "edge_count":      int,
            },
        }
        """

    @abstractmethod
    async def get_node(
        self,
        node_id: str,
        company_id: str,
    ) -> Optional[dict]:
        """Fetch a single node's property dict by ID.  Returns None if absent."""

    @abstractmethod
    async def cypher_read(
        self,
        query: str,
        params: Optional[dict],
        company_id: str,
    ) -> list[dict]:
        """
        Execute a read-only Cypher query and return results as plain dicts.

        Used by the governance agent's query_graph tool (Step 9).
        """

    @abstractmethod
    async def get_all_node_ids(
        self,
        company_id: str,
    ) -> dict[str, str]:
        """
        Return a mapping from semantic_id suffix → full node_id for all stored nodes.

        The key is the last segment of the node ID (after the second colon),
        lowercased.  Used by the transform pipeline to build a global node map
        that includes seeded nodes.

        Example return: {"revenue_growth": "nexus:goal:revenue_growth", "cfo": "nexus:actor:cfo"}
        """

    @abstractmethod
    async def vector_search(
        self,
        embedding: list[float],
        top_k: int = 5,
        company_id: str = "default",
        label: str = "Chunk",
        index_name: str = "chunk_embeddings",
    ) -> list[dict]:
        """
        Nearest-neighbour search over a Neo4j vector index.

        Returns list of {"node": <property dict>, "score": float}.
        """

    # ------------------------------------------------------------------
    # Graph RAG query methods (Step 8c)
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_all_rules(
        self,
        company_id: str,
    ) -> list[dict]:
        """
        Return all active Rule nodes with conditions, consequences,
        and GOVERNED_BY goals.

        Returns list of dicts:
            {rule_id, label, properties, goals: [...], approvers: [...]}
        """

    @abstractmethod
    async def get_approval_chain_for_rules(
        self,
        rule_ids: list[str],
        company_id: str,
    ) -> list[dict]:
        """
        Traverse REQUIRES_APPROVAL_FROM + ESCALATES_TO for given triggered rules.

        Returns list of dicts:
            {rule_id, actor_id, actor_label, escalation_chain: [...]}
        """

    @abstractmethod
    async def get_goal_conflicts(
        self,
        goal_ids: list[str],
        company_id: str,
    ) -> list[dict]:
        """
        Find CONFLICTS_WITH edges between the given goals.

        Returns list of dicts:
            {goal1_id, goal2_id, goal1_label, goal2_label, conflict_label}
        """

    @abstractmethod
    async def get_gaps_for_rules(
        self,
        rule_ids: list[str],
        company_id: str,
    ) -> list[dict]:
        """
        Find HAS_GAP edges from triggered rules.

        Returns list of dicts:
            {rule_id, gap_id, gap_label, gap_properties}
        """

    @abstractmethod
    async def search_similar_decisions(
        self,
        decision_embedding: list[float],
        company_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Find similar past decisions via vector search, then enrich with
        their triggered rules, approvers, and outcomes.

        Returns list of dicts: each is a vector search result enriched
        with governance context.
        """

    @abstractmethod
    async def safe_cypher_read(
        self,
        query: str,
        params: Optional[dict] = None,
        company_id: str = "default",
        result_limit: int = 50,
    ) -> list[dict]:
        """
        Execute a read-only Cypher query with safety constraints.

        Safety guarantees:
        1. Only MATCH, CALL, RETURN, WITH, WHERE, ORDER BY, UNWIND,
           OPTIONAL MATCH are allowed.
           Rejects: CREATE, MERGE, SET, DELETE, DETACH, REMOVE, DROP,
           FOREACH, LOAD CSV, CALL {...} subqueries.
        2. Tenant isolation is enforced via database routing
           (get_company_database(company_id)), not via query parameters.
        3. LIMIT is enforced: if the query contains no LIMIT, one is appended.
           If it contains a LIMIT > result_limit, it is clamped.
        4. Database routing uses get_company_database(company_id).

        Returns:
            list of dicts (property maps from Neo4j records)

        Raises:
            ValueError: if query contains mutating keywords
        """
