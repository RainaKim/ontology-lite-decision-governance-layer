"""
app/services/risk_evidence_llm.py — Optional LLM semantics inference helper.

Contract (dev_rules §2):
  - LLM is called ONLY for classification/extraction. No scores. No weights.
  - Output is validated through RiskSemantics (Pydantic) before use.
  - Any failure (network, JSON parse, validation) returns None — never raises.
  - The caller proceeds without semantics when None is returned.

Usage::

    semantics = infer_risk_semantics(
        decision_text=record.input_text,
        company_summary=company_summary,
        triggered_rules_summary=triggered_rules_summary,
    )
    # semantics is RiskSemantics | None

NOTE: BedrockClient has been removed. This function is a stub that returns None
until a LangChain-based replacement is implemented.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.schemas.risk_semantics import RiskSemantics

logger = logging.getLogger(__name__)


def infer_risk_semantics(
    decision_text: str,
    company_summary: dict,
    triggered_rules_summary: list[dict],
    *,
    _client: Any = None,  # Reserved for future injection; unused until LangChain replacement
) -> Optional[RiskSemantics]:
    """
    Stub: previously called BedrockClient to classify goal impacts and compliance facts.

    Returns None until replaced by LangChain-based implementation.
    Never raises.
    """
    logger.debug("infer_risk_semantics: Bedrock removed — returning None (stub)")
    return None
