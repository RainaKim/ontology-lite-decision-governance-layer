"""
Graph Repository - Abstract Interface

Repository pattern for swappable graph backend.
Start with in-memory, evolve to Neo4j without touching service logic.
"""

from abc import ABC, abstractmethod
from typing import Optional
from app.graph_ontology import Node, Edge, DecisionGraph


class BaseGraphRepository(ABC):
    """
    Abstract graph repository interface.

    Design philosophy:
    - Governance is deterministic (rule engine)
    - Graph is structural memory (what happened, why, who)
    - Repository abstracts storage implementation

    Implementations:
    - InMemoryGraphRepository (Day 1-2, demo stability)
    - Neo4jGraphRepository (Day 3+, enterprise scale)
    """

    @abstractmethod
    async def add_node(self, node: Node) -> Node:
        """
        Add a single node to the graph.

        Args:
            node: Node to add

        Returns:
            Created node (with any server-generated fields)

        Raises:
            ValueError if node.id already exists (use update for modifications)
        """
        pass

    @abstractmethod
    async def add_edge(self, edge: Edge) -> Edge:
        """
        Add a single edge to the graph.

        Args:
            edge: Edge to add

        Returns:
            Created edge

        Raises:
            ValueError if from_node or to_node doesn't exist
        """
        pass

    @abstractmethod
    async def upsert_decision_graph(
        self,
        decision: dict,
        governance: dict,
        decision_id: Optional[str] = None
    ) -> DecisionGraph:
        """
        Upsert a complete decision subgraph from decision + governance evaluation.

        This is the primary write operation for the governance system.
        Converts flat decision object → graph structure.

        Graph construction:
        1. Create Action node (decision itself)
        2. Create Actor nodes (owners, approvers)
        3. Create Risk nodes (from decision.risks)
        4. Create Policy nodes (from triggered rules)
        5. Create edges:
           - Actor -[OWNS]-> Action (owners)
           - Action -[REQUIRES_APPROVAL_BY]-> Actor (approval chain)
           - Action -[GOVERNED_BY]-> Policy (triggered rules)
           - Action -[TRIGGERS]-> Risk (identified risks)

        Args:
            decision: Decision dict (from Decision.model_dump())
            governance: Governance evaluation dict (from GovernanceResult.to_dict())
            decision_id: Optional explicit ID (generated if not provided)

        Returns:
            DecisionGraph containing all created nodes and edges
        """
        pass

    @abstractmethod
    async def get_governance_context(
        self,
        decision_id: str,
        depth: int = 2
    ) -> dict:
        """
        Retrieve governance context for a decision via graph traversal.

        Returns connected subgraph within N hops from decision node.
        Used for:
        - Audit trails (what rules applied?)
        - Impact analysis (who is affected?)
        - Approval status (who approved?)
        - Risk relationships (what risks are shared?)

        Args:
            decision_id: Root decision node ID
            depth: Traversal depth (default 2 hops)

        Returns:
            Dict containing:
            {
                "decision": Node,
                "actors": list[Node],
                "policies": list[Node],
                "risks": list[Node],
                "edges": list[Edge],
                "metadata": {
                    "traversal_depth": int,
                    "node_count": int,
                    "edge_count": int
                }
            }
        """
        pass

    @abstractmethod
    async def get_node(self, node_id: str) -> Optional[Node]:
        """
        Retrieve a single node by ID.

        Args:
            node_id: Node identifier

        Returns:
            Node if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_nodes_by_type(self, node_type: str, limit: int = 100) -> list[Node]:
        """
        Find nodes by type.

        Args:
            node_type: NodeType value to filter by
            limit: Maximum results to return

        Returns:
            List of matching nodes
        """
        pass

    @abstractmethod
    async def get_edges_from_node(self, node_id: str) -> list[Edge]:
        """
        Get all outgoing edges from a node.

        Args:
            node_id: Source node ID

        Returns:
            List of edges where from_node == node_id
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """
        Clear entire graph (for testing/demo reset).

        WARNING: Destructive operation.
        """
        pass


