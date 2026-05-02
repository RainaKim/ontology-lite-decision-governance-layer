"""
Core graph models for the DecisionGovernance AI ontology.

Node      — a single entity in the governance graph
Edge      — a typed relationship between two nodes
DecisionGraph — a decision subgraph returned from a pipeline run

ID scheme (enforced by make_node_id):
    {company_id}:{node_type_lowercase}:{semantic_id}
    e.g.  nexus:goal:revenue_growth
          nexus:rule:R1
          nexus:actor:cfo
          nexus:decision:20240115_a1b2c3
"""

from __future__ import annotations

import re
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.ontology.node_types import NodeType, MergeStrategy, get_merge_strategy
from app.ontology.edge_predicates import EdgePredicate


# ---------------------------------------------------------------------------
# Node ID
# ---------------------------------------------------------------------------

_NODE_ID_PATTERN = re.compile(
    r"^[a-z0-9_]+:[a-z0-9_]+:[a-z0-9_.:\-]+$"
)


def make_node_id(company_id: str, node_type: NodeType, semantic_id: str) -> str:
    """
    Build a stable, namespaced node ID.

    Format: {company_id}:{node_type_lowercase}:{semantic_id}

    Args:
        company_id:   Company identifier (e.g. "nexus", "mayo")
        node_type:    NodeType enum value
        semantic_id:  Human-readable semantic slug (e.g. "G1", "revenue_growth", "cfo")

    Returns:
        Stable node ID string (e.g. "nexus:goal:revenue_growth")

    Raises:
        ValueError if any component is empty or contains invalid characters
    """
    if not company_id or not semantic_id:
        raise ValueError("company_id and semantic_id must be non-empty")

    type_slug = node_type.value.lower()
    # Normalize semantic_id: lowercase, replace spaces with underscores
    sem = semantic_id.strip().lower().replace(" ", "_")
    node_id = f"{company_id}:{type_slug}:{sem}"

    if not _NODE_ID_PATTERN.match(node_id):
        raise ValueError(
            f"Generated node ID '{node_id}' contains invalid characters. "
            "Use alphanumeric, underscore, hyphen, dot, or colon only."
        )
    return node_id


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class Node(BaseModel):
    """
    A single entity in the governance graph.

    Ontology mapping:
        id         — Individual (unique identifier)
        type       — Class (which domain or instance class this belongs to)
        label      — Human-readable display name
        properties — Datatype properties (key-value attributes for this individual)
        embedding  — 1536d vector embedding (Chunk nodes only; None for all others)
        source_chunk_ids — Provenance: which Chunk nodes this node was derived from
        confidence — Extraction confidence (0.0–1.0); None for manually authored nodes
    """

    id: str = Field(..., description="Stable node ID ({company_id}:{type}:{semantic_id})")
    type: NodeType = Field(..., description="Node type (class)")
    label: str = Field(..., description="Human-readable display name")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Datatype properties for this individual",
    )
    embedding: Optional[list[float]] = Field(
        default=None,
        description="1536d vector embedding (Chunk nodes only)",
    )
    source_chunk_ids: list[str] = Field(
        default_factory=list,
        description="Chunk node IDs this node was derived from (provenance)",
    )
    confidence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Extraction confidence score (0.0–1.0)",
    )

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        if not _NODE_ID_PATTERN.match(v):
            raise ValueError(
                f"Node ID '{v}' must follow the format "
                "'{{company_id}}:{{type}}:{{semantic_id}}' with alphanumeric/underscore chars"
            )
        return v

    @field_validator("embedding")
    @classmethod
    def validate_embedding_dimension(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        if v is not None and len(v) != 1536:
            raise ValueError(f"Embedding must be 1536 dimensions, got {len(v)}")
        return v

    @property
    def merge_strategy(self) -> MergeStrategy:
        return get_merge_strategy(self.type)

    @property
    def company_id(self) -> str:
        return self.id.split(":")[0]

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Edge
# ---------------------------------------------------------------------------

class Edge(BaseModel):
    """
    A typed relationship between two nodes.

    Ontology mapping:
        from_node  — subject (source individual)
        predicate  — object property (relation type)
        to_node    — object (target individual)
        properties — edge-level metadata (rationale, timestamp, ...)
        confidence — extraction confidence for this edge (0.0–1.0)
        source_chunk_id — provenance: which Chunk node this edge was derived from
    """

    from_node: str = Field(..., description="Source node ID")
    to_node: str = Field(..., description="Target node ID")
    predicate: EdgePredicate = Field(..., description="Relation type")
    properties: Optional[dict[str, Any]] = Field(
        default=None,
        description="Edge-level metadata (rationale, sequential_order, ...)",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Edge confidence (0.0=guess, 1.0=explicit/seeded)",
    )
    source_chunk_id: Optional[str] = Field(
        default=None,
        description="Chunk node ID this edge was derived from (provenance)",
    )

    model_config = {"use_enum_values": True}


# ---------------------------------------------------------------------------
# Decision graph
# ---------------------------------------------------------------------------

class DecisionGraph(BaseModel):
    """
    A decision subgraph returned from a validation pipeline run.

    Contains all nodes and edges created or traversed for a single decision.
    The decision_id references the root Decision node.
    """

    decision_id: str = Field(..., description="Root Decision node ID")
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    metadata: Optional[dict[str, Any]] = Field(
        default=None,
        description="Graph-level metadata (node_count, edge_count, ontology_version, ...)",
    )

    def get_node(self, node_id: str) -> Optional[Node]:
        """Look up a node by ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def get_edges_from(self, node_id: str) -> list[Edge]:
        """Get all outgoing edges from a node."""
        return [e for e in self.edges if e.from_node == node_id]

    def get_edges_to(self, node_id: str) -> list[Edge]:
        """Get all incoming edges to a node."""
        return [e for e in self.edges if e.to_node == node_id]

    def get_nodes_by_type(self, node_type: NodeType) -> list[Node]:
        """Filter nodes by type."""
        type_value = node_type.value if hasattr(node_type, "value") else node_type
        return [n for n in self.nodes if n.type == type_value]

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)
