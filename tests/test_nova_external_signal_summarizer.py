"""
Tests for app/services/nova_external_signal_summarizer.py

All tests mock _call_nova — no real Bedrock calls are made.
"""

import pytest
from unittest.mock import patch

from app.schemas.external_signals import ExternalSignalsPayload


# ── Shared test fixtures ──────────────────────────────────────────────────────


def _nexus_sources():
    return [
        {
            "sourceId": "NEXUS_EXT_001",
            "title": "KPMG Korea: Enterprise IT Capital Expenditure Governance Benchmark 2025",
            "sourceLabel": "KPMG Korea 2025",
            "sourceType": "industry_benchmark",
            "recency": "2025",
            "summaryText": "CFO review mandatory for unbudgeted IT expenditures above 50M KRW in 78% of surveyed companies.",
            "category": "market_benchmark",
        },
        {
            "sourceId": "NEXUS_EXT_003",
            "title": "Korea PIPC: PIPL 2025 Amendment Enforcement Guidance",
            "sourceLabel": "PIPC Korea 2025",
            "sourceType": "regulatory_guideline",
            "recency": "2025",
            "summaryText": "CISO-level accountability required for PII-processing decisions; penalties up to KRW 3B.",
            "category": "regulatory_guidance",
        },
    ]


def _mayo_sources():
    return [
        {
            "sourceId": "MAYO_EXT_001",
            "title": "HHS OCR: 2025 HIPAA Enforcement Priorities",
            "sourceLabel": "HHS OCR 2025",
            "sourceType": "government",
            "recency": "2025",
            "summaryText": "Compliance Officer accountability required for all PHI-processing decisions.",
            "category": "regulatory_guidance",
        },
    ]


