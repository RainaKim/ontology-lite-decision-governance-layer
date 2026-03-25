"""
Onboarding pipeline schemas — Step 7.

LangGraph state types and Pydantic models for inter-node communication.

State flow
----------
  OnboardingState  — shared mutable state across all nodes
  ScoutInput       — per-artifact input sent to each scout node via Send API
  ExtractedNode    — single ontology node extracted from an artifact
  ExtractedEdge    — single relationship extracted from an artifact
  ScoutResult      — full output of one scout invocation (one artifact)
  TransformSummary — what the transform node wrote to the graph
  OnboardingReport — final output: confidence, gaps, node/edge counts
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Extraction models (LLM structured output targets)
# ---------------------------------------------------------------------------


class ExtractedNode(BaseModel):
    """
    A single ontology node extracted from an artifact by an LLM.

    node_type must be a domain-layer NodeType value (not schema or instance layer).
    semantic_id is a short slug used to build the stable node ID.
    """

    node_type: Literal[
        "Goal", "Rule", "Decision", "Actor", "Department", "KPI", "Jurisdiction",
        "Gap", "Conflict", "GovernanceRisk"
    ]
    semantic_id: str = Field(
        ...,
        description=(
            "Short lowercase slug for the node ID, e.g. 'revenue_growth', 'R1', 'cfo'. "
            "Use the rule/goal ID if one is stated, otherwise derive a 2-4 word slug."
        ),
    )
    label: str = Field(..., description="Human-readable display name")
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value attributes specific to this node type",
    )
    confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Extraction confidence (0.0=guess, 1.0=explicit statement)",
    )
    source_excerpt: str = Field(
        default="",
        description="Short verbatim quote (≤ 100 chars) that led to this extraction",
    )

    # --- Temporal fields (Change 4.1) ---
    effective_date: Optional[str] = Field(
        default=None,
        description="ISO date when this node takes effect (YYYY-MM-DD or YYYY-QN)",
    )
    expiry_date: Optional[str] = Field(
        default=None,
        description="ISO date when this node expires (YYYY-MM-DD or null if permanent)",
    )
    temporal_scope: Optional[Literal[
        "Q1", "Q2", "Q3", "Q4", "H1", "H2", "annual", "permanent"
    ]] = Field(
        default=None,
        description="Time scope for this node",
    )
    recurring: Optional[bool] = Field(
        default=None,
        description="Whether this node's constraint recurs every period",
    )


class ExtractedEdge(BaseModel):
    """A relationship between two extracted nodes."""

    from_semantic_id: str = Field(..., description="semantic_id of the source node")
    to_semantic_id: str = Field(..., description="semantic_id of the target node")
    predicate: str = Field(
        ...,
        description=(
            "Relationship type. Use one of: SUPPORTS, CONFLICTS_WITH, MEASURED_BY, "
            "REQUIRES_APPROVAL_FROM, REQUIRES_REVIEW_FROM, ESCALATES_TO, GOVERNED_BY, "
            "GENERATES_RISK, HAS_RISK, MITIGATES, DERIVED_FROM, BELONGS_TO, HAS_GAP, "
            "TRIGGERED, APPROVED_BY"
        ),
    )
    evidence: str = Field(default="", description="Brief justification for this edge")


class ArtifactExtraction(BaseModel):
    """
    Structured LLM output for a single artifact chunk.

    This is the Pydantic model passed to `llm.with_structured_output()`.
    """

    nodes: list[ExtractedNode] = Field(
        default_factory=list,
        description="Ontology nodes found in this artifact",
    )
    edges: list[ExtractedEdge] = Field(
        default_factory=list,
        description="Relationships between extracted nodes",
    )


# ---------------------------------------------------------------------------
# Scout result
# ---------------------------------------------------------------------------


SCOUT_TYPES = Literal["document", "conversation", "data", "web"]


class ScoutResult(BaseModel):
    """Complete output of processing one artifact file."""

    scout_type: SCOUT_TYPES
    artifact_path: str
    extracted_nodes: list[ExtractedNode] = Field(default_factory=list)
    extracted_edges: list[ExtractedEdge] = Field(default_factory=list)
    raw_chunks: list[str] = Field(
        default_factory=list,
        description="Text chunks used during extraction (for Chunk node creation)",
    )
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Transform summary
# ---------------------------------------------------------------------------


class TransformSummary(BaseModel):
    """What the transform node wrote to the graph repository."""

    nodes_written: int = 0
    nodes_deduped: int = 0
    edges_written: int = 0
    edges_dropped: int = 0
    chunks_written: int = 0
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Onboarding report
# ---------------------------------------------------------------------------


class OnboardingReport(BaseModel):
    """Final output of a completed onboarding run."""

    company_id: str
    nodes_by_type: dict[str, int] = Field(default_factory=dict)
    edges_by_type: dict[str, int] = Field(default_factory=dict)
    total_artifacts_processed: int = 0
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Aggregate extraction confidence across all scouts",
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Expected ontology classes with zero extracted instances",
    )
    warnings: list[str] = Field(default_factory=list)
    completed: bool = False

    # --- Structural validation fields (populated by validate node) ---
    orphan_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of domain nodes with zero edges",
    )
    edge_to_node_ratio: float = Field(
        default=0.0,
        description="Ratio of edges to nodes in the graph",
    )
    structural_warnings: list[str] = Field(
        default_factory=list,
        description="Warnings from structural graph validation (orphans, missing patterns)",
    )
    edges_dropped: int = Field(
        default=0,
        description="Number of edges dropped during transform (unresolved endpoints)",
    )


# ---------------------------------------------------------------------------
# LangGraph state types
# ---------------------------------------------------------------------------


class ScoutInput(TypedDict):
    """
    Input sent to each scout node via LangGraph's Send API.

    Each parallel scout invocation receives exactly one artifact path.
    """

    company_id: str
    artifact_path: str
    seeded_nodes_context: str


class OnboardingState(TypedDict):
    """
    Shared mutable state for the entire onboarding LangGraph.

    Fields marked with operator.add reducer accumulate values
    from parallel scout nodes without overwriting each other.
    """

    company_id: str
    artifact_paths: list[str]

    # Compact markdown table of nodes created by seed_company_graph().
    # Passed to every scout so LLM prompts can reference existing entities.
    seeded_nodes_context: str

    # Rule IDs from CompanyConfig for seeded-rule-ID deduplication (Change 3.2)
    seeded_rule_ids: list[str]

    # Goal IDs from CompanyConfig for seeded-goal-ID deduplication (Fix #2)
    seeded_goal_ids: list[str]

    # Goal ID → label mapping for label-based goal dedup (V4 Fix #2)
    seeded_goal_labels: dict[str, str]

    # Accumulated by parallel scout nodes (reducer: append)
    scout_results: Annotated[list[ScoutResult], operator.add]

    # Set by transform node
    transform_summary: Optional[TransformSummary]

    # Set by validate node
    report: Optional[OnboardingReport]

    # Accumulated error messages from any node (reducer: append)
    errors: Annotated[list[str], operator.add]
