"""
Tests for Step 9 — Governance Agent (LangGraph).

Tests the schemas, tools, and agent wiring without requiring a real LLM
or Neo4j instance. Uses mocks for the repository and LLM.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from pydantic import ValidationError

from app.validation.schemas import (
    GovernanceGap,
    PrecedentDecision,
    ValidationResult,
    ValidationState,
    _VALID_VERDICTS,
)
from app.validation.tools import create_tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_repo():
    """Create a mock BaseGraphRepository with all required async methods."""
    repo = AsyncMock()
    repo.get_all_rules = AsyncMock(return_value=[
        {
            "rule_id": "nexus:rule:R1",
            "label": "CFO Approval Required",
            "properties": {"conditions": [{"field": "cost", "operator": ">", "value": 50000}]},
            "goals": [{"id": "nexus:goal:cost_stability", "label": "Cost Stability"}],
            "approvers": [{"id": "nexus:actor:cfo", "label": "CFO"}],
        }
    ])
    repo.search_similar_decisions = AsyncMock(return_value=[
        {
            "id": "nexus:decision:20260101_abc123",
            "label": "Previous hiring decision",
            "score": 0.87,
            "outcome": "APPROVED",
            "context": {},
        }
    ])
    repo.get_goal_conflicts = AsyncMock(return_value=[])
    repo.get_gaps_for_rules = AsyncMock(return_value=[
        {
            "rule_id": "nexus:rule:R1",
            "gap_id": "nexus:gap:budget_forecast",
            "gap_label": "No budget forecast available",
            "gap_properties": {},
        }
    ])
    repo.safe_cypher_read = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def sample_governance_result():
    """Minimal GovernanceResult.to_dict() shape."""
    return {
        "approval_chain": [
            {
                "level": "C_LEVEL",
                "role": "CFO",
                "required": True,
                "rationale": "Cost exceeds $50K threshold",
                "source_rule_id": "R1",
                "rule_action": "require_approval",
            }
        ],
        "flags": ["FINANCIAL_THRESHOLD_EXCEEDED"],
        "requires_human_review": True,
        "triggered_rules": [
            {
                "rule_id": "R1",
                "name": "CFO Approval",
                "description": "CFO approval for expenses > $50K",
                "rule_type": "financial",
                "status": "TRIGGERED",
                "visible_in_graph": True,
                "reason": "Rule triggered: require_approval",
            }
        ],
        "computed_risk_score": 4.5,
    }


@pytest.fixture
def sample_risk_scoring():
    """Minimal RiskScoringResult shape."""
    return {
        "aggregate": {"score": 55, "band": "MEDIUM", "confidence": 0.85},
        "dimensions": [],
    }


# ---------------------------------------------------------------------------
# 1. ValidationResult Pydantic model validation
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_valid_verdicts(self):
        for verdict in ["APPROVE", "REJECT", "ESCALATE", "REVIEW"]:
            result = ValidationResult(
                verdict=verdict,
                confidence=0.8,
                agent_reasoning="Test reasoning",
            )
            assert result.verdict == verdict

    def test_confidence_bounds(self):
        result = ValidationResult(
            verdict="APPROVE",
            confidence=0.0,
            agent_reasoning="Low confidence",
        )
        assert result.confidence == 0.0

        result = ValidationResult(
            verdict="APPROVE",
            confidence=1.0,
            agent_reasoning="High confidence",
        )
        assert result.confidence == 1.0

    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            ValidationResult(
                verdict="APPROVE",
                confidence=-0.1,
                agent_reasoning="Invalid",
            )

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            ValidationResult(
                verdict="APPROVE",
                confidence=1.1,
                agent_reasoning="Invalid",
            )

    def test_default_empty_lists(self):
        result = ValidationResult(
            verdict="REVIEW",
            confidence=0.5,
            agent_reasoning="Minimal",
        )
        assert result.precedent_decisions == []
        assert result.governance_gaps == []
        assert result.goal_impacts == []
        assert result.triggered_rule_ids == []
        assert result.approval_chain == []

    def test_full_result(self):
        result = ValidationResult(
            verdict="ESCALATE",
            confidence=0.75,
            agent_reasoning="High cost decision requires CFO sign-off",
            precedent_decisions=[
                PrecedentDecision(
                    decision_id="d1",
                    similarity_score=0.9,
                    label="Similar hire",
                    rules_triggered=["R1"],
                    outcome="APPROVED",
                )
            ],
            governance_gaps=[
                GovernanceGap(
                    gap_type="internal_data",
                    description="Budget forecast missing",
                    severity="medium",
                    integration_request="Connect budget API",
                )
            ],
            triggered_rule_ids=["R1", "R5"],
            approval_chain=[{"role": "CFO", "level": "C_LEVEL"}],
        )
        assert len(result.precedent_decisions) == 1
        assert len(result.governance_gaps) == 1
        assert result.triggered_rule_ids == ["R1", "R5"]


# ---------------------------------------------------------------------------
# 2. GovernanceGap model
# ---------------------------------------------------------------------------


class TestGovernanceGap:
    def test_valid_gap(self):
        gap = GovernanceGap(
            gap_type="external_knowledge",
            description="No regulatory context for APAC",
            severity="high",
        )
        assert gap.gap_type == "external_knowledge"
        assert gap.integration_request is None

    def test_gap_with_integration_request(self):
        gap = GovernanceGap(
            gap_type="internal_data",
            description="Budget remaining unknown",
            severity="medium",
            integration_request="POST /v1/companies/{id}/context",
        )
        assert gap.integration_request is not None

    def test_all_gap_types(self):
        for gap_type in ["external_knowledge", "internal_data", "governance_config"]:
            gap = GovernanceGap(
                gap_type=gap_type,
                description="Test",
                severity="low",
            )
            assert gap.gap_type == gap_type


# ---------------------------------------------------------------------------
# 3. PrecedentDecision model
# ---------------------------------------------------------------------------


class TestPrecedentDecision:
    def test_valid_precedent(self):
        p = PrecedentDecision(
            decision_id="nexus:decision:20260101_abc",
            similarity_score=0.92,
            label="Previous engineering hire",
            rules_triggered=["R1", "R5"],
            outcome="APPROVED",
        )
        assert p.similarity_score == 0.92
        assert len(p.rules_triggered) == 2

    def test_precedent_minimal(self):
        p = PrecedentDecision(
            decision_id="d1",
            similarity_score=0.5,
            label="Old decision",
        )
        assert p.rules_triggered == []
        assert p.outcome is None


# ---------------------------------------------------------------------------
# 4. create_tools returns expected number of tools
# ---------------------------------------------------------------------------


class TestCreateTools:
    def test_tool_count(self, mock_repo):
        tools = create_tools(mock_repo)
        assert len(tools) == 6

    def test_tool_names(self, mock_repo):
        tools = create_tools(mock_repo)
        names = {t.name for t in tools}
        expected = {
            "search_governance_rules",
            "search_similar_decisions",
            "get_goal_conflicts",
            "get_governance_gaps",
            "query_graph",
            "get_operational_context",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# 5. Individual tool functions with mocked repo
# ---------------------------------------------------------------------------


class TestToolFunctions:
    @pytest.mark.asyncio
    async def test_search_governance_rules(self, mock_repo):
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "search_governance_rules")
        result = await tool.ainvoke({"company_id": "nexus_analytics"})
        assert len(result) == 1
        assert result[0]["rule_id"] == "nexus:rule:R1"
        mock_repo.get_all_rules.assert_awaited_once_with(
            "nexus_analytics", rule_ids=None, limit=20
        )

    @pytest.mark.asyncio
    async def test_search_governance_rules_error(self, mock_repo):
        mock_repo.get_all_rules = AsyncMock(side_effect=Exception("DB error"))
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "search_governance_rules")
        result = await tool.ainvoke({"company_id": "nexus_analytics"})
        assert result == []

    @pytest.mark.asyncio
    async def test_get_goal_conflicts(self, mock_repo):
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "get_goal_conflicts")
        result = await tool.ainvoke({
            "company_id": "nexus_analytics",
            "goal_ids": ["nexus:goal:cost_stability"],
        })
        assert result == []
        mock_repo.get_goal_conflicts.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_governance_gaps(self, mock_repo):
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "get_governance_gaps")
        result = await tool.ainvoke({
            "company_id": "nexus_analytics",
            "rule_ids": ["nexus:rule:R1"],
        })
        assert len(result) == 1
        assert result[0]["gap_label"] == "No budget forecast available"

    @pytest.mark.asyncio
    async def test_query_graph_safe(self, mock_repo):
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "query_graph")
        result = await tool.ainvoke({
            "company_id": "nexus_analytics",
            "cypher_query": "MATCH (n:Rule) RETURN n.id LIMIT 5",
        })
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_query_graph_rejects_mutation(self, mock_repo):
        mock_repo.safe_cypher_read = AsyncMock(
            side_effect=ValueError("Mutating Cypher operations are not allowed")
        )
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "query_graph")
        result = await tool.ainvoke({
            "company_id": "nexus_analytics",
            "cypher_query": "CREATE (n:Bad) RETURN n",
        })
        assert isinstance(result, list)
        assert len(result) == 1
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_get_operational_context(self, mock_repo):
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "get_operational_context")
        result = await tool.ainvoke({"company_id": "nexus_analytics"})
        assert result["company_id"] == "nexus_analytics"
        assert result["source"] == "mock"
        assert "budget" in result
        assert "headcount" in result

    @pytest.mark.asyncio
    async def test_search_similar_decisions_no_embedding(self, mock_repo):
        """When embed_text returns None, tool should handle gracefully."""
        tools = create_tools(mock_repo)
        tool = next(t for t in tools if t.name == "search_similar_decisions")
        # The tool uses a dynamic import inside the function body, so we
        # patch at the source module where embed_text is defined.
        with patch(
            "app.onboarding.transform.embedder.embed_text",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await tool.ainvoke({
                "company_id": "nexus_analytics",
                "query_text": "hire engineers",
            })
            assert isinstance(result, list)
            # Either empty or a note about embedding unavailability
            if result:
                assert "note" in result[0] or "score" in result[0]


# ---------------------------------------------------------------------------
# 6. build_governance_agent compiles
# ---------------------------------------------------------------------------


class TestBuildGovernanceAgent:
    def test_agent_compiles(self, mock_repo):
        """Verify the StateGraph compiles without errors."""
        with patch("app.validation.governance_agent.get_llm") as mock_get_llm:
            mock_llm = MagicMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_get_llm.return_value = mock_llm

            from app.validation.governance_agent import build_governance_agent
            agent = build_governance_agent(mock_repo)

            # A compiled graph should have an invoke method
            assert hasattr(agent, "ainvoke")
            assert hasattr(agent, "invoke")
            mock_get_llm.assert_called_once_with("capable")


# ---------------------------------------------------------------------------
# 7. run_governance_agent returns ValidationResult (mocked LLM)
# ---------------------------------------------------------------------------


class TestRunGovernanceAgent:
    @pytest.mark.asyncio
    async def test_returns_validation_result(
        self, mock_repo, sample_governance_result, sample_risk_scoring
    ):
        """run_governance_agent returns a ValidationResult with mocked LLM."""
        from langchain_core.messages import AIMessage
        from app.validation.governance_agent import run_governance_agent

        # Mock the LLM to return a verdict directly (no tool calls)
        mock_response = AIMessage(
            content='Based on analysis:\n```json\n{"verdict": "ESCALATE", "confidence": 0.75, "reasoning": "High cost needs CFO sign-off."}\n```'
        )

        with patch("app.validation.governance_agent.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_llm.return_value = mock_llm

            result = await run_governance_agent(
                company_id="nexus_analytics",
                decision_text="Hire 3 engineers at $150K each",
                decision_payload={"cost": 450000},
                governance_result=sample_governance_result,
                risk_scoring=sample_risk_scoring,
                graph_context=None,
                repo=mock_repo,
            )

            assert isinstance(result, ValidationResult)
            assert result.verdict == "ESCALATE"
            assert result.confidence == 0.75
            assert "CFO" in result.agent_reasoning
            assert result.triggered_rule_ids == ["R1"]


# ---------------------------------------------------------------------------
# 8. run_governance_agent error handling
# ---------------------------------------------------------------------------


class TestRunGovernanceAgentErrorHandling:
    @pytest.mark.asyncio
    async def test_returns_review_on_llm_failure(
        self, mock_repo, sample_governance_result
    ):
        """When the LLM fails, agent returns a default REVIEW result."""
        from app.validation.governance_agent import run_governance_agent

        with patch("app.validation.governance_agent.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_llm.ainvoke = AsyncMock(
                side_effect=Exception("LLM API timeout")
            )
            mock_get_llm.return_value = mock_llm

            result = await run_governance_agent(
                company_id="nexus_analytics",
                decision_text="Test decision",
                decision_payload={},
                governance_result=sample_governance_result,
                risk_scoring=None,
                graph_context=None,
                repo=mock_repo,
            )

            assert isinstance(result, ValidationResult)
            assert result.verdict == "REVIEW"
            assert result.confidence == 0.3
            assert "Agent error" in result.agent_reasoning

    @pytest.mark.asyncio
    async def test_returns_review_on_bad_verdict(
        self, mock_repo, sample_governance_result
    ):
        """When the LLM returns an invalid verdict, agent defaults to REVIEW."""
        from langchain_core.messages import AIMessage
        from app.validation.governance_agent import run_governance_agent

        mock_response = AIMessage(
            content='```json\n{"verdict": "MAYBE", "confidence": 0.9, "reasoning": "Not sure"}\n```'
        )

        with patch("app.validation.governance_agent.get_llm") as mock_get_llm:
            mock_llm = AsyncMock()
            mock_llm.bind_tools = MagicMock(return_value=mock_llm)
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)
            mock_get_llm.return_value = mock_llm

            result = await run_governance_agent(
                company_id="nexus_analytics",
                decision_text="Test decision",
                decision_payload={},
                governance_result=sample_governance_result,
                risk_scoring=None,
                graph_context=None,
                repo=mock_repo,
            )

            assert isinstance(result, ValidationResult)
            assert result.verdict == "REVIEW"


# ---------------------------------------------------------------------------
# 9. ValidationState TypedDict construction
# ---------------------------------------------------------------------------


class TestValidationState:
    def test_construct_state(self):
        """ValidationState can be constructed as a plain dict."""
        state: ValidationState = {
            "company_id": "nexus_analytics",
            "decision_text": "Hire engineers",
            "decision_payload": {"cost": 450000},
            "governance_result": {"triggered_rules": [], "flags": []},
            "risk_scoring": None,
            "graph_context": None,
            "precedent_decisions": [],
            "governance_gaps": [],
            "goal_impacts": [],
            "agent_reasoning": "",
            "verdict": "REVIEW",
            "confidence": 0.5,
            "messages": [],
            "external_signals": None,
            "error": None,
        }
        assert state["company_id"] == "nexus_analytics"
        assert state["verdict"] == "REVIEW"
        assert state["confidence"] == 0.5
        assert state["messages"] == []

    def test_valid_verdicts_set(self):
        """Verify the set of valid verdicts."""
        assert _VALID_VERDICTS == {"APPROVE", "REJECT", "ESCALATE", "REVIEW"}


# ---------------------------------------------------------------------------
# 10. Verdict parsing helpers
# ---------------------------------------------------------------------------


class TestVerdictParsing:
    def test_parse_json_block(self):
        from app.validation.governance_agent import _parse_verdict_json

        text = 'Some analysis.\n```json\n{"verdict": "APPROVE", "confidence": 0.9, "reasoning": "All good."}\n```'
        verdict, confidence, reasoning = _parse_verdict_json(text)
        assert verdict == "APPROVE"
        assert confidence == 0.9
        assert reasoning == "All good."

    def test_parse_raw_json(self):
        from app.validation.governance_agent import _parse_verdict_json

        text = 'My analysis: {"verdict": "REJECT", "confidence": 0.2, "reasoning": "Rule violated."}'
        verdict, confidence, reasoning = _parse_verdict_json(text)
        assert verdict == "REJECT"
        assert confidence == 0.2

    def test_parse_fallback_text(self):
        from app.validation.governance_agent import _parse_verdict_json

        text = "Based on the analysis, I recommend we ESCALATE this decision to the CFO."
        verdict, confidence, reasoning = _parse_verdict_json(text)
        assert verdict == "ESCALATE"
        assert confidence == 0.5  # fallback

    def test_parse_invalid_verdict_defaults_to_review(self):
        from app.validation.governance_agent import _parse_verdict_json

        text = '```json\n{"verdict": "DENY", "confidence": 0.8, "reasoning": "Bad"}\n```'
        verdict, confidence, reasoning = _parse_verdict_json(text)
        assert verdict == "REVIEW"

    def test_parse_no_verdict_text(self):
        from app.validation.governance_agent import _parse_verdict_json

        text = "I need more information before I can decide."
        verdict, confidence, reasoning = _parse_verdict_json(text)
        assert verdict == "REVIEW"
