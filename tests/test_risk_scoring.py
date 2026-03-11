"""
Unit tests for RiskScoringService.

Covers:
  1. Marketing overspend (finance company) — cost 250M, remaining 50M
  2. Healthcare PII access — uses_pii=True with triggered HIPAA compliance rule
  3. Missing baseline — no remaining_budget; scoring still works, confidence reduced
  4. UI-readability contract:
     - No forbidden substrings in evidence.label
     - signals[0] is always SUMMARY
     - signals length <= 4 (1 summary + max 3 details)
     - Evidence labels are Korean-readable
     - Deterministic ordering

Run:
    python -m pytest tests/test_risk_scoring.py -v
"""

import re
import pytest
from app.services.risk_scoring_service import RiskScoringService, _band


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HANGUL_RE = re.compile(r"[가-힣]")

def _has_korean(text: str) -> bool:
    """Heuristic: at least one Hangul character OR whitespace."""
    return bool(_HANGUL_RE.search(text)) or " " in text

_FORBIDDEN_SUBSTRINGS = [
    "field:",
    "used_for:",
    "thresholds_applied",
    "note:",
    "rule_id:",
]

def _collect_all_evidence_labels(result) -> list[str]:
    """Collect every evidence.label across all signals in all dimensions."""
    labels = []
    for dim in result.dimensions:
        for sig in dim.signals:
            for ev in sig.evidence:
                if ev.label is not None:
                    labels.append(ev.label)
    return labels


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def service():
    return RiskScoringService()


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
            "description": "벤더 합리화 및 프로세스 자동화를 통해 운영비용 10% 절감",
            "priority": "high",
            "kpis": [
                {"kpi_id": "K5", "name": "운영비 절감률", "target": "전년 대비 10% 절감"},
            ],
        },
        {
            "goal_id": "G1",
            "name": "글로벌 매출 확대",
            "description": "신규 시장 진출을 통해 매출 25% 성장",
            "priority": "high",
            "kpis": [],
        },
    ],
}

HEALTHCARE_COMPANY = {
    "company": {"industry": "헬스케어", "name": "Mayo Central Hospital"},
    "risk_tolerance": {
        "financial": {
            "unbudgeted_spend_threshold": 100_000,
            "high_cost_threshold": 500_000,
            "critical_cost_threshold": 5_000_000,
        }
    },
    "strategic_goals": [
        {
            "goal_id": "G1",
            "name": "환자 안전 우수성",
            "description": "환자 안전 및 임상 품질 향상",
            "priority": "critical",
            "kpis": [],
        },
        {
            "goal_id": "G2",
            "name": "규제 및 데이터 준수",
            "description": "HIPAA 및 개인정보 규제 완전 준수",
            "priority": "critical",
            "kpis": [],
        },
    ],
}


# ---------------------------------------------------------------------------
# Scenario 1: Marketing overspend
# ---------------------------------------------------------------------------

