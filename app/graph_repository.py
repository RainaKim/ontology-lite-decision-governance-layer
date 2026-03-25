"""
Graph Repository - Abstract Interface

Repository pattern for swappable graph backend.
Start with in-memory, evolve to Neo4j without touching service logic.
"""

from abc import ABC, abstractmethod
from typing import Optional
from app.ontology.models import Node, Edge, DecisionGraph


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
        decision_id: Optional[str] = None,
        company_context: Optional[dict] = None,
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
       so Nova can reason about "last time we took this risk, it materialized."
    4. The Nova prompt already asks for historical pattern analysis. It just
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
        decision_id: Optional[str] = None,
        company_context: Optional[dict] = None,
    ) -> DecisionGraph:
        """Build decision subgraph from decision + governance."""
        from app.ontology.models import Node, Edge
        from app.ontology.node_types import NodeType
        from app.ontology.edge_predicates import EdgePredicate
        import uuid

        if decision_id is None:
            decision_id = f"decision_{uuid.uuid4().hex[:8]}"

        nodes = []
        edges = []

        # 1. Create Decision node
        decision_props: dict = {}
        if decision.get("risk_score") is not None:
            decision_props["risk_score"] = decision["risk_score"]
        if decision.get("strategic_impact"):
            decision_props["strategic_impact"] = decision["strategic_impact"]
        action_node = Node(
            id=decision_id,
            type=NodeType.DECISION,
            label=decision.get("decision_statement", ""),
            properties=decision_props,
        )
        await self.add_node(action_node)
        nodes.append(action_node)

        # 2. Create Actor nodes for explicitly stated owners only.
        # If owners is empty (not stated in input), no Actor nodes are added here.
        # Ownership inference is delegated to the reasoning step (step 4).
        for idx, owner in enumerate(decision.get("owners", [])):
            actor_id = f"{decision_id}_owner_{idx}"
            actor_props: dict = {}
            if owner.get("role"):
                actor_props["role"] = owner["role"]
            actor_node = Node(
                id=actor_id,
                type=NodeType.ACTOR,
                label=owner.get("name", ""),
                properties=actor_props,
            )
            await self.add_node(actor_node)
            nodes.append(actor_node)

            # Edge: Actor -[SUBMITTED_BY]-> Decision
            edge = Edge(from_node=decision_id, to_node=actor_id, predicate=EdgePredicate.SUBMITTED_BY)
            await self.add_edge(edge)
            edges.append(edge)

        # 3. LLM extracted goals removed - use company strategic goals (G1/G2/G3) instead
        # Strategic goals are added in graph_enrichment.py with SUPPORTS/CONFLICTS_WITH edges

        # 4. Create KPI nodes
        for idx, kpi in enumerate(decision.get("kpis", [])):
            kpi_id = f"{decision_id}_kpi_{idx}"
            kpi_name = kpi.get("name", "") if isinstance(kpi, dict) else str(kpi)
            kpi_target = kpi.get("target") or "" if isinstance(kpi, dict) else ""
            kpi_node = Node(
                id=kpi_id,
                type=NodeType.KPI,
                label=f"K{idx+1}: {kpi_name[:30]} {kpi_target[:20]}",
                properties={"name": kpi_name, "target": kpi_target}
            )
            await self.add_node(kpi_node)
            nodes.append(kpi_node)

            # Edge: Goal -[MEASURED_BY]-> KPI
            edge = Edge(from_node=decision_id, to_node=kpi_id, predicate=EdgePredicate.MEASURED_BY)
            await self.add_edge(edge)
            edges.append(edge)

        # 5-7. COST/REGION/DATA_TYPE nodes removed — demoted to Decision properties.
        # cost, region, data_type extracted from decision dict and stored on the Decision node.
        cost_amount, cost_currency = self._extract_cost_and_currency(decision)

        # 8. Create Risk nodes
        # Risk nodes are created here, but edges are created in graph_enrichment
        # to connect them to the Rules that generate them (Rule → GENERATES_RISK → Risk)
        for idx, risk in enumerate(decision.get("risks", [])):
            risk_id = f"{decision_id}_risk_{idx}"
            risk_props: dict = {"source": "llm"}
            if risk.get("severity"):
                risk_props["severity"] = risk["severity"]
            if risk.get("mitigation"):
                risk_props["mitigation"] = risk["mitigation"]
            if risk.get("description_en"):
                risk_props["description_en"] = risk["description_en"]
            risk_node = Node(
                id=risk_id,
                type=NodeType.RISK,
                label=risk.get("description", ""),
                properties=risk_props,
            )
            await self.add_node(risk_node)
            nodes.append(risk_node)

            # Decision → Risk edge removed - risks now connected through rules
            # Rule → GENERATES_RISK → Risk edges added in graph_enrichment

        # 9a. Create RULE nodes first (before approvers) so we can connect approvers to rules
        # RULE nodes must exist before we create Rule → REQUIRES_APPROVAL_BY → Approver edges
        if company_context:
            from app.graph_enrichment import add_governance_rules

            rule_nodes, rule_edges = await add_governance_rules(
                decision_id=decision_id,
                decision=decision,
                governance=governance,
                company_context=company_context,
                add_node_fn=self.add_node,
                add_edge_fn=self.add_edge
            )
            nodes.extend(rule_nodes)
            edges.extend(rule_edges)

        # 9b. Create Approver nodes for approval chain (distinct from Actor/owner nodes)
        #
        # Parallel rule  (default):  Rule → Approver-A
        #                             Rule → Approver-B
        #
        # Sequential rule (requires_sequential=true):
        #                             Rule → Approver-1 → Approver-2
        #   Only the first approver connects from the Rule; each subsequent approver
        #   connects from the previous one to express ordering.

        # Build rule lookup so we can check requires_sequential
        _rule_def_lookup: dict[str, dict] = {}
        if company_context:
            for _r in company_context.get("governance_rules", []):
                _rid = _r.get("rule_id")
                if _rid:
                    _rule_def_lookup[_rid] = _r

        # Group steps by source_rule_id, preserving original order
        from collections import defaultdict as _defaultdict
        _steps_by_rule: dict[str, list[tuple[int, dict]]] = _defaultdict(list)
        for _idx, _step in enumerate(governance.get("approval_chain", [])):
            _src = _step.get("source_rule_id") or ""
            _steps_by_rule[_src].append((_idx, _step))

        for _src_rule_id, _step_list in _steps_by_rule.items():
            _rule_def = _rule_def_lookup.get(_src_rule_id, {})
            _is_sequential = (
                _rule_def.get("consequence", {}).get("requires_sequential", False)
                and len(_step_list) > 1
            )

            _prev_approver_id = None
            for _list_idx, (_idx, step) in enumerate(_step_list):
                approver_id = f"{decision_id}_approver_{step.get('level')}_{_idx}"
                rule_action = step.get("rule_action", "require_approval")
                auth_label = "ESCALATION" if rule_action == "require_review" else "REQUIRED"
                source_rule_id = step.get("source_rule_id")

                approver_node = Node(
                    id=approver_id,
                    type=NodeType.ACTOR,
                    label=step.get("role", ""),
                    properties={
                        "role": step.get("role", ""),
                        "auth_type": auth_label,
                        "source_rule_id": source_rule_id,
                        "rationale": step.get("rationale"),
                        "required": step.get("required", True),
                        "sequential_order": _list_idx + 1 if _is_sequential else None,
                    }
                )

                if approver_id not in self._nodes:
                    await self.add_node(approver_node)
                    nodes.append(approver_node)

                # Determine edge source:
                # - First step (or parallel): edge comes from the Rule node
                # - Subsequent sequential steps: edge comes from the previous approver
                if _is_sequential and _prev_approver_id is not None:
                    edge_source = _prev_approver_id
                elif source_rule_id:
                    edge_source = f"rule_{source_rule_id}"
                else:
                    edge_source = None

                if edge_source:
                    edge = Edge(
                        from_node=edge_source,
                        to_node=approver_id,
                        predicate=EdgePredicate.REQUIRES_APPROVAL_FROM,
                        properties={
                            "required": step.get("required", True),
                            "rationale": step.get("rationale"),
                        },
                    )
                    await self.add_edge(edge)
                    edges.append(edge)

                _prev_approver_id = approver_id

        # 10. POLICY nodes removed - consolidated with RULE nodes
        # Policy and Rule were duplicates. Now using only RULE nodes.

        # 11. Add Strategic Goals and Alignment Edges (Ontology Enhancement)
        if company_context:
            from app.graph_enrichment import (
                add_strategic_goals,
                add_cost_threshold_edges,
                add_approval_hierarchy_edges,
                add_cost_goal_edges,
                add_rule_risk_edges
            )

            # Decision → SUPPORTS → Goal (for KPI-aligned goals)
            sg_nodes, sg_edges = await add_strategic_goals(
                decision_id=decision_id,
                decision=decision,
                company_context=company_context,
                add_node_fn=self.add_node,
                add_edge_fn=self.add_edge
            )
            nodes.extend(sg_nodes)
            edges.extend(sg_edges)

            # NOTE: Rule nodes (R1-R8) are created earlier in step 9a
            # This ensures they exist before we create approver edges

            # Cost threshold edges: cost_node_id is None since COST nodes are removed.
            # add_cost_threshold_edges returns [] when cost_node_id is None.
            cost_node_id = None
            threshold_edges = await add_cost_threshold_edges(
                decision_id=decision_id,
                decision=decision,
                governance=governance,
                cost_node_id=cost_node_id,
                company_context=company_context,
                add_edge_fn=self.add_edge
            )
            edges.extend(threshold_edges)

            # Add Cost → CONFLICTS_WITH → Goal → GENERATES_RISK → Risk chains
            cost_goal_nodes, cost_goal_edges = await add_cost_goal_edges(
                decision_id=decision_id,
                decision=decision,
                company_context=company_context,
                cost_node_id=cost_node_id,
                add_node_fn=self.add_node,
                add_edge_fn=self.add_edge
            )
            nodes.extend(cost_goal_nodes)
            edges.extend(cost_goal_edges)

            # Detect whether strategic goal conflicts were structurally represented.
            # If so, pass the flag to add_rule_risk_edges so it skips default-fallback
            # connections for LLM-extracted risks that merely restate the same conflict.
            _has_structural_conflicts = any(
                "_goal_conflict_risk_" in n.id or "_strategic_conflict_risk_" in n.id
                for n in nodes
            )

            # Add Rule → GENERATES_RISK → Risk edges (for financial/compliance risks)
            rule_risk_nodes, rule_risk_edges = await add_rule_risk_edges(
                decision_id=decision_id,
                decision=decision,
                governance=governance,
                add_node_fn=self.add_node,
                add_edge_fn=self.add_edge,
                has_structural_conflicts=_has_structural_conflicts,
            )
            nodes.extend(rule_risk_nodes)
            edges.extend(rule_risk_edges)

            # ESCALATES_TO edges removed
            # Multiple approvers in approval_chain are parallel (from different rules),
            # not hierarchical. Each approver is independently required.
            # Example: R1 → CFO, R7 → HR Manager (parallel, not CFO → HR Manager)

        # Remove dangling LLM-extracted risk nodes (no incoming edges).
        # Structural enrichment may already cover the same conflict via goal edges,
        # leaving these nodes unconnected. Match on type + source property, not ID prefix.
        _edge_targets = {e.to_node for e in edges}
        nodes = [
            n for n in nodes
            if not (n.type == NodeType.RISK and n.properties.get("source") == "llm")
            or n.id in _edge_targets
        ]

        return DecisionGraph(
            decision_id=decision_id,
            nodes=nodes,
            edges=edges,
            metadata={
                "node_count": len(nodes),
                "edge_count": len(edges),
                "ontology_version": "2.0"
            }
        )

    def _extract_cost_and_currency(self, decision: dict) -> tuple[Optional[str], Optional[str]]:
        """Extract cost and currency from LLM-extracted cost field and decision statement."""
        cost = decision.get("cost")
        currency = None
        # Try to infer currency from decision statement or cost field
        statement = decision.get("decision_statement", "")
        if isinstance(cost, str):
            if "$" in cost or "USD" in cost:
                currency = "USD"
        elif isinstance(cost, (int, float)):
            if "$" in statement or "USD" in statement:
                currency = "USD"
        if cost is not None:
            # Format as integer if whole number, otherwise as float
            amount = f"{int(cost):,}" if isinstance(cost, (int, float)) and cost == int(cost) else str(cost)
            return amount, currency
        return None, None

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
        from app.ontology.node_types import NodeType

        decision_node = self._nodes.get(decision_id)
        actors = [self._nodes[nid] for nid in visited_nodes if self._nodes[nid].type == NodeType.ACTOR]
        policies = [self._nodes[nid] for nid in visited_nodes if self._nodes[nid].type == NodeType.RULE]
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
