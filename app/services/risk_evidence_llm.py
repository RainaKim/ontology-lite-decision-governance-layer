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

For testing, pass _client to inject a mock BedrockClient::

    semantics = infer_risk_semantics(..., _client=mock_client)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.schemas.risk_semantics import RiskSemantics
from app.services.bedrock_extractor import BedrockStructuredExtractor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template (compact, schema-first)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a risk semantics classifier for corporate governance.

Given a decision text, company strategic goals, and triggered governance rules,
classify goal relationships and extract compliance facts.

Return JSON only. No markdown. No explanations. Match this schema exactly:

{
  "goal_impacts": [
    {
      "goal_id": "<string — company goal identifier>",
      "direction": "<support | conflict | neutral>",
      "magnitude": "<low | med | high>",
      "rationale_ko": "<Korean one-sentence explanation>",
      "confidence": <0.0 to 1.0>
    }
  ],
  "compliance_facts": {
    "uses_pii": <true | false | null>,
    "anonymization_missing": <true | false | null>,
    "involves_compliance_risk": <true | false | null>
  },
  "numeric_estimates": {
    "cost_delta_pct": <number or null>,
    "revenue_uplift_pct": <number or null>
  },
  "global_confidence": <0.0 to 1.0>
}

Rules:
1. goal_impacts: classify each strategic goal. Omit goals where direction is neutral — include only support or conflict entries.
2. compliance_facts: derive from the decision text only. Do not guess. Use null when uncertain.
3. cost_delta_pct: % change in costs implied by the decision (positive = cost increase, negative = cost reduction). Null if not determinable.
4. revenue_uplift_pct: % change in revenue implied. Null if not determinable.
5. rationale_ko MUST be written in Korean.
6. global_confidence: your overall confidence in this classification (0.0 = not confident, 1.0 = highly confident).
"""

_USER_TEMPLATE = """\
## Decision Text
{decision_text}

## Company Strategic Goals
{goals_block}

## Triggered Governance Rules
{rules_block}

Classify and return JSON only.
"""


def _build_goals_block(company_summary: dict) -> str:
    goals = company_summary.get("strategic_goals", [])
    if not goals:
        return "(no strategic goals provided)"
    lines = []
    for g in goals:
        gid   = g.get("goal_id", "?")
        name  = g.get("name", "")
        desc  = g.get("description", "")
        kpis  = g.get("kpis", [])
        kpi_names = ", ".join(
            k.get("name", "") if isinstance(k, dict) else str(k)
            for k in kpis[:3]
        )
        entry = f"[{gid}] {name}: {desc}"
        if kpi_names:
            entry += f" | KPIs: {kpi_names}"
        lines.append(entry)
    return "\n".join(lines)


def _build_rules_block(triggered_rules_summary: list[dict]) -> str:
    visible = [r for r in triggered_rules_summary if r.get("status") == "TRIGGERED"]
    if not visible:
        return "(no rules triggered)"
    lines = []
    for r in visible[:5]:  # cap at 5 to avoid prompt bloat
        rid   = r.get("rule_id", "?")
        name  = r.get("name", "")
        rtype = r.get("rule_type") or r.get("type") or ""
        lines.append(f"[{rid}] {name} (type={rtype})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public inference function
# ---------------------------------------------------------------------------


def infer_risk_semantics(
    decision_text: str,
    company_summary: dict,
    triggered_rules_summary: list[dict],
    *,
    _client: Any = None,  # Injected in tests; real path creates client from env
) -> Optional[RiskSemantics]:
    """
    Call the LLM to classify goal impacts and compliance facts.

    Returns:
        RiskSemantics if successful, None on any failure.

    Never raises.  Failures are logged at DEBUG/WARNING level.
    """
    try:
        user_content = _USER_TEMPLATE.format(
            decision_text=decision_text[:3000],  # truncate to avoid token overflow
            goals_block=_build_goals_block(company_summary),
            rules_block=_build_rules_block(triggered_rules_summary),
        )

        semantics = BedrockStructuredExtractor(_client=_client).extract(
            user_content, RiskSemantics, system_prompt=_SYSTEM_PROMPT
        )
        if semantics is None:
            logger.debug("infer_risk_semantics: extractor returned None — skipping")
            return None

        logger.info(
            f"infer_risk_semantics: {len(semantics.goal_impacts)} goal_impacts, "
            f"global_confidence={semantics.global_confidence:.2f}"
        )
        return semantics

    except Exception as e:
        logger.warning(f"infer_risk_semantics: unexpected error — {e}")
        return None
