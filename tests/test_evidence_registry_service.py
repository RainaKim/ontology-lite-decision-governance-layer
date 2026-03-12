"""
Tests for app/services/evidence_registry_service.py

Covers:
1. Registry loads successfully for nexus_dynamics
2. Policy evidence returned for R1
3. Strategy evidence returned for G3
4. Approval evidence returned for CFO (via roleKey, Korean name, English name)
5. Financial evidence assembly when cost is present / absent / above threshold
6. Unknown rule_id / goal_id handled safely
7. Cache works without duplicate disk reads
8. assemble_governance_evidence returns all four categories
9. Role resolution is data-driven (no hardcoded aliases in service)
"""

import pytest

import app.services.evidence_registry_service as svc

COMPANY = "nexus_dynamics"


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure each test starts with a clean cache."""
    svc._clear_cache()
    yield
    svc._clear_cache()


# ── 1. Registry loads ─────────────────────────────────────────────────────────

class TestRegistryLoad:
    def test_loads_nexus_registry(self):
        registry = svc.load_company_registry(COMPANY)
        assert registry["index"]["companyId"] == COMPANY
        assert "policies" in registry
        assert "strategy" in registry
        assert "budget" in registry
        assert "approvals" in registry
        assert "_role_alias_table" in registry

    def test_role_alias_table_is_populated(self):
        registry = svc.load_company_registry(COMPANY)
        table = registry["_role_alias_table"]
        assert len(table) > 0
        # Every value must be a known roleKey
        known_keys = {"CEO", "CFO", "CCO", "CISO", "INTERNAL_AUDIT_DIRECTOR", "HR_MANAGER", "FINANCE_MANAGER"}
        for role_key in table.values():
            assert role_key in known_keys

    def test_missing_company_raises(self):
        with pytest.raises(FileNotFoundError, match="Evidence registry not found"):
            svc.load_company_registry("nonexistent_company_xyz")


# ── 2. Policy evidence ────────────────────────────────────────────────────────

class TestPolicyEvidence:
    def test_r1_returns_evidence(self):
        ev = svc.get_policy_evidence(COMPANY, "R1")
        assert ev is not None
        assert ev["id"] == "policy_r1"
        assert ev["category"] == "policy"
        assert ev["metadata"]["ruleId"] == "R1"

    def test_r1_has_required_fields(self):
        ev = svc.get_policy_evidence(COMPANY, "R1")
        for field in ("titleKo", "titleEn", "documentNameKo", "documentNameEn",
                      "summaryKo", "summaryEn", "citationKo", "citationEn"):
            assert ev[field], f"Field '{field}' is empty"

    def test_r1_has_financial_tag(self):
        ev = svc.get_policy_evidence(COMPANY, "R1")
        assert "financial" in ev["metadata"]["tags"]

    def test_all_rules_r1_through_r8(self):
        for rule_id in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8"):
            ev = svc.get_policy_evidence(COMPANY, rule_id)
            assert ev is not None, f"Missing policy evidence for {rule_id}"

    def test_unknown_rule_returns_none(self):
        ev = svc.get_policy_evidence(COMPANY, "R99")
        assert ev is None

    def test_assemble_rule_evidence_multiple(self):
        result = svc.assemble_rule_evidence(COMPANY, ["R1", "R6"])
        assert len(result) == 2
        ids = {e["metadata"]["ruleId"] for e in result}
        assert ids == {"R1", "R6"}

    def test_assemble_rule_evidence_skips_unknown(self):
        result = svc.assemble_rule_evidence(COMPANY, ["R1", "RXXX", "R2"])
        assert len(result) == 2


# ── 3. Strategy evidence ──────────────────────────────────────────────────────

class TestStrategyEvidence:
    def test_g3_returns_evidence(self):
        ev = svc.get_strategy_evidence(COMPANY, "G3")
        assert ev is not None
        assert ev["id"] == "strategy_g3"
        assert ev["category"] == "strategy"
        assert ev["metadata"]["goalId"] == "G3"

    def test_g3_has_kpis(self):
        ev = svc.get_strategy_evidence(COMPANY, "G3")
        kpis = ev["metadata"]["kpis"]
        assert len(kpis) >= 2
        kpi_ids = {k["kpiId"] for k in kpis}
        assert "K5" in kpi_ids
        assert "K6" in kpi_ids

    def test_g3_has_target_summary(self):
        ev = svc.get_strategy_evidence(COMPANY, "G3")
        assert ev["metadata"]["targetSummaryKo"]
        assert ev["metadata"]["targetSummaryEn"]

    def test_all_goals_g1_through_g3(self):
        for goal_id in ("G1", "G2", "G3"):
            ev = svc.get_strategy_evidence(COMPANY, goal_id)
            assert ev is not None, f"Missing strategy evidence for {goal_id}"

    def test_unknown_goal_returns_none(self):
        ev = svc.get_strategy_evidence(COMPANY, "G99")
        assert ev is None

    def test_assemble_goal_evidence_skips_unknown(self):
        result = svc.assemble_goal_evidence(COMPANY, ["G1", "GXXX", "G3"])
        assert len(result) == 2


# ── 4. Approval evidence ──────────────────────────────────────────────────────

class TestApprovalEvidence:
    def test_cfo_by_role_key(self):
        ev = svc.get_approval_evidence(COMPANY, "CFO")
        assert ev is not None
        assert ev["metadata"]["roleKey"] == "CFO"

    def test_cfo_by_korean_name(self):
        ev = svc.get_approval_evidence(COMPANY, "최고재무책임자 (CFO)")
        assert ev is not None
        assert ev["metadata"]["roleKey"] == "CFO"

    def test_cfo_by_english_name(self):
        ev = svc.get_approval_evidence(COMPANY, "Chief Financial Officer (CFO)")
        assert ev is not None
        assert ev["metadata"]["roleKey"] == "CFO"

    def test_cco_by_korean_only_name(self):
        # 준법감시인 has no English abbreviation in the role name
        ev = svc.get_approval_evidence(COMPANY, "준법감시인")
        assert ev is not None
        assert ev["metadata"]["roleKey"] == "CCO"

    def test_ciso_by_korean_name(self):
        ev = svc.get_approval_evidence(COMPANY, "정보보호최고책임자")
        assert ev is not None
        assert ev["metadata"]["roleKey"] == "CISO"

    def test_hr_manager_by_korean(self):
        ev = svc.get_approval_evidence(COMPANY, "인사팀장")
        assert ev is not None
        assert ev["metadata"]["roleKey"] == "HR_MANAGER"

    def test_unknown_role_returns_none(self):
        ev = svc.get_approval_evidence(COMPANY, "알수없는역할")
        assert ev is None

    def test_approval_has_authority_summary(self):
        ev = svc.get_approval_evidence(COMPANY, "CFO")
        assert ev["summaryKo"]
        assert ev["summaryEn"]

    def test_approval_has_level(self):
        ceo = svc.get_approval_evidence(COMPANY, "CEO")
        cfo = svc.get_approval_evidence(COMPANY, "CFO")
        assert ceo["metadata"]["level"] > cfo["metadata"]["level"]

    def test_assemble_approval_evidence_deduplicates(self):
        chain = [
            {"approver_role": "CFO"},
            {"approver_role": "CFO"},    # duplicate
            {"approver_role": "CEO"},
        ]
        result = svc.assemble_approval_evidence(COMPANY, chain)
        assert len(result) == 2
        role_keys = {e["metadata"]["roleKey"] for e in result}
        assert role_keys == {"CFO", "CEO"}

    def test_assemble_approval_evidence_uses_role_field(self):
        chain = [{"role": "준법감시인"}]
        result = svc.assemble_approval_evidence(COMPANY, chain)
        assert len(result) == 1
        assert result[0]["metadata"]["roleKey"] == "CCO"

    def test_assemble_approval_evidence_uses_title_field(self):
        chain = [{"title": "인사팀장"}]
        result = svc.assemble_approval_evidence(COMPANY, chain)
        assert len(result) == 1
        assert result[0]["metadata"]["roleKey"] == "HR_MANAGER"


# ── 5. Financial evidence ─────────────────────────────────────────────────────

class TestFinancialEvidence:
    def test_no_cost_returns_empty(self):
        result = svc.assemble_financial_evidence(COMPANY, {})
        assert result == []

    def test_cost_below_threshold_returns_dept_and_opex(self):
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 10_000_000})
        source_ids = {e["metadata"]["sourceId"] for e in result}
        assert "BS_DEPT_BUDGET" in source_ids
        assert "BS_OPEX_BASELINE" in source_ids
        assert "BS_SPEND_AUTHORITY" not in source_ids

    def test_cost_above_threshold_includes_spend_authority(self):
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 100_000_000})
        source_ids = {e["metadata"]["sourceId"] for e in result}
        assert "BS_SPEND_AUTHORITY" in source_ids

    def test_spend_authority_metadata_has_approver_role(self):
        # 100M > 내부감사실장 limit (200M)? No, 100M < 200M. So highest exceeded = 재무팀장 (50M)
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 100_000_000})
        authority = next(e for e in result if e["metadata"]["sourceId"] == "BS_SPEND_AUTHORITY")
        assert authority["metadata"]["approver_role"] == "재무팀장"
        assert authority["metadata"]["max_budget_authority"] == 50_000_000
        assert authority["metadata"]["verdict"] == "초과"

    def test_spend_authority_250m_exceeds_internal_audit(self):
        # 250M > 내부감사실장 limit (200M) → highest exceeded tier
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 250_000_000})
        authority = next(e for e in result if e["metadata"]["sourceId"] == "BS_SPEND_AUTHORITY")
        assert authority["metadata"]["approver_role"] == "내부감사실장"
        assert authority["metadata"]["max_budget_authority"] == 200_000_000

    def test_cost_above_board_threshold(self):
        # 2B > CFO limit (1B) → highest exceeded tier = CFO
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 2_000_000_000})
        authority = next(e for e in result if e["metadata"]["sourceId"] == "BS_SPEND_AUTHORITY")
        assert authority["metadata"]["approver_role"] == "최고재무책임자 (CFO)"
        assert authority["metadata"]["max_budget_authority"] == 1_000_000_000

    def test_cost_metadata_attached_to_dept_budget(self):
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 50_000_000})
        dept = next(e for e in result if e["metadata"]["sourceId"] == "BS_DEPT_BUDGET")
        assert dept["metadata"]["cost"] == 50_000_000

    def test_verdict_exceeds_budget(self):
        result = svc.assemble_financial_evidence(
            COMPANY, {"cost": 250_000_000, "remaining_budget": 50_000_000, "department": "마케팅팀"}
        )
        dept = next(e for e in result if e["metadata"]["sourceId"] == "BS_DEPT_BUDGET")
        assert dept["metadata"]["verdict"] == "예산 초과"
        assert dept["metadata"]["verdictEn"] == "over budget"
        assert dept["metadata"]["remaining_budget"] == 50_000_000
        assert dept["metadata"]["department"] == "마케팅팀"

    def test_verdict_within_budget(self):
        result = svc.assemble_financial_evidence(
            COMPANY, {"cost": 30_000_000, "remaining_budget": 50_000_000, "department": "마케팅팀"}
        )
        dept = next(e for e in result if e["metadata"]["sourceId"] == "BS_DEPT_BUDGET")
        assert dept["metadata"]["verdict"] == "예산 내 처리 가능"
        assert dept["metadata"]["verdictEn"] == "within budget"

    def test_verdict_none_when_remaining_budget_unknown(self):
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 100_000_000})
        dept = next(e for e in result if e["metadata"]["sourceId"] == "BS_DEPT_BUDGET")
        assert "verdict" not in dept["metadata"]

    def test_citation_rendered_when_all_placeholders_filled(self):
        result = svc.assemble_financial_evidence(
            COMPANY, {"cost": 250_000_000, "remaining_budget": 50_000_000, "department": "마케팅팀"}
        )
        dept = next(e for e in result if e["metadata"]["sourceId"] == "BS_DEPT_BUDGET")
        # KO template should be fully rendered (no {{...}})
        assert "{{" not in dept["citationKo"]
        assert "250,000,000" in dept["citationKo"]
        assert "50,000,000" in dept["citationKo"]
        assert "예산 초과" in dept["citationKo"]

    def test_citation_falls_back_to_summary_when_placeholders_missing(self):
        result = svc.assemble_financial_evidence(COMPANY, {"cost": 100_000_000})
        dept = next(e for e in result if e["metadata"]["sourceId"] == "BS_DEPT_BUDGET")
        # Without remaining_budget/department/verdict, template can't render → falls back to summaryKo
        assert dept["citationKo"] == dept["summaryKo"]

    def test_get_budget_evidence_specific_source(self):
        result = svc.get_budget_evidence(COMPANY, "BS_SPEND_AUTHORITY")
        assert len(result) == 1
        assert result[0]["metadata"]["sourceId"] == "BS_SPEND_AUTHORITY"

    def test_get_budget_evidence_all_sources(self):
        result = svc.get_budget_evidence(COMPANY)
        assert len(result) == 4  # all 4 budget sources


# ── 6. Normalisation shape ────────────────────────────────────────────────────

class TestNormalisationShape:
    REQUIRED_FIELDS = (
        "id", "category", "titleKo", "titleEn", "sourceType",
        "documentNameKo", "documentNameEn",
        "summaryKo", "summaryEn", "citationKo", "citationEn", "metadata",
    )

    def test_policy_shape(self):
        ev = svc.get_policy_evidence(COMPANY, "R1")
        for f in self.REQUIRED_FIELDS:
            assert f in ev, f"Missing field '{f}' in policy evidence"

    def test_strategy_shape(self):
        ev = svc.get_strategy_evidence(COMPANY, "G1")
        for f in self.REQUIRED_FIELDS:
            assert f in ev, f"Missing field '{f}' in strategy evidence"

    def test_approval_shape(self):
        ev = svc.get_approval_evidence(COMPANY, "CEO")
        for f in self.REQUIRED_FIELDS:
            assert f in ev, f"Missing field '{f}' in approval evidence"

    def test_budget_shape(self):
        result = svc.get_budget_evidence(COMPANY, "BS_DEPT_BUDGET")
        ev = result[0]
        for f in self.REQUIRED_FIELDS:
            assert f in ev, f"Missing field '{f}' in budget evidence"

    def test_category_values_are_correct(self):
        assert svc.get_policy_evidence(COMPANY, "R2")["category"] == "policy"
        assert svc.get_strategy_evidence(COMPANY, "G2")["category"] == "strategy"
        assert svc.get_approval_evidence(COMPANY, "CEO")["category"] == "approval"
        budget = svc.get_budget_evidence(COMPANY, "BS_DEPT_BUDGET")[0]
        assert budget["category"] == "financial"


# ── 7. Cache ──────────────────────────────────────────────────────────────────

class TestCache:
    def test_second_load_uses_cache(self, monkeypatch):
        load_count = 0
        original_load = svc._load_json

        def counting_load(path):
            nonlocal load_count
            load_count += 1
            return original_load(path)

        monkeypatch.setattr(svc, "_load_json", counting_load)

        svc.load_company_registry(COMPANY)
        calls_after_first = load_count

        # Second call — should NOT call _load_json again
        svc.load_company_registry(COMPANY)
        assert load_count == calls_after_first, "Cache miss: _load_json called again on second load"

    def test_clear_cache_forces_reload(self, monkeypatch):
        load_count = 0
        original_load = svc._load_json

        def counting_load(path):
            nonlocal load_count
            load_count += 1
            return original_load(path)

        monkeypatch.setattr(svc, "_load_json", counting_load)

        svc.load_company_registry(COMPANY)
        calls_after_first = load_count

        svc._clear_cache(COMPANY)
        svc.load_company_registry(COMPANY)
        assert load_count > calls_after_first, "Expected reload after cache clear"


# ── 8. assemble_governance_evidence ──────────────────────────────────────────

class TestAssembleGovernanceEvidence:
    def test_returns_all_five_categories(self):
        result = svc.assemble_governance_evidence(
            company_id=COMPANY,
            triggered_rule_ids=["R1", "R6"],
            goal_ids=["G3"],
            approval_chain=[{"approver_role": "CFO"}, {"approver_role": "CEO"}],
            decision_payload={"cost": 800_000_000},
        )
        assert "policyEvidence" in result
        assert "complianceEvidence" in result
        assert "strategyEvidence" in result
        assert "financialEvidence" in result
        assert "approvalEvidence" in result

    def test_policy_evidence_count(self):
        result = svc.assemble_governance_evidence(
            company_id=COMPANY,
            triggered_rule_ids=["R1", "R6"],
            goal_ids=[],
            approval_chain=[],
            decision_payload={},
        )
        # R1 is financial policy → policyEvidence; R6 is privacy → complianceEvidence
        assert len(result["policyEvidence"]) == 1
        assert len(result["complianceEvidence"]) == 1

    def test_strategy_evidence_count(self):
        result = svc.assemble_governance_evidence(
            company_id=COMPANY,
            triggered_rule_ids=[],
            goal_ids=["G1", "G3"],
            approval_chain=[],
            decision_payload={},
        )
        assert len(result["strategyEvidence"]) == 2

    def test_empty_inputs_return_empty_lists(self):
        result = svc.assemble_governance_evidence(
            company_id=COMPANY,
            triggered_rule_ids=[],
            goal_ids=[],
            approval_chain=[],
            decision_payload={},
        )
        assert result["policyEvidence"] == []
        assert result["strategyEvidence"] == []
        assert result["financialEvidence"] == []
        assert result["approvalEvidence"] == []