class InMemoryGraphRepository(BaseGraphRepository):
    """
    In-memory graph implementation for MVP/demo.

    Trade-offs:
    ✅ Fast, no dependencies, demo-stable
    ❌ Not persistent — each pipeline run starts from empty graph
    ❌ Cannot answer "past similar decisions with risk?" because there
       are no past decisions in memory

    WHAT NEO4J UNLOCKS (future migration):
    1. Persistent decision history — every processed decision stays as a
       connected subgraph. Policy/Actor/Risk nodes are shared across
       decisions, so graph traversal naturally finds similar past decisions.
    2. Historical risk query becomes a simple Cypher:
         MATCH (current:Action {id: $id})-[:TRIGGERS]->(r:Risk)
               <-[:TRIGGERS]-(past:Action)
         WHERE past.id <> $id
         RETURN past, r
       This returns all past decisions that triggered the same Risk nodes.
    3. Outcome tracking — add Outcome node type:
         (Decision)-[:RESULTED_IN]->(Outcome {status, actual_risk, lesson})
       so o1 can reason about "last time we took this risk, it materialized."
    4. The o1 prompt already asks for historical pattern analysis. It just
       needs the data, which only persistence can provide.
    """

    def __init__(self):
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []

    async def add_node(self, node: Node) -> Node:
        if node.id in self._nodes:
            raise ValueError(f"Node {node.id} already exists")
        self._nodes[node.id] = node
        return node

    async def add_edge(self, edge: Edge) -> Edge:
        if edge.from_node not in self._nodes:
            raise ValueError(f"Source node {edge.from_node} does not exist")
        if edge.to_node not in self._nodes:
            raise ValueError(f"Target node {edge.to_node} does not exist")
        self._edges.append(edge)
        return edge

    async def upsert_decision_graph(
        self,
        decision: dict,
        governance: dict,
        decision_id: Optional[str] = None
    ) -> DecisionGraph:
        """Build decision subgraph from decision + governance."""
        from app.graph_ontology import (
            create_action_node, create_actor_node, create_risk_node,
            create_policy_node, create_edge, EdgePredicate
        )
        import uuid

        if decision_id is None:
            decision_id = f"decision_{uuid.uuid4().hex[:8]}"

        nodes = []
        edges = []

        # 1. Create Action node (the decision itself)
        action_node = create_action_node(
            action_id=decision_id,
            statement=decision.get("decision_statement", ""),
            risk_score=decision.get("risk_score"),
            strategic_impact=decision.get("strategic_impact")
        )
        await self.add_node(action_node)
        nodes.append(action_node)

        # 2. Create Actor nodes for owners
        for idx, owner in enumerate(decision.get("owners", [])):
            actor_id = f"{decision_id}_owner_{idx}"
            actor_node = create_actor_node(
                actor_id=actor_id,
                name=owner.get("name", ""),
                role=owner.get("role")
            )
            await self.add_node(actor_node)
            nodes.append(actor_node)

            # Edge: Actor -[OWNS]-> Action
            edge = create_edge(actor_id, decision_id, EdgePredicate.OWNS)
            await self.add_edge(edge)
            edges.append(edge)

        # 3. Create Actor nodes for approval chain
        for idx, step in enumerate(governance.get("approval_chain", [])):
            actor_id = f"{decision_id}_approver_{step.get('level')}_{idx}"
            actor_node = create_actor_node(
                actor_id=actor_id,
                name=step.get("role", ""),
                role=step.get("level")
            )

            # Check if already exists before adding
            if actor_id not in self._nodes:
                await self.add_node(actor_node)
                nodes.append(actor_node)

            # Edge: Action -[REQUIRES_APPROVAL_BY]-> Actor
            edge = create_edge(
                decision_id,
                actor_id,
                EdgePredicate.REQUIRES_APPROVAL_BY,
                required=step.get("required", True),
                rationale=step.get("rationale")
            )
            await self.add_edge(edge)
            edges.append(edge)

        # 4. Create Risk nodes
        for idx, risk in enumerate(decision.get("risks", [])):
            risk_id = f"{decision_id}_risk_{idx}"
            risk_node = create_risk_node(
                risk_id=risk_id,
                description=risk.get("description", ""),
                severity=risk.get("severity"),
                mitigation=risk.get("mitigation")
            )
            await self.add_node(risk_node)
            nodes.append(risk_node)

            # Edge: Action -[TRIGGERS]-> Risk
            edge = create_edge(decision_id, risk_id, EdgePredicate.TRIGGERS)
            await self.add_edge(edge)
            edges.append(edge)

        # 5. Create Policy nodes from triggered rules
        for rule in governance.get("triggered_rules", []):
            policy_id = f"policy_{rule.get('rule_id')}"

            # Avoid duplicates (policies are shared across decisions)
            if policy_id not in self._nodes:
                policy_node = create_policy_node(
                    policy_id=policy_id,
                    name=rule.get("name", ""),
                    description=rule.get("description")
                )
                await self.add_node(policy_node)
                nodes.append(policy_node)

            # Edge: Action -[GOVERNED_BY]-> Policy
            edge = create_edge(decision_id, policy_id, EdgePredicate.GOVERNED_BY)
            await self.add_edge(edge)
            edges.append(edge)

        return DecisionGraph(
            decision_id=decision_id,
            nodes=nodes,
            edges=edges,
            metadata={
                "node_count": len(nodes),
                "edge_count": len(edges)
            }
        )

    async def get_governance_context(
        self,
        decision_id: str,
        depth: int = 2
    ) -> dict:
        """Traverse graph from decision node."""
        if decision_id not in self._nodes:
            return {
                "decision": None,
                "actors": [],
                "policies": [],
                "risks": [],
                "edges": [],
                "metadata": {"error": "Decision not found"}
            }

        # Simple BFS traversal
        visited_nodes = set()
        visited_edges = []
        current_level = {decision_id}

        for _ in range(depth):
            next_level = set()
            for node_id in current_level:
                visited_nodes.add(node_id)

                # Get outgoing edges
                for edge in self._edges:
                    if edge.from_node == node_id and edge.to_node not in visited_nodes:
                        next_level.add(edge.to_node)
                        visited_edges.append(edge)
                    # Also traverse incoming edges
                    if edge.to_node == node_id and edge.from_node not in visited_nodes:
                        next_level.add(edge.from_node)
                        visited_edges.append(edge)

            current_level = next_level
            if not current_level:
                break

        # Collect nodes by type
        from app.graph_ontology import NodeType

        decision_node = self._nodes.get(decision_id)
        actors = [self._nodes[nid] for nid in visited_nodes if self._nodes[nid].type == NodeType.ACTOR]
        policies = [self._nodes[nid] for nid in visited_nodes if self._nodes[nid].type == NodeType.POLICY]
        risks = [self._nodes[nid] for nid in visited_nodes if self._nodes[nid].type == NodeType.RISK]

        return {
            "decision": decision_node,
            "actors": actors,
            "policies": policies,
            "risks": risks,
            "edges": visited_edges,
            "metadata": {
                "traversal_depth": depth,
                "node_count": len(visited_nodes),
                "edge_count": len(visited_edges)
            }
        }

    async def get_node(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    async def find_nodes_by_type(self, node_type: str, limit: int = 100) -> list[Node]:
        results = [node for node in self._nodes.values() if node.type == node_type]
        return results[:limit]

    async def get_edges_from_node(self, node_id: str) -> list[Edge]:
        return [edge for edge in self._edges if edge.from_node == node_id]

    async def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
