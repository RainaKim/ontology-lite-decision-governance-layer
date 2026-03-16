"""
Graph Ontology - Ontology-lite Decision Governance Layer

Minimal graph schema for decision governance without full ontology overhead.
Graph-native design for swappable backend (in-memory → Neo4j).
"""

from pydantic import BaseModel, Field
from typing import Optional, Any
from enum import Enum


class NodeType(str, Enum):
    """Core node types in decision governance graph."""
    # Primary node types (uppercase for consistency)
    DECISION = "DECISION"     # Root decision node (의사결정)
    ACTOR = "ACTOR"           # All people: approvers, owners, decision makers (승인자/책임자)
    RULE = "RULE"             # Governance rules R1-R8 (규칙)
    GOAL_STRATEGIC = "GOAL_STRATEGIC"  # Company strategic goals G1-G3 (전략 목표)
    RISK = "RISK"             # Identified risks (리스크)
    KPI = "KPI"               # Key performance indicators (KPI)
    COST = "COST"             # Financial costs (비용)
    REGION = "REGION"         # Geographic regions (지역)
    # Optional/legacy types (keeping for backward compatibility, will be removed)
    GOAL = "Goal"             # LLM-extracted decision goals (목표) - consider removing
    RESOURCE = "Resource"     # Budget, systems, assets (자원)
    DATA_TYPE = "DataType"    # Data classifications (데이터 유형)


class EdgePredicate(str, Enum):
    """Edge predicates defining relationships in governance graph."""
    # Core governance predicates
    OWNS = "OWNS"                           # Actor owns Decision/Resource
    REQUIRES_APPROVAL_BY = "REQUIRES_APPROVAL_BY"  # Decision/Rule requires approval by Actor
    REQUIRES_REVIEW_BY = "REQUIRES_REVIEW_BY"      # Decision requires review by Actor
    TRIGGERS = "TRIGGERS"                   # Legacy: Decision triggers Risk (deprecated, use GENERATES_RISK)
    TRIGGERS_RULE = "TRIGGERS_RULE"         # Decision triggers Rule (more specific than TRIGGERS)
    GENERATES_RISK = "GENERATES_RISK"       # Rule generates Risk (replaces Decision → TRIGGERS → Risk)
    IMPACTS = "IMPACTS"                     # Decision impacts Resource/Actor
    MITIGATES = "MITIGATES"                 # Decision mitigates Risk
    HAS_RISK = "HAS_RISK"                   # Decision has Risk (alternative to TRIGGERS for risks)
    # Strategic alignment predicates
    SUPPORTS = "SUPPORTS"                   # Decision supports Strategic Goal
    CONFLICTS_WITH = "CONFLICTS_WITH"       # Decision conflicts with Strategic Goal
    MEASURED_BY = "MEASURED_BY"             # Strategic Goal measured by KPI
    # Financial governance predicates
    HAS_COST = "HAS_COST"                   # Decision has Cost
    EXCEEDS_THRESHOLD = "EXCEEDS_THRESHOLD" # Cost exceeds Rule threshold
    # Approval hierarchy predicates
    ESCALATES_TO = "ESCALATES_TO"           # Approver escalates to higher authority
    # Extended predicates for ontology triples
    HAS_GOAL = "HAS_GOAL"                   # Decision has goal
    HAS_KPI = "HAS_KPI"                     # Decision has KPI
    AFFECTS_REGION = "AFFECTS_REGION"       # Decision affects region
    USES_DATA = "USES_DATA"                 # Decision uses data type


class Node(BaseModel):
    """
    Graph node representing an entity in the decision governance system.

    Minimal property set for hackathon speed.
    Extensible via properties dict for enterprise evolution.
    """
    id: str = Field(..., description="Unique identifier for this node")
    type: NodeType = Field(..., description="Node type classification")
    label: str = Field(..., description="Human-readable label/name")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible properties bag (JSON-compatible values)"
    )

    class Config:
        use_enum_values = True


