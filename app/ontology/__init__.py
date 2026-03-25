"""
Ontology package — generic node vocabulary and config schema for DecisionGovernance AI.

Provides the formal ontological vocabulary used throughout the system:
- NodeType: class hierarchy (Goal, Rule, Actor, Decision, ...)
- EdgePredicate: relation types (SUPPORTS, GOVERNED_BY, ...)
- Node / Edge / DecisionGraph: Pydantic v2 graph models
- make_node_id: stable ID generator
- NODE_TYPE_REGISTRY / EDGE_REGISTRY: metadata for each type
"""

from app.ontology.node_types import (
    NodeLayer,
    MetaClass,
    MergeStrategy,
    NodeType,
    NodeTypeMetadata,
    NODE_TYPE_REGISTRY,
)
from app.ontology.edge_predicates import (
    EdgePredicate,
    EdgePredicateMetadata,
    EDGE_REGISTRY,
)
from app.ontology.models import (
    Node,
    Edge,
    DecisionGraph,
    make_node_id,
)

__all__ = [
    # Node types
    "NodeLayer",
    "MetaClass",
    "MergeStrategy",
    "NodeType",
    "NodeTypeMetadata",
    "NODE_TYPE_REGISTRY",
    # Edge predicates
    "EdgePredicate",
    "EdgePredicateMetadata",
    "EDGE_REGISTRY",
    # Models
    "Node",
    "Edge",
    "DecisionGraph",
    "make_node_id",
]
