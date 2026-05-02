"""
Company configuration schema — Tier 1 governance data.

CompanyConfig is the canonical Pydantic v2 schema for a company's governance ontology.
It is populated during onboarding (from artifacts) and loaded at validation runtime.

One JSON file per company. Consumed by:
  - Neo4jGraphRepository.seed_company_config() — writes domain-layer nodes
  - Governance rule engine (app/governance.py) — evaluates RuleConditions
  - Risk scoring service — reads risk_weights
  - Scout transform pipeline — validates extracted ontology nodes

Design principles:
  - No industry-specific logic in this schema — only numeric/structural config
  - All rule conditions reference keys from decision_dimensions (no hardcoded field names)
  - Weights must sum to 1.0 (validated)
  - Sources of rules: documented | inferred | interview
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from enum import Enum

import logging
import warnings

from pydantic import BaseModel, Field, field_validator, model_validator

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Rule condition
# ---------------------------------------------------------------------------

class ConditionOperator(str, Enum):
    # Numeric comparisons
    GT = ">"
    LT = "<"
    GTE = ">="
    LTE = "<="
    EQ = "=="
    NEQ = "!="
    # Boolean tests
    IS_TRUE = "is_true"
    IS_FALSE = "is_false"
    # String tests
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"


class RuleCondition(BaseModel):
    """
    A single condition in a governance rule.

    field    — references a key in CompanyConfig.decision_dimensions
    operator — comparison operator
    value    — threshold value (number | bool | string; ignored for IS_TRUE / IS_FALSE)

    Example:
        {"field": "cost", "operator": ">", "value": 50000}
        {"field": "affects_compliance", "operator": "is_true"}
    """

    field: str
    operator: ConditionOperator
    value: Optional[Any] = None  # not needed for is_true / is_false


# ---------------------------------------------------------------------------
# Rule consequence
# ---------------------------------------------------------------------------

class RuleAction(str, Enum):
    REQUIRE_APPROVAL = "require_approval"   # Blocks until approved
    REQUIRE_REVIEW = "require_review"       # Advisory, non-blocking
    BLOCK = "block"                         # Hard block, no approval path
    FLAG = "flag"                           # Soft flag, logs warning


class RuleConsequence(BaseModel):
    """
    What happens when a rule's conditions are satisfied.

    approver_role      — role required to approve (for REQUIRE_APPROVAL)
    requires_sequential — if true, multi-approver chain is sequential not parallel
    escalation_role    — next role if primary approver is unavailable
    message            — human-readable message (for BLOCK / FLAG actions)
    """

    action: RuleAction
    approver_role: Optional[str] = None
    requires_sequential: bool = False
    escalation_role: Optional[str] = None
    message: Optional[str] = None

    @model_validator(mode="after")
    def approver_required_for_approval(self) -> RuleConsequence:
        if self.action == RuleAction.REQUIRE_APPROVAL and not self.approver_role:
            raise ValueError("approver_role is required when action is require_approval")
        return self


# ---------------------------------------------------------------------------
# Governance rule
# ---------------------------------------------------------------------------

class GovernanceRule(BaseModel):
    """
    A single governance rule, generic and config-driven.

    conditions    — AND logic between conditions; OR logic = write two rules
    source        — where this rule was discovered during onboarding
    confidence    — extraction confidence (high = documented, low = pattern-inferred)
    source_chunk_ids — provenance: which Chunk nodes this rule was derived from
    priority      — evaluation order (higher = evaluated first); default 0
    """

    rule_id: str
    name: str
    description: Optional[str] = None
    conditions: list[RuleCondition] = Field(
        ..., min_length=1, description="AND-logic condition list (at least one required)"
    )
    consequence: RuleConsequence
    source: Literal["documented", "inferred", "interview"]
    confidence: Literal["high", "medium", "low"]
    source_chunk_ids: list[str] = Field(default_factory=list)
    priority: int = 0

    # --- Goal linkage (Change 1.1) ---
    governed_by_goal_ids: list[str] = Field(
        default_factory=list,
        description="Goal IDs this rule serves (seeded as GOVERNED_BY edges)",
    )

    # --- Temporal fields (Change 4.4) ---
    effective_date: Optional[str] = Field(
        default=None, description="ISO date when the rule takes effect (YYYY-MM-DD)"
    )
    expiry_date: Optional[str] = Field(
        default=None, description="ISO date when the rule expires (YYYY-MM-DD)"
    )
    temporal_scope: Optional[str] = Field(
        default=None,
        description="Time scope: Q1, Q2, Q3, Q4, H1, H2, annual, permanent",
    )
    recurring: Optional[bool] = Field(
        default=None, description="Whether this rule recurs every period"
    )


# ---------------------------------------------------------------------------
# KPI
# ---------------------------------------------------------------------------

class KPIConfig(BaseModel):
    """A KPI that measures a strategic goal."""

    kpi_id: str
    label: str
    unit: Optional[str] = None   # "%", "USD", "NPS", "headcount", ...
    target: Optional[str] = None  # "20%", "> 50", "< 10 days"


# ---------------------------------------------------------------------------
# Strategic goal
# ---------------------------------------------------------------------------

class StrategicGoal(BaseModel):
    """
    A company strategic goal.

    goal_id  — semantic identifier used in node ID  (e.g. "G1", "revenue_growth")
    priority — importance tier; used by risk scoring strategic dimension
    kpis     — KPIs that measure this goal; each becomes a KPI domain-layer node
    """

    goal_id: str
    label: str
    description: Optional[str] = None
    priority: Literal["critical", "high", "medium", "low"]
    owner_role: Optional[str] = None
    kpis: list[KPIConfig] = Field(default_factory=list)

    # --- Temporal fields (Change 4.4) ---
    effective_date: Optional[str] = Field(
        default=None, description="ISO date when the goal takes effect (YYYY-MM-DD)"
    )
    expiry_date: Optional[str] = Field(
        default=None, description="ISO date when the goal expires (YYYY-MM-DD)"
    )
    temporal_scope: Optional[str] = Field(
        default=None,
        description="Time scope: Q1, Q2, Q3, Q4, H1, H2, annual, permanent",
    )
    recurring: Optional[bool] = Field(
        default=None, description="Whether this goal recurs every period"
    )


# ---------------------------------------------------------------------------
# Approval hierarchy
# ---------------------------------------------------------------------------

class ApprovalHierarchyEntry(BaseModel):
    """
    One entry in the company approval hierarchy.

    approval_limit     — maximum spend/action limit in base currency (None = unlimited)
    approval_limit_note — free-text explanation for non-numeric limits
                          (e.g. "Technical decisions only")
    """

    role: str
    reports_to: Optional[str] = None
    approval_limit: Optional[float] = None
    approval_limit_note: Optional[str] = None


# ---------------------------------------------------------------------------
# Decision dimension
# ---------------------------------------------------------------------------

class DecisionDimension(BaseModel):
    """
    A typed field that the governance rule engine can evaluate.

    key  — field name referenced in RuleCondition.field
    type — determines how conditions are evaluated (numeric comparison, boolean test, ...)
    unit — display unit for numeric dimensions ("USD", "headcount", "days")
    """

    key: str
    type: Literal["number", "boolean", "string"]
    description: Optional[str] = None
    unit: Optional[str] = None
    required: bool = False


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------

class DepartmentConfig(BaseModel):
    """
    An organizational department.

    dept_id      — semantic identifier used in node ID (e.g. "engineering")
    label        — human-readable name
    member_roles — list of role strings that belong to this department
                   (must match ApprovalHierarchyEntry.role values)
    parent_dept_id — optional parent department for hierarchical org structures
    """

    dept_id: str
    label: str
    member_roles: list[str] = Field(default_factory=list)
    parent_dept_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Governance risk
# ---------------------------------------------------------------------------

class GovernanceRiskConfig(BaseModel):
    """
    A standing governance risk category that exists before any decision.

    risk_id            — semantic identifier used in node ID (e.g. "budget_overrun_risk")
    label              — human-readable name
    risk_category      — financial, compliance, operational, strategic
    severity           — critical/high/medium/low
    description        — free-text description of the risk
    generated_by_rule_ids — rules whose triggering generates this risk
    mitigated_by_rule_ids — rules that mitigate or control this risk
    """

    risk_id: str
    label: str
    risk_category: Literal["financial", "compliance", "operational", "strategic"]
    severity: Literal["critical", "high", "medium", "low"]
    description: Optional[str] = None
    generated_by_rule_ids: list[str] = Field(default_factory=list)
    mitigated_by_rule_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk weights
# ---------------------------------------------------------------------------

class GoalConflict(BaseModel):
    """
    A known conflict between two strategic goals.

    goal_id_a  — first goal in the conflict pair
    goal_id_b  — second goal in the conflict pair
    description — human-readable explanation of the tension
    """

    goal_id_a: str
    goal_id_b: str
    description: str = ""


class RiskWeightConfig(BaseModel):
    """
    Weights for the three risk scoring dimensions.
    Must sum to 1.0 (enforced by validator).

    Industry defaults (can be overridden per company):
      Standard:   financial=0.40, compliance=0.35, strategic=0.25
      Healthcare: financial=0.25, compliance=0.50, strategic=0.25
    """

    financial: float = Field(default=0.40, ge=0.0, le=1.0)
    compliance: float = Field(default=0.35, ge=0.0, le=1.0)
    strategic: float = Field(default=0.25, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> RiskWeightConfig:
        total = round(self.financial + self.compliance + self.strategic, 6)
        if abs(total - 1.0) > 1e-4:
            raise ValueError(
                f"Risk weights must sum to 1.0, got {total} "
                f"(financial={self.financial}, compliance={self.compliance}, strategic={self.strategic})"
            )
        return self


# ---------------------------------------------------------------------------
# Company config (root schema)
# ---------------------------------------------------------------------------

class CompanyConfig(BaseModel):
    """
    Canonical Tier 1 governance configuration for a single company.

    Loaded once at onboarding, consumed by all validation runs.
    All rule conditions reference keys in decision_dimensions (validated below).
    No industry-specific logic lives here — the schema is company-agnostic.
    """

    company_id: str = Field(..., description="Prefix used in all node IDs (e.g. 'nexus')")
    company_name: str
    industry: str = Field(..., description="Industry slug (e.g. 'b2b_saas', 'healthcare')")
    jurisdiction: list[str] = Field(
        ..., min_length=1, description="Legal jurisdictions (e.g. ['US', 'GDPR'])"
    )
    currency: str = Field(default="USD", description="Base currency for numeric thresholds")

    decision_dimensions: list[DecisionDimension] = Field(
        ...,
        min_length=1,
        description="Typed fields the rule engine can evaluate (must cover all rule condition fields)",
    )
    strategic_goals: list[StrategicGoal] = Field(..., min_length=1)
    governance_rules: list[GovernanceRule] = Field(..., min_length=1)
    approval_hierarchy: list[ApprovalHierarchyEntry] = Field(default_factory=list)
    departments: list[DepartmentConfig] = Field(
        default_factory=list,
        description="Organizational departments; actors are linked via member_roles",
    )
    governance_risks: list[GovernanceRiskConfig] = Field(
        default_factory=list,
        description="Standing governance risk categories; seeded as GovernanceRisk nodes",
    )
    risk_weights: RiskWeightConfig = Field(default_factory=RiskWeightConfig)
    goal_conflicts: list[GoalConflict] = Field(
        default_factory=list,
        description="Known conflicts between strategic goals; seeded as CONFLICTS_WITH edges",
    )

    # Onboarding metadata (populated by the onboarding pipeline, not manually authored)
    onboarding_completed: bool = False
    onboarding_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Aggregate confidence of the derived ontology (0.0–1.0)",
    )

    @model_validator(mode="after")
    def rule_conditions_reference_valid_dimensions(self) -> CompanyConfig:
        """All rule condition fields must exist in decision_dimensions.key."""
        dimension_keys = {dim.key for dim in self.decision_dimensions}
        errors = []
        for rule in self.governance_rules:
            for cond in rule.conditions:
                if cond.field not in dimension_keys:
                    errors.append(
                        f"Rule '{rule.rule_id}' references unknown dimension field "
                        f"'{cond.field}'. Available: {sorted(dimension_keys)}"
                    )
        if errors:
            raise ValueError("\n".join(errors))
        return self

    @model_validator(mode="after")
    def goal_ids_are_unique(self) -> CompanyConfig:
        ids = [g.goal_id for g in self.strategic_goals]
        if len(ids) != len(set(ids)):
            raise ValueError("goal_id values must be unique within a company config")
        return self

    @model_validator(mode="after")
    def rule_ids_are_unique(self) -> CompanyConfig:
        ids = [r.rule_id for r in self.governance_rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule_id values must be unique within a company config")
        return self

    @model_validator(mode="after")
    def goal_conflict_ids_are_valid(self) -> CompanyConfig:
        """All goal_conflict goal_id_a/b must reference existing strategic goals."""
        goal_ids = {g.goal_id for g in self.strategic_goals}
        for conflict in self.goal_conflicts:
            for gid in (conflict.goal_id_a, conflict.goal_id_b):
                if gid not in goal_ids:
                    raise ValueError(
                        f"GoalConflict references unknown goal_id '{gid}'. "
                        f"Available: {sorted(goal_ids)}"
                    )
        return self

    @model_validator(mode="after")
    def warn_rules_without_goal_ids(self) -> CompanyConfig:
        """Warn (not error) when a rule has no governed_by_goal_ids."""
        goal_ids = {g.goal_id for g in self.strategic_goals}
        for rule in self.governance_rules:
            if not rule.governed_by_goal_ids:
                _logger.warning(
                    "Rule '%s' has no governed_by_goal_ids — "
                    "it will not have GOVERNED_BY edges to any goal",
                    rule.rule_id,
                )
            else:
                unknown = set(rule.governed_by_goal_ids) - goal_ids
                if unknown:
                    raise ValueError(
                        f"Rule '{rule.rule_id}' references unknown goal IDs: {sorted(unknown)}. "
                        f"Available: {sorted(goal_ids)}"
                    )
        return self

    def get_rule(self, rule_id: str) -> Optional[GovernanceRule]:
        """Look up a rule by ID."""
        for rule in self.governance_rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def get_goal(self, goal_id: str) -> Optional[StrategicGoal]:
        """Look up a goal by ID."""
        for goal in self.strategic_goals:
            if goal.goal_id == goal_id:
                return goal
        return None

    def get_dimension(self, key: str) -> Optional[DecisionDimension]:
        """Look up a decision dimension by key."""
        for dim in self.decision_dimensions:
            if dim.key == key:
                return dim
        return None

    def sorted_rules(self) -> list[GovernanceRule]:
        """Return rules in evaluation order (higher priority first)."""
        return sorted(self.governance_rules, key=lambda r: r.priority, reverse=True)
