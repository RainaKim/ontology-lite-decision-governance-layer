"""
Decision Governance Layer - Pydantic v2 Schemas

Core decision objectization models with governance-ready fields.
Day 1-2 scope: Schema foundation for extraction and validation.
Day 3+ readiness: Optional governance fields (risk_score, strategic_impact, approval_chain).
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from enum import Enum


class StrategicImpact(str, Enum):
    """Strategic impact classification for governance routing."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalLevel(str, Enum):
    """Approval authority levels."""
    TEAM_LEAD = "team_lead"
    DEPARTMENT_HEAD = "department_head"
    VP = "vp"
    C_LEVEL = "c_level"
    BOARD = "board"


class Goal(BaseModel):
    """Organizational goal targeted by the decision."""
    description: str = Field(..., min_length=3, max_length=500)
    metric: Optional[str] = Field(None, description="How this goal will be measured")


class KPI(BaseModel):
    """Key Performance Indicator for decision success."""
    name: str = Field(..., min_length=3, max_length=200)
    target: Optional[str] = Field(None, description="Target value or outcome")
    measurement_frequency: Optional[str] = Field(None, description="How often measured")


class Risk(BaseModel):
    """Potential failure vector or constraint."""
    description: str = Field(..., min_length=3, max_length=500)
    severity: Optional[str] = Field(None, description="Low/Medium/High/Critical")
    mitigation: Optional[str] = Field(None, description="How to address this risk")


class Owner(BaseModel):
    """Accountable individual or role."""
    name: str = Field(..., min_length=2, max_length=200)
    role: Optional[str] = Field(None, description="Job title or functional role")
    responsibility: Optional[str] = Field(None, description="Specific accountability")


class Assumption(BaseModel):
    """Implicit belief underlying the decision."""
    description: str = Field(..., min_length=3, max_length=500)
    criticality: Optional[str] = Field(None, description="How critical is this assumption")


class ApprovalChainStep(BaseModel):
    """Single step in the approval chain (Day 3+ governance)."""
    level: ApprovalLevel
    role: str = Field(..., description="Specific role or title")
    required: bool = Field(default=True, description="Is this approval mandatory")
    rationale: Optional[str] = Field(None, description="Why this approval is needed")
    source_rule_id: Optional[str] = Field(None, description="ID of the governance rule that triggered this approval requirement")
    rule_action: Optional[str] = Field(None, description="Rule action type: require_approval | require_review | require_goal_mapping")


