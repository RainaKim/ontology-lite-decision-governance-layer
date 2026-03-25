"""
Tests for app/services/external_signal_service.py

NOTE: These tests depend on old demo_fixtures/external_profiles/ which
has been removed. Skipping until external signals are refactored.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

_PROFILE_DIR = os.path.join("app", "demo_fixtures", "external_profiles")
if not os.listdir(_PROFILE_DIR) if os.path.isdir(_PROFILE_DIR) else True:
    pytest.skip("Old external profile fixtures removed — tests need refactoring", allow_module_level=True)


# ── Profile loading ───────────────────────────────────────────────────────────


def test_load_nexus_dynamics_profile():
    from app.services.external_signal_service import load_company_external_profile

    profile = load_company_external_profile("nexus_dynamics")
    assert profile is not None
    assert profile["companyId"] == "nexus_dynamics"
    assert "market_benchmark" in profile["signalCategories"]
    assert "regulatory_guidance" in profile["signalCategories"]
    assert "market_benchmark" in profile["signalEmphasis"]
    assert "financialTriggers" not in profile  # external profile, not evidence registry


def test_load_mayo_central_profile():
    from app.services.external_signal_service import load_company_external_profile

    profile = load_company_external_profile("mayo_central")
    assert profile is not None
    assert profile["companyId"] == "mayo_central"
    assert "compliance_signal" in profile["signalCategories"]
    assert "regulatory_guidance" in profile["signalCategories"]
    assert "regulatory_guidance" in profile["signalEmphasis"]
    assert "compliance_signal" in profile["signalEmphasis"]


def test_load_unknown_company_profile_returns_none():
    from app.services.external_signal_service import load_company_external_profile

    result = load_company_external_profile("totally_unknown_company_xyz")
    assert result is None


def test_profiles_have_governance_rule_alignment():
    from app.services.external_signal_service import load_company_external_profile

    for cid in ("nexus_dynamics", "mayo_central"):
        profile = load_company_external_profile(cid)
        assert "governanceRuleAlignment" in profile, f"{cid} missing governanceRuleAlignment"
        assert len(profile["governanceRuleAlignment"]) > 0


# ── Fallback source loading ───────────────────────────────────────────────────


def test_nexus_fallback_sources_load():
    from app.services.external_signal_service import load_fallback_sources

    sources = load_fallback_sources("nexus_dynamics", {"themes": ["financial_procurement"]})
    assert len(sources) > 0
    assert all("sourceId" in s for s in sources)
    assert all("summaryText" in s for s in sources)


def test_mayo_fallback_sources_emphasize_compliance():
    from app.services.external_signal_service import load_fallback_sources

    sources = load_fallback_sources("mayo_central", {"themes": ["privacy_compliance"]})
    assert len(sources) > 0
    categories = [s.get("category") for s in sources]
    assert any(cat in ("regulatory_guidance", "compliance_signal") for cat in categories)
    # Top sources should be compliance/regulatory focused (sorted by relevance)
    assert sources[0]["category"] in ("regulatory_guidance", "compliance_signal")


def test_nexus_fallback_sources_emphasize_regulatory_for_privacy():
    from app.services.external_signal_service import load_fallback_sources

    sources = load_fallback_sources("nexus_dynamics", {"themes": ["privacy_compliance"]})
    assert len(sources) > 0
    # GDPR / PIPL sources should rank high
    source_ids = [s["sourceId"] for s in sources]
    assert any(sid in ("NEXUS_EXT_002", "NEXUS_EXT_003") for sid in source_ids)


def test_fallback_sources_max_four():
    from app.services.external_signal_service import load_fallback_sources

    # With many themes, should return at most _MAX_SOURCES results
    sources = load_fallback_sources(
        "nexus_dynamics",
        {"themes": ["financial_procurement", "risk_procurement", "labor_hiring", "new_product", "market_benchmark"]}
    )
    assert len(sources) <= 4


def test_fallback_no_themes_returns_all_sources_up_to_max():
    from app.services.external_signal_service import load_fallback_sources

    sources = load_fallback_sources("mayo_central", {"themes": []})
    assert len(sources) > 0
    assert len(sources) <= 4


def test_unknown_company_fallback_returns_empty():
    from app.services.external_signal_service import load_fallback_sources

    sources = load_fallback_sources("unknown_xyz", {"themes": []})
    assert sources == []


# ── Query context inference ───────────────────────────────────────────────────


def test_infer_context_pii_decision():
    from app.services.external_signal_service import infer_external_signal_query_context

    decision = {"decision_statement": "Deploy patient data analytics", "uses_pii": True, "cost": 50000}
    gov = {"flags": ["PRIVACY_REVIEW_REQUIRED"]}
    ctx = infer_external_signal_query_context(decision, gov, {}, "mayo_central")
    assert "privacy_compliance" in ctx["themes"]
    assert "financial_procurement" in ctx["themes"]


def test_infer_context_hiring_decision():
    from app.services.external_signal_service import infer_external_signal_query_context

    decision = {"decision_statement": "Hire production staff", "involves_hiring": True, "cost": 42000}
    gov = {"flags": []}
    ctx = infer_external_signal_query_context(decision, gov, {}, "nexus_dynamics")
    assert "labor_hiring" in ctx["themes"]
    assert "financial_procurement" in ctx["themes"]


def test_infer_context_procurement_with_high_risk_dimensions():
    from app.services.external_signal_service import infer_external_signal_query_context

    decision = {"decision_statement": "Order 1000 ice cream cups", "cost": 1800}
    gov = {"flags": ["HIGH_FINANCIAL_RISK"]}
    risk_scoring = {
        "aggregate": {"band": "MEDIUM"},
        "dimensions": [
            {"id": "procurement", "band": "HIGH"},
            {"id": "financial", "band": "LOW"},
        ]
    }
    ctx = infer_external_signal_query_context(decision, gov, risk_scoring, "nexus_dynamics")
    assert "financial_procurement" in ctx["themes"]
    assert "risk_procurement" in ctx["themes"]
    assert "risk_financial" in ctx["themes"]
    assert ctx["risk_band"] == "MEDIUM"


def test_infer_context_deduplicates_themes():
    from app.services.external_signal_service import infer_external_signal_query_context

    decision = {"decision_statement": "PII processing decision", "uses_pii": True}
    gov = {"flags": ["PRIVACY_REVIEW_REQUIRED", "PRIVACY_FLAG_2"]}  # two privacy flags
    ctx = infer_external_signal_query_context(decision, gov, None, "nexus_dynamics")
    # privacy_compliance should appear only once
    assert ctx["themes"].count("privacy_compliance") == 1


# ── Live fetch (stub) ─────────────────────────────────────────────────────────


def test_best_effort_provider_returns_empty():
    from app.services.external_signal_service import BestEffortWebFetchProvider

    provider = BestEffortWebFetchProvider()
    result = provider.fetch("enterprise technology benchmark", max_results=3)
    assert result == []


def test_retrieve_live_sources_swallows_errors():
    from app.services.external_signal_service import retrieve_live_sources

    class BrokenProvider:
        def fetch(self, query, max_results=3):
            raise RuntimeError("network error")

    result = retrieve_live_sources(BrokenProvider(), "test query")
    assert result == []


# ── Full pipeline (curated fallback) ─────────────────────────────────────────


def test_build_external_signals_uses_curated_fallback():
    """build_external_signals should return signals via curated fallback for known companies."""
    from app.services.external_signal_service import build_external_signals
    from app.schemas.external_signals import ExternalSignalsPayload

    decision = {"decision_statement": "Deploy enterprise customer analytics", "cost": 80000000}
    gov = {"flags": [], "triggered_rules": []}

    result = build_external_signals("nexus_dynamics", decision, gov, None, lang="en")

    assert result is not None
    assert isinstance(result, ExternalSignalsPayload)
    total = len(result.marketSignals) + len(result.regulatorySignals) + len(result.operationalSignals)
    assert total > 0


def test_build_external_signals_no_profile_returns_none():
    from app.services.external_signal_service import build_external_signals

    result = build_external_signals("unknown_company_xyz", {}, {}, None)
    assert result is None
