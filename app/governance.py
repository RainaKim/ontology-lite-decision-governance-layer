"""
Decision Governance Layer - Rule Engine

Hybrid governance evaluation:
- Rule matching (deterministic Python)
- Conflict resolution (o1 reasoning)
- Approval optimization (o1 reasoning)
"""

import json
import logging
from pathlib import Path
from typing import Optional
from enum import Enum

from app.schemas import Decision, ApprovalChainStep, ApprovalLevel
from app.o1_reasoner import O1Reasoner

logger = logging.getLogger(__name__)


class GovernanceFlag(str, Enum):
    """Governance flags for decision review requirements."""
    MISSING_APPROVAL = "MISSING_APPROVAL"
    PRIVACY_REVIEW_REQUIRED = "PRIVACY_REVIEW_REQUIRED"
    CRITICAL_CONFLICT = "CRITICAL_CONFLICT"
    HIGH_RISK = "HIGH_RISK"
    STRATEGIC_CRITICAL = "STRATEGIC_CRITICAL"
    STRATEGIC_MISALIGNMENT = "STRATEGIC_MISALIGNMENT"
    MISSING_OWNER = "MISSING_OWNER"
    MISSING_RISK_ASSESSMENT = "MISSING_RISK_ASSESSMENT"
    FINANCIAL_THRESHOLD_EXCEEDED = "FINANCIAL_THRESHOLD_EXCEEDED"
    GOVERNANCE_COVERAGE_GAP = "GOVERNANCE_COVERAGE_GAP"


class GovernanceResult:
    """Result of governance evaluation."""

    def __init__(
        self,
        approval_chain: list[ApprovalChainStep],
        flags: list[GovernanceFlag],
        requires_human_review: bool,
        triggered_rules: list[dict],
        computed_risk_score: Optional[float] = None
    ):
        self.approval_chain = approval_chain
        self.flags = flags
        self.requires_human_review = requires_human_review
        self.triggered_rules = triggered_rules
        self.computed_risk_score = computed_risk_score

    def to_dict(self):
        """Convert to dictionary for JSON serialization."""
        return {
            "approval_chain": [
                {
                    "level": step.level.value,
                    "role": step.role,
                    "required": step.required,
                    "rationale": step.rationale,
                    "source_rule_id": step.source_rule_id,
                    "rule_action": step.rule_action
                }
                for step in self.approval_chain
            ],
            "flags": [flag.value for flag in self.flags],
            "requires_human_review": self.requires_human_review,
            "triggered_rules": self.triggered_rules,
            "computed_risk_score": self.computed_risk_score
        }


from app.config.company_registry import COMPANY_RULES_FILES as _COMPANY_RULES_FILES

_DEFAULT_RULES_FILE = "mock_company.json"

_SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 8.0,
    "high": 3.0,
    "medium": 1.5,
    "low": 0.5,
}

_STRATEGIC_IMPACT_BONUS: dict[str, float] = {
    "critical": 3.5,
    "high": 1.5,
    "medium": 0.0,
    "low": 0.0,
}


def load_rules(rules_path: str = None, company_id: str = None, lang: str = "ko") -> dict:
    """Load governance rules from JSON file, selecting by company_id and lang."""
    lang_key = lang if lang in ("ko", "en") else "ko"
    if rules_path is None:
        files = _COMPANY_RULES_FILES.get(company_id, {})
        filename = files.get("merged") or _DEFAULT_RULES_FILE
        rules_path = Path(__file__).parent.parent / filename
    with open(rules_path, 'r') as f:
        raw = json.load(f)
    # If this is a merged file with translations, extract the lang-specific view
    if "translations" in raw:
        translation = raw.get("translations", {}).get(lang_key, {})
        data = {**raw, **translation}
        if "rules" in translation:
            data["governance_rules"] = translation["rules"]
        return data
    return raw


