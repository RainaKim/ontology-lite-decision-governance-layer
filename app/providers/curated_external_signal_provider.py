"""
curated_external_signal_provider.py — Deterministic fallback external signal provider.

Used when Nova generation fails or times out. Returns pre-computed, company-aware
signals built directly from curated source JSON files.

Behavior:
  - Deterministic: same inputs always produce the same output
  - Company-aware: signal selection driven by company + decision type
  - Graceful: returns None (not error) when no signals can be produced

Design contract: identical to Nova output — same ExternalSignalsPayload shape,
same separation from internal governance evidence.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.schemas.external_signals import (
    ExternalSignal,
    ExternalSignalSource,
    ExternalSignalsPayload,
)

logger = logging.getLogger(__name__)

_SOURCES_DIR = Path(__file__).parent.parent / "demo_fixtures" / "external_sources"

from app.config.company_registry import PROFILE_ALIASES as _PROFILE_ALIASES

# Maps category → bucket for signal grouping
_CATEGORY_BUCKET = {
    "trend_signal": "market",
    "market_benchmark": "market",
    "regulatory_guidance": "regulatory",
    "compliance_signal": "regulatory",
    "operational_signal": "operational",
}

def _load_priorities(company_id: str) -> dict[str, list[str]]:
    path = Path(__file__).parent.parent / "demo_fixtures" / "external_sources" / f"{company_id}_priorities.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def get_fallback_signals(
    company_id: str,
    decision_context: dict,
    triggered_rules: Optional[list[dict]] = None,
) -> Optional[ExternalSignalsPayload]:
    """
    Build deterministic external signals from curated sources.

    Args:
        company_id:      Company ID (e.g. "sool_sool_icecream").
        decision_context: Structured context dict:
                          decision_text, decision_type, cost, risk_band.
        triggered_rules: Optional list of triggered governance rule dicts.

    Returns:
        ExternalSignalsPayload with 2–3 signals, or None if sources unavailable.
    """
    sources = _load_sources(company_id)
    if not sources:
        logger.warning(f"[curated_fb][{company_id}] No curated sources available")
        return None

    decision_type = decision_context.get("decision_type", "general")
    decision_text = decision_context.get("decision_text", "")

    # Select sources by decision-type priority, fall back to relevance tag scoring
    selected = _select_sources(company_id, decision_type, sources)
    if not selected:
        logger.warning(f"[curated_fb][{company_id}] No matching sources for type={decision_type}")
        return None

    market: list[ExternalSignal] = []
    regulatory: list[ExternalSignal] = []
    operational: list[ExternalSignal] = []

    for i, src in enumerate(selected[:3], 1):
        signal = _source_to_signal(src, decision_text, f"EXT_FB_{i:03d}")
        bucket = _CATEGORY_BUCKET.get(src.get("category", ""), "operational")
        if bucket == "market":
            market.append(signal)
        elif bucket == "regulatory":
            regulatory.append(signal)
        else:
            operational.append(signal)

    if not (market or regulatory or operational):
        return None

    logger.info(
        f"[curated_fb][{company_id}] Fallback signals — "
        f"market={len(market)}, regulatory={len(regulatory)}, operational={len(operational)}"
    )

    return ExternalSignalsPayload(
        marketSignals=market,
        regulatorySignals=regulatory,
        operationalSignals=operational,
        generatedAt=datetime.now(timezone.utc).isoformat(),
    )


# ── Internal helpers ──────────────────────────────────────────────────────────


def _load_sources(company_id: str) -> list[dict]:
    """Load curated source entries for a company."""
    file_stem = _PROFILE_ALIASES.get(company_id, company_id)
    path = _SOURCES_DIR / f"{file_stem}_sources.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text("utf-8")).get("sources", [])
    except Exception as exc:
        logger.warning(f"[curated_fb] Failed to load {path}: {exc}")
        return []


def _select_sources(
    company_id: str,
    decision_type: str,
    all_sources: list[dict],
) -> list[dict]:
    """Return up to 3 sources ordered by decision-type priority."""
    company_priorities = _load_priorities(company_id)
    priority_ids = company_priorities.get(decision_type) or company_priorities.get("general", [])

    src_map = {s.get("sourceId", ""): s for s in all_sources}

    # Build ordered list from priority, then fill with remaining to reach max 3
    ordered: list[dict] = []
    for sid in priority_ids:
        if sid in src_map:
            ordered.append(src_map[sid])
    # Append remaining sources not yet included (for companies without explicit priority)
    seen = {s.get("sourceId") for s in ordered}
    for src in all_sources:
        if src.get("sourceId") not in seen:
            ordered.append(src)

    return ordered[:3]


def _source_to_signal(src: dict, decision_text: str, signal_id: str) -> ExternalSignal:
    """Convert a curated source entry to an ExternalSignal."""
    source_type = src.get("sourceType", "industry_benchmark")
    relevance_en = src.get("relevanceHintEn", "This benchmark provides relevant context for the current decision.")
    relevance_ko = src.get("relevanceHintKo", "이 벤치마크는 현재 결정에 관련된 맥락을 제공합니다.")

    summary_text = src.get("summaryText", "")
    # Trim summary to 1 sentence
    summary_1s = summary_text.split(". ")[0] + "." if ". " in summary_text else summary_text

    return ExternalSignal(
        id=signal_id,
        category=src.get("category", "operational_signal"),
        titleKo=src.get("title", "외부 신호"),
        titleEn=src.get("title", "External signal"),
        summaryKo=summary_1s,
        summaryEn=summary_1s,
        decisionRelevanceKo=relevance_ko,
        decisionRelevanceEn=relevance_en,
        confidence=0.70,  # deterministic fallback uses conservative confidence
        source=ExternalSignalSource(
            sourceId=src.get("sourceId", signal_id),
            title=src.get("title", ""),
            sourceLabel=src.get("sourceLabel", ""),
            sourceType=source_type,
            recency=src.get("recency"),
        ),
        tags=src.get("relevanceTags"),
    )
