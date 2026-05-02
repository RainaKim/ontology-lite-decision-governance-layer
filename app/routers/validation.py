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
from app.services.risk_scoring_service import RiskScoringService
from app.validation.governance_agent import run_governance_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/validate", tags=["validation"])

# Module-level InMemory repo singleton — avoids creating a new instance per request
_inmemory_repo: Optional[Any] = None


def _get_inmemory_repo():
    """Return a module-level InMemoryGraphRepository singleton."""
    global _inmemory_repo
    if _inmemory_repo is None:
        from app.graph.in_memory_repository import InMemoryGraphRepository
        _inmemory_repo = InMemoryGraphRepository()
    return _inmemory_repo


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
    """Output of the validation endpoint.

    NOTE: This overlaps with app.schemas.responses.ValidationPayload but has a
    different shape (flat vs nested). TODO: consolidate into a single canonical
    schema when the API surface stabilises.
    """

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
    external_signals: Optional[dict[str, Any]] = None
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
    # TODO(P1): Wire JWT/RBAC auth before production deployment.
    # Any authenticated user can currently query governance rules for any company.

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
            company_context=request.decision_dimensions,
            company_id=request.company_id,
        )
        gov_dict = gov_result.to_dict()

        # External signals (non-fatal, before risk scoring for adjustments)
        ext_signals_payload = None
        ext_adjustments: list[dict] = []
        try:
            from app.services.external_signal_service import build_external_signals as _build_ext
            ext_signals_payload = _build_ext(
                company_id=request.company_id,
                decision=request.decision_dimensions,
                governance_result=gov_dict,
                risk_scoring=None,
            )
            if ext_signals_payload is not None:
                ext_adjustments = [
                    a.model_dump() if hasattr(a, "model_dump") else a
                    for a in (ext_signals_payload.riskAdjustments or [])
                ]
        except Exception as ext_err:
            logger.warning("External signals failed (non-fatal): %s", ext_err)

        # Risk scoring (non-fatal)
        risk_scoring_result: Optional[dict] = None
        try:
            import dataclasses
            rs_service = RiskScoringService()
            rs_result = rs_service.score(
                decision_payload=request.decision_dimensions,
                company_payload={},
                governance_result=gov_dict,
                company_id=request.company_id,
                external_signal_adjustments=ext_adjustments or None,
            )
            risk_scoring_result = dataclasses.asdict(rs_result)
        except Exception as rs_err:
            logger.warning("Risk scoring failed (non-fatal): %s", rs_err)
    except Exception as e:
        logger.error("Layer 1 governance evaluation failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Validation failed: governance evaluation error",
        )

    # Phase 2: run governance agent (Layer 2)
    repo: BaseGraphRepository
    neo4j_repo_local = None  # track locally-created Neo4j repos for cleanup
    try:
        if os.getenv("NEO4J_URI"):
            try:
                from app.graph.neo4j_repository import Neo4jGraphRepository

                neo4j_repo_local = Neo4jGraphRepository()
                await neo4j_repo_local.initialize(request.company_id)
                repo = neo4j_repo_local
            except Exception:
                if neo4j_repo_local is not None:
                    try:
                        await neo4j_repo_local.close()
                    except Exception:
                        pass
                    neo4j_repo_local = None
                repo = _get_inmemory_repo()
        else:
            repo = _get_inmemory_repo()

        try:
            _ext_signals_dict = ext_signals_payload.model_dump() if ext_signals_payload else None
            result = await run_governance_agent(
                company_id=request.company_id,
                decision_text=request.decision_text,
                decision_payload=request.decision_dimensions,
                governance_result=gov_dict,
                risk_scoring=risk_scoring_result,
                graph_context=None,
                repo=repo,
                external_signals=_ext_signals_dict,
            )
        finally:
            # Only close repos we created locally (not shared singletons)
            if neo4j_repo_local is not None:
                try:
                    await neo4j_repo_local.close()
                except Exception:
                    pass
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Governance agent failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Validation failed: governance evaluation error",
        )

    # Phase 3: assemble response
    try:
        return ValidationResponse(
            decision_id=None,
            company_id=request.company_id,
            verdict=result.verdict.value if hasattr(result.verdict, 'value') else result.verdict,
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
            risk_score=risk_scoring_result,
            external_signals=ext_signals_payload.model_dump() if ext_signals_payload else None,
            similar_decisions=[
                p.model_dump() if hasattr(p, "model_dump") else p
                for p in result.precedent_decisions[:3]
            ],
        )
    except Exception as e:
        logger.error("Response assembly failed: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Validation failed: response assembly error",
        )