def compute_risk_score(decision: Decision) -> float:
    """
    Compute risk score (0–10) combining individual risk items with structural signals.

    Two layers:
    1. Individual risks (LLM-extracted): weighted by severity
    2. Structural signals: strategic_impact and compliance flags
       These ensure the numeric score stays consistent with qualitative judgements —
       e.g. a HIPAA violation with strategic_impact=critical should score ≥ 7 (HIGH_RISK),
       not 3 (one extracted high-severity risk item) while the UI labels it "매우 높음".

    Structural bonus calibration:
      strategic_impact=critical  → +3.5  (serious strategic exposure)
      strategic_impact=high      → +1.5
      involves_compliance_risk   → +2.5  (regulatory/legal breach risk)
      uses_pii                   → +1.0  (data exposure risk)
    """
    if decision.risk_score is not None:
        return decision.risk_score

    # --- Layer 1: individual risk items ---
    total_score = 0.0
    for risk in (decision.risks or []):
        severity = (risk.severity or "medium").lower()
        total_score += _SEVERITY_WEIGHTS.get(severity, 1.0)

    # --- Layer 2: structural signals ---
    if decision.strategic_impact:
        total_score += _STRATEGIC_IMPACT_BONUS.get(decision.strategic_impact.value, 0.0)

    if getattr(decision, "involves_compliance_risk", False):
        total_score += 2.5

    if getattr(decision, "uses_pii", False):
        total_score += 1.0

    return round(min(total_score, 10.0), 1)


def get_approver_level(approver_id: str, rules_data: dict) -> int:
    """Get approval level from personnel hierarchy."""
    personnel = rules_data.get('approval_hierarchy', {}).get('personnel', [])

    for person in personnel:
        if person.get('id') == approver_id:
            return person.get('level', 1)

    return 1  # Default level


def find_role_in_hierarchy(role_name: str, rules_data: dict) -> dict:
    """
    Find a person by role in the personnel hierarchy.

    Args:
        role_name: Role to search for (e.g., "CEO", "CTO", "CFO")
        rules_data: Company data containing personnel hierarchy

    Returns:
        Person dict if found, None otherwise
    """
    personnel = rules_data.get('approval_hierarchy', {}).get('personnel', [])

    for person in personnel:
        if person.get('role', '').upper() == role_name.upper():
            return person

    return None


def extract_field_value(field: str, decision: Decision, company_context: dict) -> any:
    """
    Generic field value extractor.

    All governance-relevant fields are extracted by the LLM and stored on the
    Decision object. This function simply reads them off the model, falling back
    to company_context for any company-level overrides.

    Returns:
        Extracted value (str, bool, int, float, or None)
    """
    # LLM-extracted fields live directly on the Decision object
    if hasattr(decision, field):
        return getattr(decision, field)

    # Company context can supply additional fields (e.g. estimated_cost override)
    if field in company_context:
        return company_context[field]

    return None


def evaluate_company_rule(rule: dict, decision: Decision, company_context: dict) -> tuple[bool, any]:
    """
    Fully generic rule evaluation based on condition structure.

    Works with ANY company's governance rules defined in JSON.
    No hardcoded rule IDs or company-specific logic.

    Returns:
        (triggered: bool, result: Any)
    """
    condition = rule.get('condition', {})

    # Handle OR conditions
    if 'operator' in condition and condition['operator'] == 'OR':
        sub_conditions = condition.get('conditions', [])
        for sub_cond in sub_conditions:
            triggered, result = evaluate_single_condition(sub_cond, decision, company_context)
            if triggered:
                return True, result
        return False, None

    # Handle single condition
    return evaluate_single_condition(condition, decision, company_context)