class TestMarketingOverspend:
    DECISION = {
        "decision_statement": "마케팅 캠페인 예산 2.5억 집행 결정",
        "cost": 250_000_000,
        "remaining_budget": 50_000_000,
        "uses_pii": False,
        "involves_compliance_risk": False,
        "strategic_impact": "high",
        "goals": [{"description": "글로벌 매출 확대를 위한 마케팅 투자"}],
        "kpis": [],
        "risks": [],
    }
    GOVERNANCE = {
        "triggered_rules": [
            {
                "rule_id": "R1",
                "name": "자본적 지출 승인",
                "rule_type": "financial",
                "type": "financial",
                "status": "TRIGGERED",
                "consequence": {"action": "require_approval", "severity": "high"},
            }
        ]
    }

    def test_financial_dimension_exists(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        assert any(d.id == "financial" for d in result.dimensions)

    def test_financial_score_is_medium_plus(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        fin = next(d for d in result.dimensions if d.id == "financial")
        assert fin.score >= 50
        assert fin.band in ("MEDIUM", "HIGH", "CRITICAL")

    def test_overspend_ratio_signal_present_with_correct_value(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        fin = next(d for d in result.dimensions if d.id == "financial")
        # signals[0] is SUMMARY; look in signals[1..] for OVERSPEND_RATIO
        detail_signals = {s.id: s for s in fin.signals[1:]}
        assert "OVERSPEND_RATIO" in detail_signals, "OVERSPEND_RATIO detail signal must exist"
        assert abs(detail_signals["OVERSPEND_RATIO"].value - 5.0) < 0.01

    def test_aggregate_is_medium_plus(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        assert result.aggregate.score >= 40

    def test_result_serialises_cleanly(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        d = result.to_dict()
        assert "aggregate" in d and "dimensions" in d
        assert d["aggregate"]["band"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        for dim in d["dimensions"]:
            for sig in dim["signals"]:
                assert "id" in sig and "label" in sig and "value" in sig


# ---------------------------------------------------------------------------
# Scenario 2: Healthcare PII access
# ---------------------------------------------------------------------------

class TestHealthcarePII:
    DECISION = {
        "decision_statement": "환자 데이터를 외부 연구기관에 공유하는 결정",
        "cost": 50_000,
        "uses_pii": True,
        "involves_compliance_risk": True,
        "strategic_impact": "high",
        "goals": [],
        "kpis": [],
        "risks": [],
    }
    GOVERNANCE = {
        "triggered_rules": [
            {
                "rule_id": "R2",
                "name": "HIPAA 데이터 준수",
                "rule_type": "compliance",
                "type": "compliance",
                "status": "TRIGGERED",
                "consequence": {"action": "require_review", "severity": "critical"},
            }
        ]
    }

    def test_compliance_dimension_exists(self, service):
        result = service.score(self.DECISION, HEALTHCARE_COMPANY, self.GOVERNANCE, None)
        assert any(d.id == "compliance" for d in result.dimensions)

    def test_compliance_score_is_high(self, service):
        result = service.score(self.DECISION, HEALTHCARE_COMPANY, self.GOVERNANCE, None)
        comp = next(d for d in result.dimensions if d.id == "compliance")
        assert comp.score >= 70
        assert comp.band in ("HIGH", "CRITICAL")

    def test_pii_detected_signal_in_details(self, service):
        result = service.score(self.DECISION, HEALTHCARE_COMPANY, self.GOVERNANCE, None)
        comp = next(d for d in result.dimensions if d.id == "compliance")
        detail_ids = {s.id for s in comp.signals[1:]}
        assert "PII_DETECTED" in detail_ids

    def test_healthcare_weights_compliance_higher(self, service):
        finance_r = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        health_r  = service.score(self.DECISION, HEALTHCARE_COMPANY, self.GOVERNANCE, None)
        assert health_r.aggregate.score >= finance_r.aggregate.score - 5


# ---------------------------------------------------------------------------
# Scenario 3: Missing baseline
# ---------------------------------------------------------------------------

class TestMissingBaseline:
    DECISION = {
        "decision_statement": "벤더 합리화를 통해 운영비용 절감 추진",
        "cost": 300_000_000,
        "uses_pii": False,
        "involves_compliance_risk": False,
        "strategic_impact": "high",
        "goals": [{"description": "운영비용 절감 및 효율화"}],
        "kpis": [],
        "risks": [],
    }
    GOVERNANCE = {
        "triggered_rules": [
            {
                "rule_id": "R1",
                "name": "자본적 지출 승인",
                "rule_type": "financial",
                "type": "financial",
                "status": "TRIGGERED",
                "consequence": {"action": "require_approval", "severity": "high"},
            }
        ]
    }

    def test_scoring_completes(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        assert result is not None
        assert result.aggregate.score >= 0

    def test_confidence_reduced(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        assert result.aggregate.confidence <= 0.85

    def test_no_overspend_ratio_in_details(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        fin = next((d for d in result.dimensions if d.id == "financial"), None)
        if fin:
            detail_ids = {s.id for s in fin.signals[1:]}
            assert "OVERSPEND_RATIO" not in detail_ids

    def test_financial_score_non_zero(self, service):
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        fin = next((d for d in result.dimensions if d.id == "financial"), None)
        assert fin is not None and fin.score > 0

    def test_kpi_impact_estimate_low_confidence(self, service):
        graph_payload = {
            "nodes": [
                {"id": "d1", "type": "Decision", "label": "Cost Decision"},
                {"id": "G3", "type": "Goal", "label": "운영비용 효율화"},
            ],
            "edges": [{"source": "d1", "relation": "SUPPORTS_GOAL", "target": "G3"}],
        }
        result = service.score(self.DECISION, FINANCE_COMPANY, self.GOVERNANCE, graph_payload)
        strat = next((d for d in result.dimensions if d.id == "strategic"), None)
        if strat and strat.kpi_impact_estimate:
            assert strat.kpi_impact_estimate.get("confidence") in ("low", "very_low", "medium")


# ---------------------------------------------------------------------------
# Step 4 — UI-readability contract (all scenarios)
# ---------------------------------------------------------------------------

class TestUIReadabilityContract:
    """
    Asserts the output contract that the frontend depends on:
      - signals[0].id == "SUMMARY" for every dimension
      - signals length <= 4
      - No forbidden substrings in any evidence.label
      - Evidence labels are human-readable (Korean or whitespace)
      - Deterministic: two identical calls produce identical signal ordering
    """

    OVERSPEND_DECISION = {
        "cost": 250_000_000,
        "remaining_budget": 50_000_000,
        "uses_pii": True,
        "involves_compliance_risk": False,
        "goals": [],
        "kpis": [],
        "risks": [],
    }
    GOVERNANCE = {
        "triggered_rules": [
            {
                "rule_id": "R1",
                "name": "자본적 지출 승인",
                "rule_type": "financial",
                "type": "financial",
                "status": "TRIGGERED",
                "consequence": {"action": "require_approval", "severity": "high"},
            },
            {
                "rule_id": "R6",
                "name": "개인정보 및 보안 검토",
                "rule_type": "compliance",
                "type": "compliance",
                "status": "TRIGGERED",
                "consequence": {"action": "require_review", "severity": "high"},
            },
        ]
    }

    def test_summary_is_always_first(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for dim in result.dimensions:
            assert len(dim.signals) >= 1, f"Dimension {dim.id} has no signals"
            assert dim.signals[0].id == "SUMMARY", (
                f"Dimension {dim.id}: signals[0].id must be 'SUMMARY', "
                f"got '{dim.signals[0].id}'"
            )

    def test_signals_max_four(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for dim in result.dimensions:
            assert len(dim.signals) <= 4, (
                f"Dimension {dim.id}: expected <= 4 signals, got {len(dim.signals)}"
            )

    def test_no_forbidden_substrings_in_evidence_labels(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        labels = _collect_all_evidence_labels(result)
        for label in labels:
            for forbidden in _FORBIDDEN_SUBSTRINGS:
                assert forbidden not in label, (
                    f"Evidence label contains forbidden substring '{forbidden}': {label!r}"
                )

    def test_evidence_labels_are_human_readable(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        labels = _collect_all_evidence_labels(result)
        assert len(labels) > 0, "Expected at least one evidence label"
        for label in labels:
            assert _has_korean(label), (
                f"Evidence label is not human-readable Korean: {label!r}"
            )

    def test_summary_signal_has_severity_matching_band(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for dim in result.dimensions:
            summary = dim.signals[0]
            assert summary.severity == dim.band, (
                f"Dimension {dim.id}: SUMMARY.severity={summary.severity} "
                f"!= band={dim.band}"
            )

    def test_summary_signal_has_exactly_one_evidence(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for dim in result.dimensions:
            summary = dim.signals[0]
            assert len(summary.evidence) == 1, (
                f"Dimension {dim.id}: SUMMARY signal must have exactly 1 evidence item, "
                f"got {len(summary.evidence)}"
            )

    def test_detail_signals_max_two_evidence_each(self, service):
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for dim in result.dimensions:
            for sig in dim.signals[1:]:
                assert len(sig.evidence) <= 2, (
                    f"Dimension {dim.id}, signal {sig.id}: "
                    f"expected <= 2 evidence, got {len(sig.evidence)}"
                )

    def test_deterministic_ordering(self, service):
        """Same inputs → identical signal id sequence on every call."""
        r1 = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        r2 = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for d1, d2 in zip(r1.dimensions, r2.dimensions):
            ids1 = [s.id for s in d1.signals]
            ids2 = [s.id for s in d2.signals]
            assert ids1 == ids2, (
                f"Dimension {d1.id}: non-deterministic signal order {ids1} vs {ids2}"
            )

    def test_evidence_source_is_korean(self, service):
        """evidence.source should be a Korean provenance badge."""
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        for dim in result.dimensions:
            for sig in dim.signals:
                for ev in sig.evidence:
                    if ev.source is not None:
                        assert _has_korean(ev.source), (
                            f"Evidence source should be Korean: {ev.source!r}"
                        )

    def test_no_forbidden_substrings_in_serialised_dict(self, service):
        """Serialised to_dict must also be clean (no dev-facing strings in labels)."""
        result = service.score(self.OVERSPEND_DECISION, FINANCE_COMPANY, self.GOVERNANCE, None)
        d = result.to_dict()
        for dim in d["dimensions"]:
            for sig in dim["signals"]:
                for ev in sig.get("evidence", []):
                    label = ev.get("label", "") or ""
                    for forbidden in _FORBIDDEN_SUBSTRINGS:
                        assert forbidden not in label, (
                            f"Serialised evidence label contains '{forbidden}': {label!r}"
                        )


# ---------------------------------------------------------------------------
# Band mapping
# ---------------------------------------------------------------------------

class TestBandMapping:
    @pytest.mark.parametrize("score,expected", [
        (0, "LOW"), (39, "LOW"),
        (40, "MEDIUM"), (69, "MEDIUM"),
        (70, "HIGH"), (84, "HIGH"),
        (85, "CRITICAL"), (100, "CRITICAL"),
    ])
    def test_band_boundaries(self, score, expected):
        assert _band(score) == expected