def _valid_nova_output_two_signals():
    return """{
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


def _valid_nova_output_regulatory():
    return """{
  "signals": [
    {
      "id": "EXT_SIG_001",
      "bucket": "regulatory",
      "category": "regulatory_guidance",
      "titleKo": "HIPAA 집행 우선순위",
      "titleEn": "HIPAA enforcement priorities",
      "summaryKo": "PHI 처리 결정에 컴플라이언스 오피서 검토가 필수입니다.",
      "summaryEn": "Compliance Officer review is required for all PHI-processing decisions.",
      "confidence": 0.88,
      "sourceId": "MAYO_EXT_001",
      "tags": ["hipaa", "phi"]
    }
  ]
}"""


# ── _parse_and_validate tests ─────────────────────────────────────────────────


def test_valid_output_produces_payload():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    payload = _parse_and_validate(_valid_nova_output_two_signals(), _nexus_sources())
    assert payload is not None
    assert isinstance(payload, ExternalSignalsPayload)
    assert len(payload.marketSignals) == 1
    assert len(payload.regulatorySignals) == 1
    assert len(payload.operationalSignals) == 0


def test_market_signal_fields_correct():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    payload = _parse_and_validate(_valid_nova_output_two_signals(), _nexus_sources())
    sig = payload.marketSignals[0]
    assert sig.id == "EXT_SIG_001"
    assert sig.category == "market_benchmark"
    assert sig.titleEn == "Korea enterprise IT capex benchmark"
    assert sig.confidence == 0.81
    assert sig.tags == ["capex", "governance"]


def test_source_provenance_attached():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    payload = _parse_and_validate(_valid_nova_output_two_signals(), _nexus_sources())
    sig = payload.marketSignals[0]
    assert sig.source.sourceId == "NEXUS_EXT_001"
    assert sig.source.sourceLabel == "KPMG Korea 2025"
    assert sig.source.sourceType == "industry_benchmark"
    assert sig.source.recency == "2025"


def test_regulatory_bucket_maps_correctly():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    payload = _parse_and_validate(_valid_nova_output_regulatory(), _mayo_sources())
    assert payload is not None
    assert len(payload.regulatorySignals) == 1
    assert len(payload.marketSignals) == 0
    assert len(payload.operationalSignals) == 0
    assert payload.regulatorySignals[0].source.sourceId == "MAYO_EXT_001"


def test_invalid_json_returns_none():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    result = _parse_and_validate("This is not valid JSON { broken }", _nexus_sources())
    assert result is None


def test_empty_string_returns_none():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    result = _parse_and_validate("", _nexus_sources())
    assert result is None


def test_empty_signals_list_returns_none():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    result = _parse_and_validate('{"signals": []}', _nexus_sources())
    assert result is None


def test_markdown_fenced_json_stripped():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    fenced = "```json\n" + _valid_nova_output_two_signals() + "\n```"
    payload = _parse_and_validate(fenced, _nexus_sources())
    assert payload is not None
    assert len(payload.marketSignals) == 1


def test_markdown_fence_without_language_stripped():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    fenced = "```\n" + _valid_nova_output_two_signals() + "\n```"
    payload = _parse_and_validate(fenced, _nexus_sources())
    assert payload is not None


def test_unknown_source_id_uses_fallback_provenance():
    """Signals referencing unknown sourceIds still produce valid output."""
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    raw = """{
  "signals": [
    {
      "id": "EXT_SIG_X",
      "bucket": "market",
      "category": "market_benchmark",
      "titleKo": "시장 벤치마크",
      "titleEn": "Market benchmark",
      "summaryKo": "요약.",
      "summaryEn": "Summary.",
      "confidence": 0.6,
      "sourceId": "UNKNOWN_SOURCE_999",
      "tags": []
    }
  ]
}"""
    payload = _parse_and_validate(raw, _nexus_sources())
    assert payload is not None
    assert len(payload.marketSignals) == 1
    sig = payload.marketSignals[0]
    assert sig.source.sourceId == "UNKNOWN_SOURCE_999"
    assert sig.source.sourceLabel == "External Source"  # fallback label


def test_generated_at_is_populated():
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    payload = _parse_and_validate(_valid_nova_output_two_signals(), _nexus_sources())
    assert payload.generatedAt is not None
    assert "T" in payload.generatedAt  # ISO 8601 format


def test_unrecognized_bucket_maps_to_operational():
    """Signals with unexpected bucket values fall into operational."""
    from app.services.nova_external_signal_summarizer import _parse_and_validate

    raw = """{
  "signals": [
    {
      "id": "EXT_SIG_X",
      "bucket": "unknown_bucket_type",
      "category": "trend_signal",
      "titleKo": "알 수 없는 버킷",
      "titleEn": "Unknown bucket",
      "summaryKo": "요약.",
      "summaryEn": "Summary.",
      "confidence": 0.5,
      "sourceId": "NEXUS_EXT_001",
      "tags": []
    }
  ]
}"""
    payload = _parse_and_validate(raw, _nexus_sources())
    assert payload is not None
    assert len(payload.operationalSignals) == 1
    assert len(payload.marketSignals) == 0
    assert len(payload.regulatorySignals) == 0


# ── generate_external_signals end-to-end (mocked Nova) ───────────────────────


def _make_decision_context(decision: dict, risk_band: str = "UNKNOWN") -> dict:
    return {
        "decision_text": decision.get("decision_statement", ""),
        "decision_type": "procurement",
        "cost": decision.get("cost"),
        "strategic_impact": "N/A",
        "risk_band": risk_band,
    }


def _make_internal_entities(decision: dict) -> dict:
    return {
        "cost": decision.get("cost"),
        "involves_hiring": decision.get("involves_hiring"),
        "uses_pii": decision.get("uses_pii"),
        "new_product_development": decision.get("new_product_development"),
        "triggered_flags": [],
    }


def test_generate_returns_payload_when_nova_succeeds():
    from app.services import nova_external_signal_summarizer as mod

    profile = {
        "companyId": "nexus_dynamics",
        "companyName": "Nexus Dynamics",
        "industry": "corporate_finance_technology",
        "regions": ["South Korea (HQ)", "North America"],
        "signalEmphasis": ["market_benchmark", "regulatory_guidance"],
    }
    decision = {"decision_statement": "Deploy enterprise customer analytics", "uses_pii": True, "cost": 80000000}
    sources = _nexus_sources()

    with patch.object(mod, "_call_nova", return_value=_valid_nova_output_two_signals()):
        result = mod.generate_external_signals(
            company_profile=profile,
            decision_context=_make_decision_context(decision),
            triggered_rules=[],
            internal_entities=_make_internal_entities(decision),
            available_sources=sources,
        )

    assert result is not None
    assert isinstance(result, ExternalSignalsPayload)
    assert len(result.marketSignals) + len(result.regulatorySignals) == 2


def test_generate_returns_none_when_nova_raises():
    from app.services import nova_external_signal_summarizer as mod

    profile = {"companyId": "nexus_dynamics", "companyName": "Nexus Dynamics",
               "industry": "corporate_finance_technology", "regions": []}
    decision = {"decision_statement": "Deploy enterprise customer analytics", "cost": 80000000}

    with patch.object(mod, "_call_nova", side_effect=RuntimeError("BEDROCK_API_KEY not set")):
        result = mod.generate_external_signals(
            company_profile=profile,
            decision_context=_make_decision_context(decision),
            triggered_rules=[],
            internal_entities=_make_internal_entities(decision),
            available_sources=_nexus_sources(),
        )

    assert result is None


def test_generate_returns_none_on_invalid_nova_json():
    from app.services import nova_external_signal_summarizer as mod

    profile = {"companyId": "mayo_central", "companyName": "Mayo Central Hospital",
               "industry": "healthcare", "regions": ["North America"]}
    decision = {"decision_statement": "Deploy analytics", "uses_pii": True}

    with patch.object(mod, "_call_nova", return_value="Sorry, I cannot produce JSON for this."):
        result = mod.generate_external_signals(
            company_profile=profile,
            decision_context=_make_decision_context(decision),
            triggered_rules=[],
            internal_entities=_make_internal_entities(decision),
            available_sources=_mayo_sources(),
        )

    assert result is None


def test_generate_includes_risk_band_in_prompt():
    """Verify risk band is included in the Nova prompt."""
    from app.services import nova_external_signal_summarizer as mod

    profile = {"companyId": "nexus_dynamics", "companyName": "Nexus Dynamics",
               "industry": "corporate_finance_technology", "regions": ["South Korea (HQ)"]}
    decision = {"decision_statement": "Deploy enterprise customer analytics", "uses_pii": True, "cost": 80000000}

    captured_prompt = []

    def mock_call_nova(prompt):
        captured_prompt.append(prompt)
        return _valid_nova_output_two_signals()

    with patch.object(mod, "_call_nova", side_effect=mock_call_nova):
        mod.generate_external_signals(
            company_profile=profile,
            decision_context=_make_decision_context(decision, risk_band="MEDIUM"),
            triggered_rules=[],
            internal_entities=_make_internal_entities(decision),
            available_sources=_nexus_sources(),
        )

    assert len(captured_prompt) == 1
    assert "MEDIUM" in captured_prompt[0]
    assert "Deploy enterprise customer analytics" in captured_prompt[0]