def evaluate_single_condition(condition: dict, decision: Decision, company_context: dict) -> tuple[bool, any]:
    """
    Generic condition evaluator.

    Supports any field, operator, and value from governance rule JSON.
    """
    field = condition.get('field')
    operator = condition.get('operator')
    value = condition.get('value')

    # Extract field value using generic extractor
    actual_value = extract_field_value(field, decision, company_context)

    # Evaluate based on operator
    if operator == '>':
        return (actual_value is not None and actual_value > value), {"field": field}
    elif operator == '>=':
        return (actual_value is not None and actual_value >= value), {"field": field}
    elif operator == '<':
        return (actual_value is not None and actual_value < value), {"field": field}
    elif operator == '<=':
        return (actual_value is not None and actual_value <= value), {"field": field}
    elif operator == '==':
        return (actual_value == value), {"field": field}
    elif operator == '!=':
        return (actual_value != value), {"field": field}
    elif operator == 'contains':
        # For string fields, check if value is in actual_value
        if isinstance(actual_value, str):
            return (str(value).lower() in actual_value.lower()), {"field": field}
        return False, {"field": field}
    elif operator == 'overlaps_with':
        # For boolean extraction fields (like launch_date)
        return (actual_value is True), {"field": field}

    return False, None




def select_approval_chain(decision: Decision, rules_data: dict, company_context: dict) -> tuple[list[ApprovalChainStep], list[dict]]:
    """
    Select approval chain based on rule matching.
    Returns (approval_chain, triggered_rules).

    Note: triggered_rules now includes ALL evaluated rules with status field:
    - TRIGGERED: rule condition met, action taken
    - PASSED: rule evaluated but condition not met
    - UNSATISFIED: rule requires something (e.g. goal mapping) that's missing
    - INACTIVE: rule is active=false
    """
    rules = rules_data.get("governance_rules", [])
    triggered_rules = []
    approval_steps = []
    approval_set = set()  # Track unique approvers

    # Evaluate all rules (can trigger multiple)
    for rule in rules:
        rule_id = rule.get("rule_id", "")

        # Handle inactive rules
        if not rule.get("active", True):
            triggered_rules.append({
                "rule_id": rule_id,
                "name": rule.get("name", ""),
                "description": rule.get("description", ""),
                "rule_type": rule.get("type", "unknown"),
                "status": "INACTIVE",
                "visible_in_graph": False,
                "reason": "Rule is not active"
            })
            continue

        # Check if rule is triggered
        triggered, _ = evaluate_company_rule(rule, decision, company_context)

        if triggered:
            logger.info(f"Rule {rule_id} ({rule['name']}) TRIGGERED")

            # Determine if this is a graph-visible rule
            consequence = rule.get("consequence", {})
            action = consequence.get("action", "")
            visible_in_graph = action in ["require_approval", "require_review", "block", "require_goal_mapping", "escalate"]

            triggered_rules.append({
                "rule_id": rule_id,
                "name": rule.get("name", ""),
                "description": rule.get("description", ""),
                "rule_type": rule.get("type", "unknown"),
                "status": "TRIGGERED",
                "visible_in_graph": visible_in_graph,
                "reason": f"Rule triggered: {action}",
                "condition": rule.get("condition"),
                "consequence": consequence
            })

            # Extract approval requirements
            consequence = rule.get("consequence", {})
            action = consequence.get("action")

            if action in ["require_approval", "require_review"]:
                # Get approver info
                approver_roles = consequence.get("approver_roles") or [consequence.get("approver_role")]
                approver_ids = consequence.get("approver_ids") or [consequence.get("approver_id")]

                for role, approver_id in zip(approver_roles, approver_ids):
                    if approver_id and approver_id not in approval_set:
                        approval_set.add(approver_id)

                        # Get level from personnel
                        level = get_approver_level(approver_id, rules_data)

                        # Map level to ApprovalLevel enum
                        level_map = {1: ApprovalLevel.TEAM_LEAD, 2: ApprovalLevel.DEPARTMENT_HEAD,
                                   3: ApprovalLevel.VP, 4: ApprovalLevel.C_LEVEL}
                        approval_level = level_map.get(level, ApprovalLevel.TEAM_LEAD)

                        approval_steps.append(ApprovalChainStep(
                            level=approval_level,
                            role=role,
                            required=True,
                            rationale=rule['description'],
                            source_rule_id=rule['rule_id'],
                            rule_action=action
                        ))

            # require_goal_mapping means: flag for strategic alignment review,
            # but does NOT add an approver. The rule is tracked in triggered_rules
            # and raises a STRATEGIC_CRITICAL flag via detect_flags.
            # CEO approval only comes from R3 (strategic_impact == critical) or R5 (cost > 1B).

        else:
            # Rule not triggered - check if it's UNSATISFIED (violation)
            consequence = rule.get("consequence", {})
            action = consequence.get("action", "")

            # UNSATISFIED: require_goal_mapping but no KPIs/goals provided
            if action == "require_goal_mapping":
                has_kpis = len(decision.kpis) > 0 if hasattr(decision, 'kpis') and decision.kpis else False
                has_goals = len(decision.goals) > 0 if hasattr(decision, 'goals') and decision.goals else False

                if not has_kpis and not has_goals:
                    # This is a violation - add to triggered_rules
                    triggered_rules.append({
                        "rule_id": rule_id,
                        "name": rule.get("name", ""),
                        "description": rule.get("description", ""),
                        "rule_type": rule.get("type", "unknown"),
                        "status": "UNSATISFIED",
                        "visible_in_graph": True,
                        "reason": f"Rule requires goal/KPI mapping but none provided"
                    })

            # UNSATISFIED: require_approval but no owner assigned
            elif action in ["require_approval", "require_review"]:
                has_owners = len(decision.owners) > 0 if hasattr(decision, 'owners') and decision.owners else False
                if not has_owners and rule.get("requires_owner", False):
                    # This is a violation - add to triggered_rules
                    triggered_rules.append({
                        "rule_id": rule_id,
                        "name": rule.get("name", ""),
                        "description": rule.get("description", ""),
                        "rule_type": rule.get("type", "unknown"),
                        "status": "UNSATISFIED",
                        "visible_in_graph": True,
                        "reason": f"Rule requires owner assignment but none provided"
                    })

            # PASSED rules are NOT added to triggered_rules (filtered out)

    return approval_steps, triggered_rules


