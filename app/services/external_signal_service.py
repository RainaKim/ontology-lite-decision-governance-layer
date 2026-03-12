"""
external_signal_service.py — Company-aware external signal retrieval pipeline.

Pipeline:
  1. Load company external profile (company-specific signal categories + themes)
  2. Infer retrieval context from decision fields + governance findings
  3. Attempt live fetch (best-effort; gracefully returns [] in demo environments)
  4. Load curated sources for Nova grounding if live fetch is sparse (< 2 results)
  5. Call Nova (generate_external_signals) with structured context dicts
  6. If Nova fails/unavailable → curated fallback via get_fallback_signals()
  7. Return payload (None on any failure — always non-fatal)

Design contract:
  - External signals NEVER modify internal governance decisions.
  - Internal evidence registry (governance_evidence) is NEVER replaced or mixed.
  - Separation is enforced at the schema level: ExternalSignalsPayload vs governance_evidence.
  - All failures are non-fatal: caller receives None and continues.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Protocol

from app.schemas.external_signals import ExternalSignalsPayload

logger = logging.getLogger(__name__)

_PROFILES_DIR = Path(__file__).parent.parent / "demo_fixtures" / "external_profiles"
_SOURCES_DIR = Path(__file__).parent.parent / "demo_fixtures" / "external_sources"

# Max curated fallback sources to pass to Nova (keeps prompt bounded)
_MAX_SOURCES = 4

# Company ID → profile file name mapping (handles cases where file name differs from ID)
from app.config.company_registry import PROFILE_ALIASES as _PROFILE_ALIASES

# --- Configuration tables (edit here to extend, not in function bodies) ---

_DECISION_TYPE_PRIORITY: list[tuple[str, str]] = [
    ("involves_hiring", "hiring"),
    ("uses_pii", "privacy"),
    ("new_product_development", "new_product"),
]

_FLAG_KEYWORD_THEMES: list[tuple[tuple[str, ...], str]] = [
    (("FINANCIAL", "BUDGET", "COST"),             "risk_financial"),
    (("PRIVACY", "PII", "PHI"),                   "privacy_compliance"),
    (("COMPLIANCE", "REGULATORY", "VIOLATION"),   "regulatory_compliance"),
    (("STRATEGIC", "CONFLICT", "MISALIGNMENT"),   "strategic_benchmark"),
]

_STRATEGIC_IMPACT_KEYWORDS: tuple[str, ...] = ("STRATEGIC", "CONFLICT", "MISALIGNMENT")


# ── Live fetch provider interface ─────────────────────────────────────────────


class LiveFetchProvider(Protocol):
    """Protocol for live external data fetch providers."""

    def fetch(self, query: str, max_results: int = 3) -> list[dict]:
        """Attempt to fetch external sources matching the query. Returns [] on failure."""
        ...


class BestEffortWebFetchProvider:
    """
    Best-effort live web fetch — returns [] in demo/CI environments.

    This is the live fetch hook. When a production web search integration
    is available, replace this with a real provider (e.g. Bing Search API,
    Google Custom Search, Perplexity API) that returns source dicts matching
    the same shape as curated fallback sources.

    Curated fallback sources ensure stable demo behavior when live fetch
    is unavailable or returns insufficient results.
    """

    def fetch(self, query: str, max_results: int = 3) -> list[dict]:
        logger.debug(
            f"[external_signals][live_fetch] Best-effort stub — "
            f"no live provider configured, using curated fallback"
        )
        return []


# Default provider — stub for demo stability
_DEFAULT_LIVE_PROVIDER = BestEffortWebFetchProvider()


# ── Public entry point ────────────────────────────────────────────────────────


def build_external_signals(
    company_id: str,
    decision: dict,
    governance_result: dict,
    risk_scoring: Optional[dict],
    lang: str = "ko",
    live_provider: Optional[LiveFetchProvider] = None,
) -> Optional[ExternalSignalsPayload]:
    """
    Orchestrate the full external signal retrieval pipeline.

    Args:
        company_id:         Company ID from the decision record.
        decision:           Decision dict (from decision_obj.model_dump()).
        governance_result:  Governance evaluation dict (gov_dict).
        risk_scoring:       Risk scoring result dict (record.risk_scoring), may be None.
        lang:               Language code "ko" | "en".
        live_provider:      Optional live fetch provider (defaults to best-effort stub).

    Returns:
        ExternalSignalsPayload if signals were generated, else None.
    """
    try:
        profile = load_company_external_profile(company_id)
        if profile is None:
            logger.info(
                f"[external_signals][{company_id}] No external profile found — skipping"
            )
            return None

        query_context = infer_external_signal_query_context(
            decision, governance_result, risk_scoring, company_id
        )

        # Step 3: Live fetch (best-effort)
        provider = live_provider or _DEFAULT_LIVE_PROVIDER
        live_query = _build_live_query(profile, query_context)
        live_sources = retrieve_live_sources(provider, live_query)

        # Step 4: Load curated fallback if live result is insufficient
        if len(live_sources) < 2:
            logger.info(
                f"[external_signals][{company_id}] "
                f"Live fetch returned {len(live_sources)} source(s) — "
                f"loading curated fallback"
            )
            fallback = load_fallback_sources(company_id, query_context)
            sources = live_sources + fallback
        else:
            sources = live_sources

        # Build structured context dicts for Nova
        decision_type = _infer_decision_type(decision)
        decision_context = {
            "decision_text": decision.get("decision_statement", ""),
            "decision_type": decision_type,
            "cost": decision.get("cost"),
            "strategic_impact": _infer_strategic_impact(governance_result),
            "risk_band": (risk_scoring or {}).get("aggregate", {}).get("band", "UNKNOWN"),
        }
        internal_entities = {
            "cost": decision.get("cost"),
            "involves_hiring": decision.get("involves_hiring"),
            "uses_pii": decision.get("uses_pii"),
            "new_product_development": decision.get("new_product_development"),
            "headcount_change": decision.get("headcount_change"),
            "triggered_flags": (governance_result or {}).get("flags", []),
        }
        triggered_rules = (governance_result or {}).get("triggered_rules", [])

        # Step 5: Nova generation
        from app.services.nova_external_signal_summarizer import generate_external_signals

        payload = generate_external_signals(
            company_profile=profile,
            decision_context=decision_context,
            triggered_rules=triggered_rules,
            internal_entities=internal_entities,
            available_sources=sources or [],
        )

        if payload is not None:
            return payload

        # Step 6: Curated fallback when Nova fails or is unavailable
        logger.info(
            f"[external_signals][{company_id}] Nova unavailable — using curated fallback"
        )
        from app.providers.curated_external_signal_provider import get_fallback_signals

        return get_fallback_signals(company_id, decision_context, triggered_rules)

    except Exception as exc:
        logger.warning(
            f"[external_signals][{company_id}] Signal retrieval failed (non-fatal): {exc}",
            exc_info=True,
        )
        return None


# ── Profile loader ────────────────────────────────────────────────────────────


def load_company_external_profile(company_id: str) -> Optional[dict]:
    """
    Load the external signal profile for a company.

    Supports alias mapping (e.g. mayo_central → mayo_central_hospital.json).
    Returns None if no profile file exists for the company.
    """
    file_stem = _PROFILE_ALIASES.get(company_id, company_id)
    profile_path = _PROFILES_DIR / f"{file_stem}.json"

    if not profile_path.exists():
        return None

    try:
        return json.loads(profile_path.read_text("utf-8"))
    except Exception as exc:
        logger.warning(f"[external_signals] Failed to load profile {profile_path}: {exc}")
        return None


# ── Query context inference ───────────────────────────────────────────────────


def infer_external_signal_query_context(
    decision: dict,
    governance_result: dict,
    risk_scoring: Optional[dict],
    company_id: str,
) -> dict:
    """
    Derive retrieval themes from decision fields + governance findings.

    Themes drive both the live search query and the fallback source relevance
    scoring. Themes are always additive — never exclusive.
    """
    themes: list[str] = []

    # From decision fields
    if decision.get("uses_pii"):
        themes.append("privacy_compliance")
    if decision.get("involves_hiring"):
        themes.append("labor_hiring")
    if decision.get("involves_compliance_risk"):
        themes.append("regulatory_compliance")
    if decision.get("new_product_development"):
        themes.append("new_product")

    cost = decision.get("cost")
    if cost and isinstance(cost, (int, float)) and cost > 0:
        themes.append("financial_procurement")

    # From governance flags
    flags = governance_result.get("flags", []) if governance_result else []
    for flag in flags:
        for keywords, theme in _FLAG_KEYWORD_THEMES:
            if any(kw in flag for kw in keywords):
                themes.append(theme)

    # From risk scoring — add themes for HIGH/CRITICAL dimensions
    if risk_scoring:
        for dim in risk_scoring.get("dimensions", []):
            if dim.get("band") in ("HIGH", "CRITICAL"):
                dim_id = dim.get("id", "")
                if dim_id == "procurement":
                    themes.append("risk_procurement")
                elif dim_id == "financial":
                    themes.append("risk_financial")
                elif dim_id in ("compliance", "compliance_privacy"):
                    themes.append("risk_compliance")
                elif dim_id == "strategic":
                    themes.append("strategic_benchmark")

    return {
        "themes": list(dict.fromkeys(themes)),  # deduplicate, preserve order
        "statement": decision.get("decision_statement", ""),
        "company_id": company_id,
        "risk_band": (risk_scoring or {}).get("aggregate", {}).get("band", "UNKNOWN"),
    }


# ── Live fetch ────────────────────────────────────────────────────────────────


def retrieve_live_sources(
    provider: LiveFetchProvider,
    query: str,
) -> list[dict]:
    """
    Attempt live retrieval via the provider. Always returns a list (may be empty).
    Failures are swallowed — curated fallback handles the gap.
    """
    try:
        return provider.fetch(query, max_results=3) or []
    except Exception as exc:
        logger.debug(f"[external_signals][live_fetch] fetch failed: {exc}")
        return []


def _build_live_query(profile: dict, query_context: dict) -> str:
    """Build a search query string from profile themes and decision context."""
    themes = query_context.get("themes", [])
    default_themes = profile.get("searchThemes", {}).get("default", [])

    # Map decision themes to profile-specific search phrases
    decision_types = profile.get("searchThemes", {}).get("decisionTypes", {})
    phrases: list[str] = []
    for theme in themes:
        theme_phrases = decision_types.get(theme, [])
        phrases.extend(theme_phrases[:1])  # top phrase per theme

    if not phrases:
        phrases = default_themes[:2]

    return " ".join(phrases[:3])  # keep query compact


# ── Curated fallback loader ───────────────────────────────────────────────────


def load_fallback_sources(
    company_id: str,
    query_context: dict,
) -> list[dict]:
    """
    Load and relevance-rank curated fallback sources for a company.

    Sources are ranked by relevance tag overlap with query themes.
    Returns top _MAX_SOURCES most relevant sources.
    """
    file_stem = _PROFILE_ALIASES.get(company_id, company_id)
    sources_path = _SOURCES_DIR / f"{file_stem}_sources.json"

    if not sources_path.exists():
        logger.warning(
            f"[external_signals] No fallback sources file for {company_id} "
            f"at {sources_path}"
        )
        return []

    try:
        data = json.loads(sources_path.read_text("utf-8"))
    except Exception as exc:
        logger.warning(f"[external_signals] Failed to load fallback sources: {exc}")
        return []

    all_sources = data.get("sources", [])
    if not all_sources:
        return []

    themes = set(query_context.get("themes", []))
    if not themes:
        # No specific themes — return all sources up to max
        return all_sources[:_MAX_SOURCES]

    # Score by relevance tag overlap
    scored = []
    for src in all_sources:
        tags = set(src.get("relevanceTags", []))
        overlap = len(themes & tags)
        scored.append((overlap, src))

    scored.sort(key=lambda x: -x[0])
    return [src for _, src in scored[:_MAX_SOURCES]]


# ── Decision context helpers ──────────────────────────────────────────────────


def _infer_decision_type(decision: dict) -> str:
    """
    Derive decision type from structured LLM-extracted boolean fields.
    Priority order driven by _DECISION_TYPE_PRIORITY config table.
    """
    for field, dtype in _DECISION_TYPE_PRIORITY:
        if decision.get(field):
            return dtype
    cost = decision.get("cost")
    if cost and isinstance(cost, (int, float)) and cost > 0:
        return "procurement"
    return "general"


def _infer_strategic_impact(governance_result: Optional[dict]) -> str:
    """Derive a strategic impact summary from governance flags."""
    if not governance_result:
        return "N/A"
    for flag in governance_result.get("flags", []):
        if any(kw in flag.upper() for kw in _STRATEGIC_IMPACT_KEYWORDS):
            return "Potential strategic conflict"
    return "N/A"
