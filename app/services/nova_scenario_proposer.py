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

import json
import logging
import os
from typing import Optional

import httpx
from pydantic import ValidationError

from app.schemas.nova_scenarios import (
    ALLOWED_TEMPLATE_IDS,
    NovaScenarioProposal,
    NovaScenarioResponse,
)
from app.utils.formatters import format_krw
from app.config.bedrock_config import NOVA_MODEL_ID, BEDROCK_REGION

logger = logging.getLogger(__name__)

_MODEL_ID = NOVA_MODEL_ID
_MAX_TOKENS = 1024
_REGION = BEDROCK_REGION

# Bedrock Runtime REST endpoint — API key passed as Bearer token
_BEDROCK_ENDPOINT = (
    f"https://bedrock-runtime.{_REGION}.amazonaws.com"
    f"/model/{_MODEL_ID}/invoke"
)

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
        raw = _call_nova(prompt)
        proposals = _parse_and_validate(raw)
        if proposals:
            logger.info(
                f"[nova] Nova scenario proposals generated — {len(proposals)} proposal(s)"
            )
        return proposals
    except Exception as exc:
        logger.warning(
            f"[nova] Nova proposal failed (non-fatal): {exc} — "
            "using fallback scenarios"
        )
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
        cost=format_krw(decision.get("cost")),
        uses_pii=decision.get("uses_pii"),
        strategic_impact=decision.get("strategic_impact"),
        triggered_rules=", ".join(triggered) if triggered else "없음",
        approval_chain=", ".join(approval_chain) if approval_chain else "없음",
        aggregate_score=agg.get("score", 0),
        aggregate_band=agg.get("band", "LOW"),
        financial_score=dims.get("financial", {}).get("score", 0),
        compliance_score=dims.get("compliance", {}).get("score", 0),
        strategic_score=dims.get("strategic", {}).get("score", 0),
    )


# ── Nova call ─────────────────────────────────────────────────────────────────

def _call_nova(prompt: str) -> str:
    """
    Invoke Amazon Nova via AWS Bedrock Runtime REST API.

    Authentication: BEDROCK_API_KEY from environment, passed as Bearer token.
    Raises on missing key, network error, or non-2xx response —
    caller (propose_scenarios_with_nova) handles via try/except.
    """
    api_key = os.environ.get("BEDROCK_API_KEY")
    if not api_key:
        raise RuntimeError("BEDROCK_API_KEY not set in environment")

    payload = {
        "messages": [
            {"role": "user", "content": [{"text": prompt}]}
        ],
        "inferenceConfig": {
            "temperature": 0,
            "maxTokens": _MAX_TOKENS,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = httpx.post(
        _BEDROCK_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=30.0,
    )
    response.raise_for_status()
    response_body = response.json()

    # Nova converse-style response: output.message.content[0].text
    return response_body["output"]["message"]["content"][0]["text"]


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
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.startswith("```")
        ).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"[nova] JSON parse failed: {exc} — using fallback scenarios")
        return None

    try:
        validated = NovaScenarioResponse(**data)
    except ValidationError as exc:
        logger.warning(f"[nova] Nova output invalid — using fallback scenarios: {exc}")
        return None

    # Filter to known templateIds only
    known = [p for p in validated.scenarios if p.templateId in ALLOWED_TEMPLATE_IDS]
    unknown = [p.templateId for p in validated.scenarios if p.templateId not in ALLOWED_TEMPLATE_IDS]
    if unknown:
        logger.warning(
            f"[nova] Ignoring unknown templateId(s): {unknown} — using fallback scenarios "
            "for those entries"
        )

    if not known:
        logger.warning("[nova] Nova output invalid — using fallback scenarios")
        return None

    return known
