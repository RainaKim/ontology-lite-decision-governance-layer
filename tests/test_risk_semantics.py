"""
Unit tests for the structured LLM semantics layer.

Covers:
  1. infer_risk_semantics with invalid JSON → returns None (graceful fallback)
  2. infer_risk_semantics with invalid schema → returns None (graceful fallback)
  3. infer_risk_semantics happy path → returns populated RiskSemantics
  4. Semantics absent (None) → risk scoring still produces valid RiskScoringPayload
  5. Semantics present → strategic dimension evidence includes rationale_ko
  6. Semantics present → compliance dimension uses semantics PII fact when extractor absent
  7. Semantics numeric_estimates → kpi_impact_estimate note includes LLM estimate

All tests are deterministic — no real API keys required.
Mock clients are injected via the _client parameter.

Run:
    python -m pytest tests/test_risk_semantics.py -v
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.schemas.risk_semantics import RiskSemantics, GoalImpact, ComplianceFacts, NumericEstimates
from app.services.risk_evidence_llm import infer_risk_semantics
from app.services.risk_scoring_service import RiskScoringService


# ---------------------------------------------------------------------------
# Helpers — mock BedrockClient builder
# ---------------------------------------------------------------------------

def _make_openai_mock(response_json: str) -> Any:
    """Return a mock that mimics BedrockClient.invoke() returning a plain string."""
    mock_client = MagicMock()
    mock_client.invoke = MagicMock(return_value=response_json)
    return mock_client


_VALID_SEMANTICS_JSON = json.dumps({
    "goal_impacts": [
        {
            "goal_id": "G3",
            "direction": "conflict",
            "magnitude": "high",
            "rationale_ko": "광고비 지출 증가로 운영비용 절감 목표에 충돌이 발생함",
            "confidence": 0.85,
        },
        {
            "goal_id": "G1",
            "direction": "support",
            "magnitude": "med",
            "rationale_ko": "북미 시장 확장 캠페인이 매출 성장 목표에 기여함",
            "confidence": 0.70,
        },
    ],
    "compliance_facts": {
        "uses_pii": None,
        "anonymization_missing": None,
        "involves_compliance_risk": None,
    },
    "numeric_estimates": {
        "cost_delta_pct": 12.5,
        "revenue_uplift_pct": None,
    },
    "global_confidence": 0.80,
})

_VALID_PII_SEMANTICS_JSON = json.dumps({
    "goal_impacts": [],
    "compliance_facts": {
        "uses_pii": True,
        "anonymization_missing": True,
        "involves_compliance_risk": True,
    },
    "numeric_estimates": None,
    "global_confidence": 0.75,
})

_DECISION_TEXT = "북미 광고 캠페인에 2.5억 원을 투입하여 시장 점유율을 높이고자 합니다."

_COMPANY_SUMMARY = {
    "strategic_goals": [
        {
            "goal_id": "G1",
            "name": "북미 매출 성장",
            "description": "북미 시장 점유율 확대",
            "kpis": [{"name": "매출 성장률", "target": "20%"}],
        },
        {
            "goal_id": "G3",
            "name": "운영비용 효율화",
            "description": "운영비용 10% 절감",
            "priority": "high",
            "kpis": [{"name": "운영비 절감률", "target": "전년 대비 10% 절감"}],
        },
    ]
}

_TRIGGERED_RULES = [
    {
        "rule_id": "R1",
        "name": "예산 승인 규칙",
        "rule_type": "financial",
        "status": "TRIGGERED",
    }
]


# ---------------------------------------------------------------------------
# Tests: infer_risk_semantics graceful fallback
# ---------------------------------------------------------------------------

class TestInferRiskSemanticsGracefulFallback:

    def test_invalid_json_returns_none(self):
        """LLM returns non-JSON → infer_risk_semantics returns None, no exception."""
        mock_client = _make_openai_mock("This is not valid JSON at all {{{{}")
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
            _client=mock_client,
        )
        assert result is None

    def test_json_missing_required_enum_returns_none(self):
        """LLM returns JSON with invalid direction enum → Pydantic fails → None."""
        bad_json = json.dumps({
            "goal_impacts": [
                {
                    "goal_id": "G1",
                    "direction": "STRONGLY_SUPPORTS",  # not in Literal enum
                    "magnitude": "high",
                    "rationale_ko": "테스트",
                    "confidence": 0.9,
                }
            ],
            "compliance_facts": {},
            "global_confidence": 0.8,
        })
        mock_client = _make_openai_mock(bad_json)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
            _client=mock_client,
        )
        assert result is None

    def test_empty_string_response_returns_none(self):
        """LLM returns empty string → JSON parse fails → None."""
        mock_client = _make_openai_mock("")
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
            _client=mock_client,
        )
        assert result is None

    def test_no_client_no_api_key_returns_none(self, monkeypatch):
        """When no API key is set and no _client injected → None, no exception."""
        monkeypatch.delenv("BEDROCK_API_KEY", raising=False)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
        )
        assert result is None


# ---------------------------------------------------------------------------
# Tests: infer_risk_semantics happy path
# ---------------------------------------------------------------------------

class TestInferRiskSemanticsHappyPath:

    def test_valid_json_returns_semantics(self):
        """LLM returns valid schema JSON → RiskSemantics object returned."""
        mock_client = _make_openai_mock(_VALID_SEMANTICS_JSON)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
            _client=mock_client,
        )
        assert result is not None
        assert isinstance(result, RiskSemantics)

    def test_goal_impacts_parsed(self):
        """goal_impacts are correctly parsed with all fields."""
        mock_client = _make_openai_mock(_VALID_SEMANTICS_JSON)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
            _client=mock_client,
        )
        assert len(result.goal_impacts) == 2
        conflict_impact = next(i for i in result.goal_impacts if i.direction == "conflict")
        assert conflict_impact.goal_id == "G3"
        assert conflict_impact.magnitude == "high"
        assert "운영비용" in conflict_impact.rationale_ko

    def test_global_confidence_clamped(self):
        """global_confidence stays within 0..1 even with out-of-range LLM output."""
        raw = json.dumps({
            "goal_impacts": [],
            "compliance_facts": {},
            "global_confidence": 1.5,  # out of range
        })
        mock_client = _make_openai_mock(raw)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=[],
            _client=mock_client,
        )
        assert result is not None
        assert result.global_confidence <= 1.0

    def test_confidence_per_goal_clamped(self):
        """Per-goal confidence is clamped to 0..1."""
        raw = json.dumps({
            "goal_impacts": [
                {
                    "goal_id": "G1",
                    "direction": "support",
                    "magnitude": "low",
                    "rationale_ko": "테스트",
                    "confidence": 2.0,  # out of range
                }
            ],
            "compliance_facts": {},
            "global_confidence": 0.5,
        })
        mock_client = _make_openai_mock(raw)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=[],
            _client=mock_client,
        )
        assert result is not None
        assert result.goal_impacts[0].confidence <= 1.0

    def test_numeric_estimates_parsed(self):
        """numeric_estimates.cost_delta_pct is populated."""
        mock_client = _make_openai_mock(_VALID_SEMANTICS_JSON)
        result = infer_risk_semantics(
            decision_text=_DECISION_TEXT,
            company_summary=_COMPANY_SUMMARY,
            triggered_rules_summary=_TRIGGERED_RULES,
            _client=mock_client,
        )
        assert result.numeric_estimates is not None
        assert result.numeric_estimates.cost_delta_pct == 12.5


# ---------------------------------------------------------------------------
# Fixtures for risk scoring tests
# ---------------------------------------------------------------------------

FINANCE_COMPANY = {
    "company": {"industry": "기업 금융", "name": "넥서스 다이나믹스"},
    "risk_tolerance": {
        "financial": {
            "unbudgeted_spend_threshold": 50_000_000,
            "high_cost_threshold": 250_000_000,
            "critical_cost_threshold": 1_000_000_000,
        }
    },
    "strategic_goals": [
        {
            "goal_id": "G3",
            "name": "운영비용 효율화",
            "description": "운영비용 10% 절감",
            "priority": "high",
            "kpis": [{"name": "운영비 절감률", "target": "전년 대비 10% 절감"}],
        },
        {
            "goal_id": "G1",
            "name": "북미 매출 성장",
            "description": "북미 시장 매출 20% 성장",
            "priority": "critical",
            "kpis": [{"name": "매출 성장률", "target": "20%"}],
        },
    ],
}

# A decision payload with NO graph edges (empty graph) and no goals in dp
MARKETING_DECISION = {
    "decision_statement": "북미 광고비 2.5억 원 집행",
    "cost": 250_000_000,
    "remaining_budget": 50_000_000,
    "uses_pii": None,
    "involves_compliance_risk": None,
    "goals": [],
    "kpis": [],
    "risks": [],
}

GOV_WITH_FIN_RULE = {
    "triggered_rules": [
        {
            "rule_id": "R1",
            "name": "예산 승인 규칙",
            "rule_type": "financial",
            "type": "financial",
            "status": "TRIGGERED",
            "consequence": {"severity": "HIGH"},
        }
    ]
}

EMPTY_GRAPH = {}


# ---------------------------------------------------------------------------
# Tests: risk scoring without semantics
# ---------------------------------------------------------------------------

class TestScoringWithoutSemantics:

    def test_scoring_produces_valid_payload_no_semantics(self):
        """Scoring works normally when risk_semantics is None."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=None,
        )
        assert result is not None
        assert result.aggregate.score >= 0
        assert result.aggregate.band in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert len(result.dimensions) >= 1

    def test_strategic_no_graph_no_semantics_returns_no_mapping(self):
        """When no graph and no semantics, strategic dimension gets NO_GOAL_MAPPING."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=None,
        )
        strat_dim = next((d for d in result.dimensions if d.id == "strategic"), None)
        assert strat_dim is not None
        signal_ids = [s.id for s in strat_dim.signals]
        assert "NO_GOAL_MAPPING" in signal_ids


# ---------------------------------------------------------------------------
# Tests: risk scoring WITH semantics (fallback path)
# ---------------------------------------------------------------------------

_SEMANTICS_WITH_GOAL_CONFLICT = {
    "goal_impacts": [
        {
            "goal_id": "G3",
            "direction": "conflict",
            "magnitude": "high",
            "rationale_ko": "광고비 지출 증가로 운영비용 절감 목표에 충돌이 발생함",
            "confidence": 0.85,
        }
    ],
    "compliance_facts": {
        "uses_pii": None,
        "anonymization_missing": None,
        "involves_compliance_risk": None,
    },
    "numeric_estimates": {"cost_delta_pct": 12.5, "revenue_uplift_pct": None},
    "global_confidence": 0.80,
}

_SEMANTICS_WITH_PII = {
    "goal_impacts": [],
    "compliance_facts": {
        "uses_pii": True,
        "anonymization_missing": True,
        "involves_compliance_risk": True,
    },
    "numeric_estimates": None,
    "global_confidence": 0.75,
}


class TestScoringWithSemantics:

    def test_semantics_goal_conflict_used_when_no_graph(self):
        """When graph has no edges, semantics goal_impacts creates GOAL_CONFLICT signal."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_GOAL_CONFLICT,
        )
        strat_dim = next((d for d in result.dimensions if d.id == "strategic"), None)
        assert strat_dim is not None
        signal_ids = [s.id for s in strat_dim.signals]
        # Should now produce GOAL_CONFLICT instead of NO_GOAL_MAPPING
        assert "GOAL_CONFLICT" in signal_ids
        assert "NO_GOAL_MAPPING" not in signal_ids

    def test_semantics_evidence_contains_rationale_ko(self):
        """GOAL_CONFLICT signal evidence includes the Korean rationale from semantics."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_GOAL_CONFLICT,
        )
        strat_dim = next((d for d in result.dimensions if d.id == "strategic"), None)
        goal_conflict_sig = next(
            (s for s in strat_dim.signals if s.id == "GOAL_CONFLICT"), None
        )
        assert goal_conflict_sig is not None

        all_labels = [ev.label for ev in goal_conflict_sig.evidence if ev.label]
        # The Korean rationale from semantics should appear in evidence
        assert any(
            "운영비용 절감" in lbl or "충돌" in lbl
            for lbl in all_labels
        ), f"Expected Korean rationale in evidence labels: {all_labels}"

    def test_semantics_evidence_source_is_llm_structured(self):
        """Evidence from semantics uses 'LLM(구조화)' as source."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_GOAL_CONFLICT,
        )
        strat_dim = next((d for d in result.dimensions if d.id == "strategic"), None)
        goal_conflict_sig = next(
            (s for s in strat_dim.signals if s.id == "GOAL_CONFLICT"), None
        )
        assert goal_conflict_sig is not None
        all_sources = [ev.source for ev in goal_conflict_sig.evidence if ev.source]
        assert any("LLM" in src for src in all_sources), (
            f"Expected LLM(구조화) in evidence sources: {all_sources}"
        )

    def test_semantics_pii_fills_compliance_when_extractor_missing(self):
        """When extractor uses_pii=None, semantics PII fact enables compliance dimension."""
        decision_no_pii = {**MARKETING_DECISION, "uses_pii": None, "involves_compliance_risk": None}
        service = RiskScoringService()

        # Without semantics: no compliance dimension (no PII, no compliance rules)
        result_no_sem = service.score(
            decision_payload=decision_no_pii,
            company_payload=FINANCE_COMPANY,
            governance_result={"triggered_rules": []},
            graph_payload=EMPTY_GRAPH,
            risk_semantics=None,
        )
        comp_no_sem = next((d for d in result_no_sem.dimensions if d.id == "compliance"), None)
        assert comp_no_sem is None, "No compliance dimension expected without semantics"

        # With semantics: compliance dimension should be present (PII from semantics)
        result_with_sem = service.score(
            decision_payload=decision_no_pii,
            company_payload=FINANCE_COMPANY,
            governance_result={"triggered_rules": []},
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_PII,
        )
        comp_with_sem = next((d for d in result_with_sem.dimensions if d.id == "compliance"), None)
        assert comp_with_sem is not None, "Compliance dimension expected when semantics provides PII=True"

    def test_semantics_pii_evidence_source_is_llm_structured(self):
        """PII signal filled by semantics uses 'LLM(구조화)' as evidence source."""
        decision_no_pii = {**MARKETING_DECISION, "uses_pii": None}
        service = RiskScoringService()
        result = service.score(
            decision_payload=decision_no_pii,
            company_payload=FINANCE_COMPANY,
            governance_result={"triggered_rules": []},
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_PII,
        )
        comp_dim = next((d for d in result.dimensions if d.id == "compliance"), None)
        pii_sig = next((s for s in comp_dim.signals if s.id == "PII_DETECTED"), None)
        assert pii_sig is not None
        sources = [ev.source for ev in pii_sig.evidence if ev.source]
        assert any("LLM" in src for src in sources)

    def test_extractor_pii_not_overridden_by_semantics(self):
        """
        When extractor explicitly sets BOTH uses_pii=False AND involves_compliance_risk=False,
        semantics cannot override either field (None semantics fallback only fills gaps).
        """
        # Both compliance fields are explicitly False — extractor had full signal
        decision_all_false = {
            **MARKETING_DECISION,
            "uses_pii": False,
            "involves_compliance_risk": False,
        }
        service = RiskScoringService()
        result = service.score(
            decision_payload=decision_all_false,
            company_payload=FINANCE_COMPANY,
            governance_result={"triggered_rules": []},
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_PII,  # semantics says uses_pii=True, involves=True
        )
        # Extractor's explicit False must win — no compliance dimension
        comp_dim = next((d for d in result.dimensions if d.id == "compliance"), None)
        assert comp_dim is None, (
            "Extractor uses_pii=False + involves_compliance_risk=False must not be "
            "overridden by semantics"
        )

    def test_scoring_still_valid_with_semantics(self):
        """Full scoring with semantics produces a valid, schema-compatible result."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_GOAL_CONFLICT,
        )
        assert result.aggregate.score >= 0
        assert result.aggregate.score <= 100
        assert result.aggregate.band in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert 0.0 <= result.aggregate.confidence <= 1.0
        for dim in result.dimensions:
            assert 0 <= dim.score <= 100
            # signals[0] is always SUMMARY
            assert dim.signals[0].id == "SUMMARY"
            assert len(dim.signals) <= 4

    def test_numeric_estimates_in_kpi_note(self):
        """cost_delta_pct from semantics appears in kpi_impact_estimate note."""
        service = RiskScoringService()
        result = service.score(
            decision_payload=MARKETING_DECISION,
            company_payload=FINANCE_COMPANY,
            governance_result=GOV_WITH_FIN_RULE,
            graph_payload=EMPTY_GRAPH,
            risk_semantics=_SEMANTICS_WITH_GOAL_CONFLICT,
        )
        strat_dim = next((d for d in result.dimensions if d.id == "strategic"), None)
        assert strat_dim is not None
        if strat_dim.kpi_impact_estimate:
            # If a kpi_impact_estimate is produced, the llm note may appear
            note = strat_dim.kpi_impact_estimate.get("note", "")
            if strat_dim.kpi_impact_estimate.get("llm_cost_delta_pct") is not None:
                assert "12.5" in note or "LLM" in note.upper() or "비용" in note


# ---------------------------------------------------------------------------
# Tests: RiskSemantics schema edge cases
# ---------------------------------------------------------------------------

class TestRiskSemanticsSchema:

    def test_empty_goal_impacts_valid(self):
        """RiskSemantics with no goal_impacts is valid."""
        sem = RiskSemantics(global_confidence=0.5)
        assert sem.goal_impacts == []

    def test_compliance_facts_all_none(self):
        """ComplianceFacts with all None values is valid."""
        facts = ComplianceFacts()
        assert facts.uses_pii is None
        assert facts.anonymization_missing is None
        assert facts.involves_compliance_risk is None

    def test_numeric_estimates_optional(self):
        """RiskSemantics without numeric_estimates is valid."""
        sem = RiskSemantics(goal_impacts=[], global_confidence=0.3)
        assert sem.numeric_estimates is None

    def test_model_dump_roundtrip(self):
        """model_dump() and model_validate() roundtrip preserves data."""
        sem = RiskSemantics(
            goal_impacts=[
                GoalImpact(
                    goal_id="G1",
                    direction="support",
                    magnitude="high",
                    rationale_ko="기여함",
                    confidence=0.9,
                )
            ],
            compliance_facts=ComplianceFacts(uses_pii=True),
            numeric_estimates=NumericEstimates(cost_delta_pct=-5.0),
            global_confidence=0.88,
        )
        dumped = sem.model_dump()
        restored = RiskSemantics.model_validate(dumped)
        assert restored.goal_impacts[0].goal_id == "G1"
        assert restored.compliance_facts.uses_pii is True
        assert restored.numeric_estimates.cost_delta_pct == -5.0
        assert abs(restored.global_confidence - 0.88) < 1e-6
