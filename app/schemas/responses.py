"""
app/schemas/responses.py — Outbound response models for the v1 API.

Console payload shape is LOCKED — do not change field names without
coordinating with the frontend team.

Normalization note: raw engine output (string flags, rules without status,
approval chain without status) is transformed into these structured types
at the response assembly layer (NOT in the governance engine itself).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DecisionStatus(str, Enum):
    """Lifecycle state of a submitted decision."""
    pending = "pending"
    processing = "processing"
    complete = "complete"
    failed = "failed"


class FlagSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FlagCategory(str, Enum):
    financial = "financial"
    privacy = "privacy"
    conflict = "conflict"
    strategic = "strategic"
    governance = "governance"
    compliance = "compliance"


class RuleStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    PASSED = "PASSED"


# ---------------------------------------------------------------------------
# Company responses
# ---------------------------------------------------------------------------


class CompanySummaryResponse(BaseModel):
    """Compact company representation — embedded in console payload and list endpoint."""
    id: str
    name: str
    industry: str
    size: str
    governance_framework: str


class CompanyDetailResponse(CompanySummaryResponse):
    """Full company context — GET /v1/companies/{id}."""
    description: str
    approval_chain_summary: str
    total_governance_rules: int
    strategic_goals: list[dict[str, Any]] = Field(default_factory=list)
    approval_hierarchy: dict[str, Any] = Field(default_factory=dict)


class CompanyListResponse(BaseModel):
    """GET /v1/companies response."""
    companies: list[CompanySummaryResponse]
    total: int


# ---------------------------------------------------------------------------
# Decision submission response
# ---------------------------------------------------------------------------


class CreateDecisionResponse(BaseModel):
    """
    POST /v1/decisions — 202 Accepted.

    Caller should immediately open the stream_url SSE connection to receive
    real-time pipeline progress events.
    """
    decision_id: str
    status: DecisionStatus = DecisionStatus.pending
    message: str = "Decision submitted for governance evaluation"
    stream_url: str = Field(
        description="SSE endpoint to connect to for real-time pipeline progress"
    )


# ---------------------------------------------------------------------------
# SSE event models (GET /v1/decisions/{id}/stream)
# ---------------------------------------------------------------------------


class SSEStepEvent(BaseModel):
    """
    'event: step' payload — emitted as each pipeline step begins.

    Serialized to JSON and sent as: `data: <json>\\n\\n`
    """
    decision_id: str
    step: int = Field(ge=1, le=5)
    label: str = Field(
        description="One of: extracting, evaluating_governance, building_graph, reasoning, building_decision_pack"
    )
    message: str


class SSECompleteEvent(BaseModel):
    """
    'event: complete' payload — emitted when pipeline finishes successfully.
    UI should fetch result_url to get the full console payload.
    """
    decision_id: str
    status: DecisionStatus = DecisionStatus.complete
    result_url: str = Field(description="URL to fetch the full console payload")


class SSEErrorEvent(BaseModel):
    """'event: error' payload — emitted when pipeline fails."""
    decision_id: str
    status: DecisionStatus = DecisionStatus.failed
    message: str


# ---------------------------------------------------------------------------
# Normalized governance types
# ---------------------------------------------------------------------------


class NormalizedFlag(BaseModel):
    """
    Structured flag — transformed from raw engine string flags.

    Engine emits: ["HIGH_FINANCIAL_RISK", "BOARD_APPROVAL_REQUIRED"]
    API emits:    [{ code, category, severity, message }, ...]

    Transformation logic lives in the router/response-assembly layer.
    """
    code: str = Field(description="Original engine flag code, e.g. HIGH_FINANCIAL_RISK")
    category: FlagCategory
    severity: FlagSeverity
    message: str


class NormalizedRule(BaseModel):
    """
    Governance rule with explicit TRIGGERED / PASSED status.

    Engine only returns triggered rules. The API layer derives PASSED rules
    by comparing against the full company rule set.
    """
    rule_id: str
    name: str
    type: str
    description: str
    short_description: Optional[str] = Field(None, description="Truncated description for dashboard display (max 80 chars)")
    status: RuleStatus
    severity: str
    consequence: dict[str, Any] = Field(default_factory=dict)


class NormalizedApprovalStep(BaseModel):
    """
    Approval chain step with explicit pending status.

    Engine emits steps without a status field. The API layer adds
    status: "pending" to every step on a freshly submitted decision.
    """
    role: str
    name: Optional[str] = None
    level: Optional[int] = None
    status: str = Field(default="pending", description="pending | approved | rejected")
    reason: Optional[str] = None
    source_rule_id: Optional[str] = Field(None, description="Rule ID that triggered this approval requirement")
    auth_type: str = Field(default="REQUIRED", description="REQUIRED (require_approval) | ESCALATION (require_review)")


# ---------------------------------------------------------------------------
# Console payload sections
# ---------------------------------------------------------------------------


class DecisionSummary(BaseModel):
    """Structured decision extracted from input text."""
    statement: str
    goals: list[dict[str, Any]] = Field(default_factory=list)
    kpis: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    owners: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[dict[str, Any]] = Field(default_factory=list)
    required_approvals: list[str] = Field(default_factory=list)


class DerivedAttributes(BaseModel):
    """Deterministically computed attributes from extraction + governance steps."""
    risk_level: str = Field(description="low | medium | high | critical")
    confidence: float = Field(ge=0.0, le=1.0)
    strategic_impact: str = Field(description="low | medium | high | critical")
    completeness_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Fraction of expected decision fields that were populated"
    )


class GovernancePayload(BaseModel):
    """
    Governance evaluation results — null until step 2 completes.

    Contains normalized flags, rules (with TRIGGERED/PASSED status),
    and approval chain (with pending status on each step).
    """
    status: str = Field(description="compliant | review_required | blocked")
    requires_human_review: bool
    risk_score: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    flags: list[NormalizedFlag] = Field(default_factory=list)
    triggered_rules: list[NormalizedRule] = Field(default_factory=list)
    all_rules: list[NormalizedRule] = Field(
        default_factory=list,
        description="All rules evaluated — includes both TRIGGERED and PASSED"
    )
    approval_chain: list[NormalizedApprovalStep] = Field(default_factory=list)


class GraphNode(BaseModel):
    """A node in the knowledge graph."""
    id: str
    type: str  # e.g., "Decision", "Goal", "KPI", "Risk", "Owner", "Cost", "Region", "DataType"
    label: str  # Human-readable label
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """An edge (triple) in the knowledge graph: subject → predicate → object."""
    source: str  # Node ID
    target: str  # Node ID
    relation: str  # e.g., "HAS_GOAL", "HAS_COST", "AFFECTS_REGION", "USES_DATA"
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphPayload(BaseModel):
    """Graph construction output — null until step 3 completes."""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    analysis_method: str = "deterministic_subgraph"
    subgraph_summary: Optional[dict[str, Any]] = None


class ReasoningPayload(BaseModel):
    """Graph reasoning output — null until step 4 completes."""
    analysis_method: str
    logical_contradictions: list[str] = Field(default_factory=list)
    graph_recommendations: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    raw_analysis: Optional[str] = None


class DecisionPackPayload(BaseModel):
    """Execution-ready decision artifact — null until step 5 completes."""
    title: str
    summary: dict[str, Any] = Field(default_factory=dict)
    goals_kpis: dict[str, Any] = Field(default_factory=dict)
    risks: list[Any] = Field(default_factory=list)
    approval_chain: list[Any] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    audit: dict[str, Any] = Field(default_factory=dict)
    graph_reasoning: Optional[dict[str, Any]] = None


class ExtractionMetadata(BaseModel):
    """Metadata about the extraction process."""
    completeness_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    completeness_issues: list[str] = Field(default_factory=list)
    extraction_method: str = Field(
        default="llm",
        description="llm | deterministic"
    )
    company_id: str
    processed_at: str


# ---------------------------------------------------------------------------
# Full console payload — LOCKED SHAPE
# ---------------------------------------------------------------------------


class ConsolePayloadResponse(BaseModel):
    """
    GET /v1/decisions/{id} — full console payload.

    Field order matches the UI rendering order. DO NOT rename or reorder
    top-level keys without coordinating with the frontend team.

    Governance, graph_payload, reasoning, and decision_pack are null
    during 'processing' and populated as each pipeline step completes.
    """

    decision_id: str
    status: DecisionStatus

    # Company context snapshot (captured at submission time)
    company: CompanySummaryResponse

    # Structured decision (available after step 1)
    decision: Optional[DecisionSummary] = None

    # Derived attributes (available after step 2)
    derived_attributes: Optional[DerivedAttributes] = None

    # Governance evaluation (available after step 2)
    governance: Optional[GovernancePayload] = None

    # Graph construction (available after step 3)
    graph_payload: Optional[GraphPayload] = None

    # Graph reasoning (available after step 4)
    reasoning: Optional[ReasoningPayload] = None

    # Decision pack (available after step 5)
    decision_pack: Optional[DecisionPackPayload] = None

    # Extraction metadata (available after step 1)
    extraction_metadata: Optional[ExtractionMetadata] = None
