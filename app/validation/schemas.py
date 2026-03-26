"""
Validation pipeline schemas — Step 9.

LangGraph state types and Pydantic models for the governance agent.

Models
------
  GovernanceGap      — a detected gap in governance coverage
  PrecedentDecision  — a similar past decision found via vector search
  ValidationResult   — internal domain model output of the governance agent

State
-----
  ValidationState    — shared mutable state for the LangGraph agent
"""

from __future__ import annotations

from operator import add as _list_add
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class GovernanceVerdict(str, Enum):
    """Valid governance verdicts."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"
    REVIEW = "REVIEW"


# ---------------------------------------------------------------------------
# Pydantic domain models
# ---------------------------------------------------------------------------


class GovernanceGap(BaseModel):
    """A detected gap in governance coverage."""

    gap_type: Literal["external_knowledge", "internal_data", "governance_config"] = Field(
        description="Type of gap: 'external_knowledge' | 'internal_data' | 'governance_config'"
    )
    description: str
    severity: Literal["low", "medium", "high"] = Field(
        description="Severity: 'low' | 'medium' | 'high'"
    )
    integration_request: Optional[str] = Field(
        default=None,
        description="For internal_data gaps: what integration is needed to fill the gap",
    )


class PrecedentDecision(BaseModel):
    """A similar past decision found via vector search."""

    decision_id: str
    similarity_score: float
    label: str
    rules_triggered: list[str] = Field(default_factory=list)
    outcome: Optional[str] = None


class ValidationResult(BaseModel):
    """
    Internal domain model -- output of the governance agent.

    Consumed by build_console_payload() in normalizers.py and mapped into
    the existing ConsolePayloadResponse shape. The API response shape
    does not change.
    """

    verdict: GovernanceVerdict = Field(
        description="APPROVE | REJECT | ESCALATE | REVIEW"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    agent_reasoning: str
    precedent_decisions: list[PrecedentDecision] = Field(default_factory=list)
    governance_gaps: list[GovernanceGap] = Field(default_factory=list)
    goal_impacts: list[dict[str, Any]] = Field(default_factory=list)
    triggered_rule_ids: list[str] = Field(default_factory=list)
    approval_chain: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

_VALID_VERDICTS: frozenset[str] = frozenset(v.value for v in GovernanceVerdict)

_MAX_MESSAGES = 20


def _messages_reducer(existing: list, new: list) -> list:
    """Append new messages to existing, then trim to keep bounded size.

    Keeps the system message (index 0) plus the last (_MAX_MESSAGES - 1)
    messages so the conversation never grows unboundedly.
    """
    combined = existing + new
    if len(combined) <= _MAX_MESSAGES:
        return combined
    system_msgs = [m for m in combined[:1] if hasattr(m, 'type') and getattr(m, 'type', '') == 'system']
    tail = combined[-(_MAX_MESSAGES - len(system_msgs)):]
    return system_msgs + tail


def _replace_reducer(existing: list, new: list) -> list:
    """Last writer wins — replaces existing value entirely."""
    return new if new else existing


class ValidationState(TypedDict):
    """
    Shared state for the governance agent LangGraph.

    Fields marked with Annotated[list, operator.add] accumulate values
    from multiple agent reasoning rounds without overwriting each other.
    """

    company_id: str
    decision_text: str
    decision_payload: dict
    governance_result: dict          # GovernanceResult.to_dict()
    risk_scoring: Optional[dict]     # RiskScoringResult shape
    graph_context: Optional[dict]    # from get_governance_context()

    # Agent-populated fields
    precedent_decisions: Annotated[list, _replace_reducer]
    governance_gaps: Annotated[list, _replace_reducer]
    goal_impacts: Annotated[list, _list_add]
    agent_reasoning: str
    verdict: str
    confidence: float
    messages: Annotated[list, _messages_reducer]
    external_signals: Optional[dict]
    error: Optional[str]
