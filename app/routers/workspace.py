"""
app/routers/workspace.py — Workspace dashboard endpoints.

Routes:
  GET /v1/workspace/metrics    → WorkspaceMetricsResponse
  GET /v1/workspace/decisions  → WorkspaceDecisionsResponse
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.repositories import decision_repository
from app.services.user_service import get_current_user

router = APIRouter(prefix="/v1/workspace", tags=["workspace"])

_ALLOWED_STATUSES = {"pending", "blocked", "validated"}
_ALLOWED_SORTS = {"created_at:desc", "created_at:asc", "risk_level:desc"}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CreateWorkspaceDecisionRequest(BaseModel):
    proposed_text: str = Field(..., description="Decision text to analyse")
    proposed_text_en: Optional[str] = Field(default=None, description="Decision text in English")
    agent_name: str = Field(default="AI Agent", max_length=200)
    agent_name_en: Optional[str] = Field(default=None, max_length=200)
    department: str = Field(default="Unknown", max_length=100)
    department_en: Optional[str] = Field(default=None, max_length=100)
    impact_label: Optional[str] = Field(default=None, max_length=50)
    impact_label_en: Optional[str] = Field(default=None, max_length=50)
    lang: str = Field(default="ko", description="'ko' or 'en' — passed to governance pipeline")
    use_nova_graph: bool = Field(default=False)


class CreateWorkspaceDecisionResponse(BaseModel):
    workspace_decision_id: str
    analysis_decision_id: str
    status: str
    stream_url: str


class WorkspaceMetricsResponse(BaseModel):
    decisions_today: int
    pending_count: int
    blocked_count: int


class WorkspaceDecisionItem(BaseModel):
    decision_id: str
    agent_name: Optional[str]
    agent_name_en: Optional[str]
    department: Optional[str]
    department_en: Optional[str]
    status: str
    proposed_text: Optional[str]
    proposed_text_ko: Optional[str]
    proposed_text_en: Optional[str]
    confidence: float
    risk_level: str
    impact_label: Optional[str]
    impact_label_en: Optional[str]
    contract_value: Optional[int]
    affected_count: Optional[int]
    created_at: str
    validated_at: Optional[str]


class WorkspaceDecisionsResponse(BaseModel):
    items: list[WorkspaceDecisionItem]
    total: int
    limit: int
    offset: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/decisions", response_model=CreateWorkspaceDecisionResponse, status_code=202)
def create_workspace_decision(
    request: CreateWorkspaceDecisionRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreateWorkspaceDecisionResponse:
    """
    POST /v1/workspace/decisions

    Creates a workspace decision record (status=pending) and immediately
    triggers the governance pipeline. On completion the pipeline writes
    risk_level, confidence, contract_value, and status back to the record.
    """
    from app.main import extractor, graph_repo
    from app.repositories import decision_store
    from app.services.pipeline_service import run_pipeline
    from app.services import company_service as _cs

    if not current_user.company_id:
        raise HTTPException(
            status_code=400,
            detail="No company selected. Update your profile with a valid company_id first.",
        )
    if not _cs.get_company_v1(current_user.company_id, lang=request.lang):
        raise HTTPException(
            status_code=400,
            detail=f"company_id '{current_user.company_id}' has no governance context.",
        )

    # 1. Persist workspace record
    ws_record = decision_repository.create(
        db,
        company_id=current_user.company_id,
        agent_name=request.agent_name,
        agent_name_en=request.agent_name_en,
        department=request.department,
        department_en=request.department_en,
        proposed_text=request.proposed_text,
        proposed_text_en=request.proposed_text_en,
        impact_label=request.impact_label,
        impact_label_en=request.impact_label_en,
    )

    # 2. Create pipeline record linked to workspace record
    analysis_text = request.proposed_text_en or request.proposed_text
    pipeline_record = decision_store.create(
        company_id=current_user.company_id,
        input_text=analysis_text,
        lang=request.lang,
        workspace_decision_id=ws_record.id,
    )

    # 3. Trigger pipeline in background
    background_tasks.add_task(
        run_pipeline,
        decision_id=pipeline_record.decision_id,
        extractor=extractor,
        graph_repo=graph_repo,
        use_nova_governance=False,
        use_nova_graph=request.use_nova_graph,
    )

    return CreateWorkspaceDecisionResponse(
        workspace_decision_id=ws_record.id,
        analysis_decision_id=pipeline_record.decision_id,
        status="pending",
        stream_url=f"/v1/decisions/{pipeline_record.decision_id}/stream",
    )


@router.get("/metrics", response_model=WorkspaceMetricsResponse)
def get_metrics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceMetricsResponse:
    """
    GET /v1/workspace/metrics

    Summary counts scoped to the authenticated user's company.
    """
    cid = current_user.company_id
    return WorkspaceMetricsResponse(
        decisions_today=decision_repository.count_today(db, cid),
        pending_count=decision_repository.count_by_status(db, cid, "pending"),
        blocked_count=decision_repository.count_by_status(db, cid, "blocked"),
    )


@router.get("/decisions", response_model=WorkspaceDecisionsResponse)
def list_decisions(
    status: Optional[str] = Query(default=None, description="쉼표 구분 다중값. pending,blocked,validated"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(default="created_at:desc"),
    lang: str = Query(default="en", description="'ko' or 'en' — resolves display text server-side"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceDecisionsResponse:
    """
    GET /v1/workspace/decisions

    Paginated decision feed scoped to the authenticated user's company.
    When lang=en, all text fields are resolved to their _en variants
    (falling back to the Korean original only if no English value exists).
    """
    # Validate status values
    statuses: Optional[list[str]] = None
    if status:
        statuses = [s.strip() for s in status.split(",")]
        invalid = [s for s in statuses if s not in _ALLOWED_STATUSES]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status value(s): {invalid}. Allowed: pending, blocked, validated",
            )

    if sort not in _ALLOWED_SORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort value. Allowed: {sorted(_ALLOWED_SORTS)}",
        )

    items, total = decision_repository.list_decisions(
        db,
        company_id=current_user.company_id,
        statuses=statuses,
        limit=limit,
        offset=offset,
        sort=sort,
    )

    use_en = lang == "en"

    return WorkspaceDecisionsResponse(
        items=[
            WorkspaceDecisionItem(
                decision_id=d.id,
                agent_name=d.agent_name_en if use_en else d.agent_name,
                agent_name_en=d.agent_name_en,
                department=d.department_en if use_en else d.department,
                department_en=d.department_en,
                status=d.status,
                proposed_text=d.proposed_text_en if use_en else d.proposed_text,
                proposed_text_ko=d.proposed_text,
                proposed_text_en=d.proposed_text_en,
                confidence=d.confidence,
                risk_level=d.risk_level,
                impact_label=d.impact_label_en if use_en else d.impact_label,
                impact_label_en=d.impact_label_en,
                contract_value=d.contract_value,
                affected_count=d.affected_count,
                created_at=d.created_at.isoformat(),
                validated_at=d.validated_at.isoformat() if d.validated_at else None,
            )
            for d in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
