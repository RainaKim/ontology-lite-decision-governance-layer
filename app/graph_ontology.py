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
    ACTOR = "Actor"           # People, roles, departments (who)
    ACTION = "Action"         # Decisions, tasks, executions (what)
    POLICY = "Policy"         # Rules, constraints, governance policies (how)
    RISK = "Risk"             # Failure vectors, threats, concerns (why not)
    RESOURCE = "Resource"     # Budget, systems, assets, capabilities (with what)


class EdgePredicate(str, Enum):
    """Edge predicates defining relationships in governance graph."""
    OWNS = "OWNS"                           # Actor owns Action/Resource
    REQUIRES_APPROVAL_BY = "REQUIRES_APPROVAL_BY"  # Action requires approval by Actor
    GOVERNED_BY = "GOVERNED_BY"             # Action governed by Policy
    TRIGGERS = "TRIGGERS"                   # Action triggers Policy/Risk
    IMPACTS = "IMPACTS"                     # Action impacts Resource/Actor
    MITIGATES = "MITIGATES"                 # Action mitigates Risk


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
    """Create an Action node (decision, task)."""
    properties = {}
    if risk_score is not None:
        properties["risk_score"] = risk_score
    if strategic_impact:
        properties["strategic_impact"] = strategic_impact

    return Node(
        id=action_id,
        type=NodeType.ACTION,
        label=statement,
        properties=properties
    )


def create_policy_node(policy_id: str, name: str, description: Optional[str] = None) -> Node:
    """Create a Policy node (rule, constraint)."""
    properties = {}
    if description:
        properties["description"] = description

    return Node(
        id=policy_id,
        type=NodeType.POLICY,
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
