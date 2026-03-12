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

For testing, pass _client to inject a mock BedrockClient::

    result = extract_decision_context(..., _client=mock_client)
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.services.bedrock_extractor import BedrockStructuredExtractor

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

# These keywords in a *key* or *category* indicate judgment items that must
# stay on the right panel. They are NOT semantic labels — they are structural
# identifiers produced by the LLM schema we define ourselves, so this is a
# config-table guard, not a keyword-based semantic classifier (dev_rules §4).
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
    """
    Return True when an entity is safe for the left panel.

    Blocks:
    - kind == "judgment"
    - low confidence (< 0.3)
    - key or category starting with a judgment prefix
    - empty value
    """
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
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a decision context extractor for a corporate governance system.

Given a raw decision text, extract structured context entities that describe
WHAT the decision is (facts and context), NOT whether it is risky or approved.

Return JSON only. No markdown. Match this schema exactly:

{
  "proposal": "<one-sentence Korean summary of the proposed decision>",
  "proposal_en": "<one-sentence English summary>",
  "source_label": "<agent or team name if mentioned, else 'AI Agent'>",
  "entities": [
    {
      "key": "<snake_case machine key>",
      "label": "<Korean human-readable label>",
      "label_en": "<English human-readable label>",
      "value": "<Korean display value>",
      "value_en": "<English display value>",
      "category": "<one of: action|department|cost|headcount|region|timeline|channel|product|technology|vendor|budget_period|metric|other>",
      "kind": "<fact|context|judgment>",
      "confidence": <0.0 to 1.0>
    }
  ]
}

Rules:
1. Extract ONLY what is explicitly stated in the decision text. Do not infer or hallucinate.
2. kind = "fact"     → objective, verifiable data point (cost, headcount, date, channel)
   kind = "context"  → background or framing information (reason, motivation, market condition)
   kind = "judgment" → governance conclusion (risk level, approval needed, policy conflict)
3. Do NOT include kind="judgment" entities — governance conclusions belong in a separate panel.
4. Keep values concise (< 80 chars). Translate to English for value_en.
5. Confidence: 1.0 = explicitly stated, 0.7 = strongly implied, 0.4 = weakly implied, 0.0 = guessed.
6. Always include at least one entity with key="proposed_action" and kind="fact" for the decision statement.
7. Aim for 3–8 entities. Quality over quantity.
"""

_USER_TEMPLATE = """\
## Decision Text
{decision_text}

## Language
Display language: {lang}

Extract and return JSON only.
"""


# ---------------------------------------------------------------------------
# Public extraction function
# ---------------------------------------------------------------------------


def extract_decision_context(
    decision_text: str,
    agent_name: str = "AI Agent",
    agent_name_en: str = "AI Agent",
    lang: str = "ko",
    *,
    _client: Any = None,
) -> Optional[dict]:
    """
    Call the LLM to extract structured decision context entities.

    Returns:
        dict (serialised DecisionContextPayload-compatible) on success,
        None on any failure.

    Never raises.
    """
    try:
        user_content = _USER_TEMPLATE.format(
            decision_text=decision_text[:3000],
            lang="Korean" if lang == "ko" else "English",
        )

        ctx = BedrockStructuredExtractor(_client=_client).extract(
            user_content, _ContextRaw, system_prompt=_SYSTEM_PROMPT
        )
        if ctx is None:
            logger.debug("extract_decision_context: extractor returned None — skipping")
            return None

        safe_entities = filter_left_panel_entities(ctx.entities)
        is_en = lang == "en"
        src_label = (agent_name_en if is_en else agent_name) or "AI Agent"

        serialised: dict = {
            "proposal": ctx.proposal,        # always Korean
            "proposal_en": ctx.proposal_en,  # always English
            "source": {
                "type": "AI_AGENT",
                "label": src_label,
            },
            "entities": [
                {
                    "key": e.key,
                    "label": e.label_en if is_en else e.label,
                    "value": e.value_en if is_en else e.value,
                    "category": e.category,
                    "kind": e.kind,
                    "confidence": e.confidence,
                }
                for e in safe_entities
            ],
        }
        logger.info(
            f"extract_decision_context: {len(safe_entities)}/{len(ctx.entities)} entities "
            f"passed left-panel filter"
        )
        return serialised

    except Exception as e:
        logger.warning(f"extract_decision_context: unexpected error — {e}")
        return None
