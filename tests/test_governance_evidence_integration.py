"""
Integration tests: evidence registry wired into runtime pipeline components.

Covers:
1. Risk scoring: financial dimension includes registry evidence when company_id given
2. Risk scoring: compliance dimension includes R6 registry evidence for PII scenario
3. Risk scoring: strategic dimension includes goal evidence when goals detected
4. Risk scoring: no crash when company_id is None or unknown
5. Risk scoring: no crash when registry has no entry for a triggered rule
6. Normalizers: triggered rules carry policy evidence
7. Normalizers: approval chain steps carry authority evidence
8. Normalizers: build_console_payload returns governance_evidence block
9. No duplicate evidence records in assembled governance_evidence
10. Existing risk scoring tests still pass (regression)
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
from typing import Optional

from app.services.risk_scoring_service import RiskScoringService, _fetch_registry_evidence
import app.services.evidence_registry_service as ers


COMPANY = "nexus_dynamics"


@pytest.fixture(autouse=True)
def clear_registry_cache():
    ers._clear_cache()
    yield
    ers._clear_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_triggered_rule(rule_id: str, rule_type: str, severity: str = "high") -> dict:
    return {
        "rule_id": rule_id,
        "name": f"Test rule {rule_id}",
        "type": rule_type,
        "rule_type": rule_type,
        "status": "TRIGGERED",
        "severity": severity,
        "consequence": {"severity": severity},
    }


_NEXUS_COMPANY = {
    "risk_tolerance": {
        "financial": {
            "unbudgeted_spend_threshold": 50_000_000,
            "high_cost_threshold": 250_000_000,
            "critical_cost_threshold": 1_000_000_000,
        }
    },
    "strategic_goals": [
        {"goal_id": "G1", "name": "글로벌 매출 확대", "priority": "high"},
        {"goal_id": "G2", "name": "규제 및 윤리 준수", "priority": "critical"},
        {"goal_id": "G3", "name": "운영비용 효율화", "priority": "high"},
    ],
}


# ---------------------------------------------------------------------------
# 1. Financial dimension registry evidence
# ---------------------------------------------------------------------------

class TestFinancialRegistryEvidence:
    def test_financial_dim_has_registry_evidence_when_company_id_given(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 200_000_000},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R1", "financial")]},
            graph_payload=None,
            company_id=COMPANY,
        )
        fin = next((d for d in result.dimensions if d.id == "financial"), None)
        assert fin is not None
        assert len(fin.evidence) > 0, "Financial dimension should have registry evidence"

    def test_financial_dim_evidence_has_internal_policy_source(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 200_000_000},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R1", "financial")]},
            graph_payload=None,
            company_id=COMPANY,
        )
        fin = next(d for d in result.dimensions if d.id == "financial")
        sources = {e.source for e in fin.evidence}
        assert "내부 정책" in sources or "내부 예산 문서" in sources

    def test_financial_dim_no_registry_when_no_company_id(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 200_000_000},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R1", "financial")]},
            graph_payload=None,
            company_id=None,
        )
        fin = next((d for d in result.dimensions if d.id == "financial"), None)
        assert fin is not None
        assert fin.evidence == []  # no registry without company_id

    def test_spend_authority_evidence_included_above_threshold(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 100_000_000},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R1", "financial")]},
            graph_payload=None,
            company_id=COMPANY,
        )
        fin = next(d for d in result.dimensions if d.id == "financial")
        budget_ev_ids = [e.ref.get("id", "") for e in fin.evidence]
        assert any("bs_spend_authority" in eid for eid in budget_ev_ids)

    def test_to_dict_serializes_dimension_evidence(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 200_000_000},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R1", "financial")]},
            graph_payload=None,
            company_id=COMPANY,
        )
        d = result.to_dict()
        fin_dim = next(dim for dim in d["dimensions"] if dim["id"] == "financial")
        # evidence should now be serialized (not hardcoded [])
        assert isinstance(fin_dim["evidence"], list)
        assert len(fin_dim["evidence"]) > 0


# ---------------------------------------------------------------------------
# 2. Compliance dimension registry evidence
# ---------------------------------------------------------------------------

class TestComplianceRegistryEvidence:
    def test_compliance_dim_has_registry_evidence_for_pii_r6(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 10_000_000, "uses_pii": True},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R6", "privacy", "high")]},
            graph_payload=None,
            company_id=COMPANY,
        )
        comp = next((d for d in result.dimensions if d.id == "compliance"), None)
        assert comp is not None
        assert len(comp.evidence) > 0

    def test_compliance_dim_evidence_references_r6(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 10_000_000, "uses_pii": True},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R6", "privacy", "high")]},
            graph_payload=None,
            company_id=COMPANY,
        )
        comp = next(d for d in result.dimensions if d.id == "compliance")
        ev_ids = [e.ref.get("id", "") for e in comp.evidence]
        assert any("r6" in eid for eid in ev_ids)


# ---------------------------------------------------------------------------
# 3. Strategic dimension registry evidence
# ---------------------------------------------------------------------------

class TestStrategicRegistryEvidence:
    def _make_graph_with_support(self, goal_label: str = "G3") -> dict:
        return {
            "nodes": [{"id": goal_label, "type": "Goal", "label": "운영비용 효율화"}],
            "edges": [{"source": "decision_1", "target": goal_label, "relation": "supports_goal"}],
        }

    def test_strategic_dim_has_goal_registry_evidence(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 10_000_000, "goals": []},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": []},
            graph_payload=self._make_graph_with_support("G3"),
            company_id=COMPANY,
        )
        strat = next((d for d in result.dimensions if d.id == "strategic"), None)
        assert strat is not None
        assert len(strat.evidence) > 0

    def test_strategic_dim_evidence_includes_goal_source(self):
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 10_000_000, "goals": []},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": []},
            graph_payload=self._make_graph_with_support("G3"),
            company_id=COMPANY,
        )
        strat = next(d for d in result.dimensions if d.id == "strategic")
        sources = {e.source for e in strat.evidence}
        assert "내부 전략 문서" in sources


# ---------------------------------------------------------------------------
# 4. Safety: unknown company / missing registry
# ---------------------------------------------------------------------------

class TestRegistryFallbackSafety:
    def test_unknown_company_id_does_not_crash(self):
        svc = RiskScoringService()
        # Should not raise, just return no registry evidence
        result = svc.score(
            decision_payload={"cost": 200_000_000},
            company_payload=_NEXUS_COMPANY,
            governance_result={"triggered_rules": [_make_triggered_rule("R1", "financial")]},
            graph_payload=None,
            company_id="nonexistent_company_xyz",
        )
        fin = next((d for d in result.dimensions if d.id == "financial"), None)
        assert fin is not None
        assert fin.evidence == []

    def test_unknown_rule_id_does_not_crash(self):
        ev = ers.get_policy_evidence(COMPANY, "R_UNKNOWN_XYZ")
        assert ev is None  # safe, no crash

    def test_fetch_registry_evidence_no_company_id_returns_empty(self):
        result = _fetch_registry_evidence(None, rule_ids=["R1"])
        assert result == []


# ---------------------------------------------------------------------------
# 5. Normalizer: triggered rules carry policy evidence
# ---------------------------------------------------------------------------

class TestNormalizerRuleEvidence:
    def _build_record(self, triggered_rules):
        """Build a minimal DecisionRecord mock for normalizer testing."""
        from app.repositories.decision_store import DecisionRecord
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        record = DecisionRecord(
            decision_id="test-001",
            company_id=COMPANY,
            status="complete",
            input_text="test",
            created_at=now,
            updated_at=now,
            lang="ko",
        )
        record.governance = {
            "governance_status": "review_required",
            "requires_human_review": True,
            "flags": [],
            "triggered_rules": triggered_rules,
            "approval_chain": [],
        }
        return record

    def test_triggered_rule_has_policy_evidence(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record([
            _make_triggered_rule("R1", "financial")
        ])
        payload = build_console_payload(record)
        assert payload.governance is not None
        triggered = payload.governance.triggered_rules
        assert len(triggered) == 1
        assert triggered[0].evidence is not None
        assert len(triggered[0].evidence) == 1
        ev = triggered[0].evidence[0]
        assert ev["category"] == "policy"
        assert ev["metadata"]["ruleId"] == "R1"

    def test_triggered_rule_evidence_has_required_fields(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record([_make_triggered_rule("R6", "privacy")])
        payload = build_console_payload(record)
        ev = payload.governance.triggered_rules[0].evidence[0]
        for field in ("id", "category", "titleKo", "documentNameKo", "citationKo"):
            assert field in ev, f"Missing field '{field}' in rule evidence"

    def test_unknown_rule_id_evidence_is_none(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record([_make_triggered_rule("R99", "financial")])
        payload = build_console_payload(record)
        # Should not crash; evidence should be None
        assert payload.governance.triggered_rules[0].evidence is None

    def test_passed_rules_have_no_evidence(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record([])
        payload = build_console_payload(record)
        # all_rules includes passed rules — they should have no evidence attached
        for rule in payload.governance.all_rules:
            assert rule.evidence is None


# ---------------------------------------------------------------------------
# 6. Normalizer: approval chain carries authority evidence
# ---------------------------------------------------------------------------

class TestNormalizerApprovalEvidence:
    def _build_record_with_chain(self, approval_chain):
        from app.repositories.decision_store import DecisionRecord
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        record = DecisionRecord(
            decision_id="test-002",
            company_id=COMPANY,
            status="complete",
            input_text="test",
            created_at=now,
            updated_at=now,
            lang="ko",
        )
        record.governance = {
            "governance_status": "review_required",
            "requires_human_review": True,
            "flags": [],
            "triggered_rules": [],
            "approval_chain": approval_chain,
        }
        return record

    def test_cfo_approval_step_has_authority_evidence(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record_with_chain([
            {"role": "CFO", "source_rule_id": "R1", "rule_action": "require_approval"}
        ])
        payload = build_console_payload(record)
        chain = payload.governance.approval_chain
        assert len(chain) == 1
        assert chain[0].evidence is not None
        assert chain[0].evidence["metadata"]["roleKey"] == "CFO"

    def test_approval_step_evidence_has_authority_summary(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record_with_chain([
            {"role": "준법감시인", "source_rule_id": "R2", "rule_action": "require_review"}
        ])
        payload = build_console_payload(record)
        ev = payload.governance.approval_chain[0].evidence
        assert ev is not None
        assert ev["summaryKo"]
        assert ev["category"] == "approval"

    def test_unknown_role_approval_evidence_is_none(self):
        from app.routers.normalizers import build_console_payload
        record = self._build_record_with_chain([
            {"role": "알수없는역할", "rule_action": "require_approval"}
        ])
        payload = build_console_payload(record)
        assert payload.governance.approval_chain[0].evidence is None


# ---------------------------------------------------------------------------
# 7. Top-level governance_evidence block
# ---------------------------------------------------------------------------

class TestGovernanceEvidenceBlock:
    def _complete_record(self):
        from app.repositories.decision_store import DecisionRecord
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        record = DecisionRecord(
            decision_id="test-003",
            company_id=COMPANY,
            status="complete",
            input_text="test",
            created_at=now,
            updated_at=now,
            lang="ko",
        )
        record.governance = {
            "governance_status": "review_required",
            "requires_human_review": True,
            "flags": [],
            "triggered_rules": [_make_triggered_rule("R1", "financial")],
            "approval_chain": [{"role": "CFO", "rule_action": "require_approval"}],
        }
        record.decision = {"cost": 200_000_000, "goals": []}
        return record

    def test_governance_evidence_is_present(self):
        from app.routers.normalizers import build_console_payload
        payload = build_console_payload(self._complete_record())
        assert payload.governance_evidence is not None

    def test_governance_evidence_has_five_categories(self):
        from app.routers.normalizers import build_console_payload
        payload = build_console_payload(self._complete_record())
        ge = payload.governance_evidence
        assert "policyEvidence" in ge
        assert "complianceEvidence" in ge
        assert "strategyEvidence" in ge
        assert "financialEvidence" in ge
        assert "approvalEvidence" in ge

    def test_policy_evidence_matches_triggered_rule(self):
        from app.routers.normalizers import build_console_payload
        payload = build_console_payload(self._complete_record())
        policy_ev = payload.governance_evidence["policyEvidence"]
        assert len(policy_ev) == 1
        assert policy_ev[0]["metadata"]["ruleId"] == "R1"

    def test_approval_evidence_matches_chain_role(self):
        from app.routers.normalizers import build_console_payload
        payload = build_console_payload(self._complete_record())
        approval_ev = payload.governance_evidence["approvalEvidence"]
        assert len(approval_ev) == 1
        assert approval_ev[0]["metadata"]["roleKey"] == "CFO"

    def test_no_duplicate_policy_evidence(self):
        from app.routers.normalizers import build_console_payload
        record = self._complete_record()
        # Add same rule twice in triggered_rules
        record.governance["triggered_rules"] = [
            _make_triggered_rule("R1", "financial"),
            _make_triggered_rule("R1", "financial"),
        ]
        payload = build_console_payload(record)
        policy_ev = payload.governance_evidence["policyEvidence"]
        ids = [e["id"] for e in policy_ev]
        assert len(ids) == len(set(ids)), "Duplicate policy evidence IDs found"

    def test_governance_evidence_none_when_no_governance(self):
        from app.routers.normalizers import build_console_payload
        from app.repositories.decision_store import DecisionRecord
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        record = DecisionRecord(
            decision_id="test-004",
            company_id=COMPANY,
            status="processing",
            input_text="test",
            created_at=now,
            updated_at=now,
            lang="ko",
        )
        payload = build_console_payload(record)
        assert payload.governance_evidence is None
