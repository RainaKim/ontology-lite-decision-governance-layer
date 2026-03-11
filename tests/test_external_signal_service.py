"""
Tests for app/services/external_signal_service.py

All tests are deterministic — Nova is mocked; no network calls are made.
"""

import os
import pytest
from unittest.mock import patch, MagicMock


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


def test_load_sool_sool_icecream_profile():
    from app.services.external_signal_service import load_company_external_profile

    profile = load_company_external_profile("sool_sool_icecream")
    assert profile is not None
    assert profile["companyId"] == "sool_sool_icecream"
    assert "trend_signal" in profile["signalCategories"]
    assert "operational_signal" in profile["signalCategories"]
    assert "trend_signal" in profile["signalEmphasis"]
    assert "operational_signal" in profile["signalEmphasis"]


def test_load_unknown_company_profile_returns_none():
    from app.services.external_signal_service import load_company_external_profile

    result = load_company_external_profile("totally_unknown_company_xyz")
    assert result is None


def test_profiles_have_governance_rule_alignment():
    from app.services.external_signal_service import load_company_external_profile

    for cid in ("nexus_dynamics", "mayo_central", "sool_sool_icecream"):
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


def test_sool_fallback_sources_emphasize_ops_and_trends():
    from app.services.external_signal_service import load_fallback_sources

    sources = load_fallback_sources("sool_sool_icecream", {"themes": ["financial_procurement", "risk_procurement"]})
    assert len(sources) > 0
    categories = {s.get("category") for s in sources}
    assert categories & {"trend_signal", "operational_signal"}


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
        "sool_sool_icecream",
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
    ctx = infer_external_signal_query_context(decision, gov, {}, "sool_sool_icecream")
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
    ctx = infer_external_signal_query_context(decision, gov, risk_scoring, "sool_sool_icecream")
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


# ── Full pipeline (mocked Nova) ───────────────────────────────────────────────


def _nova_output_for_sool_sool():
    return """{
  "signals": [
    {
      "id": "EXT_SIG_001",
      "bucket": "market",
      "category": "trend_signal",
      "titleKo": "프로모션 후 수요 둔화",
      "titleEn": "Post-promo demand softening",
      "summaryKo": "SNS 프로모션 종료 후 수요가 25-35% 감소하는 경향이 있습니다.",
      "summaryEn": "Demand typically softens 25-35% after SNS promotional cycles end.",
      "confidence": 0.78,
      "sourceId": "SOOL_EXT_001",
      "tags": ["demand_trend", "procurement"]
    },
    {
      "id": "EXT_SIG_002",
      "bucket": "operational",
      "category": "operational_signal",
      "titleKo": "재고 과잉 주문 위험",
      "titleEn": "Over-order inventory risk",
      "summaryKo": "소규모 F&B 운영자는 프로모션 예측 기반 주문 시 22% 과다 발주 위험이 있습니다.",
      "summaryEn": "Small F&B operators face a 22% over-order rate when ordering based solely on promotional forecasts.",
      "confidence": 0.82,
      "sourceId": "SOOL_EXT_002",
      "tags": ["inventory", "operations"]
    }
  ]
}"""


def test_build_external_signals_returns_payload_with_mocked_nova():
    from app.services import nova_external_signal_summarizer as nova_mod
    from app.services.external_signal_service import build_external_signals
    from app.schemas.external_signals import ExternalSignalsPayload

    decision = {"decision_statement": "Order 1000 ice cream cups", "cost": 1800}
    gov = {"flags": ["HIGH_FINANCIAL_RISK"], "triggered_rules": [{"rule_id": "R1", "status": "TRIGGERED", "name": "Large Purchase Approval"}]}
    risk_scoring = {
        "aggregate": {"score": 48, "band": "MEDIUM"},
        "dimensions": [{"id": "procurement", "band": "HIGH"}, {"id": "financial", "band": "LOW"}]
    }

    with patch.object(nova_mod, "_call_nova", return_value=_nova_output_for_sool_sool()):
        result = build_external_signals("sool_sool_icecream", decision, gov, risk_scoring, lang="en")

    assert result is not None
    assert isinstance(result, ExternalSignalsPayload)
    assert len(result.marketSignals) == 1
    assert len(result.operationalSignals) == 1
    assert result.marketSignals[0].titleEn == "Post-promo demand softening"
    assert result.operationalSignals[0].confidence == 0.82
    assert result.generatedAt is not None


