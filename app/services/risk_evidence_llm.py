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
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.schemas.risk_semantics import RiskSemantics

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a governance risk semantics classifier. Given a decision text, company \
strategic goals, and triggered governance rules, extract structured risk semantics.

Your output must conform EXACTLY to the following schema:
- goal_impacts: list of objects with goal_id (str), direction ("support"|"conflict"|"neutral"), \
magnitude ("low"|"med"|"high"), rationale_ko (one Korean sentence), confidence (0.0-1.0)
- compliance_facts: object with optional booleans uses_pii, anonymization_missing, involves_compliance_risk
- numeric_estimates: optional object with cost_delta_pct (float, positive=increase) and revenue_uplift_pct (float)
- global_confidence: float 0.0-1.0

Rules:
1. Only classify — never compute scores or weights.
2. For goal_impacts, only include goals where direction != neutral.
3. rationale_ko MUST be in Korean.
4. If unsure, set confidence lower rather than guessing."""


def infer_risk_semantics(
    decision_text: str,
    company_summary: dict,
    triggered_rules_summary: list[dict],
    *,
    _client: Any = None,  # Accepts a LangChain BaseChatModel for testing; falls back to get_llm("fast")
) -> Optional[RiskSemantics]:
    """
    Classify goal impacts and compliance facts from decision text using LangChain.

    Uses ``get_llm("fast").with_structured_output(RiskSemantics)`` for extraction.
    Never raises — returns None on any failure so the pipeline continues.
    """
    try:
        if _client is None:
            from app.config.llm import get_llm
            _client = get_llm("fast")

        structured_llm = _client.with_structured_output(RiskSemantics)

        goals_text = json.dumps(company_summary.get("strategic_goals", []), ensure_ascii=False, default=str)
        rules_text = json.dumps(triggered_rules_summary, ensure_ascii=False, default=str)

        user_content = (
            f"## Decision Text\n{decision_text}\n\n"
            f"## Company Strategic Goals\n{goals_text}\n\n"
            f"## Triggered Governance Rules\n{rules_text}"
        )

        result = structured_llm.invoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=user_content),
        ])

        if isinstance(result, RiskSemantics):
            logger.info(
                "infer_risk_semantics: success — %d goal_impacts, confidence=%.2f",
                len(result.goal_impacts),
                result.global_confidence,
            )
            return result

        logger.warning("infer_risk_semantics: unexpected return type %s — returning None", type(result))
        return None

    except Exception as exc:
        logger.warning("infer_risk_semantics failed (non-fatal): %s", exc, exc_info=True)
        return None
