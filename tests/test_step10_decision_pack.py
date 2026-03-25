"""
Tests for Step 10 — Decision Pack Wiring, Validation Endpoint,
and Synthetic Decision History.

Tests the following:
1. build_console_payload() backward compatibility (validation_result=None)
2. build_console_payload() with a full ValidationResult
3. ValidationRequest Pydantic model construction
4. ValidationResponse Pydantic model construction
5. Validation endpoint with mocked run_governance_agent (200)
6. Validation endpoint with mocked run_governance_agent raising (500)
7. generate_decision_history.py logic (mock LLM + Neo4j)
"""

from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.repositories.decision_store import DecisionRecord
from app.routers.normalizers import build_console_payload
from app.validation.schemas import (
    GovernanceGap,
    PrecedentDecision,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_record():
    """A minimal DecisionRecord with enough data for build_console_payload."""
    now = datetime.now(timezone.utc).isoformat()
    return DecisionRecord(
        decision_id="test-001",
        company_id="nexus_dynamics",
        status="complete",
        input_text="Hire 3 engineers",
        created_at=now,
        updated_at=now,
        current_step=4,
    )


@pytest.fixture
def sample_validation_result():
    """A full ValidationResult for testing."""
    return ValidationResult(
        verdict="ESCALATE",
        confidence=0.75,
        agent_reasoning="High cost decision requires CFO sign-off. Multiple rules triggered.",
        precedent_decisions=[
            PrecedentDecision(
                decision_id="dec-prev-001",
                similarity_score=0.91,
                label="Previous engineering hire at $160K",
                rules_triggered=["R1", "R5"],
                outcome="APPROVED",
            ),
            PrecedentDecision(
                decision_id="dec-prev-002",
                similarity_score=0.84,
                label="Contractor hire for data pipeline",
                rules_triggered=["R5"],
                outcome="APPROVED",
            ),
            PrecedentDecision(
                decision_id="dec-prev-003",
                similarity_score=0.78,
                label="Senior engineer hire rejected",
                rules_triggered=["R1", "R6"],
                outcome="REJECTED",
            ),
            PrecedentDecision(
                decision_id="dec-prev-004",
                similarity_score=0.72,
                label="Batch hiring 5 analysts",
                rules_triggered=["R2", "R5"],
                outcome="APPROVED",
            ),
        ],
        governance_gaps=[
            GovernanceGap(
                gap_type="internal_data",
                description="Budget forecast for Q3 not available",
                severity="medium",
                integration_request="POST /v1/companies/{id}/context",
            ),
        ],
        goal_impacts=[{"goal_id": "G2", "impact": "negative", "reason": "Over budget"}],
        triggered_rule_ids=["R1", "R5"],
        approval_chain=[
            {"role": "CFO", "level": "C_LEVEL"},
            {"role": "CTO", "level": "C_LEVEL"},
        ],
    )


# ---------------------------------------------------------------------------
# 1. build_console_payload with validation_result=None (backward compat)
# ---------------------------------------------------------------------------


class TestBuildConsolePayloadBackwardCompat:
    def test_no_validation_result(self, minimal_record):
        """build_console_payload works without validation_result."""
        payload = build_console_payload(minimal_record, validation_result=None)
        assert payload.decision_id == "test-001"
        assert payload.validation_verdict is None
        assert payload.validation_confidence is None
        assert payload.validation_reasoning is None
        assert payload.governance_gaps is None
        assert payload.similar_decisions is None

    def test_no_validation_result_default(self, minimal_record):
        """build_console_payload with no validation_result arg at all."""
        payload = build_console_payload(minimal_record)
        assert payload.validation_verdict is None


# ---------------------------------------------------------------------------
# 2. build_console_payload with full ValidationResult
# ---------------------------------------------------------------------------


class TestBuildConsolePayloadWithValidation:
    def test_full_validation_result(self, minimal_record, sample_validation_result):
        """All validation fields populate correctly."""
        payload = build_console_payload(
            minimal_record,
            validation_result=sample_validation_result,
        )
        assert payload.validation_verdict == "ESCALATE"
        assert payload.validation_confidence == 0.75
        assert "CFO" in payload.validation_reasoning
        assert payload.governance_gaps is not None
        assert len(payload.governance_gaps) == 1
        assert payload.governance_gaps[0]["gap_type"] == "internal_data"
        # similar_decisions capped at 3
        assert payload.similar_decisions is not None
        assert len(payload.similar_decisions) == 3

    def test_validation_from_record_dict(self, minimal_record):
        """Validation result stored as dict on record is also consumed."""
        minimal_record.validation_result = {
            "verdict": "APPROVE",
            "confidence": 0.9,
            "agent_reasoning": "All rules satisfied.",
            "governance_gaps": [],
            "precedent_decisions": [
                {"decision_id": "d1", "similarity_score": 0.8, "label": "Test"}
            ],
        }
        payload = build_console_payload(minimal_record)
        assert payload.validation_verdict == "APPROVE"
        assert payload.validation_confidence == 0.9
        assert payload.similar_decisions is not None
        assert len(payload.similar_decisions) == 1


# ---------------------------------------------------------------------------
# 3. ValidationRequest Pydantic model
# ---------------------------------------------------------------------------


class TestValidationRequest:
    def test_construct(self):
        from app.routers.validation import ValidationRequest

        req = ValidationRequest(
            decision_text="Hire 3 engineers at $150K each",
            decision_dimensions={"cost": 450000, "involves_hiring": True},
            company_id="nexus_analytics",
        )
        assert req.decision_text == "Hire 3 engineers at $150K each"
        assert req.decision_dimensions["cost"] == 450000
        assert req.company_id == "nexus_analytics"

    def test_minimal(self):
        from app.routers.validation import ValidationRequest

        req = ValidationRequest(
            decision_text="Test",
            company_id="test_co",
        )
        assert req.decision_dimensions == {}


# ---------------------------------------------------------------------------
# 4. ValidationResponse Pydantic model
# ---------------------------------------------------------------------------


class TestValidationResponse:
    def test_construct(self):
        from app.routers.validation import ValidationResponse

        resp = ValidationResponse(
            decision_id="d-123",
            company_id="nexus_analytics",
            verdict="APPROVE",
            confidence=0.92,
            reasoning="All governance requirements met.",
            conditions=[],
            approval_chain=[{"role": "CFO"}],
            triggered_rules=[{"rule_id": "R1", "status": "TRIGGERED"}],
            goal_conflicts=[],
            governance_gaps=[],
            risk_score=None,
            similar_decisions=[],
        )
        assert resp.verdict == "APPROVE"
        assert resp.confidence == 0.92
        assert len(resp.approval_chain) == 1

    def test_minimal(self):
        from app.routers.validation import ValidationResponse

        resp = ValidationResponse(
            company_id="test",
            verdict="REVIEW",
            confidence=0.5,
            reasoning="Needs review.",
        )
        assert resp.triggered_rules == []
        assert resp.similar_decisions == []


# ---------------------------------------------------------------------------
# 5. Validation endpoint — 200 success
# ---------------------------------------------------------------------------


class TestValidationEndpoint:
    @pytest.mark.asyncio
    async def test_validate_success(self):
        """validate_decision returns correct shape with mocked dependencies."""
        from app.routers.validation import validate_decision, ValidationRequest

        mock_result = ValidationResult(
            verdict="APPROVE",
            confidence=0.9,
            agent_reasoning="All rules satisfied.",
            triggered_rule_ids=["R1"],
            approval_chain=[{"role": "CFO", "level": "C_LEVEL"}],
        )

        # Mock governance result
        mock_gov_result = MagicMock()
        mock_gov_result.to_dict.return_value = {
            "triggered_rules": [{"rule_id": "R1", "status": "TRIGGERED"}],
            "flags": [],
            "approval_chain": [],
            "requires_human_review": True,
            "computed_risk_score": 3.0,
        }

        request = ValidationRequest(
            decision_text="Hire 3 engineers at $150K each",
            decision_dimensions={"cost": 450000},
            company_id="nexus_analytics",
        )

        with patch(
            "app.validation.governance_agent.run_governance_agent",
            new_callable=AsyncMock,
            return_value=mock_result,
        ), patch(
            "app.governance.evaluate_governance",
            return_value=mock_gov_result,
        ):
            response = await validate_decision(request)

            assert response.verdict == "APPROVE"
            assert response.confidence == 0.9
            assert response.company_id == "nexus_analytics"
            assert response.reasoning == "All rules satisfied."


# ---------------------------------------------------------------------------
# 6. Validation endpoint — 500 on error
# ---------------------------------------------------------------------------


class TestValidationEndpointError:
    @pytest.mark.asyncio
    async def test_validate_error(self):
        """validate_decision raises HTTPException when evaluate_governance fails."""
        from fastapi import HTTPException
        from app.routers.validation import validate_decision, ValidationRequest

        request = ValidationRequest(
            decision_text="Test decision",
            decision_dimensions={},
            company_id="test",
        )

        with patch(
            "app.governance.evaluate_governance",
            side_effect=Exception("LLM timeout"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await validate_decision(request)
            assert exc_info.value.status_code == 500
            assert "Validation failed" in exc_info.value.detail


# ---------------------------------------------------------------------------
# 7. Decision history generation — mock LLM + Neo4j
# ---------------------------------------------------------------------------


class TestDecisionHistoryGeneration:
    def test_fallback_decisions_count(self):
        """get_fallback_decisions returns 20 decisions."""
        from scripts.generate_decision_history import get_fallback_decisions

        decisions = get_fallback_decisions()
        assert len(decisions) == 20

    def test_fallback_decisions_shape(self):
        """Each fallback decision has required fields."""
        from scripts.generate_decision_history import get_fallback_decisions

        decisions = get_fallback_decisions()
        required_fields = {
            "id", "date", "description", "decision_type",
            "status", "triggered_rule_ids", "approver_role",
        }
        for d in decisions:
            assert required_fields.issubset(d.keys()), (
                f"Decision {d.get('id')} missing fields: "
                f"{required_fields - set(d.keys())}"
            )

    def test_fallback_decisions_types(self):
        """Fallback decisions have diverse decision_types."""
        from scripts.generate_decision_history import get_fallback_decisions

        decisions = get_fallback_decisions()
        types = {d["decision_type"] for d in decisions}
        assert "hiring" in types
        assert "compliance" in types
        assert "budget" in types
        assert "vendor" in types

    def test_fallback_decisions_mixed_status(self):
        """Fallback decisions have both approved and rejected."""
        from scripts.generate_decision_history import get_fallback_decisions

        decisions = get_fallback_decisions()
        statuses = {d["status"] for d in decisions}
        assert "approved" in statuses
        assert "rejected" in statuses

    @pytest.mark.asyncio
    async def test_generate_via_llm_mocked(self):
        """generate_decisions_via_llm with mocked LLM."""
        from scripts.generate_decision_history import generate_decisions_via_llm

        mock_decisions = [
            {"id": "DEC-001", "date": "2024-01-15", "description": "Test decision", "decision_type": "budget", "amount": 50000, "status": "approved", "triggered_rule_ids": ["R1"], "approver_role": "CFO", "outcome_notes": "Approved"}
        ]

        mock_response = MagicMock()
        mock_response.content = json.dumps(mock_decisions)

        with patch("app.config.llm.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_llm.return_value = mock_llm

            decisions = await generate_decisions_via_llm(1)
            assert len(decisions) == 1
            assert decisions[0]["id"] == "DEC-001"

    @pytest.mark.asyncio
    async def test_generate_via_llm_failure_returns_empty(self):
        """generate_decisions_via_llm returns empty list on error."""
        from scripts.generate_decision_history import generate_decisions_via_llm

        with patch("app.config.llm.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))
            mock_get_llm.return_value = mock_llm

            decisions = await generate_decisions_via_llm(5)
            assert decisions == []

    @pytest.mark.asyncio
    async def test_write_decisions_to_neo4j_mocked(self):
        """write_decisions_to_neo4j with mocked repo and embedder."""
        from scripts.generate_decision_history import write_decisions_to_neo4j

        mock_repo = AsyncMock()
        mock_repo.write_node = AsyncMock()

        decisions = [
            {"id": "DEC-001", "description": "Test decision", "decision_type": "budget", "status": "approved"},
            {"id": "DEC-002", "description": "Another decision", "decision_type": "hiring", "status": "rejected"},
        ]

        with patch(
            "app.onboarding.transform.embedder.embed_text",
            new_callable=AsyncMock,
            return_value=[0.1] * 1536,
        ):
            count = await write_decisions_to_neo4j(decisions, "nexus_analytics", repo=mock_repo)
            assert count == 2
            assert mock_repo.write_node.await_count == 2

    @pytest.mark.asyncio
    async def test_write_decisions_handles_partial_failure(self):
        """write_decisions_to_neo4j counts only successful writes."""
        from scripts.generate_decision_history import write_decisions_to_neo4j

        mock_repo = AsyncMock()
        # First call succeeds, second raises
        mock_repo.write_node = AsyncMock(
            side_effect=[None, Exception("Neo4j error")]
        )

        decisions = [
            {"id": "DEC-001", "description": "Good", "decision_type": "budget", "status": "approved"},
            {"id": "DEC-002", "description": "Bad", "decision_type": "hiring", "status": "rejected"},
        ]

        with patch(
            "app.onboarding.transform.embedder.embed_text",
            new_callable=AsyncMock,
            return_value=None,
        ):
            count = await write_decisions_to_neo4j(decisions, "nexus_analytics", repo=mock_repo)
            assert count == 1


# ---------------------------------------------------------------------------
# 8. DecisionRecord.validation_result field exists
# ---------------------------------------------------------------------------


class TestDecisionRecordValidationField:
    def test_field_exists(self):
        """DecisionRecord has validation_result field."""
        now = datetime.now(timezone.utc).isoformat()
        record = DecisionRecord(
            decision_id="test",
            company_id="test",
            status="pending",
            input_text="test",
            created_at=now,
            updated_at=now,
        )
        assert record.validation_result is None

    def test_field_stores_dict(self):
        """validation_result can store a dict."""
        now = datetime.now(timezone.utc).isoformat()
        record = DecisionRecord(
            decision_id="test",
            company_id="test",
            status="pending",
            input_text="test",
            created_at=now,
            updated_at=now,
            validation_result={"verdict": "APPROVE", "confidence": 0.9},
        )
        assert record.validation_result["verdict"] == "APPROVE"
