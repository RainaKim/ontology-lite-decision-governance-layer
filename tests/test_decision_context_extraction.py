"""
tests/test_decision_context_extraction.py

Unit tests for app/services/decision_context_service.py.

All tests inject a mock BedrockClient via _client= so no real API calls are made.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.services.decision_context_service import (
    _EntityRaw,
    extract_decision_context,
    filter_left_panel_entities,
    is_left_panel_safe,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(response: dict | str) -> MagicMock:
    """Return a mock BedrockClient whose .invoke() returns the given JSON."""
    client = MagicMock()
    if isinstance(response, dict):
        client.invoke.return_value = json.dumps(response)
    else:
        client.invoke.return_value = response
    return client


def _entity(**kwargs) -> _EntityRaw:
    defaults = dict(
        key="cost",
        label="비용",
        label_en="Cost",
        value="5,000만 원",
        value_en="₩50M",
        category="cost",
        kind="fact",
        confidence=0.9,
    )
    defaults.update(kwargs)
    return _EntityRaw(**defaults)


# ---------------------------------------------------------------------------
# is_left_panel_safe
# ---------------------------------------------------------------------------

class TestIsLeftPanelSafe:
    def test_fact_high_confidence_is_safe(self):
        assert is_left_panel_safe(_entity(kind="fact", confidence=0.9)) is True

    def test_context_kind_is_safe(self):
        assert is_left_panel_safe(_entity(kind="context", confidence=0.7)) is True

    def test_judgment_kind_is_blocked(self):
        assert is_left_panel_safe(_entity(kind="judgment", confidence=0.9)) is False

    def test_low_confidence_is_blocked(self):
        assert is_left_panel_safe(_entity(kind="fact", confidence=0.2)) is False

    def test_exactly_03_confidence_is_safe(self):
        # threshold is < 0.3; exactly 0.3 passes
        assert is_left_panel_safe(_entity(kind="fact", confidence=0.3)) is True

    def test_below_03_confidence_is_blocked(self):
        assert is_left_panel_safe(_entity(kind="fact", confidence=0.29)) is False

    def test_empty_value_is_blocked(self):
        assert is_left_panel_safe(_entity(value="", value_en="")) is False

    def test_whitespace_value_is_blocked(self):
        assert is_left_panel_safe(_entity(value="   ")) is False

    def test_risk_key_prefix_is_blocked(self):
        assert is_left_panel_safe(_entity(key="risk_level", kind="fact")) is False

    def test_approval_key_prefix_is_blocked(self):
        assert is_left_panel_safe(_entity(key="approval_required", kind="fact")) is False

    def test_governance_key_prefix_is_blocked(self):
        assert is_left_panel_safe(_entity(key="governance_status", kind="fact")) is False

    def test_compliance_risk_category_is_blocked(self):
        assert is_left_panel_safe(_entity(category="compliance_risk")) is False

    def test_normal_category_with_risk_in_value_is_safe(self):
        # "risk" in the *value* is fine; only key/category prefix matters
        assert is_left_panel_safe(_entity(key="department", category="department", value="risk mgmt dept")) is True


# ---------------------------------------------------------------------------
# filter_left_panel_entities
# ---------------------------------------------------------------------------

class TestFilterLeftPanelEntities:
    def test_removes_judgment_keeps_fact(self):
        entities = [
            _entity(key="proposed_action", kind="fact", confidence=0.95),
            _entity(key="risk_level", kind="judgment", confidence=0.9),
            _entity(key="cost", kind="fact", confidence=0.85),
        ]
        result = filter_left_panel_entities(entities)
        keys = [e.key for e in result]
        assert "proposed_action" in keys
        assert "cost" in keys
        assert "risk_level" not in keys

    def test_empty_list(self):
        assert filter_left_panel_entities([]) == []

    def test_all_blocked(self):
        entities = [
            _entity(key="approval_needed", kind="judgment"),
            _entity(key="risk_score", kind="fact", confidence=0.1),
        ]
        assert filter_left_panel_entities(entities) == []


# ---------------------------------------------------------------------------
# extract_decision_context — happy path
# ---------------------------------------------------------------------------

HAPPY_RESPONSE = {
    "proposal": "생산 직원 1명을 신규 채용하기로 결정했습니다.",
    "proposal_en": "Decided to hire 1 new production staff member.",
    "source_label": "AI Agent",
    "entities": [
        {
            "key": "proposed_action",
            "label": "제안 내용",
            "label_en": "Proposed Action",
            "value": "생산 직원 1명 신규 채용",
            "value_en": "Hire 1 new production staff member",
            "category": "action",
            "kind": "fact",
            "confidence": 0.95,
        },
        {
            "key": "headcount_change",
            "label": "인원 변경",
            "label_en": "Headcount Change",
            "value": "+1명",
            "value_en": "+1 person",
            "category": "headcount",
            "kind": "fact",
            "confidence": 0.9,
        },
        {
            "key": "justification",
            "label": "근거",
            "label_en": "Justification",
            "value": "전분기 대비 12% 매출 증가",
            "value_en": "12% QoQ revenue increase",
            "category": "context",
            "kind": "context",
            "confidence": 0.85,
        },
        {
            "key": "channel",
            "label": "채용 경로",
            "label_en": "Hiring Channel",
            "value": "LinkedIn 채용 공고",
            "value_en": "LinkedIn job listing",
            "category": "channel",
            "kind": "fact",
            "confidence": 0.8,
        },
    ],
}


class TestExtractDecisionContext:
    def test_happy_path_ko(self):
        client = _make_client(HAPPY_RESPONSE)
        result = extract_decision_context(
            decision_text="생산 직원 1명을 채용합니다.",
            lang="ko",
            _client=client,
        )
        assert result is not None
        assert result["proposal"] == HAPPY_RESPONSE["proposal"]
        assert result["source"]["type"] == "AI_AGENT"
        entities = result["entities"]
        assert len(entities) == 4
        keys = [e["key"] for e in entities]
        assert "proposed_action" in keys
        assert "headcount_change" in keys

    def test_happy_path_en_uses_english_fields(self):
        client = _make_client(HAPPY_RESPONSE)
        result = extract_decision_context(
            decision_text="Hiring 1 production staff.",
            lang="en",
            _client=client,
        )
        assert result is not None
        # proposal always Korean; proposal_en always English regardless of lang param
        assert result["proposal"] == HAPPY_RESPONSE["proposal"]
        assert result["proposal_en"] == HAPPY_RESPONSE["proposal_en"]
        entities = result["entities"]
        # English values (lang="en" still controls entity label/value language)
        action = next(e for e in entities if e["key"] == "proposed_action")
        assert action["value"] == "Hire 1 new production staff member"
        assert action["label"] == "Proposed Action"

    def test_agent_name_injected_as_source_label_ko(self):
        client = _make_client(HAPPY_RESPONSE)
        result = extract_decision_context(
            decision_text="결정 내용",
            agent_name="인사봇",
            agent_name_en="HR Bot",
            lang="ko",
            _client=client,
        )
        assert result["source"]["label"] == "인사봇"

    def test_agent_name_injected_as_source_label_en(self):
        client = _make_client(HAPPY_RESPONSE)
        result = extract_decision_context(
            decision_text="Decision text",
            agent_name="인사봇",
            agent_name_en="HR Bot",
            lang="en",
            _client=client,
        )
        assert result["source"]["label"] == "HR Bot"

    def test_judgment_entities_filtered_out(self):
        response_with_judgment = {
            **HAPPY_RESPONSE,
            "entities": [
                *HAPPY_RESPONSE["entities"],
                {
                    "key": "approval_required",
                    "label": "승인 필요",
                    "label_en": "Approval Required",
                    "value": "CFO 승인",
                    "value_en": "CFO approval",
                    "category": "approval",
                    "kind": "judgment",
                    "confidence": 0.9,
                },
            ],
        }
        client = _make_client(response_with_judgment)
        result = extract_decision_context(
            decision_text="결정 내용",
            lang="ko",
            _client=client,
        )
        keys = [e["key"] for e in result["entities"]]
        assert "approval_required" not in keys

    def test_returns_none_on_json_error(self):
        client = _make_client("not valid json !!!")
        result = extract_decision_context("결정 내용", _client=client)
        assert result is None

    def test_returns_none_on_pydantic_error(self):
        bad_response = {"proposal": "ok", "entities": [{"key": "x"}]}  # missing required fields
        client = _make_client(bad_response)
        result = extract_decision_context("결정 내용", _client=client)
        assert result is None

    def test_returns_none_when_client_is_none(self):
        # No client, no env var — should return None gracefully
        result = extract_decision_context("결정 내용", _client=None)
        assert result is None

    def test_returns_none_on_client_exception(self):
        client = MagicMock()
        client.invoke.side_effect = RuntimeError("network timeout")
        result = extract_decision_context("결정 내용", _client=client)
        assert result is None

    def test_entity_fields_include_kind_and_confidence(self):
        client = _make_client(HAPPY_RESPONSE)
        result = extract_decision_context("결정 내용", _client=client)
        for entity in result["entities"]:
            assert "kind" in entity
            assert "confidence" in entity
            assert entity["kind"] in ("fact", "context", "judgment")
            assert 0.0 <= entity["confidence"] <= 1.0

    def test_all_safe_entities_pass_through(self):
        """All entities in HAPPY_RESPONSE are safe — none should be filtered."""
        client = _make_client(HAPPY_RESPONSE)
        result = extract_decision_context("결정 내용", _client=client)
        assert len(result["entities"]) == len(HAPPY_RESPONSE["entities"])

    def test_low_confidence_entity_filtered(self):
        response_with_low_conf = {
            **HAPPY_RESPONSE,
            "entities": [
                *HAPPY_RESPONSE["entities"],
                {
                    "key": "vague_fact",
                    "label": "모호한 사실",
                    "label_en": "Vague fact",
                    "value": "어쩌면 있을 수도",
                    "value_en": "Maybe",
                    "category": "other",
                    "kind": "fact",
                    "confidence": 0.1,
                },
            ],
        }
        client = _make_client(response_with_low_conf)
        result = extract_decision_context("결정 내용", _client=client)
        keys = [e["key"] for e in result["entities"]]
        assert "vague_fact" not in keys
