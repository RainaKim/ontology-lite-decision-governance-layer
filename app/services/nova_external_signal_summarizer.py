"""
nova_external_signal_summarizer.py — Nova-powered external signal generation.

Generates structured ExternalSignalsPayload using Amazon Nova (AWS Bedrock).
Each signal includes:
  - summary:           what the external benchmark says (1 sentence)
  - decisionRelevance: why it matters for THIS specific decision (1 sentence)

Architecture contract:
  - Nova generates signals grounded in provided company context + curated sources.
  - Nova does NOT compute governance scores, rules, or approval logic.
  - All outputs are Pydantic-validated before use.
  - Any failure returns None — caller falls back to curated provider.
  - External signals NEVER modify governance verdicts, risk scores, or approval chains.

Public API:
  generate_external_signals(company_profile, decision_context, triggered_rules,
                             internal_entities, available_sources=None)
    → Optional[ExternalSignalsPayload]
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from pydantic import BaseModel, ValidationError

from app.schemas.external_signals import (
    ExternalSignal,
    ExternalSignalSource,
    ExternalSignalsPayload,
)
from app.config.bedrock_config import NOVA_MODEL_ID, BEDROCK_REGION

logger = logging.getLogger(__name__)

_MODEL_ID = NOVA_MODEL_ID
_MAX_TOKENS = 1400
_REGION = BEDROCK_REGION
_BEDROCK_ENDPOINT = (
    f"https://bedrock-runtime.{_REGION}.amazonaws.com"
    f"/model/{_MODEL_ID}/invoke"
)

_VALID_SOURCE_TYPES = frozenset({
    "industry_benchmark",
    "market_research",
    "regulatory_guideline",
    "operational_study",
    "labor_regulation",
})

# ── Internal Nova output schema ───────────────────────────────────────────────


class _NovaSignalItem(BaseModel):
    """Single signal as returned by Nova — validated before conversion."""
    id: str
    bucket: str                        # "market" | "regulatory" | "operational"
    category: str
    titleKo: str
    titleEn: Optional[str] = None
    summaryKo: str
    summaryEn: Optional[str] = None
    decisionRelevanceKo: str = ""
    decisionRelevanceEn: str = ""
    confidence: float = 0.7
    sourceId: str
    sourceTitle: Optional[str] = None
    sourceLabel: Optional[str] = None
    sourceType: Optional[str] = None
    recency: Optional[str] = None
    tags: Optional[list[str]] = None


class _NovaSignalOutput(BaseModel):
    signals: list[_NovaSignalItem]


# ── Prompt template ───────────────────────────────────────────────────────────

_PROMPT_TEMPLATE = """\
You are an industry analyst providing contextual external signals that may affect \
a company's governance decision.

COMPANY CONTEXT:
Company: {company_name} ({industry})
Market / Regions: {regions}
Key Signal Areas: {signal_emphasis}

DECISION CONTEXT:
Decision: {decision_text}
Decision Type: {decision_type}
Cost / Investment: {cost}
Strategic Impact: {strategic_impact}

GOVERNANCE CONTEXT:
Triggered Rules: {triggered_rules}
Governance Flags: {governance_flags}
Risk Level: {risk_band}

KEY DECISION ENTITIES:
{entities}

AVAILABLE REFERENCE SOURCES (use sourceId from these if relevant):
{available_sources}

GENERATE exactly 1–2 market signals, 1–2 operational signals, and 0–1 regulatory signals.

Each signal MUST include:
- "summary": 1 sentence describing the external benchmark or industry pattern itself
- "decisionRelevance": 1 sentence explaining WHY this signal matters specifically \
for THIS decision (must reference the decision context)
- confidence: 0.5–0.9 based on source recency and relevance
- source metadata with sourceType from: \
industry_benchmark, market_research, regulatory_guideline, operational_study, labor_regulation

Rules:
- Signals must be realistic and grounded in known industry patterns
- Use approximate benchmark language where exact figures are uncertain
- Do NOT repeat internal governance findings (triggered rules, approval chain) as signals
- Do NOT fabricate statistics not supported by the reference sources
- Each signal must be actionable context for the decision reviewer
- Return JSON only — no explanation text outside the JSON block

OUTPUT FORMAT (JSON only):

