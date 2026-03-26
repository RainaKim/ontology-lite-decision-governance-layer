"""
tavily_live_fetch_provider.py — Live external signal retrieval via Tavily search.

Pipeline:
  1. Build targeted search queries from decision context + governance findings
  2. Search Tavily (max 5 results per query, 2 queries max)
  3. LLM synthesis: raw results → List[ExternalSignal] + List[RiskAdjustment]
  4. Return structured payload; caller handles fallback on empty result

Design:
  - Uses fast LLM tier (extraction/classification task)
  - All LLM output validated via Pydantic before use
  - Non-fatal: any exception returns ([], [])
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

_MAX_RESULTS_PER_QUERY = 5
_MAX_QUERIES = 2
_MAX_CONTENT_CHARS = 800  # truncate Tavily content snippets before LLM


# ── LLM output schema ─────────────────────────────────────────────────────────

class _SynthesizedSignal(BaseModel):
    """LLM-extracted signal — intermediate, validated before use."""
    id: str
    category: str  # market_benchmark | regulatory_guidance | operational_signal | trend_signal | compliance_signal
    title: str
    summary: str
    decision_relevance: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_title: str
    source_type: str  # industry_benchmark | market_research | regulatory_guideline | operational_study | labor_regulation
    url: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class _SynthesizedAdjustment(BaseModel):
    """LLM-extracted risk adjustment — intermediate, validated before use."""
    dimension: str  # financial | compliance | strategic
    delta: int = Field(ge=-15, le=15)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_signal_id: str


class _SynthesisOutput(BaseModel):
    """Full LLM synthesis output — validated before any field is trusted."""
    signals: list[_SynthesizedSignal] = Field(default_factory=list)
    risk_adjustments: list[_SynthesizedAdjustment] = Field(default_factory=list)


# ── Query builder ─────────────────────────────────────────────────────────────

def _build_queries(decision_context: dict, company_profile: dict) -> list[str]:
    """
    Build 1-2 targeted Tavily search queries from decision context.

    Queries are specific enough to return relevant market/regulatory results
    but broad enough to find something useful.
    """
    decision_text = decision_context.get("decision_text", "")
    decision_type = decision_context.get("decision_type", "general")
    industry = company_profile.get("industry", "technology")
    cost = decision_context.get("cost")
    risk_band = decision_context.get("risk_band", "UNKNOWN")

    queries = []

    # Primary query — decision type specific
    if decision_type == "hiring":
        queries.append(f"{industry} engineer compensation benchmark salary 2024 2025")
        if risk_band in ("HIGH", "CRITICAL"):
            queries.append(f"tech hiring trends {industry} Series B 2024 headcount freeze")
    elif decision_type == "privacy":
        queries.append(f"GDPR enforcement actions analytics companies 2024 fines penalties")
        queries.append(f"EU data privacy compliance costs enterprise 2024")
    elif decision_type == "procurement":
        if cost and cost > 100000:
            queries.append(f"{industry} vendor procurement governance best practices 2024")
        queries.append(f"cloud infrastructure cost benchmarks {industry} 2024")
    else:
        # General: use decision text keywords + industry
        keywords = " ".join(decision_text.split()[:8])
        queries.append(f"{keywords} {industry} industry benchmark 2024")

    return queries[:_MAX_QUERIES]


# ── LLM synthesis ─────────────────────────────────────────────────────────────

_SYNTHESIS_PROMPT = """You are a governance analyst. Given search results about a business decision, extract structured external signals and risk adjustments.

DECISION CONTEXT:
{decision_context}

GOVERNANCE FINDINGS:
- Triggered rules: {triggered_rules}
- Risk band: {risk_band}

SEARCH RESULTS:
{search_results}

Extract external signals that are genuinely relevant to this specific decision. For each signal, also determine if it warrants a risk score adjustment.

Risk adjustment guidelines:
- financial: adjust if market data shows the decision is significantly above/below market rate (e.g., paying 30% above market → +8 financial risk; paying at market → -5 financial risk)
- compliance: adjust if regulatory signals show elevated enforcement risk or recent penalties in this area (+5 to +15)
- strategic: adjust if industry trends contradict or strongly support the decision direction (-10 to +10)
- Only generate adjustments with clear, specific evidence. Do NOT generate adjustments for vague signals.
- Delta range: -15 (reduces risk) to +15 (increases risk)

