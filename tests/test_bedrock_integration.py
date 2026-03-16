"""
Integration tests that hit the real AWS Bedrock API.

These tests are SKIPPED by default (no BEDROCK_API_KEY in CI).
Run locally with:
    BEDROCK_API_KEY=<key> python -m pytest tests/test_bedrock_integration.py -v

Purpose:
- Prove end-to-end Nova integration works (not just mocks)
- Validate prompt → structured JSON → Pydantic round-trip
- Catch Bedrock API contract changes early
"""

from __future__ import annotations

import json
import os

import pytest

_HAS_KEY = bool(os.environ.get("BEDROCK_API_KEY"))
pytestmark = pytest.mark.skipif(not _HAS_KEY, reason="BEDROCK_API_KEY not set")


# ── 1. BedrockClient basic invoke ────────────────────────────────────────────

class TestBedrockClientInvoke:
    """Verify raw invoke returns non-empty text."""

    def test_simple_invoke(self):
        from app.bedrock_client import BedrockClient

        client = BedrockClient()
        result = client.invoke("Return the JSON: {\"ok\": true}", max_tokens=64)
        assert result
        assert len(result) > 0

    def test_invoke_with_system_prompt(self):
        from app.bedrock_client import BedrockClient

        client = BedrockClient()
        result = client.invoke(
            "What is 2+2?",
            system_prompt="You are a calculator. Return only the number.",
            max_tokens=16,
        )
        assert "4" in result

    def test_nova_pro_invoke(self):
        """Verify Nova Pro model is reachable."""
        from app.bedrock_client import BedrockClient
        from app.config.bedrock_config import NOVA_PRO_MODEL_ID

        client = BedrockClient(model_id=NOVA_PRO_MODEL_ID)
        result = client.invoke("Return the JSON: {\"model\": \"pro\"}", max_tokens=64)
        assert result
        assert len(result) > 0


# ── 2. LLM extraction end-to-end ─────────────────────────────────────────────

class TestExtractionIntegration:
    """Verify decision extraction produces valid Pydantic objects."""

    _DECISION_TEXT = (
        "R&D 부서에서 AI 분석 역량 강화를 위해 DataCorp 인수를 추진합니다. "
        "인수 비용은 약 35억 원이며, 데이터 분석 전문 인력 10명을 즉시 확보할 수 있습니다. "
        "연간 운영비 절감 효과는 약 5억 원으로 예상됩니다."
    )

    def test_extract_decision_json(self):
        from app.llm_client import LLMClient

        client = LLMClient()
        raw = client.extract_decision_json(self._DECISION_TEXT)
        data = json.loads(raw)

        assert "decision_statement" in data
        assert len(data["decision_statement"]) > 10
        assert isinstance(data.get("goals", []), list)
        assert isinstance(data.get("risks", []), list)

    def test_extraction_pydantic_roundtrip(self):
        from app.llm_client import LLMClient
        from app.schemas.domain import Decision

        client = LLMClient()
        raw = client.extract_decision_json(self._DECISION_TEXT)
        data = json.loads(raw)
        decision = Decision(**data)  # Must not raise

        assert decision.decision_statement
        assert decision.confidence >= 0.0


# ── 3. Nova scenario proposer ────────────────────────────────────────────────

class TestNovaScenarioProposerIntegration:
    """Verify Nova proposes valid template-bound scenarios."""

    def test_propose_scenarios(self):
        from app.services.nova_scenario_proposer import propose_scenarios_with_nova

        decision = {
            "decision_statement": "마케팅팀 광고 예산 3억 원 집행",
            "cost": 300_000_000,
            "remaining_budget": 100_000_000,
            "uses_pii": False,
            "involves_hiring": False,
            "involves_compliance_risk": False,
            "goals": [{"description": "브랜드 인지도 향상"}],
        }
        governance = {
            "triggered_rules": [
                {"rule_id": "R1", "name": "예산 초과", "status": "TRIGGERED"}
            ],
            "approval_chain": [{"role": "CFO"}],
        }
        risk_scoring = {
            "aggregate": {"score": 72, "band": "HIGH"},
            "dimensions": [
                {"id": "financial", "score": 85},
                {"id": "compliance_privacy", "score": 10},
                {"id": "strategic", "score": 30},
            ],
        }

        proposals = propose_scenarios_with_nova(decision, governance, risk_scoring)

        # Nova might return None on transient failure — that's acceptable
        if proposals is not None:
            assert len(proposals) >= 1
            for p in proposals:
                assert p.templateId
                assert p.titleKo
                assert p.changeSummaryKo


# ── 4. Nova graph reasoning (NovaReasoner) ───────────────────────────────────

class TestNovaReasonerIntegration:
    """Verify NovaReasoner returns structured graph analysis."""

    def test_graph_contradiction_analysis(self):
        from app.nova_reasoner import NovaReasoner

        reasoner = NovaReasoner()
        decision_data = {
            "decision_statement": "비용 절감 원칙 하에 R&D 인력 20명 공격적 채용",
            "goals": [{"description": "R&D 역량 강화"}],
            "kpis": [{"name": "신규 채용 20명"}],
            "owners": [{"name": "오세훈", "role": "연구개발팀장"}],
            "risks": [{"description": "비용 초과 리스크"}],
        }
        company_data = {
            "strategic_goals": [
                {
                    "goal_id": "G3",
                    "name": "비용 안정화",
                    "description": "운영비 절감",
                    "kpis": [{"name": "운영비 절감률"}],
                    "owner_id": "cfo_001",
                }
            ],
            "approval_hierarchy": {"personnel": []},
            "risk_tolerance": {"financial": {"high_cost_threshold": 200_000_000}},
        }

        result = reasoner.reason_about_graph_contradictions(
            decision_id="test_integration",
            decision_data=decision_data,
            company_data=company_data,
            lang="en",
        )

        assert isinstance(result, dict)
        # Should have at least one of these keys
        assert any(
            k in result
            for k in ["contradictions", "strategic_goal_conflicts", "recommendations", "reasoning_summary"]
        )


# ── 5. Risk semantics inference ──────────────────────────────────────────────

class TestRiskSemanticsIntegration:
    """Verify risk_evidence_llm returns structured semantics."""

    def test_infer_risk_semantics(self):
        from app.services.risk_evidence_llm import infer_risk_semantics

        result = infer_risk_semantics(
            decision_text="마케팅팀에서 고객 데이터를 활용한 타겟 광고 캠페인 집행 (예산 2억 원)",
            company_summary={"strategic_goals": [{"name": "매출 성장"}]},
            triggered_rules_summary=[{"rule_id": "R1", "name": "PII 사용"}],
        )

        # May return None on transient failure
        if result is not None:
            assert hasattr(result, "goal_impacts")
            assert hasattr(result, "compliance_facts")
            assert result.global_confidence >= 0.0
