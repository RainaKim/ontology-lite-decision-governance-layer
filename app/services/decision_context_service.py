"""
app/services/decision_context_service.py — LLM-based decision context extraction.

Goal: produce the left-panel-safe DecisionContextPayload from raw decision text.

Contract (dev_rules §2):
  - LLM extracts structured entities; it never computes scores or weights.
  - Output is validated through Pydantic before use.
  - Any failure returns None — never raises. Caller proceeds without context.
  - Judgment-kind entities (risks, approvals, governance conclusions) are
    filtered out by is_left_panel_safe() before the payload is returned.

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

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal Pydantic models — raw LLM output shape
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
# System prompt for context extraction
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a decision context extractor. Given a decision text proposed by an AI agent, \
extract structured entities that describe the factual context of the decision.

Your output must conform to this schema:
- proposal: a one-sentence English summary of the proposed decision
- proposal_en: same as proposal (English)
- source_label: the name of the AI agent that proposed the decision
- entities: a list of extracted entities, each with:
  - key: snake_case identifier (e.g. "budget_amount", "department", "timeline")
  - label: human-readable label in the decision's language
  - label_en: English label
  - value: extracted value in the decision's language
  - value_en: English value
  - category: one of "financial", "organizational", "temporal", "technical", "operational"
  - kind: one of "fact" (objective data), "context" (background info), "judgment" (subjective assessment)
  - confidence: 0.0-1.0

Rules:
1. Extract ONLY factual entities — costs, departments, timelines, headcounts, tools, etc.
2. Do NOT extract risk assessments, approval requirements, or governance conclusions — those are "judgment" kind.
3. Set kind="fact" for numbers, dates, names. Set kind="context" for background information.
4. If a value is ambiguous, set lower confidence.
5. Do NOT invent information not present in the text."""


# ---------------------------------------------------------------------------
# Public extraction function
# ---------------------------------------------------------------------------


def extract_decision_context(
    decision_text: str,
    agent_name: str = "AI Agent",
    agent_name_en: str = "AI Agent",
    lang: str = "en",
    *,
    _client: Any = None,  # Accepts a LangChain BaseChatModel for testing; falls back to get_llm("fast")
) -> Optional[dict]:
    """
    Extract structured decision context entities from raw decision text using LangChain.

    Uses ``get_llm("fast").with_structured_output(_ContextRaw)`` for extraction.
    Filters out judgment-kind entities before returning.
    Never raises — returns None on any failure so the pipeline continues.
    """
    try:
        if _client is None:
            from app.config.llm import get_llm
            _client = get_llm("fast")

        structured_llm = _client.with_structured_output(_ContextRaw)

        user_content = (
            f"Agent name: {agent_name_en}\n"
            f"Language: {lang}\n\n"
            f"## Decision Text\n{decision_text}"
        )

        raw_result: _ContextRaw = structured_llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])

        if not isinstance(raw_result, _ContextRaw):
            logger.warning(
                "extract_decision_context: unexpected return type %s — returning None",
                type(raw_result),
            )
            return None

        # Override source_label with the actual agent name
        raw_result.source_label = agent_name

        # Filter out judgment entities before returning
        safe_entities = filter_left_panel_entities(raw_result.entities)

        payload = {
            "proposal": raw_result.proposal,
            "proposal_en": raw_result.proposal_en,
            "source_label": raw_result.source_label,
            "entities": [e.model_dump() for e in safe_entities],
        }

        logger.info(
            "extract_decision_context: success — %d entities (%d after filtering)",
            len(raw_result.entities),
            len(safe_entities),
        )
        return payload

    except Exception as exc:
        logger.warning("extract_decision_context failed (non-fatal): %s", exc, exc_info=True)
        return None