Return JSON only:
{{
  "signals": [
    {{
      "id": "EXT_SIG_001",
      "category": "market_benchmark|regulatory_guidance|operational_signal|trend_signal|compliance_signal",
      "title": "...",
      "summary": "One sentence describing the external data point.",
      "decision_relevance": "One sentence: why this matters for THIS specific decision.",
      "confidence": 0.7,
      "source_title": "...",
      "source_type": "industry_benchmark|market_research|regulatory_guideline|operational_study|labor_regulation",
      "url": "...",
      "tags": ["tag1", "tag2"]
    }}
  ],
  "risk_adjustments": [
    {{
      "dimension": "financial|compliance|strategic",
      "delta": 8,
      "rationale": "One sentence explaining the adjustment.",
      "confidence": 0.75,
      "source_signal_id": "EXT_SIG_001"
    }}
  ]
}}

Rules:
- Only include signals that are directly relevant to the decision. Discard generic results.
- Maximum 4 signals total. Maximum 3 risk adjustments.
- If no results are relevant, return {{"signals": [], "risk_adjustments": []}}
- Return valid JSON only. No markdown fences."""


def _synthesize_with_llm(
    decision_context: dict,
    triggered_rules: list,
    search_results: list[dict],
) -> _SynthesisOutput:
    """Call fast LLM tier to synthesize raw search results into structured signals."""
    from app.config.llm import get_llm

    # Format search results for prompt
    formatted_results = []
    for i, r in enumerate(search_results[:8]):  # cap at 8 results
        content = (r.get("content") or r.get("snippet") or "")[:_MAX_CONTENT_CHARS]
        formatted_results.append(
            f"[{i+1}] {r.get('title', 'Untitled')}\n"
            f"URL: {r.get('url', '')}\n"
            f"Content: {content}"
        )

    prompt = _SYNTHESIS_PROMPT.format(
        decision_context=json.dumps(decision_context, indent=2),
        triggered_rules=", ".join(
            r.get("rule_id", str(r)) if isinstance(r, dict) else str(r)
            for r in triggered_rules
        ) if triggered_rules else "none",
        risk_band=decision_context.get("risk_band", "UNKNOWN"),
        search_results="\n\n".join(formatted_results) if formatted_results else "No results found.",
    )

    llm = get_llm("fast")
    from langchain_core.messages import HumanMessage
    response = llm.invoke([HumanMessage(content=prompt)])
    raw = response.content if hasattr(response, "content") else str(response)

    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    data = json.loads(raw)
    return _SynthesisOutput.model_validate(data)


# ── Public provider ───────────────────────────────────────────────────────────

def fetch_and_synthesize(
    decision_context: dict,
    company_profile: dict,
    triggered_rules: list,
) -> tuple[list, list]:
    """
    Run Tavily search + LLM synthesis.

    Returns:
        (raw_signals_dicts, raw_adjustments_dicts) — dicts ready for schema conversion.
        Both lists may be empty on failure or no relevant results.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.debug("[tavily] TAVILY_API_KEY not set — skipping live fetch")
        return [], []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)

        queries = _build_queries(decision_context, company_profile)
        all_results: list[dict] = []

        for query in queries:
            logger.info("[tavily] Searching: %s", query)
            try:
                resp = client.search(
                    query=query,
                    search_depth="basic",
                    max_results=_MAX_RESULTS_PER_QUERY,
                    include_answer=False,
                )
                results = resp.get("results", [])
                all_results.extend(results)
                logger.info("[tavily] Query returned %d results", len(results))
            except Exception as qe:
                logger.warning("[tavily] Query failed: %s", qe)

        if not all_results:
            logger.info("[tavily] No results from any query")
            return [], []

        # LLM synthesis
        synthesis = _synthesize_with_llm(decision_context, triggered_rules, all_results)
        logger.info(
            "[tavily] Synthesis complete — %d signals, %d adjustments",
            len(synthesis.signals),
            len(synthesis.risk_adjustments),
        )

        return (
            [s.model_dump() for s in synthesis.signals],
            [a.model_dump() for a in synthesis.risk_adjustments],
        )

    except (ValidationError, json.JSONDecodeError) as ve:
        logger.warning("[tavily] LLM synthesis validation failed: %s", ve)
        return [], []
    except Exception as e:
        logger.warning("[tavily] fetch_and_synthesize failed (non-fatal): %s", e, exc_info=True)
        return [], []
