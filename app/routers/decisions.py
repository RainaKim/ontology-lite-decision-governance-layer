"""
Decisions Router — POST /v1/decisions, GET /v1/decisions/{id}, GET /v1/decisions/{id}/stream

Contract-compliant endpoints for decision submission and retrieval.
All routes are mounted under /v1 via APIRouter prefix.

SSE stream is the primary status channel. Polling GET /{id} is secondary.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import user_repository
from app.services import auth_service

from app.schemas.requests import CreateDecisionRequest
from app.services.rbac_service import require_any, require_manager_up
from app.schemas.responses import (
    CreateDecisionResponse,
    ConsolePayloadResponse,
    DecisionStatus,
    SSEStepEvent,
    SSECompleteEvent,
    SSEErrorEvent,
)
from app.services import company_service
from app.repositories import decision_store
from app.routers.normalizers import build_console_payload

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
    Connect to /v1/decisions/{id}/stream for real-time SSE progress.
    Fetch /v1/decisions/{id} after stream completes for full payload.
    """
    # Validate company exists (using contract-compliant IDs)
    if not company_service.get_company_v1(request.company_id, lang=request.lang):
        raise HTTPException(
            status_code=422,
            detail=f"Unknown company_id '{request.company_id}'. "
                   f"Valid: nexus_dynamics, mayo_central",
        )

    # Enforce tenant isolation: non-admins may only submit under their own company.
    from app.services.rbac_service import UserRole
    if current_user.role != UserRole.ADMIN and current_user.company_id != request.company_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot submit decisions for a different company.",
        )

    # Create record (persist flags so pipeline can read them)
    record = decision_store.create(
        company_id=request.company_id,
        input_text=request.input_text,
        use_o1_governance=request.use_o1_governance,
        use_o1_graph=request.use_o1_graph,
        lang=request.lang,
        agent_name=request.agent_name,
        agent_name_en=request.agent_name_en,
        workspace_decision_id=request.workspace_decision_id,
    )

    # Import here to avoid circular imports
    from app.main import extractor, graph_repo
    from app.services.pipeline_service import run_pipeline

    # Enqueue pipeline (non-blocking) — pass flags explicitly
    background_tasks.add_task(
        run_pipeline,
        decision_id=record.decision_id,
        extractor=extractor,
        graph_repo=graph_repo,
        use_o1_governance=request.use_o1_governance,
        use_o1_graph=request.use_o1_graph,
    )

    logger.info(f"Decision submitted: {record.decision_id} (company={request.company_id})")

    return CreateDecisionResponse(
        decision_id=record.decision_id,
        status=DecisionStatus.pending,
        message="Decision submitted for governance evaluation",
        stream_url=f"/v1/decisions/{record.decision_id}/stream",
    )


@router.get("/decisions/{decision_id}/stream")
async def stream_decision_status(
    decision_id: str,
    request: Request,
    token: str = Query(..., description="Bearer token (EventSource cannot set headers)"),
    lang: str = Query(default="ko", description="Language for labels: 'ko' or 'en'"),
    db: Session = Depends(get_db),
):
    """
    GET /v1/decisions/{decision_id}/stream — SSE stream for real-time pipeline progress.

    Event types:
      - step: pipeline progress (step 1-5)
      - complete: pipeline finished, fetch full payload
      - error: pipeline failed

    Connection stays open until complete or error.
    """
    # Validate token (EventSource cannot send Authorization header)
    try:
        payload = auth_service.decode_token(token)
        user_id = payload.get("sub")
        if not user_id or not user_repository.get_by_id(db, user_id):
            raise HTTPException(status_code=401, detail="Invalid token")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    record = decision_store.get(decision_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events by polling decision_store."""
        last_step = 0

        # Step events fire AFTER each stage completes (data is ready when event arrives).
        # Labels must match STAGE_LOG keys in the frontend trace log (exact match).
        step_messages = {
            1: "Decision entities extracted",
            2: "Policy evaluation and graph mapping complete",
            3: "Reasoning analysis complete",
        }

        step_labels = {
            1: "extracting",
            2: "evaluating_governance",
            3: "reasoning",
        }

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                logger.info(f"[{decision_id}] SSE client disconnected")
                break

            record = decision_store.get(decision_id)
            if not record:
                # Record disappeared — emit error and close
                error_event = SSEErrorEvent(
                    decision_id=decision_id,
                    status=DecisionStatus.failed,
                    message="Decision record not found",
                )
                yield f"event: error\ndata: {error_event.model_dump_json()}\n\n"
                break

            current_step = record.current_step

            # Emit one step event per completed stage (cap at 3 — step 4 is the "complete" event).
            # Pause between emissions so the frontend renders each step before the next arrives,
            # even when the pipeline completes faster than the poll interval.
            while last_step < current_step and last_step < 3:
                last_step += 1
                if last_step in step_labels:
                    step_event = SSEStepEvent(
                        decision_id=decision_id,
                        step=last_step,
                        label=step_labels[last_step],
                        message=step_messages[last_step],
                    )
                    yield f"event: step\ndata: {step_event.model_dump_json()}\n\n"
                    await asyncio.sleep(0.5)  # pace: one step per 500ms

            # Check terminal states
            if record.status == "complete":
                complete_event = SSECompleteEvent(
                    decision_id=decision_id,
                    status=DecisionStatus.complete,
                    result_url=f"/v1/decisions/{decision_id}",
                )
                yield f"event: complete\ndata: {complete_event.model_dump_json()}\n\n"
                break

            if record.status == "failed":
                error_event = SSEErrorEvent(
                    decision_id=decision_id,
                    status=DecisionStatus.failed,
                    message=record.error or "Pipeline failed",
                )
                yield f"event: error\ndata: {error_event.model_dump_json()}\n\n"
                break

            # Poll interval
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/decisions/{decision_id}", response_model=ConsolePayloadResponse)
async def get_decision(
    decision_id: str,
    lang: str = Query(default=None, description="Language override: 'ko' or 'en'"),
    _: object = Depends(require_any),
):
    """
    GET /v1/decisions/{decision_id} — Full console payload.

    Fetch after receiving 'event: complete' from SSE stream.
    Returns partial payload (nulls) during processing.
    """
    record = decision_store.get(decision_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")

    return build_console_payload(record, lang=lang)