{{
  "signals": [
    {{
      "id": "EXT_SIG_001",
      "bucket": "market",
      "category": "trend_signal",
      "titleKo": "한국어 제목 (30자 이내)",
      "titleEn": "English title (under 40 chars)",
      "summaryKo": "외부 벤치마크 설명 1문장.",
      "summaryEn": "1-sentence description of the external benchmark.",
      "decisionRelevanceKo": "이 신호가 이 결정에 중요한 이유 1문장.",
      "decisionRelevanceEn": "1-sentence reason this signal matters for THIS specific decision.",
      "confidence": 0.75,
      "sourceId": "SOURCE_ID",
      "sourceTitle": "Full source title",
      "sourceLabel": "Short label e.g. IDFA 2025",
      "sourceType": "industry_benchmark",
      "recency": "2025",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}
"""


# ── Primary public function ───────────────────────────────────────────────────


def generate_external_signals(
    company_profile: dict,
    decision_context: dict,
    triggered_rules: list[dict],
    internal_entities: dict,
    available_sources: Optional[list[dict]] = None,
) -> Optional[ExternalSignalsPayload]:
    """
    Generate structured external signals using Amazon Nova.

    Args:
        company_profile:   External profile dict (from load_company_external_profile).
        decision_context:  Structured context dict:
                             decision_text, decision_type, cost,
                             strategic_impact, risk_band.
        triggered_rules:   List of triggered governance rule dicts.
        internal_entities: Key decision entities:
                             cost, involves_hiring, uses_pii,
                             new_product_development, triggered_flags, etc.
        available_sources: Optional curated source dicts for Nova grounding.

    Returns:
        ExternalSignalsPayload on success, None on any failure.
    """
    try:
        prompt = _build_prompt(
            company_profile, decision_context, triggered_rules,
            internal_entities, available_sources or []
        )
        raw = _call_nova(prompt)
        payload = _parse_and_validate(raw, available_sources or [])
        if payload:
            cid = company_profile.get("companyId", "?")
            logger.info(
                f"[nova_ext][{cid}] Signals generated — "
                f"market={len(payload.marketSignals)}, "
                f"regulatory={len(payload.regulatorySignals)}, "
                f"operational={len(payload.operationalSignals)}"
            )
        return payload
    except Exception as exc:
        cid = company_profile.get("companyId", "?")
        logger.warning(
            f"[nova_ext][{cid}] Nova generation failed (non-fatal): {exc}"
        )
        return None


# ── Prompt builder ────────────────────────────────────────────────────────────


def _build_prompt(
    company_profile: dict,
    decision_context: dict,
    triggered_rules: list[dict],
    internal_entities: dict,
    available_sources: list[dict],
) -> str:
    company_name = company_profile.get("companyName", company_profile.get("companyId", "Unknown"))
    industry = company_profile.get("industry", "")
    regions = ", ".join(company_profile.get("regions", []))
    signal_emphasis = ", ".join(company_profile.get("signalEmphasis", []))

    decision_text = decision_context.get("decision_text", "")
    decision_type = decision_context.get("decision_type", "general")
    cost = decision_context.get("cost")
    cost_str = f"${cost:,}" if cost else "N/A"
    strategic_impact = decision_context.get("strategic_impact", "N/A")
    risk_band = decision_context.get("risk_band", "UNKNOWN")

    triggered_names = [
        r.get("name") or r.get("rule_id", "")
        for r in triggered_rules if r
    ]
    triggered_str = ", ".join(triggered_names[:4]) if triggered_names else "None"

    flags = internal_entities.get("triggered_flags", [])
    flags_str = ", ".join(flags[:5]) if flags else "None"

    entity_lines = []
    if internal_entities.get("cost"):
        entity_lines.append(f"  Cost: ${internal_entities['cost']:,}")
    if internal_entities.get("involves_hiring"):
        entity_lines.append("  Involves hiring: yes")
    if internal_entities.get("uses_pii"):
        entity_lines.append("  Uses PII/personal data: yes")
    if internal_entities.get("new_product_development"):
        entity_lines.append("  New product development: yes")
    if internal_entities.get("headcount_change"):
        entity_lines.append(f"  Headcount change: {internal_entities['headcount_change']}")
    entities_str = "\n".join(entity_lines) if entity_lines else "  (no specific entities extracted)"

    source_lines = []
    for src in available_sources[:5]:
        sid = src.get("sourceId", "")
        title = src.get("title", "")
        label = src.get("sourceLabel", "")
        summary = (src.get("summaryText", ""))[:200]
        source_lines.append(f"[{sid}] {title} ({label})\n  {summary}")
    available_sources_str = (
        "\n\n".join(source_lines)
        if source_lines
        else "None provided — use your knowledge of industry benchmarks"
    )

    return _PROMPT_TEMPLATE.format(
        company_name=company_name,
        industry=industry,
        regions=regions or "N/A",
        signal_emphasis=signal_emphasis or "market, regulatory, operational",
        decision_text=decision_text,
        decision_type=decision_type,
        cost=cost_str,
        strategic_impact=strategic_impact,
        triggered_rules=triggered_str,
        governance_flags=flags_str,
        risk_band=risk_band,
        entities=entities_str,
        available_sources=available_sources_str,
    )


# ── Nova call ─────────────────────────────────────────────────────────────────


def _call_nova(prompt: str) -> str:
    """
    Invoke Amazon Nova via AWS Bedrock Runtime REST API.
    Authentication: BEDROCK_API_KEY env var as Bearer token.
    Raises on missing key, network error, or non-2xx response.
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
    body = response.json()
    return body["output"]["message"]["content"][0]["text"]


# ── Parse + validate ──────────────────────────────────────────────────────────


def _parse_and_validate(
    raw: str,
    available_sources: list[dict],
) -> Optional[ExternalSignalsPayload]:
    """
    Parse Nova raw output → validate → map to ExternalSignalsPayload.
    Returns None on parse error, validation failure, or empty signals.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(line for line in lines if not line.startswith("```")).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(f"[nova_ext] JSON parse failed: {exc}")
        return None

    try:
        validated = _NovaSignalOutput(**data)
    except ValidationError as exc:
        logger.warning(f"[nova_ext] Validation failed: {exc}")
        return None

    if not validated.signals:
        logger.warning("[nova_ext] Nova returned empty signals list")
        return None

    source_map: dict[str, dict] = {s.get("sourceId", ""): s for s in available_sources}

    market: list[ExternalSignal] = []
    regulatory: list[ExternalSignal] = []
    operational: list[ExternalSignal] = []

    for item in validated.signals:
        src_type = item.sourceType or ""
        if src_type not in _VALID_SOURCE_TYPES:
            src_type = _coerce_source_type(src_type)

        fallback_src = source_map.get(item.sourceId, {})
        signal = ExternalSignal(
            id=item.id,
            category=item.category,
            titleKo=item.titleKo,
            titleEn=item.titleEn,
            summaryKo=item.summaryKo,
            summaryEn=item.summaryEn,
            decisionRelevanceKo=item.decisionRelevanceKo,
            decisionRelevanceEn=item.decisionRelevanceEn,
            confidence=max(0.0, min(1.0, item.confidence)),
            source=ExternalSignalSource(
                sourceId=item.sourceId,
                title=item.sourceTitle or fallback_src.get("title", item.sourceId),
                sourceLabel=item.sourceLabel or fallback_src.get("sourceLabel", "External Source"),
                sourceType=src_type or fallback_src.get("sourceType", "industry_benchmark"),
                recency=item.recency or fallback_src.get("recency"),
            ),
            tags=item.tags,
        )

        bucket = (item.bucket or "").lower()
        if bucket == "market":
            market.append(signal)
        elif bucket == "regulatory":
            regulatory.append(signal)
        else:
            operational.append(signal)

    return ExternalSignalsPayload(
        marketSignals=market,
        regulatorySignals=regulatory,
        operationalSignals=operational,
        generatedAt=datetime.now(timezone.utc).isoformat(),
    )


def _coerce_source_type(raw: str) -> str:
    """Map legacy or unrecognised sourceType values to valid canonical values."""
    _MAP = {
        "regulatory": "regulatory_guideline",
        "government": "regulatory_guideline",
        "industry_report": "industry_benchmark",
        "trade_association": "industry_benchmark",
        "labor_guideline": "labor_regulation",
        "news": "market_research",
    }
    return _MAP.get((raw or "").lower(), "industry_benchmark")
