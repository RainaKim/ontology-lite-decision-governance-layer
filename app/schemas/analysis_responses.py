"""
app/schemas/analysis_responses.py — Response schemas for analysis tool endpoints.

Covers:
  - GET /v1/decisions/{id}/reasoning-trace
  - GET/POST/PATCH /v1/agents
  - GET /v1/escalation-rules
  - GET /v1/agents/policies/export
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reasoning Timeline
# ---------------------------------------------------------------------------


class ReasoningTraceStep(BaseModel):
    id: int
    name: str
    description: str
    timestamp: str
    duration: str
    status: str = Field(description="completed | failed | skipped")
    summary: str
    entities: list[str] = Field(default_factory=list)
    ontology: list[str] = Field(default_factory=list)


class ReasoningTraceResponse(BaseModel):
    decision_id: str
    total_duration_ms: int
    steps: list[ReasoningTraceStep] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent Boundaries
# ---------------------------------------------------------------------------


class AgentItem(BaseModel):
    id: str
    name: str
    version: str
    department: str
    domain: str
    autonomy: str = Field(description="Policy Bound | Conditional | Human Controlled | Autonomous")
    autonomy_level: int = Field(ge=0, le=100)
    policy: str
    status: str = Field(description="Active | Restricted")
    constraints: list[str] = Field(default_factory=list)
    linked_policies: list[str] = Field(default_factory=list)


class AgentListResponse(BaseModel):
    total: int
    active_count: int
    decision_rules_count: int
    escalations_today: int
    items: list[AgentItem] = Field(default_factory=list)


class AgentCreateRequest(BaseModel):
    name: str
    version: str
    department: str
    domain: str
    autonomy: str
    autonomy_level: int = Field(ge=0, le=100)
    policy: str
    status: str = "Active"
    constraints: list[str] = Field(default_factory=list)
    linked_policies: list[str] = Field(default_factory=list)


class AgentUpdateRequest(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    department: Optional[str] = None
    domain: Optional[str] = None
    autonomy: Optional[str] = None
    autonomy_level: Optional[int] = Field(default=None, ge=0, le=100)
    policy: Optional[str] = None
    status: Optional[str] = None
    constraints: Optional[list[str]] = None
    linked_policies: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Escalation Rules
# ---------------------------------------------------------------------------


class EscalationRule(BaseModel):
    id: str
    severity: str = Field(description="CRITICAL | HIGH | MEDIUM")
    trigger: str
    action: str
    responsible: str


class EscalationRulesResponse(BaseModel):
    items: list[EscalationRule] = Field(default_factory=list)
