"""
app/schemas/external_signals.py — External signal payload schemas.

External signals are supplementary context from public market, regulatory,
and operational sources outside the company's internal governance system.

Design contract:
  - External signals are ADDITIVE and SUPPLEMENTARY only.
  - They NEVER modify internal governance rules, approval chains, or risk scores.
  - They NEVER replace internal evidence registry output.
  - They provide market/regulatory/operational context to help decision reviewers
    understand the external environment in which the decision is being made.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ExternalSignalSource(BaseModel):
    """Provenance of a single external signal."""
    sourceId: str = Field(description="Unique identifier for the source document")
    title: str = Field(description="Full document/report title")
    sourceLabel: str = Field(description="Short display label, e.g. 'IDFA 2025', 'HHS OCR'")
    sourceType: str = Field(
        description=(
            "industry_benchmark | market_research | regulatory_guideline | "
            "operational_study | labor_regulation"
        )
    )
    url: Optional[str] = Field(default=None, description="Source URL (populated by live search)")
    recency: Optional[str] = Field(
        default=None,
        description="Recency indicator: 'recent' | 'quarterly' | 'annual' | year string e.g. '2025'"
    )


class RiskAdjustment(BaseModel):
    """
    A structured risk score adjustment derived from an external signal.

    These are computed by LLM synthesis and applied to risk dimension scores
    BEFORE final risk band computation. Delta is clamped to [-15, +15].
    """
    dimension: Literal["financial", "compliance", "strategic"]
    delta: int = Field(
        description="Points to add to dimension score (-15 to +15). Negative = reduces risk.",
        ge=-15,
        le=15,
    )
    rationale: str = Field(description="One sentence explaining why this adjustment applies.")
    confidence: float = Field(ge=0.0, le=1.0)
    source_signal_id: str = Field(description="ID of the ExternalSignal that caused this adjustment.")


class ExternalSignal(BaseModel):
    """
    A single structured external signal relevant to the decision under governance.

    Signals are generated from company-specific context and curated sources.
    They are purely informational — they do not alter scores or approval requirements.

    Fields:
      summary         — 1 sentence: describes the external benchmark / signal itself
      decisionRelevance — 1 sentence: explains WHY the signal matters for THIS specific decision
    """
    id: str = Field(description="Unique signal identifier, e.g. 'EXT_SIG_001'")
    category: str = Field(
        description=(
            "market_benchmark | regulatory_guidance | operational_signal | "
            "trend_signal | compliance_signal"
        )
    )
    title: str = Field(description="Signal title")
    summary: str = Field(description="1 sentence description of the external benchmark")
    decisionRelevance: str = Field(
        default="",
        description="1 sentence: why this signal matters specifically for THIS decision"
    )
    confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="0.5–0.9 based on source recency and relevance to the decision"
    )
    source: ExternalSignalSource
    tags: Optional[list[str]] = Field(default=None, description="Searchable tags, e.g. 'demand_trend'")


class ExternalSignalsPayload(BaseModel):
    """
    Full external signal output — attached as an additive top-level field
    on ConsolePayloadResponse.

    Signals are grouped by type:
      marketSignals      — demand, competitive, consumer trend signals
      regulatorySignals  — compliance, legal, regulatory guidance signals
      operationalSignals — supply chain, cost, operational benchmark signals

    generatedAt: ISO 8601 timestamp of when this payload was produced.
    """
    marketSignals: list[ExternalSignal] = Field(default_factory=list)
    regulatorySignals: list[ExternalSignal] = Field(default_factory=list)
    operationalSignals: list[ExternalSignal] = Field(default_factory=list)
    riskAdjustments: list[RiskAdjustment] = Field(default_factory=list)
    generatedAt: Optional[str] = None