def infer_owner_from_approval_chain(approval_chain: list, rules_data: dict) -> Optional[str]:
    """
    Infer the decision owner from the approval chain using the personnel hierarchy.

    Ownership ≠ approval. Strategy:
    1. Find the lowest-level required approver (closest to the operational work)
    2. If that approver has direct reports → the direct report is the inferred owner
       (e.g. R1 requires CFO → 재무팀장 reports to CFO → 재무팀장 is owner)
    3. If no direct reports → the approver themselves is the inferred owner
       (e.g. R6 requires CISO → CISO owns security decisions directly)

    Returns the inferred owner role, or None if no approval chain exists.
    """
    if not approval_chain:
        return None

    personnel = rules_data.get('approval_hierarchy', {}).get('personnel', [])

    # Find the lowest-level required approver (smallest level = closest to the work)
    lowest_level = 999
    lowest_approver_id = None
    lowest_approver_role = None

    for step in approval_chain:
        role = step.role if hasattr(step, 'role') else step.get('role', '')
        for person in personnel:
            if person.get('role', '').upper() == role.upper():
                level = person.get('level', 999)
                if level < lowest_level:
                    lowest_level = level
                    lowest_approver_id = person.get('id')
                    lowest_approver_role = person.get('role')

    if not lowest_approver_id:
        return None

    # Look for direct reports to this approver
    direct_reports = [p for p in personnel if p.get('reports_to') == lowest_approver_id]

    if direct_reports:
        # The direct report owns the operational work
        return direct_reports[0].get('role')

    # No direct reports — the approver themselves is the domain owner
    return lowest_approver_role