class Edge(BaseModel):
    """
    Graph edge representing a relationship between nodes.

    Triple structure: (from) -[predicate]-> (to)
    """
    from_node: str = Field(..., alias="from", description="Source node ID")
    to_node: str = Field(..., alias="to", description="Target node ID")
    predicate: EdgePredicate = Field(..., description="Relationship type")
    properties: Optional[dict[str, Any]] = Field(
        None,
        description="Optional edge metadata (weight, timestamp, rationale, etc.)"
    )

    class Config:
        use_enum_values = True
        populate_by_name = True


class DecisionGraph(BaseModel):
    """
    Complete graph representation of a decision with governance context.

    Used for upsert operations and graph traversal results.
    """
    decision_id: str = Field(..., description="Root decision node ID")
    nodes: list[Node] = Field(default_factory=list, description="All nodes in this decision subgraph")
    edges: list[Edge] = Field(default_factory=list, description="All edges in this decision subgraph")
    metadata: Optional[dict[str, Any]] = Field(
        None,
        description="Graph-level metadata (creation time, version, etc.)"
    )


# Helper functions for creating common node/edge patterns

def create_actor_node(actor_id: str, name: str, role: Optional[str] = None) -> Node:
    """Create an Actor node (person, role, department)."""
    properties = {}
    if role:
        properties["role"] = role

    return Node(
        id=actor_id,
        type=NodeType.ACTOR,
        label=name,
        properties=properties
    )


def create_action_node(
    action_id: str,
    statement: str,
    risk_score: Optional[float] = None,
    strategic_impact: Optional[str] = None
) -> Node:
    """Create a Decision node (root of decision graph)."""
    properties = {}
    if risk_score is not None:
        properties["risk_score"] = risk_score
    if strategic_impact:
        properties["strategic_impact"] = strategic_impact

    return Node(
        id=action_id,
        type=NodeType.DECISION,
        label=statement,
        properties=properties
    )


def create_strategic_goal_node(
    goal_id: str,
    name: str,
    priority: Optional[str] = None,
    owner_id: Optional[str] = None
) -> Node:
    """Create a Strategic Goal node (G1, G2, G3)."""
    properties = {"name": name}
    if priority:
        properties["priority"] = priority
    if owner_id:
        properties["owner_id"] = owner_id

    return Node(
        id=goal_id,
        type=NodeType.GOAL_STRATEGIC,
        label=name,
        properties=properties
    )


def create_rule_node(
    rule_id: str,
    name: str,
    rule_type: Optional[str] = None,
    description: Optional[str] = None
) -> Node:
    """Create a Rule node (R1-R8)."""
    properties = {"name": name}
    if rule_type:
        properties["type"] = rule_type
    if description:
        properties["description"] = description

    return Node(
        id=rule_id,
        type=NodeType.RULE,
        label=f"{rule_id}: {name}",
        properties=properties
    )


def create_policy_node(policy_id: str, name: str, description: Optional[str] = None) -> Node:
    """Create a Policy node (rule, constraint)."""
    properties = {}
    if description:
        properties["description"] = description

    return Node(
        id=policy_id,
        type=NodeType.RULE,
        label=name,
        properties=properties
    )


def create_risk_node(
    risk_id: str,
    description: str,
    severity: Optional[str] = None,
    mitigation: Optional[str] = None
) -> Node:
    """Create a Risk node."""
    properties = {}
    if severity:
        properties["severity"] = severity
    if mitigation:
        properties["mitigation"] = mitigation

    return Node(
        id=risk_id,
        type=NodeType.RISK,
        label=description,
        properties=properties
    )


def create_resource_node(resource_id: str, name: str, resource_type: Optional[str] = None) -> Node:
    """Create a Resource node (budget, system, asset)."""
    properties = {}
    if resource_type:
        properties["resource_type"] = resource_type

    return Node(
        id=resource_id,
        type=NodeType.RESOURCE,
        label=name,
        properties=properties
    )


def create_edge(from_id: str, to_id: str, predicate: EdgePredicate, **properties) -> Edge:
    """Create an edge with optional properties."""
    edge_properties = properties if properties else None

    return Edge(
        from_node=from_id,
        to_node=to_id,
        predicate=predicate,
        properties=edge_properties
    )
