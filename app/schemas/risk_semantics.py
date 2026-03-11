"""
app/schemas/risk_semantics.py — Structured LLM semantics output model.

Pydantic v2 model produced by infer_risk_semantics() in
app/services/risk_evidence_llm.py.

Contract:
- LLM outputs ONLY these fields — no scores, no weights, no thresholds.
- Downstream deterministic logic (risk_scoring_service) uses this as a
  fallback input when structural/graph data is absent.
- All rationale text is Korean (rationale_ko).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class GoalImpact(BaseModel):
    """Classified relationship between the decision and one company strategic goal."""

    goal_id: str = Field(description="Company strategic goal identifier, e.g. G1")
    direction: Literal["support", "conflict", "neutral"]
    magnitude: Literal["low", "med", "high"]
    rationale_ko: str = Field(
        description="One Korean sentence explaining why this direction was chosen."
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


class ComplianceFacts(BaseModel):
    """
    Boolean compliance signals re-derived from decision text by the LLM.

    Used only when the extractor's structured fields (uses_pii,
    anonymization_missing, involves_compliance_risk) are absent/None.
    The LLM is not allowed to OVERRIDE existing extractor values.
    """

    uses_pii: Optional[bool] = None
    anonymization_missing: Optional[bool] = None
    involves_compliance_risk: Optional[bool] = None


class NumericEstimates(BaseModel):
    """
    Optional quantitative inferences from the decision text.

    Used only to enrich evidence notes — never to alter formula weights.
    Positive = increase, negative = reduction (percentage points).
    """

    cost_delta_pct: Optional[float] = Field(
        default=None,
        description="Estimated % cost change. Positive = cost increase, negative = reduction.",
    )
    revenue_uplift_pct: Optional[float] = Field(
        default=None,
        description="Estimated % revenue change. Positive = uplift.",
    )


class RiskSemantics(BaseModel):
    """
    Structured semantics inferred by LLM — used as fallback input only.

    Shape is intentionally stable: callers check presence of each sub-field
    before use; missing fields mean 'no LLM data available'.

    All rationale text MUST be in Korean.
    """

    goal_impacts: list[GoalImpact] = Field(
        default_factory=list,
        description="One entry per company goal where direction != neutral.",
    )
    compliance_facts: ComplianceFacts = Field(
        default_factory=ComplianceFacts,
        description="Compliance boolean signals — supplement extractor output only.",
    )
    numeric_estimates: Optional[NumericEstimates] = Field(
        default=None,
        description="Quantitative estimates for evidence notes.",
    )
    global_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="LLM self-reported confidence for the entire response.",
    )

    @field_validator("global_confidence", mode="before")
    @classmethod
    def _clamp_global(cls, v: float) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return 0.5
