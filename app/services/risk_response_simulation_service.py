"""
Risk Response Simulation Service — Deterministic counterfactual scenario engine.

Generates 2-3 remediation scenarios from template config, re-evaluates each
scenario through the same governance + risk-scoring pipeline used for live
decisions, and returns structured before/after comparison.

Architecture rules:
- LLM never computes final scores or approval outcomes.
- All scores come from evaluate_governance() (use_nova=False) + RiskScoringService.score().
- Templates are config-driven (simulation_templates.json); no per-company if/else.
- Patch strategies are pure functions of decision payload + company context.
- Confidence is a deterministic heuristic, never a probabilistic model.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Nova proposer imported at module level so tests can patch it cleanly.
# boto3 is only touched inside _call_nova() — absent credentials are non-fatal.
from app.services.nova_scenario_proposer import propose_scenarios_with_nova  # noqa: E402
# ── Template config ────────────────────────────────────────────────────────────
_TEMPLATES_PATH = (
    Path(__file__).parent.parent / "demo_fixtures" / "simulation_templates.json"
)

# ── Confidence heuristics ─────────────────────────────────────────────────────
# Reflects scenario directness: direct spend cuts score highest; inferred
# process changes (goal mapping, compliance flag) score lower because they
# assume the organisational change is actually executed.
_CONFIDENCE: dict[str, float] = {
    "set_cost_to_remaining_budget": 0.90,   # direct, measurable
    "set_cost_to_high_threshold":   0.85,   # direct, threshold-driven
    "remove_pii_usage":             0.85,   # direct flag
    "defer_hiring":                 0.80,   # direct flag change
    "reduce_cost_by_half":          0.75,   # heuristic factor
    "clear_compliance_flag":        0.70,   # assumes process is actually added
    "inject_goal_alignment":        0.65,   # inferred alignment benefit
}

# ── Band ordering ─────────────────────────────────────────────────────────────
_BANDS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]




def _derive_status(gov_dict: dict) -> str:
    """Derive governance_status from re-evaluated governance dict."""
    if gov_dict.get("requires_human_review"):
        return "review_required"
    chain = gov_dict.get("approval_chain") or []
    triggered = [
        r for r in gov_dict.get("triggered_rules", [])
        if r.get("status", "").upper() == "TRIGGERED"
    ]
    if chain or triggered:
        return "needs_approval"
    return "approved"


# ── Main service ──────────────────────────────────────────────────────────────

class RiskResponseSimulationService:
    """Deterministic risk-response simulation — generates and evaluates remediation scenarios."""

    _templates: Optional[list[dict]] = None

    @classmethod
    def _load_templates(cls) -> list[dict]:
        if cls._templates is None:
            cls._templates = json.loads(_TEMPLATES_PATH.read_text())["templates"]
        return cls._templates

    # ── Public entry point ────────────────────────────────────────────────────

    def simulate(
        self,
        decision_payload: dict,
        governance_result: dict,
        risk_scoring: dict,
        company_payload: dict,
        company_id: Optional[str] = None,
        lang: str = "ko",
    ) -> dict:
        """Run simulation and return payload dict ready for storage."""
        baseline_outcome = self._build_outcome(governance_result, risk_scoring, company_id, lang=lang)

        issue_types = self._classify_issues(decision_payload, governance_result, risk_scoring)
        if not issue_types:
            logger.info("[simulation] No qualifying issues — no scenarios generated")
            return {"baseline": baseline_outcome, "scenarios": [], "generatedAt": _now_iso()}

        # ── Nova scenario proposals (non-fatal) ──────────────────────────────
        # Nova proposes which templates to apply; all evaluation remains
        # deterministic (governance + risk scoring are re-run, not estimated).
        nova_proposals = propose_scenarios_with_nova(
            decision=decision_payload,
            governance_result=governance_result,
            risk_scoring=risk_scoring,
        )

        if nova_proposals:
            candidates = self._proposals_to_candidates(
                nova_proposals, decision_payload, company_payload
            )
            if not candidates:
                # All Nova proposals failed validation / patch building → fall back
                logger.warning(
                    "[simulation] Nova output invalid — using fallback scenarios"
                )
                candidates = self._generate_candidates(
                    decision_payload, governance_result, risk_scoring,
                    company_payload, issue_types
                )
        else:
            candidates = self._generate_candidates(
                decision_payload, governance_result, risk_scoring, company_payload, issue_types
            )

        # Evaluate each candidate: re-run governance + risk scoring
        evaluated: list[dict] = []
        for cand in candidates:
            try:
                result = self._evaluate_scenario(
                    decision_payload, cand, company_payload, company_id, lang=lang
                )
                if result is not None:
                    evaluated.append(result)
            except Exception as exc:
                logger.warning(
                    f"[simulation] Scenario '{cand.get('scenarioId')}' failed: {exc}"
                )

        evaluated = evaluated[:3]

        # Finalise: compute deltas, resolved/remaining issues (needs baseline_risk)
        self._finalise(evaluated, baseline_outcome, risk_scoring)

        # Mark the single best scenario as recommended
        self._mark_recommended(evaluated, baseline_outcome)

        return {"baseline": baseline_outcome, "scenarios": evaluated, "generatedAt": _now_iso()}

    # ── Outcome builder ───────────────────────────────────────────────────────

    def _build_outcome(
        self,
        gov_dict: dict,
        risk_dict: dict,
        company_id: Optional[str] = None,
        lang: str = "ko",
    ) -> dict:
        agg = (risk_dict or {}).get("aggregate", {})
        triggered = [
            r for r in (gov_dict or {}).get("triggered_rules", [])
            if r.get("status", "").upper() == "TRIGGERED"
        ]
        chain = (gov_dict or {}).get("approval_chain", [])
        status = (gov_dict or {}).get("governance_status") or _derive_status(gov_dict or {})

        # Build source_rule_id → EN approver_role and EN rule name maps from EN company data
        _en_approver_by_rule: dict[str, str] = {}
        _en_name_by_rule: dict[str, str] = {}
        if company_id:
            try:
                from app.services import company_service
                _en_data = company_service.get_company_data(company_id, lang="en")
                if _en_data:
                    for _r in _en_data.get("governance_rules", []):
                        _rid = _r.get("rule_id")
                        _role_en = (_r.get("consequence") or {}).get("approver_role")
                        _name_en = _r.get("name") or ""
                        if _rid:
                            if _role_en:
                                _en_approver_by_rule[_rid] = _role_en
                            if _name_en:
                                _en_name_by_rule[_rid] = _name_en
            except Exception:
                pass

        required_ko: list[str] = []
        required_en: list[str] = []
        for s in chain:
            if not s:
                continue
            role_ko = s.get("role") or s.get("approver_role", "")
            required_ko.append(role_ko)
            src = s.get("source_rule_id")
            role_en = _en_approver_by_rule.get(src, role_ko) if src else role_ko
            required_en.append(role_en)

        # Build rule_id → name map for human-readable issue labels
        # Use EN company data names when lang="en"; fall back to governance result names
        triggered_rule_names: dict[str, str] = {}
        for r in triggered:
            rid = r.get("rule_id")
            if not rid:
                continue
            if lang == "en" and rid in _en_name_by_rule:
                triggered_rule_names[rid] = _en_name_by_rule[rid]
            else:
                name = r.get("name") or ""
                triggered_rule_names[rid] = name if name else rid

        return {
            "aggregateRiskScore": int(agg.get("score", 0)),
            "band": agg.get("band", "LOW"),
            "status": status,
            "requiredApprovals": required_ko,
            "requiredApprovalsEn": required_en,
            "triggeredRuleIds": list(triggered_rule_names.keys()),
            "triggeredRuleNames": triggered_rule_names,
        }

    # ── Issue classification ──────────────────────────────────────────────────

    def _classify_issues(
        self, decision_payload: dict, governance_result: dict, risk_scoring: dict
    ) -> set[str]:
        issues: set[str] = set()
        dims = {d["id"]: d for d in (risk_scoring or {}).get("dimensions", [])}
        triggered = [
            r for r in (governance_result or {}).get("triggered_rules", [])
            if r.get("status", "").upper() == "TRIGGERED"
        ]
        triggered_types = {
            (r.get("rule_type") or r.get("type") or "").lower() for r in triggered
        }

        cost = decision_payload.get("cost")
        remaining = decision_payload.get("remaining_budget")
        if dims.get("financial", {}).get("score", 0) >= 40 or (
            cost and remaining and cost > remaining
        ):
            issues.add("financial")

        if (
            dims.get("compliance", {}).get("score", 0) >= 40
            or decision_payload.get("uses_pii")
            or decision_payload.get("involves_compliance_risk")
            or triggered_types & {"compliance", "privacy"}
        ):
            issues.add("compliance")

        if (
            dims.get("strategic", {}).get("score", 0) >= 50
            or "strategic" in triggered_types
            or decision_payload.get("involves_hiring")
        ):
            issues.add("strategic")

        return issues

    # ── Candidate generation ──────────────────────────────────────────────────

    def _generate_candidates(
        self,
        decision_payload: dict,
        governance_result: dict,
        risk_scoring: dict,
        company_payload: dict,
        issue_types: set[str],
    ) -> list[dict]:
        conditions = self._compute_conditions(
            decision_payload, governance_result, risk_scoring, company_payload
        )
        templates = self._load_templates()

        relevant = [
            t for t in templates
            if t["issueType"] in issue_types
            and all(conditions.get(c) for c in t.get("applicabilityConditions", []))
        ]
        relevant.sort(key=lambda t: t["priority"])

        candidates: list[dict] = []
        seen_strategies: set[str] = set()

        for tmpl in relevant:
            strategy = tmpl["patchStrategy"]
            if strategy in seen_strategies:
                continue
            patch = self._build_patch(strategy, decision_payload, company_payload)
            if patch is None:
                continue

            candidates.append({
                "scenarioId":      f"sim_{tmpl['templateId']}",
                "templateId":      tmpl["templateId"],
                "titleKo":         tmpl["titleKo"],
                "titleEn":         tmpl.get("titleEn"),
                "changeSummaryKo": self._summary_ko(strategy, decision_payload, patch),
                "changeSummaryEn": self._summary_en(strategy, decision_payload, patch),
                "issueTypes":      [tmpl["issueType"]],
                "changeSet":       patch,
                "confidence":      _CONFIDENCE.get(strategy, 0.70),
            })
            seen_strategies.add(strategy)
            if len(candidates) >= 3:
                break

        return candidates

    # ── Nova proposals → candidates ───────────────────────────────────────────

    def _proposals_to_candidates(
        self,
        proposals: list,
        decision_payload: dict,
        company_payload: dict,
    ) -> list[dict]:
        """
        Convert validated NovaScenarioProposal objects into candidate dicts
        that _evaluate_scenario() can consume.

        For each proposal:
          1. Look up template by templateId (Step 6 validation)
          2. Derive patchStrategy from template config
          3. Build changeSet via _build_patch() (returns None if not applicable)
          4. Assemble candidate — Nova's titleKo/changeSummaryKo are used as-is;
             changeSummaryEn and titleEn fall back to template or strategy defaults.
        """
        templates_by_id = {t["templateId"]: t for t in self._load_templates()}
        seen_strategies: set[str] = set()
        candidates: list[dict] = []

        for proposal in proposals:
            tmpl = templates_by_id.get(proposal.templateId)
            if tmpl is None:
                # templateId not in config — skip (already warned in proposer)
                logger.warning(
                    f"[simulation] templateId '{proposal.templateId}' not in "
                    "simulation_templates.json — skipping"
                )
                continue

            strategy = tmpl["patchStrategy"]
            if strategy in seen_strategies:
                continue

            patch = self._build_patch(strategy, decision_payload, company_payload)
            if patch is None:
                # Template not applicable to this decision's current values
                continue

            candidates.append({
                "scenarioId":      f"sim_{proposal.templateId}",
                "templateId":      proposal.templateId,
                "titleKo":         proposal.titleKo,
                "titleEn":         tmpl.get("titleEn"),
                "changeSummaryKo": proposal.changeSummaryKo,
                "changeSummaryEn": self._summary_en(strategy, decision_payload, patch),
                "issueTypes":      [tmpl["issueType"]],
                "changeSet":       patch,
                "confidence":      _CONFIDENCE.get(strategy, 0.70),
            })
            seen_strategies.add(strategy)
            if len(candidates) >= 3:
                break

        return candidates

    # ── Applicability conditions ──────────────────────────────────────────────

    def _compute_conditions(
        self,
        decision_payload: dict,
        governance_result: dict,
        risk_scoring: dict,
        company_payload: dict,
    ) -> dict[str, bool]:
        cost = decision_payload.get("cost")
        remaining = decision_payload.get("remaining_budget")
        fin_tol = (company_payload or {}).get("risk_tolerance", {}).get("financial", {})
        high_threshold = fin_tol.get("high_cost_threshold", 200_000_000)
        dims = {d["id"]: d for d in (risk_scoring or {}).get("dimensions", [])}
        return {
            "cost_exceeds_remaining_budget": bool(cost and remaining and cost > remaining),
            "cost_exceeds_high_threshold":   bool(cost and cost > high_threshold),
            "cost_is_large":                 bool(cost and cost > 50_000_000),
            "uses_pii":                      bool(decision_payload.get("uses_pii")),
            "involves_compliance_risk":      bool(decision_payload.get("involves_compliance_risk")),
            "no_goals_mapped":               not bool(decision_payload.get("goals")),
            "strategic_conflict_detected":   dims.get("strategic", {}).get("score", 0) > 50,
            "involves_hiring":               bool(decision_payload.get("involves_hiring")),
        }

    # ── Patch builders ────────────────────────────────────────────────────────

    def _build_patch(
        self, strategy: str, decision_payload: dict, company_payload: dict
    ) -> Optional[dict]:
        cost = decision_payload.get("cost")
        remaining = decision_payload.get("remaining_budget")
        fin_tol = (company_payload or {}).get("risk_tolerance", {}).get("financial", {})
        high_threshold = fin_tol.get("high_cost_threshold", 200_000_000)

        if strategy == "set_cost_to_remaining_budget":
            if not (cost and remaining and cost > remaining):
                return None
            return {"cost": float(remaining)}

        if strategy == "set_cost_to_high_threshold":
            if not cost or cost <= high_threshold:
                return None
            return {"cost": float(high_threshold * 0.9)}

        if strategy == "reduce_cost_by_half":
            if not cost or cost <= 0:
                return None
            return {"cost": float(cost * 0.5)}

        if strategy == "remove_pii_usage":
            if not decision_payload.get("uses_pii"):
                return None
            return {"uses_pii": False}

        if strategy == "clear_compliance_flag":
            if not decision_payload.get("involves_compliance_risk"):
                return None
            return {"involves_compliance_risk": False}

        if strategy == "inject_goal_alignment":
            if decision_payload.get("goals"):
                return None
            return {"goals": [{"description": "전략 목표 달성에 기여", "metric": None}]}

        if strategy == "defer_hiring":
            if not decision_payload.get("involves_hiring"):
                return None
            return {"involves_hiring": False, "headcount_change": 0}

        logger.warning(f"[simulation] Unknown patch strategy '{strategy}'")
        return None

    # ── Change summaries ──────────────────────────────────────────────────────

    def _summary_ko(self, strategy: str, decision_payload: dict, patch: dict) -> str:
        cost = decision_payload.get("cost")
        c = f"₩{int(cost)}" if cost is not None else "미정"
        pc = f"₩{int(patch['cost'])}" if patch.get("cost") is not None else "미정"
        if strategy == "set_cost_to_remaining_budget":
            return f"요청 금액을 {c}에서 잔여 예산({pc}) 수준으로 조정"
        if strategy == "set_cost_to_high_threshold":
            return f"요청 금액을 {c}에서 승인 기준 이하({pc})로 조정"
        if strategy == "reduce_cost_by_half":
            return f"요청 금액을 {c}에서 절반({pc})으로 분할 집행"
        if strategy == "remove_pii_usage":
            return "고객 개인정보(PII) 처리를 익명화로 대체하여 개인정보 보호 리스크 해소"
        if strategy == "clear_compliance_flag":
            return "준법감시인 사전 검토 절차를 의무화하여 컴플라이언스 리스크 해소"
        if strategy == "inject_goal_alignment":
            return "의사결정을 전략 목표와 명시적으로 연계하여 전략 정합성 확보"
        if strategy == "defer_hiring":
            return "채용 계획을 다음 분기로 연기하여 비용 안정화 목표와의 충돌 해소"
        return "의사결정 조건 변경"

    def _summary_en(self, strategy: str, decision_payload: dict, patch: dict) -> str:
        cost = decision_payload.get("cost")
        c = f"₩{int(cost)}" if cost is not None else "TBD"
        pc = f"₩{int(patch['cost'])}" if patch.get("cost") is not None else "TBD"
        if strategy == "set_cost_to_remaining_budget":
            return f"Reduce requested amount from {c} to remaining budget ({pc})"
        if strategy == "set_cost_to_high_threshold":
            return f"Reduce requested amount from {c} to below approval threshold ({pc})"
        if strategy == "reduce_cost_by_half":
            return f"Reduce requested amount from {c} to half ({pc}) via phased rollout"
        if strategy == "remove_pii_usage":
            return "Replace direct PII handling with anonymized processing to eliminate privacy risk"
        if strategy == "clear_compliance_flag":
            return "Mandate prior compliance officer review to resolve compliance risk"
        if strategy == "inject_goal_alignment":
            return "Explicitly link decision to strategic goals to improve alignment"
        if strategy == "defer_hiring":
            return "Defer hiring to next quarter to resolve conflict with cost stability goal"
        return "Modify decision conditions"

    # ── Scenario evaluation ───────────────────────────────────────────────────

    def _evaluate_scenario(
        self,
        baseline_payload: dict,
        scenario: dict,
        company_payload: dict,
        company_id: Optional[str],
        lang: str = "ko",
    ) -> Optional[dict]:
        patched = copy.deepcopy(baseline_payload)
        patched.update(scenario["changeSet"])

        # Validate patch against Decision schema
        try:
            from app.schemas.domain import Decision
            decision_obj = Decision(**patched)
        except Exception as exc:
            logger.warning(
                f"[simulation] '{scenario['scenarioId']}': Decision validation failed: {exc}"
            )
            return None

        # Re-run governance deterministically
        try:
            from app.governance import evaluate_governance
            gov_result = evaluate_governance(
                decision_obj,
                company_context=company_payload,
                use_nova=False,
                company_id=company_id,
                lang=lang,
            )
            sim_gov = gov_result.to_dict()
        except Exception as exc:
            logger.warning(
                f"[simulation] '{scenario['scenarioId']}': governance failed: {exc}"
            )
            return None

        # Re-run risk scoring
        try:
            from app.services.risk_scoring_service import RiskScoringService
            sim_risk_obj = RiskScoringService().score(
                decision_payload=patched,
                company_payload=company_payload or {},
                governance_result=sim_gov,
                graph_payload=None,
                risk_semantics=None,
                company_id=company_id,
            )
            sim_risk = sim_risk_obj.to_dict()
        except Exception as exc:
            logger.warning(
                f"[simulation] '{scenario['scenarioId']}': risk scoring failed: {exc}"
            )
            return None

        sim_outcome = self._build_outcome(sim_gov, sim_risk, company_id, lang=lang)

        return {
            "scenarioId":      scenario["scenarioId"],
            "templateId":      scenario["templateId"],
            "titleKo":         scenario["titleKo"],
            "titleEn":         scenario.get("titleEn"),
            "changeSummaryKo": scenario["changeSummaryKo"],
            "changeSummaryEn": scenario.get("changeSummaryEn"),
            "issueTypes":      scenario.get("issueTypes", []),
            "expectedOutcome": sim_outcome,
            "confidence":      scenario.get("confidence", 0.70),
            "isRecommended":   False,
            # Internal: kept until _finalise() runs, then removed
            "_simRisk":        sim_risk,
        }

    # ── Post-processing ───────────────────────────────────────────────────────

    def _finalise(
        self,
        scenarios: list[dict],
        baseline_outcome: dict,
        baseline_risk: dict,
    ) -> None:
        """Compute delta, resolved issues, remaining issues; strip internal fields."""
        b_dims = {
            d["id"]: d["score"]
            for d in (baseline_risk or {}).get("dimensions", [])
        }

        for s in scenarios:
            sim_risk = s.pop("_simRisk", {})
            sim_outcome = s["expectedOutcome"]
            s_dims = {d["id"]: d["score"] for d in sim_risk.get("dimensions", [])}

            # Aggregate delta
            agg_delta = (
                sim_outcome["aggregateRiskScore"]
                - baseline_outcome["aggregateRiskScore"]
            )
            delta: dict = {"aggregateRiskScoreDelta": agg_delta}

            # Per-dimension deltas
            for dim_id, field in [
                ("financial",  "financialRiskDelta"),
                ("compliance", "complianceRiskDelta"),
                ("strategic",  "strategicRiskDelta"),
            ]:
                if dim_id in b_dims and dim_id in s_dims:
                    delta[field] = s_dims[dim_id] - b_dims[dim_id]

            s["delta"] = delta

            # Resolved / remaining issues
            baseline_ids = set(baseline_outcome.get("triggeredRuleIds") or [])
            sim_ids = set(sim_outcome.get("triggeredRuleIds") or [])
            b_names = baseline_outcome.get("triggeredRuleNames") or {}
            s_names = sim_outcome.get("triggeredRuleNames") or {}
            # Merge: baseline names are authoritative for resolved, sim names for remaining
            all_names = {**b_names, **s_names}

            resolved: list[str] = []
            resolved_en: list[str] = []
            resolved_ids = baseline_ids - sim_ids
            for rid in sorted(resolved_ids):
                rule_name = all_names.get(rid) or rid
                resolved.append(f"해소: {rule_name}")
                resolved_en.append(f"Resolved: {rule_name}")

            b_band_idx = _BANDS.index(baseline_outcome.get("band", "LOW")) if baseline_outcome.get("band") in _BANDS else 0
            s_band_idx = _BANDS.index(sim_outcome.get("band", "LOW")) if sim_outcome.get("band") in _BANDS else 0
            if s_band_idx < b_band_idx:
                _b_band = baseline_outcome.get('band')
                _s_band = sim_outcome.get('band')
                resolved.append(f"리스크 등급 개선 ({_b_band} → {_s_band})")
                resolved_en.append(f"Risk band improved ({_b_band} → {_s_band})")

            remaining: list[str] = []
            remaining_en: list[str] = []
            for rid in sorted(sim_ids):
                rule_name = all_names.get(rid) or rid
                remaining.append(f"미해소: {rule_name}")
                remaining_en.append(f"Still triggered: {rule_name}")
            roles_ko = sim_outcome.get("requiredApprovals") or []
            roles_en = sim_outcome.get("requiredApprovalsEn") or roles_ko
            for role_ko, role_en in zip(roles_ko, roles_en):
                item = f"{role_ko} 승인 필요"
                if item not in remaining:
                    remaining.append(item)
                    remaining_en.append(f"{role_en} approval still required")

            s["resolvedIssues"] = list(dict.fromkeys(resolved))
            s["resolvedIssuesEn"] = list(dict.fromkeys(resolved_en))
            s["remainingIssues"] = list(dict.fromkeys(remaining))
            s["remainingIssuesEn"] = list(dict.fromkeys(remaining_en))

    # ── Recommendation ────────────────────────────────────────────────────────

    def _mark_recommended(
        self, scenarios: list[dict], baseline_outcome: dict
    ) -> None:
        """Mark at most one scenario as recommended using deterministic ranking."""
        improving = [
            s for s in scenarios
            if s.get("delta", {}).get("aggregateRiskScoreDelta", 0) < 0
        ]
        if not improving:
            return

        def _rank(s: dict) -> tuple:
            # Priority: (1) largest score reduction, (2) fewest remaining issues,
            # (3) highest confidence
            agg_delta = s.get("delta", {}).get("aggregateRiskScoreDelta", 0)
            remaining = len(s.get("remainingIssues") or [])
            confidence = -(s.get("confidence") or 0.0)
            return (agg_delta, remaining, confidence)

        best = min(improving, key=_rank)
        best["isRecommended"] = True


# ── Utility ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
