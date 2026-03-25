"""
Neo4j graph repository — async implementation.

Implements BaseGraphRepository against a Neo4j 5.11+ instance using the
async driver.  One database per company (multi-tenant isolation).

Usage
-----
    repo = Neo4jGraphRepository()
    await repo.initialize("nexus_analytics")   # seed schema + constraints
    await repo.write_graph(decision_graph, "nexus_analytics")
    await repo.close()
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.config.neo4j import (
    NEO4J_URI,
    NEO4J_USERNAME,
    NEO4J_PASSWORD,
    get_company_database,
)
from app.graph.base import BaseGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.init_schema import get_schema_seed_statements
from app.ontology.models import DecisionGraph, Edge, Node
from app.ontology.node_types import MergeStrategy, NodeType, get_merge_strategy, get_neo4j_labels

logger = logging.getLogger(__name__)


class Neo4jGraphRepository(BaseGraphRepository):
    """
    Async Neo4j-backed graph repository.

    Thread-safe: the async driver manages a connection pool internally.
    One instance per application; per-request database routing via
    get_company_database(company_id).
    """

    def __init__(self) -> None:
        # Lazy import keeps startup fast when Neo4j is not configured.
        from neo4j import AsyncGraphDatabase

        self._driver = AsyncGraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USERNAME, NEO4J_PASSWORD),
        )
        logger.info(f"Neo4jGraphRepository connected to {NEO4J_URI}")

    async def close(self) -> None:
        """Close the driver and release all connections."""
        await self._driver.close()

    # ------------------------------------------------------------------
    # Schema init
    # ------------------------------------------------------------------

    async def initialize(self, company_id: str) -> None:
        """
        Seed schema layer for a company database.

        Runs all constraint / index / MetaClass / OntologyClass MERGE statements.
        Idempotent — safe to call on every startup.
        """
        database = get_company_database(company_id)
        statements = get_schema_seed_statements()

        async with self._driver.session(database=database) as session:
            for statement in statements:
                try:
                    await session.run(statement)
                except Exception as exc:
                    logger.warning(
                        f"Schema init statement skipped: {exc} | "
                        f"stmt: {statement[:80]}"
                    )

        logger.info(
            f"Schema initialized for company={company_id!r} "
            f"db={database!r} ({len(statements)} statements)"
        )

    # ------------------------------------------------------------------
    # Single-node write
    # ------------------------------------------------------------------

    async def write_node(self, node: Node, company_id: str) -> None:
        """
        Write a single node.

        MERGE for domain-layer nodes (stable IDs).
        CREATE for instance-layer nodes (always new).
        MERGE on content_hash for Chunk nodes.
        """
        database = get_company_database(company_id)
        strategy = get_merge_strategy(node.type)
        labels = ":".join(get_neo4j_labels(NodeType(node.type)))
        props = _build_node_props(node)

        async with self._driver.session(database=database) as session:
            if strategy == MergeStrategy.MERGE_ON_HASH:
                content_hash = node.properties.get("content_hash") or node.id
                await session.run(
                    f"MERGE (n:{labels} {{content_hash: $hash}}) SET n += $props",
                    hash=content_hash,
                    props=props,
                )
            elif strategy == MergeStrategy.MERGE:
                await session.run(
                    f"MERGE (n:{labels} {{id: $id}}) SET n += $props",
                    id=node.id,
                    props=props,
                )
            else:
                await session.run(f"CREATE (n:{labels} $props)", props=props)

    # ------------------------------------------------------------------
    # Single-edge write
    # ------------------------------------------------------------------

    async def write_edge(self, edge: Edge, company_id: str) -> None:
        """Write a typed relationship.  Always MERGE (idempotent)."""
        database = get_company_database(company_id)
        rel_type = (
            edge.predicate if isinstance(edge.predicate, str) else edge.predicate.value
        )
        edge_props = edge.properties or {}

        async with self._driver.session(database=database) as session:
            await session.run(
                "MATCH (a {id: $from_id}), (b {id: $to_id}) "
                f"MERGE (a)-[r:{rel_type}]->(b) "
                "SET r += $props",
                from_id=edge.from_node,
                to_id=edge.to_node,
                props=edge_props,
            )

    # ------------------------------------------------------------------
    # Bulk graph write
    # ------------------------------------------------------------------

    async def write_graph(self, graph: DecisionGraph, company_id: str) -> None:
        """
        Write a complete DecisionGraph in a single session.

        Writes all nodes first, then all edges.
        Node writes respect MERGE/CREATE strategy per type.
        Edge writes are always MERGE.
        """
        database = get_company_database(company_id)

        async with self._driver.session(database=database) as session:
            for node in graph.nodes:
                await _write_node_in_session(session, node)
            for edge in graph.edges:
                await _write_edge_in_session(session, edge)

        logger.info(
            f"Wrote graph: decision={graph.decision_id!r} "
            f"nodes={graph.node_count} edges={graph.edge_count} "
            f"db={database!r}"
        )

    # ------------------------------------------------------------------
    # Read: governance context (2-hop traversal)
    # ------------------------------------------------------------------

    async def get_governance_context(
        self,
        decision_id: str,
        depth: int = 2,
    ) -> dict:
        """
        Return all nodes/edges within *depth* hops of *decision_id*.

        Reconstructs Node and Edge objects from Neo4j records so the caller
        can access .id, .label, .type, .properties, .predicate.
        """
        company_id = decision_id.split(":")[0]
        database = get_company_database(company_id)

        cypher = """
        MATCH (d {id: $id})
        OPTIONAL MATCH (d)-[r1]-(n1)
        OPTIONAL MATCH (n1)-[r2]-(n2)
          WHERE n2.id <> $id
        RETURN
          d,
          collect(DISTINCT n1) AS level1,
          collect(DISTINCT n2) AS level2,
          collect(DISTINCT {
            from_id: CASE WHEN startNode(r1).id IS NOT NULL THEN startNode(r1).id ELSE '' END,
            to_id:   CASE WHEN endNode(r1).id   IS NOT NULL THEN endNode(r1).id   ELSE '' END,
            type:    type(r1),
            props:   properties(r1)
          }) AS edges1,
          collect(DISTINCT {
            from_id: CASE WHEN startNode(r2).id IS NOT NULL THEN startNode(r2).id ELSE '' END,
            to_id:   CASE WHEN endNode(r2).id   IS NOT NULL THEN endNode(r2).id   ELSE '' END,
            type:    type(r2),
            props:   properties(r2)
          }) AS edges2
        """

        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, id=decision_id)
            record = await result.single()

        if not record or record["d"] is None:
            return {
                "decision": None,
                "actors": [],
                "policies": [],
                "risks": [],
                "edges": [],
                "metadata": {"error": "Decision not found"},
            }

        # Collect all Neo4j nodes
        all_neo4j_nodes = [record["d"]]
        all_neo4j_nodes += [n for n in record["level1"] if n is not None]
        if depth >= 2:
            all_neo4j_nodes += [n for n in record["level2"] if n is not None]

        # Convert Neo4j nodes → Node objects
        node_map: dict[str, Node] = {}
        for neo_node in all_neo4j_nodes:
            if neo_node is None:
                continue
            props = dict(neo_node)
            node_id = props.get("id", "")
            if not node_id or node_id in node_map:
                continue
            node_type_str = props.pop("node_type", "Decision")
            label = props.pop("label", node_id)
            confidence = props.pop("confidence", None)
            source_chunk_ids = props.pop("source_chunk_ids", [])
            embedding = props.pop("embedding", None)
            props.pop("id", None)
            try:
                node_type = NodeType(node_type_str)
            except ValueError:
                node_type = NodeType.DECISION
            node_map[node_id] = Node(
                id=node_id,
                type=node_type,
                label=label,
                properties=props,
                confidence=confidence,
                source_chunk_ids=source_chunk_ids or [],
                embedding=embedding,
            )

        decision_node = node_map.get(decision_id)

        # Build edge list (deduplicated)
        seen_edges: set[tuple] = set()
        edges: list[Edge] = []
        for raw_list in (record["edges1"], record["edges2"]):
            for raw in raw_list:
                if not raw or not raw.get("type"):
                    continue
                key = (raw["from_id"], raw["to_id"], raw["type"])
                if key in seen_edges or not raw["from_id"] or not raw["to_id"]:
                    continue
                seen_edges.add(key)
                try:
                    predicate = EdgePredicate(raw["type"])
                except ValueError:
                    continue
                edges.append(
                    Edge(
                        from_node=raw["from_id"],
                        to_node=raw["to_id"],
                        predicate=predicate,
                        properties=dict(raw.get("props") or {}),
                    )
                )

        neighbour_nodes = [n for nid, n in node_map.items() if nid != decision_id]
        return {
            "decision": decision_node,
            "actors": [n for n in neighbour_nodes if n.type == NodeType.ACTOR],
            "policies": [n for n in neighbour_nodes if n.type == NodeType.RULE],
            "risks": [n for n in neighbour_nodes if n.type == NodeType.RISK],
            "edges": edges,
            "metadata": {
                "traversal_depth": depth,
                "node_count": len(node_map),
                "edge_count": len(edges),
            },
        }

    # ------------------------------------------------------------------
    # Read: single node
    # ------------------------------------------------------------------

    async def get_node(self, node_id: str, company_id: str) -> Optional[dict]:
        """Fetch a single node's property dict by ID.  Returns None if absent."""
        database = get_company_database(company_id)
        async with self._driver.session(database=database) as session:
            result = await session.run(
                "MATCH (n {id: $id}) RETURN properties(n) AS props LIMIT 1",
                id=node_id,
            )
            record = await result.single()
        return dict(record["props"]) if record else None

    # ------------------------------------------------------------------
    # Read: arbitrary Cypher
    # ------------------------------------------------------------------

    async def cypher_read(
        self,
        query: str,
        params: Optional[dict] = None,
        company_id: str = "default",
    ) -> list[dict]:
        """
        Execute a read-only Cypher query and return results as dicts.

        Used by the governance agent's query_graph tool (Step 9).
        """
        database = get_company_database(company_id)
        async with self._driver.session(database=database) as session:
            result = await session.run(query, **(params or {}))
            return [dict(record) async for record in result]

    # ------------------------------------------------------------------
    # Read: all node IDs (for global edge resolution)
    # ------------------------------------------------------------------

    async def get_all_node_ids(self, company_id: str) -> dict[str, str]:
        """
        Return semantic_id_suffix → full_node_id for all stored nodes.

        Queries Neo4j for all nodes with an id property starting with the
        company prefix.  Used by the transform pipeline to build a global
        node map that includes seeded nodes.
        """
        database = get_company_database(company_id)
        prefix = f"{company_id}:"
        cypher = (
            "MATCH (n) WHERE n.id STARTS WITH $prefix "
            "RETURN n.id AS node_id"
        )
        result: dict[str, str] = {}
        async with self._driver.session(database=database) as session:
            records = await session.run(cypher, prefix=prefix)
            async for record in records:
                node_id = record["node_id"]
                parts = node_id.split(":")
                if len(parts) >= 3:
                    semantic_suffix = parts[-1].lower()
                    result[semantic_suffix] = node_id
        return result

    # ------------------------------------------------------------------
    # Read: vector search
    # ------------------------------------------------------------------

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
        database = get_company_database(company_id)
        cypher = (
            f"CALL db.index.vector.queryNodes('{index_name}', $k, $embedding) "
            "YIELD node, score "
            "RETURN properties(node) AS node, score"
        )
        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, k=top_k, embedding=embedding)
            return [
                {"node": dict(r["node"]), "score": r["score"]}
                async for r in result
            ]

    # ------------------------------------------------------------------
    # Graph RAG query methods (Step 8c)
    # ------------------------------------------------------------------

    async def get_rules_for_decision(self, company_id: str) -> list[dict]:
        """Return all active Rule nodes with GOVERNED_BY goals and REQUIRES_APPROVAL_FROM actors."""
        database = get_company_database(company_id)
        prefix = f"{company_id}:"
        cypher = (
            "MATCH (r:Rule) WHERE r.id STARTS WITH $prefix "
            "OPTIONAL MATCH (r)-[:GOVERNED_BY]->(g:Goal) "
            "OPTIONAL MATCH (r)-[:REQUIRES_APPROVAL_FROM]->(a:Actor) "
            "RETURN r.id AS rule_id, r.label AS label, properties(r) AS properties, "
            "collect(DISTINCT {id: g.id, label: g.label}) AS goals, "
            "collect(DISTINCT {id: a.id, label: a.label}) AS approvers"
        )
        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, prefix=prefix)
            records = []
            async for record in result:
                goals = [g for g in record["goals"] if g.get("id") is not None]
                approvers = [a for a in record["approvers"] if a.get("id") is not None]
                records.append({
                    "rule_id": record["rule_id"],
                    "label": record["label"],
                    "properties": dict(record["properties"]) if record["properties"] else {},
                    "goals": goals,
                    "approvers": approvers,
                })
            return records

    async def get_approval_chain_for_rules(
        self, rule_ids: list[str], company_id: str
    ) -> list[dict]:
        """Traverse REQUIRES_APPROVAL_FROM + ESCALATES_TO for given triggered rules."""
        database = get_company_database(company_id)
        cypher = (
            "MATCH (r:Rule)-[:REQUIRES_APPROVAL_FROM]->(a:Actor) "
            "WHERE r.id IN $rule_ids "
            "OPTIONAL MATCH (a)-[:ESCALATES_TO*1..3]->(higher:Actor) "
            "RETURN r.id AS rule_id, a.id AS actor_id, a.label AS actor_label, "
            "collect(DISTINCT higher.label) AS escalation_chain"
        )
        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, rule_ids=rule_ids)
            records = []
            async for record in result:
                escalation = [e for e in record["escalation_chain"] if e is not None]
                records.append({
                    "rule_id": record["rule_id"],
                    "actor_id": record["actor_id"],
                    "actor_label": record["actor_label"],
                    "escalation_chain": escalation,
                })
            return records

    async def get_goal_conflicts(
        self, goal_ids: list[str], company_id: str
    ) -> list[dict]:
        """Find CONFLICTS_WITH edges between the given goals."""
        database = get_company_database(company_id)
        # Try both patterns: direct Goal-Goal and Goal-Conflict-Goal (reified)
        cypher = (
            "MATCH (g1:Goal)-[:CONFLICTS_WITH]-(g2:Goal) "
            "WHERE g1.id IN $goal_ids AND g1.id < g2.id "
            "RETURN g1.id AS goal1_id, g2.id AS goal2_id, "
            "g1.label AS goal1_label, g2.label AS goal2_label, "
            "'' AS conflict_label "
            "UNION "
            "MATCH (g1:Goal)-[:CONFLICTS_WITH]->(c:Conflict)<-[:CONFLICTS_WITH]-(g2:Goal) "
            "WHERE g1.id IN $goal_ids AND g1.id < g2.id "
            "RETURN g1.id AS goal1_id, g2.id AS goal2_id, "
            "g1.label AS goal1_label, g2.label AS goal2_label, "
            "c.label AS conflict_label"
        )
        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, goal_ids=goal_ids)
            records = []
            seen = set()
            async for record in result:
                key = (record["goal1_id"], record["goal2_id"])
                if key not in seen:
                    seen.add(key)
                    records.append({
                        "goal1_id": record["goal1_id"],
                        "goal2_id": record["goal2_id"],
                        "goal1_label": record["goal1_label"],
                        "goal2_label": record["goal2_label"],
                        "conflict_label": record["conflict_label"] or "",
                    })
            return records

    async def get_gaps_for_rules(
        self, rule_ids: list[str], company_id: str
    ) -> list[dict]:
        """Find HAS_GAP edges from triggered rules."""
        database = get_company_database(company_id)
        cypher = (
            "MATCH (r)-[:HAS_GAP]->(gap:Gap) "
            "WHERE r.id IN $rule_ids "
            "RETURN r.id AS rule_id, gap.id AS gap_id, gap.label AS gap_label, "
            "properties(gap) AS gap_properties"
        )
        async with self._driver.session(database=database) as session:
            result = await session.run(cypher, rule_ids=rule_ids)
            records = []
            async for record in result:
                records.append({
                    "rule_id": record["rule_id"],
                    "gap_id": record["gap_id"],
                    "gap_label": record["gap_label"],
                    "gap_properties": dict(record["gap_properties"]) if record["gap_properties"] else {},
                })
            return records

    async def search_similar_decisions(
        self,
        decision_embedding: list[float],
        company_id: str,
        top_k: int = 5,
    ) -> list[dict]:
        """
        Find similar past decisions via vector search, then enrich with
        their triggered rules, approvers, and outcomes.
        """
        similar = await self.vector_search(
            decision_embedding,
            top_k,
            company_id,
            label="Decision",
            index_name="decision_embeddings",
        )
        enriched = []
        for item in similar:
            node_props = item.get("node", {})
            node_id = node_props.get("id", "")
            try:
                ctx = await self.get_governance_context(node_id, depth=1)
            except Exception:
                ctx = {}
            enriched.append({
                **node_props,
                "score": item.get("score", 0.0),
                "context": ctx,
            })
        return enriched

    # ------------------------------------------------------------------
    # Safe Cypher read (Step 8d)
    # ------------------------------------------------------------------

    _MUTATING_KEYWORDS = re.compile(
        r'\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|CALL\s*\{)\b',
        re.IGNORECASE,
    )
    _LIMIT_PATTERN = re.compile(r'\bLIMIT\s+(\d+)\b', re.IGNORECASE)

    async def safe_cypher_read(
        self,
        query: str,
        params: Optional[dict] = None,
        company_id: str = "default",
        result_limit: int = 50,
    ) -> list[dict]:
        """Execute a read-only Cypher query with safety constraints."""
        # 1. Reject mutations
        if self._MUTATING_KEYWORDS.search(query):
            raise ValueError(
                "Mutating Cypher operations are not allowed in safe_cypher_read"
            )

        # 2. Enforce LIMIT
        limit_match = self._LIMIT_PATTERN.search(query)
        if limit_match:
            existing_limit = int(limit_match.group(1))
            if existing_limit > result_limit:
                query = self._LIMIT_PATTERN.sub(f"LIMIT {result_limit}", query)
        else:
            query = query.rstrip().rstrip(";") + f" LIMIT {result_limit}"

        # 3. Inject company_id as parameter
        safe_params = dict(params or {})
        safe_params["_company_id"] = company_id

        # 4. Route to correct database
        return await self.cypher_read(query, safe_params, company_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_node_props(node: Node) -> dict[str, Any]:
    """Flatten a Node into a Neo4j-compatible property dict."""
    props: dict[str, Any] = {
        "id": node.id,
        "label": node.label,
        "node_type": node.type if isinstance(node.type, str) else node.type.value,
        **node.properties,
    }
    if node.confidence is not None:
        props["confidence"] = node.confidence
    if node.source_chunk_ids:
        props["source_chunk_ids"] = node.source_chunk_ids
    if node.embedding is not None:
        props["embedding"] = node.embedding
    return props


async def _write_node_in_session(session: Any, node: Node) -> None:
    """Write a single node within an existing async session."""
    strategy = get_merge_strategy(node.type)
    labels = ":".join(get_neo4j_labels(NodeType(node.type)))
    props = _build_node_props(node)

    if strategy == MergeStrategy.MERGE_ON_HASH:
        content_hash = node.properties.get("content_hash") or node.id
        await session.run(
            f"MERGE (n:{labels} {{content_hash: $hash}}) SET n += $props",
            hash=content_hash,
            props=props,
        )
    elif strategy == MergeStrategy.MERGE:
        await session.run(
            f"MERGE (n:{labels} {{id: $id}}) SET n += $props",
            id=node.id,
            props=props,
        )
    else:
        await session.run(f"CREATE (n:{labels} $props)", props=props)


async def _write_edge_in_session(session: Any, edge: Edge) -> None:
    """Write a single edge within an existing async session."""
    rel_type = (
        edge.predicate if isinstance(edge.predicate, str) else edge.predicate.value
    )
    edge_props = edge.properties or {}
    await session.run(
        "MATCH (a {id: $from_id}), (b {id: $to_id}) "
        f"MERGE (a)-[r:{rel_type}]->(b) "
        "SET r += $props",
        from_id=edge.from_node,
        to_id=edge.to_node,
        props=edge_props,
    )