def test_build_external_signals_nova_failure_uses_curated_fallback():
    """When Nova fails, curated fallback should supply signals for known companies."""
    from app.services import nova_external_signal_summarizer as nova_mod
    from app.services.external_signal_service import build_external_signals
    from app.schemas.external_signals import ExternalSignalsPayload

    decision = {"decision_statement": "Order 1000 ice cream cups", "cost": 1800}
    gov = {"flags": [], "triggered_rules": []}

    with patch.object(nova_mod, "_call_nova", side_effect=RuntimeError("No API key")):
        result = build_external_signals("sool_sool_icecream", decision, gov, None, lang="en")

    assert result is not None
    assert isinstance(result, ExternalSignalsPayload)
    total = len(result.marketSignals) + len(result.regulatorySignals) + len(result.operationalSignals)
    assert total > 0


def test_build_external_signals_no_profile_returns_none():
    from app.services.external_signal_service import build_external_signals

    result = build_external_signals("unknown_company_xyz", {}, {}, None)
    assert result is None


def test_mayo_signals_emphasize_regulatory_bucket():
    """Mayo decisions should produce regulatory-type signals."""
    from app.services import nova_external_signal_summarizer as nova_mod
    from app.services.external_signal_service import build_external_signals
    from app.schemas.external_signals import ExternalSignalsPayload

    nova_output = """{
  "signals": [
    {
      "id": "EXT_SIG_001",
      "bucket": "regulatory",
      "category": "regulatory_guidance",
      "titleKo": "HIPAA 집행 최신 동향",
      "titleEn": "HIPAA enforcement update",
      "summaryKo": "HHS OCR은 2025년 PHI 처리 결정에 대한 컴플라이언스 오피서 검토를 의무화했습니다.",
      "summaryEn": "HHS OCR mandated Compliance Officer review for PHI-processing decisions in 2025.",
      "confidence": 0.88,
      "sourceId": "MAYO_EXT_001",
      "tags": ["hipaa", "phi", "compliance"]
    }
  ]
}"""

    decision = {"decision_statement": "Deploy patient analytics system", "uses_pii": True, "cost": 120000}
    gov = {"flags": ["PRIVACY_REVIEW_REQUIRED"], "triggered_rules": [{"rule_id": "R2", "status": "TRIGGERED", "name": "Patient Data Privacy and HIPAA Compliance"}]}

    with patch.object(nova_mod, "_call_nova", return_value=nova_output):
        result = build_external_signals("mayo_central", decision, gov, None, lang="en")

    assert result is not None
    assert len(result.regulatorySignals) == 1
    assert len(result.marketSignals) == 0
    assert result.regulatorySignals[0].source.sourceId == "MAYO_EXT_001"


def test_nexus_signals_emphasize_market_and_regulatory():
    """Nexus decisions should produce market_benchmark or regulatory signals."""
    from app.services import nova_external_signal_summarizer as nova_mod
    from app.services.external_signal_service import build_external_signals

    nova_output = """{
  "signals": [
    {
      "id": "EXT_SIG_001",
      "bucket": "market",
      "category": "market_benchmark",
      "titleKo": "한국 기업 IT 지출 벤치마크",
      "titleEn": "Korea enterprise IT capex benchmark",
      "summaryKo": "50M KRW 이상 지출 시 CFO 검토가 78% 기업에서 필수입니다.",
      "summaryEn": "CFO review is mandatory for IT spending above 50M KRW in 78% of surveyed Korean enterprises.",
      "confidence": 0.81,
      "sourceId": "NEXUS_EXT_001",
      "tags": ["capex", "governance"]
    },
    {
      "id": "EXT_SIG_002",
      "bucket": "regulatory",
      "category": "regulatory_guidance",
      "titleKo": "한국 개인정보 보호법 개정",
      "titleEn": "Korea PIPL amendment guidance",
      "summaryKo": "2025년 PIPL 개정으로 PII 처리 시 CISO 책임이 명시적으로 요구됩니다.",
      "summaryEn": "The 2025 PIPL amendment explicitly requires CISO-level accountability for PII-processing decisions.",
      "confidence": 0.85,
      "sourceId": "NEXUS_EXT_003",
      "tags": ["pipl", "ciso", "privacy"]
    }
  ]
}"""

    decision = {"decision_statement": "Deploy enterprise customer analytics", "uses_pii": True, "cost": 80000000}
    gov = {"flags": ["FINANCIAL_THRESHOLD_EXCEEDED", "PRIVACY_REVIEW_REQUIRED"], "triggered_rules": []}

    with patch.object(nova_mod, "_call_nova", return_value=nova_output):
        result = build_external_signals("nexus_dynamics", decision, gov, None, lang="ko")

    assert result is not None
    assert len(result.marketSignals) == 1
    assert len(result.regulatorySignals) == 1
    assert result.marketSignals[0].source.sourceId == "NEXUS_EXT_001"
    assert result.regulatorySignals[0].source.sourceId == "NEXUS_EXT_003"
