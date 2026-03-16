"""
app/routers/workspace.py — Workspace dashboard endpoints.

Routes:
  GET /v1/workspace/metrics    → WorkspaceMetricsResponse
  GET /v1/workspace/decisions  → WorkspaceDecisionsResponse
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.agent import Agent
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
    agent_id: str = Field(..., description="Agent UUID — must exist in agents table")
    impact_label: Optional[str] = Field(default=None, max_length=50)
    impact_label_en: Optional[str] = Field(default=None, max_length=50)
    lang: str = Field(default="ko", description="'ko' or 'en' — passed to governance pipeline")
    use_nova_graph: bool = Field(default=True)


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


class WorkspaceAgentItem(BaseModel):
    id: str
    company_id: str
    name: str
    name_en: Optional[str] = None
    department: str
    department_en: Optional[str] = None
    autonomy: str
    risk_threshold: int
    financial_limit: Optional[float] = None
    status: str
    created_at: str
    updated_at: str


class WorkspaceAgentListResponse(BaseModel):
    items: list[WorkspaceAgentItem]
    total: int


class UpdateWorkspaceAgentRequest(BaseModel):
    autonomy: Optional[str] = Field(default=None, description="Human Controlled | Policy Bound | Conditional | Autonomous")
    risk_threshold: Optional[int] = Field(default=None, ge=0, le=100)
    financial_limit: Optional[float] = Field(default=None, ge=0)
    status: Optional[str] = Field(default=None, description="Active | Restricted | Inactive")


_ALLOWED_AUTONOMY = {"Human Controlled", "Policy Bound", "Conditional", "Autonomous"}
_ALLOWED_AGENT_STATUS = {"Active", "Restricted", "Inactive"}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=WorkspaceAgentListResponse)
def list_workspace_agents(
    status: Optional[str] = Query(default=None, description="Active | Restricted | Inactive"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceAgentListResponse:
    """
    GET /v1/workspace/agents

    Returns all agents registered under the authenticated user's company.
    """
    q = db.query(Agent).filter(Agent.company_id == current_user.company_id)
    if status:
        q = q.filter(Agent.status == status)
    q = q.order_by(Agent.name.asc())
    agents = q.all()

    return WorkspaceAgentListResponse(
        items=[
            WorkspaceAgentItem(
                id=a.id,
                company_id=a.company_id,
                name=a.name,
                name_en=a.name_en,
                department=a.department,
                department_en=a.department_en,
                autonomy=a.autonomy,
                risk_threshold=a.risk_threshold,
                financial_limit=float(a.financial_limit) if a.financial_limit is not None else None,
                status=a.status,
                created_at=a.created_at.isoformat(),
                updated_at=a.updated_at.isoformat(),
            )
            for a in agents
        ],
        total=len(agents),
    )


@router.put("/agents/{agent_id}", response_model=WorkspaceAgentItem)
def update_workspace_agent(
    agent_id: str,
    body: UpdateWorkspaceAgentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceAgentItem:
    """
    PUT /v1/workspace/agents/{agent_id}

    Update an agent's governance boundaries (autonomy, risk_threshold,
    financial_limit, status).
    """
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "autonomy" in updates and updates["autonomy"] not in _ALLOWED_AUTONOMY:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid autonomy value. Allowed: {sorted(_ALLOWED_AUTONOMY)}",
        )
    if "status" in updates and updates["status"] not in _ALLOWED_AGENT_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status value. Allowed: {sorted(_ALLOWED_AGENT_STATUS)}",
        )

    for field, value in updates.items():
        setattr(agent, field, value)
    agent.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(agent)

    return WorkspaceAgentItem(
        id=agent.id,
        company_id=agent.company_id,
        name=agent.name,
        name_en=agent.name_en,
        department=agent.department,
        department_en=agent.department_en,
        autonomy=agent.autonomy,
        risk_threshold=agent.risk_threshold,
        financial_limit=float(agent.financial_limit) if agent.financial_limit is not None else None,
        status=agent.status,
        created_at=agent.created_at.isoformat(),
        updated_at=agent.updated_at.isoformat(),
    )


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
    from app.models.agent import Agent
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

    # Resolve agent from agents table
    agent = db.query(Agent).filter(Agent.id == request.agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{request.agent_id}' not found")

    # 1. Persist workspace record
    ws_record = decision_repository.create(
        db,
        company_id=current_user.company_id,
        agent_id=agent.id,
        agent_name=agent.name,
        agent_name_en=agent.name_en,
        department=agent.department,
        department_en=agent.department_en,
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

    def _resolve(d: "Decision") -> WorkspaceDecisionItem:
        # Prefer live agent data via FK; fall back to flat columns for legacy rows
        a = d.agent
        a_name = a.name if a else d.agent_name
        a_name_en = a.name_en if a else d.agent_name_en
        a_dept = a.department if a else d.department
        a_dept_en = a.department_en if a else d.department_en

        return WorkspaceDecisionItem(
            decision_id=d.id,
            agent_name=a_name_en if use_en else a_name,
            agent_name_en=a_name_en,
            department=a_dept_en if use_en else a_dept,
            department_en=a_dept_en,
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

    return WorkspaceDecisionsResponse(
        items=[_resolve(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )
