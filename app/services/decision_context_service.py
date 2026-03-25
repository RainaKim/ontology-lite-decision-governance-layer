"""
app/services/decision_context_service.py — LLM-based decision context extraction.

Goal: produce the left-panel-safe DecisionContextPayload from raw decision text.

Contract (dev_rules §2):
  - LLM extracts structured entities; it never computes scores or weights.
  - Output is validated through Pydantic before use.
  - Any failure returns None — never raises. Caller proceeds without context.
  - Judgment-kind entities (risks, approvals, governance conclusions) are
    filtered out by is_left_panel_safe() before the payload is returned.

NOTE: BedrockClient has been removed. This function is a stub that returns None
until a LangChain-based replacement is implemented.

Usage::

    result = extract_decision_context(
        decision_text=record.input_text,
        agent_name=record.agent_name,
        agent_name_en=record.agent_name_en,
        lang=record.lang,
    )
    # result is dict | None  (serialised DecisionContextPayload)
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal Pydantic models — raw LLM output shape (kept for future LangChain use)
# ---------------------------------------------------------------------------

_KindLiteral = Literal["fact", "context", "judgment"]


class _EntityRaw(BaseModel):
    key: str
    label: str
    label_en: str
    value: str
    value_en: str
    category: str
    kind: _KindLiteral
    confidence: float = Field(ge=0.0, le=1.0)


class _ContextRaw(BaseModel):
    proposal: str = ""
    proposal_en: str = ""
    source_label: str = "AI Agent"
    entities: list[_EntityRaw] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Safety filter — belt-and-suspenders against judgment leakage
# ---------------------------------------------------------------------------

_JUDGMENT_KEY_PREFIXES = (
    "risk",
    "approval",
    "governance",
    "compliance_risk",
    "policy",
    "violation",
    "required_approval",
    "conflict",
)


def is_left_panel_safe(entity: _EntityRaw) -> bool:
    """Return True when an entity is safe for the left panel."""
    if entity.kind == "judgment":
        return False
    if entity.confidence < 0.3:
        return False
    if not entity.value.strip():
        return False
    key_lower = entity.key.lower()
    cat_lower = entity.category.lower()
    for prefix in _JUDGMENT_KEY_PREFIXES:
        if key_lower.startswith(prefix) or cat_lower.startswith(prefix):
            return False
    return True


def filter_left_panel_entities(entities: list[_EntityRaw]) -> list[_EntityRaw]:
    """Return only entities that pass is_left_panel_safe."""
    return [e for e in entities if is_left_panel_safe(e)]


# ---------------------------------------------------------------------------
# Public extraction function
# ---------------------------------------------------------------------------


def extract_decision_context(
    decision_text: str,
    agent_name: str = "AI Agent",
    agent_name_en: str = "AI Agent",
    lang: str = "en",
    *,
    _client: Any = None,  # Reserved for future LangChain injection
) -> Optional[dict]:
    """
    Stub: previously called BedrockClient to extract structured decision context entities.

    Returns None until replaced by LangChain-based implementation.
    Never raises.
    """
    logger.debug("extract_decision_context: Bedrock removed — returning None (stub)")
    return None