def detect_flags(decision: Decision, company_context: dict, computed_risk_score: float, triggered_rules: list[dict], approval_chain: list = None, rules_data: dict = None) -> list[GovernanceFlag]:
    """
    Detect governance flags based on decision properties.

    Generic flags only - no company-specific logic.
    Domain-specific flags come from triggered rules.
    """
    flags = []
    if approval_chain is None:
        approval_chain = []

    # STRUCTURAL FLAGS (universal for any company)

    # MISSING_OWNER: flag only when no explicit owner AND no owner can be inferred.
    # Owner inference: direct report to the lowest-level approver (or the approver
    # themselves if they have no direct reports). Users are not required to name an
    # owner in the input — the governance rules imply accountability.
    if not decision.owners or len(decision.owners) == 0:
        inferred = infer_owner_from_approval_chain(approval_chain, rules_data or {})
        if not inferred:
            flags.append(GovernanceFlag.MISSING_OWNER)

    # Check for missing risk assessment — only flag when no risks were identified at all.
    # Having risks without severity is still a risk assessment; don't penalize partial data.
    if not decision.risks or len(decision.risks) == 0:
        flags.append(GovernanceFlag.MISSING_RISK_ASSESSMENT)

    # High computed risk score
    if computed_risk_score >= 7.0:
        flags.append(GovernanceFlag.HIGH_RISK)

    # Strategic critical (if explicitly set)
    if decision.strategic_impact and decision.strategic_impact.value == "critical":
        flags.append(GovernanceFlag.STRATEGIC_CRITICAL)

    # Too many objectives (potential conflict indicator — structural contradiction)
    if len(decision.kpis) > 5 or len(decision.goals) > 5:
        flags.append(GovernanceFlag.CRITICAL_CONFLICT)

    # RULE-BASED FLAGS (from triggered rules)
    # Add flags based on rule types that were triggered

    rule_types = [rule.get('rule_type') or rule.get('type') for rule in triggered_rules]

    # PRIVACY_REVIEW_REQUIRED: raised for explicit 'privacy' rules OR compliance rules
    # that protect personal/health data (HIPAA, GDPR, PII).
    # R2 in healthcare is typed 'compliance' (not 'privacy') because it is a broad
    # regulatory-compliance rule, but its subject matter is data privacy — so we
    # check the rule description/name for privacy-relevant vocabulary.
    _PRIVACY_KEYWORDS = {'pii', 'hipaa', 'gdpr', 'privacy', '프라이버시', '개인정보', 'phi', 'anonymi'}
    def _is_privacy_relevant(rule: dict) -> bool:
        rt = (rule.get('rule_type') or rule.get('type') or '').lower()
        if rt == 'privacy':
            return True
        if rt == 'compliance':
            text = (rule.get('name', '') + ' ' + rule.get('description', '')).lower()
            return any(kw in text for kw in _PRIVACY_KEYWORDS)
        return False

    if any(_is_privacy_relevant(r) for r in triggered_rules):
        flags.append(GovernanceFlag.PRIVACY_REVIEW_REQUIRED)

    if 'financial' in rule_types:
        flags.append(GovernanceFlag.FINANCIAL_THRESHOLD_EXCEEDED)

    if 'strategic' in rule_types:
        # Only add if not already present (avoid duplicates)
        if GovernanceFlag.STRATEGIC_CRITICAL not in flags:
            flags.append(GovernanceFlag.STRATEGIC_CRITICAL)

    # GOVERNANCE_COVERAGE_GAP: no rules matched but decision has meaningful content.
    # Signals that the governance framework may not cover this decision type.
    # Only fire for substantive decisions (has goals/KPIs/risks, confidence > 0.3).
    if not triggered_rules:
        has_content = (
            len(decision.goals) > 0 or
            len(decision.kpis) > 0 or
            len(decision.risks) > 0
        )
        if has_content and decision.confidence > 0.3:
            flags.append(GovernanceFlag.GOVERNANCE_COVERAGE_GAP)

    # Remove duplicates
    return list(dict.fromkeys(flags))


