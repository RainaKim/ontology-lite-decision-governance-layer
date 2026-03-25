"""
Decisions Router — POST /v1/decisions, GET /v1/decisions/{id}

Contract-compliant endpoints for decision submission and retrieval.
All routes are mounted under /v1 via APIRouter prefix.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from app.schemas.requests import CreateDecisionRequest
from app.services.rbac_service import require_any, require_manager_up
from app.schemas.responses import (
    CreateDecisionResponse,
    ConsolePayloadResponse,
    DecisionStatus,
)
from app.repositories import decision_store
from app.routers.normalizers import build_console_payload
from app.dependencies.company_deps import validate_company_exists
from app.dependencies.auth_deps import require_tenant_isolation

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1",
    tags=["decisions"],
)


@router.post("/decisions", status_code=202, response_model=CreateDecisionResponse)
async def submit_decision(
    request: CreateDecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: object = Depends(require_manager_up),
):
    """
    POST /v1/decisions — Submit a decision for async governance evaluation.

    Returns 202 Accepted immediately with decision_id.
    Fetch /v1/decisions/{id} after processing completes for full payload.
    """
    # Validate company exists (using contract-compliant IDs)
    validate_company_exists(request.company_id)

    # Enforce tenant isolation: non-admins may only submit under their own company.
    require_tenant_isolation(current_user, request.company_id)

    # Create record (persist flags so pipeline can read them)
    record = decision_store.create(
        company_id=request.company_id,
        input_text=request.input_text,
        use_nova_governance=request.use_nova_governance,
        use_nova_graph=request.use_nova_graph,
        lang=request.lang,
        agent_name=request.agent_name,
        agent_name_en=request.agent_name_en,
        workspace_decision_id=request.workspace_decision_id,
    )

    # Import here to avoid circular imports
    from app.main import extractor, graph_repo
    from app.services.pipeline_service import run_pipeline

    # Enqueue pipeline (non-blocking)
    background_tasks.add_task(
        run_pipeline,
        decision_id=record.decision_id,
        extractor=extractor,
        graph_repo=graph_repo,
    )

    logger.info(f"Decision submitted: {record.decision_id} (company={request.company_id})")

    return CreateDecisionResponse(
        decision_id=record.decision_id,
        status=DecisionStatus.pending,
        message="Decision submitted for governance evaluation",
    )


@router.get("/decisions/{decision_id}", response_model=ConsolePayloadResponse)
async def get_decision(
    decision_id: str,
    _: object = Depends(require_any),
):
    """
    GET /v1/decisions/{decision_id} — Full console payload.

    Returns partial payload (nulls) during processing.
    """
    record = decision_store.get(decision_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")

    return build_console_payload(record)
