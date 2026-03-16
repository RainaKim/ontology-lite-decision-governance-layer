"""
app/routers/agents.py — Agent registry & escalation rule endpoints.

Routes:
  GET    /v1/agents                     → AgentListResponse
  GET    /v1/agents/policies/export     → JSON or PDF export
  GET    /v1/agents/{agent_id}          → AgentItem
  POST   /v1/agents                     → AgentItem (201)
  PATCH  /v1/agents/{agent_id}          → AgentItem
  GET    /v1/agents/{agent_id}/decisions → WorkspaceDecisionsResponse
  GET    /v1/escalation-rules           → EscalationRulesResponse
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.repositories import agent_store, decision_store
from app.services.rbac_service import require_any
from app.schemas.analysis_responses import (
    AgentCreateRequest,
    AgentItem,
    AgentListResponse,
    AgentUpdateRequest,
    EscalationRule,
    EscalationRulesResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["agents"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Global counters — in a real system these would come from the DB.
_DECISION_RULES_COUNT = 147
_ESCALATIONS_TODAY = 3


def _record_to_item(record: agent_store.AgentRecord) -> AgentItem:
    return AgentItem(
        id=record.id,
        name=record.name,
        version=record.version,
        department=record.department,
        domain=record.domain,
        autonomy=record.autonomy,
        autonomy_level=record.autonomy_level,
        policy=record.policy,
        status=record.status,
        constraints=record.constraints,
        linked_policies=record.linked_policies,
    )


# ---------------------------------------------------------------------------
# GET /v1/agents
# ---------------------------------------------------------------------------


@router.get("/agents", response_model=AgentListResponse)
async def list_agents(
    status: Optional[str] = Query(default=None, description="Active | Restricted"),
    department: Optional[str] = Query(default=None, description="Filter by department"),
    _: object = Depends(require_any),
) -> AgentListResponse:
    """GET /v1/agents — Returns the full agent registry with optional filters."""
    agents = agent_store.list_agents(status=status, department=department)
    all_agents = agent_store.list_agents()
    active_count = sum(1 for a in all_agents if a.status == "Active")

    return AgentListResponse(
        total=len(agents),
        active_count=active_count,
        decision_rules_count=_DECISION_RULES_COUNT,
        escalations_today=_ESCALATIONS_TODAY,
        items=[_record_to_item(a) for a in agents],
    )


# ---------------------------------------------------------------------------
# GET /v1/agents/policies/export  (must be declared BEFORE /{agent_id})
# ---------------------------------------------------------------------------


@router.get("/agents/policies/export")
async def export_agent_policies(
    format: str = Query(default="json", description="json | pdf"),
    _: object = Depends(require_any),
) -> Response:
    """
    GET /v1/agents/policies/export

    Exports all agent policies as JSON or PDF.
    """
    agents = agent_store.list_agents()
    payload = [_record_to_item(a).model_dump() for a in agents]

    if format == "pdf":
        # Generate a minimal text-based report as a downloadable PDF blob.
        # Not a full PDF spec — sufficient for download/preview in demo context.
        lines = ["Agent Policies Export", "=" * 40, ""]
        for item in payload:
            lines.append(f"Agent: {item['name']} ({item['id']})")
            lines.append(f"  Version:    {item['version']}")
            lines.append(f"  Department: {item['department']}")
            lines.append(f"  Domain:     {item['domain']}")
            lines.append(f"  Autonomy:   {item['autonomy']} ({item['autonomy_level']}%)")
            lines.append(f"  Policy:     {item['policy']}")
            lines.append(f"  Status:     {item['status']}")
            if item["constraints"]:
                lines.append("  Constraints:")
                for c in item["constraints"]:
                    lines.append(f"    - {c}")
            if item["linked_policies"]:
                lines.append(f"  Linked Policies: {', '.join(item['linked_policies'])}")
            lines.append("")
        content = "\n".join(lines).encode("utf-8")
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=agent_policies.pdf"},
        )

    # Default: JSON
    content = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=agent_policies.json"},
    )


# ---------------------------------------------------------------------------
# GET /v1/agents/{agent_id}
# ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}", response_model=AgentItem)
async def get_agent(
    agent_id: str,
    _: object = Depends(require_any),
) -> AgentItem:
    """GET /v1/agents/{agent_id} — Returns single agent detail."""
    record = agent_store.get_agent(agent_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return _record_to_item(record)


# ---------------------------------------------------------------------------
# POST /v1/agents
# ---------------------------------------------------------------------------


@router.post("/agents", response_model=AgentItem, status_code=201)
async def create_agent(
    body: AgentCreateRequest,
    _: object = Depends(require_any),
) -> AgentItem:
    """POST /v1/agents — Registers a new agent."""
    record = agent_store.create_agent(
        name=body.name,
        version=body.version,
        department=body.department,
        domain=body.domain,
        autonomy=body.autonomy,
        autonomy_level=body.autonomy_level,
        policy=body.policy,
        status=body.status,
        constraints=body.constraints,
        linked_policies=body.linked_policies,
    )
    logger.info(f"Agent created: {record.id} ({record.name})")
    return _record_to_item(record)


# ---------------------------------------------------------------------------
# PATCH /v1/agents/{agent_id}
# ---------------------------------------------------------------------------


@router.patch("/agents/{agent_id}", response_model=AgentItem)
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    _: object = Depends(require_any),
) -> AgentItem:
    """PATCH /v1/agents/{agent_id} — Partial update of agent settings."""
    record = agent_store.get_agent(agent_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    updates = body.model_dump(exclude_none=True)
    agent_store.update_agent(agent_id, **updates)
    updated = agent_store.get_agent(agent_id)
    return _record_to_item(updated)


# ---------------------------------------------------------------------------
# GET /v1/agents/{agent_id}/decisions
# ---------------------------------------------------------------------------

# Re-export workspace response schemas inline to avoid circular imports.
from pydantic import BaseModel, Field  # noqa: E402


class _WorkspaceDecisionItem(BaseModel):
    decision_id: str
    agent_name: Optional[str]
    agent_name_en: Optional[str]
    department: Optional[str] = None
    department_en: Optional[str] = None
    status: str
    proposed_text: Optional[str] = None
    proposed_text_ko: Optional[str] = None
    proposed_text_en: Optional[str] = None
    confidence: float
    risk_level: str
    impact_label: Optional[str] = None
    impact_label_en: Optional[str] = None
    contract_value: Optional[int] = None
    affected_count: Optional[int] = None
    created_at: str
    validated_at: Optional[str] = None


class _WorkspaceDecisionsResponse(BaseModel):
    items: list[_WorkspaceDecisionItem]
    total: int
    limit: int
    offset: int


_STATUS_MAP = {"complete": "validated", "failed": "blocked", "pending": "pending", "processing": "pending"}


def _record_to_workspace_item(record) -> _WorkspaceDecisionItem:
    ws_status = _STATUS_MAP.get(record.status, "pending")
    risk_level = "medium"
    confidence = 0.75
    if record.derived_attributes:
        risk_level = record.derived_attributes.get("risk_level", "medium")
        confidence = float(record.derived_attributes.get("confidence", 0.75))
    elif record.risk_scoring:
        band = (record.risk_scoring.get("aggregate") or {}).get("band", "MEDIUM")
        risk_level = band.lower()
        confidence_raw = (record.risk_scoring.get("aggregate") or {}).get("confidence", 0.75)
        confidence = float(confidence_raw)

    return _WorkspaceDecisionItem(
        decision_id=record.decision_id,
        agent_name=record.agent_name,
        agent_name_en=record.agent_name_en,
        status=ws_status,
        proposed_text=record.input_text[:200] if record.input_text else None,
        confidence=round(confidence, 2),
        risk_level=risk_level,
        created_at=record.created_at,
    )


@router.get("/agents/{agent_id}/decisions", response_model=_WorkspaceDecisionsResponse)
async def get_agent_decisions(
    agent_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None, description="pending | blocked | validated"),
    _: object = Depends(require_any),
) -> _WorkspaceDecisionsResponse:
    """
    GET /v1/agents/{agent_id}/decisions

    Returns decision history for a specific agent from the in-memory store.
    Filtered by agent_name matching the registered agent.
    """
    record = agent_store.get_agent(agent_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # Filter in-memory store by agent name
    agent_name_lower = record.name.lower()
    all_records = [
        r for r in decision_store._store.values()
        if (r.agent_name or "").lower() == agent_name_lower
        or (r.agent_name_en or "").lower() == agent_name_lower
    ]

    # Convert and optionally filter by status
    items = [_record_to_workspace_item(r) for r in all_records]
    if status:
        items = [i for i in items if i.status == status]

    # Sort newest first
    items.sort(key=lambda x: x.created_at, reverse=True)

    total = len(items)
    page = items[offset: offset + limit]

    return _WorkspaceDecisionsResponse(
        items=page,
        total=total,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# GET /v1/escalation-rules
# ---------------------------------------------------------------------------


@router.get("/escalation-rules", response_model=EscalationRulesResponse)
async def list_escalation_rules(
    _: object = Depends(require_any),
) -> EscalationRulesResponse:
    """GET /v1/escalation-rules — Returns global escalation rules."""
    rules = [EscalationRule(**r) for r in agent_store.ESCALATION_RULES]
    return EscalationRulesResponse(items=rules)
