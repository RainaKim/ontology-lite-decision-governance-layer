"""
Nova Scenario Proposer — uses Amazon Nova (via AWS Bedrock) to propose
remediation scenario candidates.

Architecture contract:
- Nova proposes WHICH templates to apply and provides Korean copy.
- Nova does NOT compute risk scores, governance rules, or approval logic.
- All outputs are validated against NovaScenarioResponse before use.
- Any failure (network, JSON parse, schema validation) returns None →
  caller falls back to deterministic template selection.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import ValidationError

from app.schemas.nova_scenarios import (
    ALLOWED_TEMPLATE_IDS,
    NovaScenarioProposal,
    NovaScenarioResponse,
)
from app.utils.llm_utils import extract_json
from app.bedrock_client import BedrockClient

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1024
_bedrock = BedrockClient()

# Prompt template — instructs Nova to pick from allowed templateIds only
_PROMPT_TEMPLATE = """\
You are assisting an enterprise AI governance system.

The following decision has governance and risk issues that require remediation.
Generate 2-3 remediation scenarios that could reduce governance risk while
keeping the decision viable.

Use ONLY the allowed scenario templates listed below. Do not invent new templateIds.

Allowed templates:
{allowed_templates}

--- Decision Summary ---
Statement: {statement}
Cost: {cost}
Uses PII: {uses_pii}
Strategic Impact: {strategic_impact}

--- Governance Findings ---
Triggered Rules: {triggered_rules}
Approval Chain: {approval_chain}

--- Risk Scoring ---
Aggregate Score: {aggregate_score} ({aggregate_band})
Financial Score: {financial_score}
Compliance Score: {compliance_score}
Strategic Score: {strategic_score}

Return JSON only. No explanation text. Output schema:

{{
  "scenarios": [
    {{
      "templateId": "<one of the allowed templates>",
      "titleKo": "<Korean title for this scenario>",
      "changeSummaryKo": "<Korean one-sentence description of the change>",
      "reasoningKo": "<Korean explanation of why this reduces risk>",
      "parameters": {{}}
    }}
  ]
}}
"""


def propose_scenarios_with_nova(
    decision: dict,
    governance_result: dict,
    risk_scoring: dict,
) -> Optional[list[NovaScenarioProposal]]:
    """
    Uses Amazon Nova to propose remediation scenario candidates.

    Returns a validated list[NovaScenarioProposal] (1-3 items, all with
    known templateIds), or None if generation or validation fails.
    """
    try:
        prompt = _build_prompt(decision, governance_result, risk_scoring)
        raw = _bedrock.invoke(prompt, max_tokens=_MAX_TOKENS)
        logger.debug(f"[nova] Raw scenario proposal output: {raw[:300]}")
        proposals = _parse_and_validate(raw)
        if proposals:
            logger.info(f"[nova] Nova scenario proposals generated — {len(proposals)} proposal(s)")
        return proposals
    except Exception as exc:
        logger.warning(f"[nova] Nova proposal failed (non-fatal): {exc} — using deterministic candidates")
        return None


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(decision: dict, governance_result: dict, risk_scoring: dict) -> str:
    dims = {d["id"]: d for d in (risk_scoring or {}).get("dimensions", [])}
    agg = (risk_scoring or {}).get("aggregate", {})

    triggered = [
        r.get("name") or r.get("rule_id", "")
        for r in (governance_result or {}).get("triggered_rules", [])
        if r.get("status", "").upper() == "TRIGGERED"
    ]
    approval_chain = [
        s.get("role") or s.get("approver_role", "")
        for s in (governance_result or {}).get("approval_chain", [])
        if s
    ]

    return _PROMPT_TEMPLATE.format(
        allowed_templates="\n".join(f"- {t}" for t in sorted(ALLOWED_TEMPLATE_IDS)),
        statement=decision.get("decision_statement", ""),
        cost=decision.get("cost"),
        uses_pii=decision.get("uses_pii"),
        strategic_impact=decision.get("strategic_impact"),
        triggered_rules=", ".join(triggered) if triggered else "없음",
        approval_chain=", ".join(approval_chain) if approval_chain else "없음",
        aggregate_score=agg.get("score", 0),
        aggregate_band=agg.get("band", "LOW"),
        financial_score=dims.get("financial", {}).get("score", 0),
        compliance_score=dims.get("compliance_privacy", {}).get("score", 0),
        strategic_score=dims.get("strategic", {}).get("score", 0),
    )


# ── JSON parse + validation ───────────────────────────────────────────────────

def _parse_and_validate(
    raw: str,
) -> Optional[list[NovaScenarioProposal]]:
    """
    Parse Nova raw output → validate against NovaScenarioResponse →
    filter to known templateIds.

    Returns filtered list (may be shorter than input) or None if nothing
    valid remains after filtering.
    """
    data = extract_json(raw)
    if data is None:
        logger.warning("[nova] JSON parse failed")
        return None

    try:
        validated = NovaScenarioResponse(**data)
    except ValidationError as exc:
        logger.warning(f"[nova] Nova output schema invalid: {exc}")
        return None

    # Filter to known templateIds only
    known = [p for p in validated.scenarios if p.templateId in ALLOWED_TEMPLATE_IDS]
    unknown = [p.templateId for p in validated.scenarios if p.templateId not in ALLOWED_TEMPLATE_IDS]
    if unknown:
        logger.warning(f"[nova] Ignoring unknown templateId(s): {unknown}")

    if not known:
        logger.warning("[nova] No valid templateIds in Nova output")
        return None

    return known
