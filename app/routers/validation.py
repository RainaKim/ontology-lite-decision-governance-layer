"""
Validation endpoint — POST /v1/validate.

Runs the full governance validation pipeline (deterministic Layer 1 +
LangGraph governance agent Layer 2) and returns a synchronous result.

No SSE, no streaming. Returns the complete validation result as JSON.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/validate", tags=["validation"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ValidationRequest(BaseModel):
    """Input to the validation endpoint."""

    decision_text: str = Field(
        ..., description="Free-text description of the proposed decision"
    )
    decision_dimensions: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured dimensions: cost, headcount_change, affects_compliance, etc.",
    )
    company_id: str = Field(
        ..., description="Company identifier (e.g. 'nexus_analytics')"
    )


class ValidationResponse(BaseModel):
    """Output of the validation endpoint."""

    decision_id: Optional[str] = None
    company_id: str
    verdict: str = Field(description="APPROVE | REJECT | ESCALATE | REVIEW")
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    conditions: list[str] = Field(default_factory=list)
    approval_chain: list[dict[str, Any]] = Field(default_factory=list)
    triggered_rules: list[dict[str, Any]] = Field(default_factory=list)
    goal_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    governance_gaps: list[dict[str, Any]] = Field(default_factory=list)
    risk_score: Optional[dict[str, Any]] = None
    similar_decisions: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("", response_model=ValidationResponse)
async def validate_decision(request: ValidationRequest):
    """
    Validate an AI-proposed decision against company governance rules.

    Runs the deterministic rule engine + LangGraph governance agent.
    Returns synchronously (no SSE, no streaming).

    Authentication is not enforced here yet -- the existing auth infrastructure
    uses JWT + RBAC via a DB-backed user model. The validation endpoint will
    be wired into the auth layer when the full pipeline is deployed.
    """
    try:
        from app.validation.governance_agent import run_governance_agent
        from app.graph.base import BaseGraphRepository

        # Use InMemoryGraphRepository as fallback when Neo4j is not configured
        import os

        repo: BaseGraphRepository
        if os.getenv("NEO4J_URI"):
            try:
                from app.graph.neo4j_repository import Neo4jGraphRepository

                repo = Neo4jGraphRepository()
            except Exception:
                from app.graph_repository import InMemoryGraphRepository

                repo = InMemoryGraphRepository()
        else:
            from app.graph_repository import InMemoryGraphRepository

            repo = InMemoryGraphRepository()

        # Run Layer 1: deterministic governance
        from app.governance import evaluate_governance, load_company_config
        from app.schemas import Decision

        # Build a minimal Decision object from request
        decision_kwargs = {
            "decision_statement": request.decision_text,
            "goals": [],
            "kpis": [],
            "risks": [],
            "owners": [],
            "assumptions": [],
            "confidence": 0.7,
        }
        # Map known dimensions onto Decision fields
        dims = request.decision_dimensions
        if "cost" in dims:
            decision_kwargs["cost"] = dims["cost"]
        if "headcount_change" in dims:
            decision_kwargs["headcount_change"] = dims["headcount_change"]
        if "uses_pii" in dims:
            decision_kwargs["uses_pii"] = dims["uses_pii"]
        if "involves_hiring" in dims:
            decision_kwargs["involves_hiring"] = dims["involves_hiring"]
        if "affects_compliance" in dims:
            decision_kwargs["involves_compliance_risk"] = dims["affects_compliance"]

        decision_obj = Decision(**decision_kwargs)
        gov_result = evaluate_governance(
            decision=decision_obj,
            company_context={},
            company_id=request.company_id,
        )
        gov_dict = gov_result.to_dict()

        # Run Layer 2: governance agent
        result = await run_governance_agent(
            company_id=request.company_id,
            decision_text=request.decision_text,
            decision_payload=request.decision_dimensions,
            governance_result=gov_dict,
            risk_scoring=None,
            graph_context=None,
            repo=repo,
        )

        return ValidationResponse(
            decision_id=None,
            company_id=request.company_id,
            verdict=result.verdict,
            confidence=result.confidence,
            reasoning=result.agent_reasoning,
            conditions=[],
            approval_chain=result.approval_chain,
            triggered_rules=[
                {"rule_id": rid, "status": "TRIGGERED"}
                for rid in result.triggered_rule_ids
            ],
            goal_conflicts=result.goal_impacts,
            governance_gaps=[
                g.model_dump() if hasattr(g, "model_dump") else g
                for g in result.governance_gaps
            ],
            risk_score=None,
            similar_decisions=[
                p.model_dump() if hasattr(p, "model_dump") else p
                for p in result.precedent_decisions[:3]
            ],
        )

    except Exception as e:
        logger.error(f"Validation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: {str(e)}",
        )