class Decision(BaseModel):
    """
    Core decision object - atomic unit for governance.

    Required fields enable extraction and validation (Day 1-2).
    Optional governance fields prepare for rule evaluation (Day 3+).
    """

    # Core decision fields (required)
    decision_statement: str = Field(
        ...,
        min_length=10,
        max_length=1000,
        description="Clear, executable action to be taken"
    )

    goals: list[Goal] = Field(
        default_factory=list,
        description="Organizational outcomes targeted"
    )

    kpis: list[KPI] = Field(
        default_factory=list,
        description="Measurable success indicators"
    )

    risks: list[Risk] = Field(
        default_factory=list,
        description="Potential failure vectors"
    )

    owners: list[Owner] = Field(
        default_factory=list,
        description="Accountable roles (empty if not stated in input)"
    )

    required_approvals: list[str] = Field(
        default_factory=list,
        description="Approval candidates identified during extraction"
    )

    assumptions: list[Assumption] = Field(
        default_factory=list,
        description="Implicit beliefs underlying decision"
    )

    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction reliability score (0-1)"
    )

    # Governance rule fields — extracted by LLM so rules can evaluate them
    counterparty_relation: Optional[str] = Field(
        None,
        description="'related_party' if decision involves subsidiaries, affiliates, or related entities; null otherwise"
    )
    policy_change_type: Optional[str] = Field(
        None,
        description="'retroactive' if decision involves retroactive policy changes; null otherwise"
    )
    uses_pii: Optional[bool] = Field(
        None,
        description="true if the decision involves processing, sharing, or exposing personal/customer data (PII); null otherwise"
    )
    cost: Optional[float] = Field(
        None,
        description="Primary financial commitment in full numeric form (e.g. 250000000 for 2.5억 원, 3500000 for $3.5M); null if no financial commitment stated. When inferred from domain knowledge (e.g. MRI equipment), use the UPPER BOUND of the typical market range for conservative governance evaluation."
    )
    cost_estimate_range: Optional[str] = Field(
        None,
        description="Human-readable cost range when cost is inferred from domain knowledge rather than explicitly stated (e.g. '$1.5M-$3.5M (typical MRI equipment)'); null if cost was explicitly stated in the input text"
    )
    target_market: Optional[str] = Field(
        None,
        description="Target market or region if explicitly mentioned (e.g. 'North America', 'EU', '북미'); null otherwise"
    )
    launch_date: Optional[bool] = Field(
        None,
        description="true if the decision involves a product launch, service deployment, or release; null otherwise"
    )
    involves_hiring: Optional[bool] = Field(
        None,
        description="true if the decision involves hiring, onboarding, or significant headcount change; null otherwise"
    )
    involves_compliance_risk: Optional[bool] = Field(
        None,
        description="true if the decision explicitly involves anti-bribery risk, ethics code violation, entertainment/gift policy breach, or similar compliance/integrity concerns; null otherwise"
    )
    headcount_change: Optional[int] = Field(
        None,
        description="Net number of people being hired (positive) or reduced (negative); null if not stated"
    )

    # Governance-ready fields (optional, Day 3+ usage)
    risk_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=10.0,
        description="Calculated risk score (0-10, computed from risks)"
    )

    strategic_impact: Optional[StrategicImpact] = Field(
        None,
        description="Strategic importance classification"
    )

    approval_chain: Optional[list[ApprovalChainStep]] = Field(
        None,
        description="Computed approval sequence based on governance rules"
    )

    @field_validator('goals', 'kpis', 'risks', 'assumptions')
    @classmethod
    def check_not_empty_if_present(cls, v):
        """Ensure lists aren't empty if provided."""
        if v is not None and len(v) == 0:
            return []  # Allow empty lists, validation happens elsewhere
        return v


class DecisionExtractionRequest(BaseModel):
    """Request payload for decision extraction endpoint."""
    decision_text: str = Field(
        ...,
        min_length=20,
        max_length=10000,
        description="Free-form decision description to be structured"
    )

    apply_governance_rules: bool = Field(
        default=False,
        description="Whether to compute governance fields (risk_score, approval_chain)"
    )


class DecisionExtractionResponse(BaseModel):
    """Response from decision extraction endpoint with deterministic governance evaluation."""
    decision: Decision
    extraction_metadata: dict = Field(
        default_factory=dict,
        description="Metadata about extraction process (retries, model used, etc.)"
    )
    governance_applied: bool = Field(
        default=False,
        description="Whether governance rules were evaluated"
    )
    approval_chain: list[dict] = Field(
        default_factory=list,
        description="Required approval chain based on governance rules"
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Governance flags (warnings/issues) identified"
    )
    triggered_rules: list[dict] = Field(
        default_factory=list,
        description="List of governance rules that were triggered"
    )
    requires_human_review: bool = Field(
        default=False,
        description="Whether human review is required before proceeding"
    )
    governance_status: str = Field(
        default="needs_approval",
        description="Final governance status: approved, needs_approval, blocked"
    )
    derived_attributes: dict = Field(
        default_factory=dict,
        description="Deterministically derived attributes (budget, EU scope, PII usage, etc.)"
    )
    completeness_issues: list[str] = Field(
        default_factory=list,
        description="List of completeness issues (missing fields)"
    )


class DecisionPack(BaseModel):
    """
    Execution-ready decision artifact (Day 3+ deliverable).

    Combines structured decision with governance evaluation results.
    """
    decision: Decision
    approval_chain: list[ApprovalChainStep]
    governance_summary: dict = Field(
        default_factory=dict,
        description="Summary of rule evaluations and compliance status"
    )
    created_at: Optional[str] = Field(None, description="Timestamp")
    pack_id: Optional[str] = Field(None, description="Unique identifier")