def evaluate_governance(decision: Decision, company_context: dict = None, use_o1: bool = True, company_id: str = None, lang: str = "ko") -> GovernanceResult:
    """
    Main governance evaluation function with o1 reasoning.

    Args:
        decision: Decision object to evaluate
        company_context: Optional company-specific context (policies, thresholds, etc.)
        use_o1: Whether to use o1 for conflict resolution (default: True)
        company_id: Which company to select rules for

    Returns:
        GovernanceResult with approval_chain, flags, requires_human_review, triggered_rules
    """
    if company_context is None:
        company_context = {}

    # Load rules for correct company and language
    rules_data = load_rules(company_id=company_id, lang=lang)

    # Compute risk score if not present
    computed_risk_score = compute_risk_score(decision)

    # Update decision with computed risk score
    if decision.risk_score is None:
        decision.risk_score = computed_risk_score

    # Select approval chain based on rules
    approval_chain, triggered_rules = select_approval_chain(decision, rules_data, company_context)

    # If multiple rules triggered and o1 enabled, use o1 for conflict resolution
    if use_o1 and len(triggered_rules) >= 2:
        approval_chain = optimize_approval_chain_with_o1(
            approval_chain, triggered_rules, decision, rules_data
        )

    # Detect flags (passing triggered_rules and approval_chain for rule-based flags)
    flags = detect_flags(decision, company_context, computed_risk_score, triggered_rules, approval_chain, rules_data)

    # Check if compliance/privacy/strategic rules were triggered (always require review)
    compliance_triggered = any(
        rule.get('rule_type') in ['compliance', 'privacy', 'strategic', 'financial']
        for rule in triggered_rules
    )

    # Determine if human review is required
    requires_human_review = (
        len(flags) > 0 or
        len(approval_chain) > 0 or  # Any approval required = human review
        compliance_triggered or
        computed_risk_score >= 7.0 or
        (decision.strategic_impact and decision.strategic_impact.value in ["high", "critical"]) or
        decision.confidence < 0.7
    )

    return GovernanceResult(
        approval_chain=approval_chain,
        flags=flags,
        requires_human_review=requires_human_review,
        triggered_rules=triggered_rules,
        computed_risk_score=computed_risk_score
    )


def optimize_approval_chain_with_o1(approval_chain: list, triggered_rules: list,
                                    decision: Decision, company_data: dict) -> list:
    """
    Use o1 to optimize approval chain when multiple rules trigger.

    Resolves conflicts and determines optimal approval sequence.
    """
    # Prepare decision data
    decision_data = {
        'decision_statement': decision.decision_statement,
        'goals': [{'description': g.description} for g in decision.goals],
        'confidence': decision.confidence,
        'risk_score': decision.risk_score
    }

    # Initialize o1 reasoner
    o1_reasoner = O1Reasoner(model="o4-mini")

    # Call o1 for governance reasoning
    o1_result = o1_reasoner.reason_about_governance_conflicts(
        triggered_rules, decision_data, company_data
    )

    # If o1 provided optimized chain, use it
    optimized = o1_result.get('optimized_approval_chain', [])
    if optimized:
        # Convert o1 format to ApprovalChainStep
        new_chain = []
        for step in optimized:
            # Map level number to ApprovalLevel enum
            level_map = {
                1: ApprovalLevel.TEAM_LEAD,
                2: ApprovalLevel.DEPARTMENT_HEAD,
                3: ApprovalLevel.VP,
                4: ApprovalLevel.C_LEVEL,
                5: ApprovalLevel.BOARD
            }
            approval_level = level_map.get(step.get('level', 1), ApprovalLevel.TEAM_LEAD)

            new_chain.append(ApprovalChainStep(
                level=approval_level,
                role=step.get('approver_role'),
                required=True,
                rationale=step.get('rationale')
            ))

        return new_chain

    # Fallback to original chain if o1 didn't optimize
    return approval_chain


def apply_governance_to_decision(decision: Decision, company_context: dict = None, company_id: str = None) -> Decision:
    """
    Apply governance evaluation and update decision object.

    Args:
        decision: Decision object to evaluate
        company_context: Optional company-specific context
        company_id: Which company to select rules for

    Returns:
        Updated Decision object with governance fields populated
    """
    result = evaluate_governance(decision, company_context, company_id=company_id)

    # Update decision with governance results
    decision.risk_score = result.computed_risk_score
    decision.approval_chain = result.approval_chain

    return decision
