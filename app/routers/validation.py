"""
Validation endpoint — POST /v1/validate.

Runs the full governance validation pipeline (deterministic Layer 1 +
LangGraph governance agent Layer 2) and returns a synchronous result.

No SSE, no streaming. Returns the complete validation result as JSON.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.governance import evaluate_governance, load_company_config
from app.graph.base import BaseGraphRepository
from app.schemas import Decision
from app.validation.governance_agent import run_governance_agent

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

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    validated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
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


@router.post(
    "",
    response_model=ValidationResponse,
    summary="Validate an AI-proposed decision",
    description=(
        "Runs the deterministic governance rule engine (Layer 1) "
        "and the LangGraph governance agent (Layer 2) against the "
        "company's governance ontology. Returns a synchronous verdict."
    ),
    response_description="Governance validation result including verdict, confidence, and reasoning",
)
async def validate_decision(request: ValidationRequest):
    """
    Validate an AI-proposed decision against company governance rules.

    Runs the deterministic rule engine + LangGraph governance agent.
    Returns synchronously (no SSE, no streaming).

    Authentication is not enforced here yet -- the existing auth infrastructure
    uses JWT + RBAC via a DB-backed user model. The validation endpoint will
    be wired into the auth layer when the full pipeline is deployed.
    """
    # Phase 1: load company config and build Decision object
    try:
        decision_obj = Decision(
            decision_statement=request.decision_text,
            goals=[],
            kpis=[],
            risks=[],
            owners=[],
            assumptions=[],
            confidence=0.7,
            **{
                k: v
                for k, v in request.decision_dimensions.items()
                if k in Decision.model_fields
            },
        )
        gov_result = evaluate_governance(
            decision=decision_obj,
            company_context={},
            company_id=request.company_id,
        )
        gov_dict = gov_result.to_dict()
    except Exception as e:
        logger.error(f"Layer 1 governance evaluation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: governance evaluation error: {str(e)}",
        )

    # Phase 2: run governance agent (Layer 2)
    repo: BaseGraphRepository
    try:
        if os.getenv("NEO4J_URI"):
            try:
                from app.graph.neo4j_repository import Neo4jGraphRepository

                repo = Neo4jGraphRepository()
                try:
                    await repo.initialize(request.company_id)
                except Exception:
                    await repo.close()
                    raise
            except Exception:
                from app.graph_repository import InMemoryGraphRepository

                repo = InMemoryGraphRepository()
        else:
            from app.graph_repository import InMemoryGraphRepository

            repo = InMemoryGraphRepository()

        try:
            result = await run_governance_agent(
                company_id=request.company_id,
                decision_text=request.decision_text,
                decision_payload=request.decision_dimensions,
                governance_result=gov_dict,
                risk_scoring=None,
                graph_context=None,
                repo=repo,
            )
        finally:
            if hasattr(repo, "close"):
                try:
                    await repo.close()
                except Exception:
                    pass
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Governance agent failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: governance agent error: {str(e)}",
        )

    # Phase 3: assemble response
    try:
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
        logger.error(f"Response assembly failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Validation failed: response assembly error: {str(e)}",
        )
