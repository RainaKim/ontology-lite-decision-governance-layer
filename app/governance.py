"""
Decision Governance Layer - Rule Engine

Hybrid governance evaluation:
- Rule matching (deterministic Python)
- Conflict resolution (o1 reasoning)
- Approval optimization (o1 reasoning)
"""

import json
from pathlib import Path
from typing import Optional
from enum import Enum

from app.schemas import Decision, ApprovalChainStep, ApprovalLevel
from app.o1_reasoner import O1Reasoner


class GovernanceFlag(str, Enum):
    """Governance flags for decision review requirements."""
    MISSING_APPROVAL = "MISSING_APPROVAL"
    PRIVACY_REVIEW_REQUIRED = "PRIVACY_REVIEW_REQUIRED"
    CRITICAL_CONFLICT = "CRITICAL_CONFLICT"
    HIGH_RISK = "HIGH_RISK"
    STRATEGIC_CRITICAL = "STRATEGIC_CRITICAL"
    MISSING_OWNER = "MISSING_OWNER"
    MISSING_RISK_ASSESSMENT = "MISSING_RISK_ASSESSMENT"
    FINANCIAL_THRESHOLD_EXCEEDED = "FINANCIAL_THRESHOLD_EXCEEDED"


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
                    "rationale": step.rationale
                }
                for step in self.approval_chain
            ],
            "flags": [flag.value for flag in self.flags],
            "requires_human_review": self.requires_human_review,
            "triggered_rules": self.triggered_rules,
            "computed_risk_score": self.computed_risk_score
        }


def load_rules(rules_path: str = None) -> dict:
    """Load governance rules from JSON file."""
    if rules_path is None:
        # Default to mock_company.json in project root
        rules_path = Path(__file__).parent.parent / "mock_company.json"

    with open(rules_path, 'r') as f:
        return json.load(f)


def compute_risk_score(decision: Decision) -> float:
    """
    Compute risk score from decision risks if not already set.
    Simple heuristic: count risks and weight by severity.
    """
    if decision.risk_score is not None:
        return decision.risk_score

    if not decision.risks:
        return 0.0

    # Severity mapping
    severity_weights = {
        "critical": 3.0,
        "high": 2.0,
        "medium": 1.0,
        "low": 0.5
    }

    total_score = 0.0
    for risk in decision.risks:
        severity = (risk.severity or "medium").lower()
        weight = severity_weights.get(severity, 1.0)
        total_score += weight

    # Normalize to 0-10 scale (cap at 10)
    # Assume 5+ critical risks = max risk
    normalized = min(total_score, 10.0)
    return round(normalized, 1)


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

    Extracts values from Decision object or infers from decision text.
    Works for any company's governance rules.

    Returns:
        Extracted value (str, bool, int, float, or None)
    """
    decision_text = f"{decision.decision_statement} {' '.join([g.description for g in decision.goals])}"
    decision_text_lower = decision_text.lower()

    # Try to get from Decision object first
    if hasattr(decision, field):
        return getattr(decision, field)

    # Try to get from company context
    if field in company_context:
        return company_context[field]

    # Field inference from text (generic patterns)

    # Cost field: Check for financial indicators
    if field == 'cost':
        # Check context first
        if 'estimated_cost' in company_context:
            return company_context['estimated_cost']

        # Infer from text: look for $ amounts, budget keywords, strategic terms
        financial_keywords = ['$', 'cost', 'budget', 'million', 'thousand', 'k', 'expense', 'investment']
        strategic_keywords = ['strategic', 'major', 'initiative', 'expansion', 'market', 'revenue',
                            'growth', 'acquisition', 'platform', 'goal', 'company-wide']

        # Rough inference: if mentions money or strategic terms, assume significant cost
        has_financial = any(kw in decision_text_lower for kw in financial_keywords)
        has_strategic = any(kw in decision_text_lower for kw in strategic_keywords)

        if has_financial or has_strategic:
            # Try to extract $ amount from text
            import re
            cost_patterns = [
                r'\$(\d+)k', r'\$(\d+),(\d+)',r'\$(\d+)m', r'\$(\d+)\s*million'
            ]
            for pattern in cost_patterns:
                match = re.search(pattern, decision_text_lower)
                if match:
                    # Extract and convert to number
                    if 'k' in decision_text_lower[match.start():match.end()]:
                        return int(match.group(1)) * 1000
                    elif 'm' in decision_text_lower[match.start():match.end()] or 'million' in decision_text_lower[match.start():match.end()]:
                        return int(match.group(1)) * 1000000

            # If no specific amount found but has indicators, assume high value
            if has_strategic:
                return 75000  # Default strategic initiative cost estimate

        return 0  # No cost indicators found

    # Target market: Check if specific market mentioned
    if field == 'target_market':
        # Return the decision text itself for contains/keyword matching
        return decision_text_lower

    # Boolean fields inferred from keywords
    if field == 'uses_pii':
        pii_keywords = ['pii', 'personal data', 'user data', 'privacy', 'gdpr', 'data protection']
        return any(kw in decision_text_lower for kw in pii_keywords)

    if field == 'launch_date':
        # Return decision text for deployment keyword matching
        deployment_keywords = ['launch', 'deploy', 'release', 'go live', 'rollout', 'ship']
        return any(kw in decision_text_lower for kw in deployment_keywords)

    # Default: return None if can't extract
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
    """
    rules = rules_data.get("governance_rules", [])
    triggered_rules = []
    approval_steps = []
    approval_set = set()  # Track unique approvers

    # Evaluate all rules (can trigger multiple)
    for rule in rules:
        if not rule.get("active", True):
            continue

        # Check if rule is triggered
        triggered, _ = evaluate_company_rule(rule, decision, company_context)

        if triggered:
            triggered_rules.append({
                "rule_id": rule["rule_id"],
                "name": rule["name"],
                "description": rule["description"],
                "rule_type": rule.get("type", "unknown")
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
                            rationale=rule['description']
                        ))

            elif action == "require_goal_mapping":
                # R4 Strategic Alignment - require CEO approval for major initiatives
                # Find CEO from personnel hierarchy
                ceo_info = find_role_in_hierarchy("CEO", rules_data)
                if ceo_info:
                    ceo_id = ceo_info['id']
                    if ceo_id not in approval_set:
                        approval_set.add(ceo_id)
                        approval_steps.append(ApprovalChainStep(
                            level=ApprovalLevel.C_LEVEL,
                            role="CEO",
                            required=True,
                            rationale=rule['description']
                        ))

    return approval_steps, triggered_rules


def detect_flags(decision: Decision, company_context: dict, computed_risk_score: float, triggered_rules: list[dict]) -> list[GovernanceFlag]:
    """
    Detect governance flags based on decision properties.

    Generic flags only - no company-specific logic.
    Domain-specific flags come from triggered rules.
    """
    flags = []

    # STRUCTURAL FLAGS (universal for any company)

    # Check for missing owner
    if not decision.owners or len(decision.owners) == 0:
        flags.append(GovernanceFlag.MISSING_OWNER)

    # Check for missing risk assessment
    if not decision.risks or len(decision.risks) == 0:
        flags.append(GovernanceFlag.MISSING_RISK_ASSESSMENT)
    else:
        # Check if risks have severity specified
        risks_without_severity = sum(1 for risk in decision.risks if not risk.severity)
        if risks_without_severity > 0:
            flags.append(GovernanceFlag.MISSING_RISK_ASSESSMENT)

    # High computed risk score
    if computed_risk_score >= 7.0:
        flags.append(GovernanceFlag.HIGH_RISK)

    # Strategic critical (if explicitly set)
    if decision.strategic_impact and decision.strategic_impact.value == "critical":
        flags.append(GovernanceFlag.STRATEGIC_CRITICAL)

    # Too many objectives (potential conflict indicator)
    if len(decision.kpis) > 5 or len(decision.goals) > 5:
        flags.append(GovernanceFlag.CRITICAL_CONFLICT)

    # Conflicting risk vs confidence (low confidence + high risk)
    if computed_risk_score >= 7.0 and decision.confidence < 0.6:
        flags.append(GovernanceFlag.CRITICAL_CONFLICT)

    # RULE-BASED FLAGS (from triggered rules)
    # Add flags based on rule types that were triggered

    rule_types = [rule.get('rule_type') or rule.get('type') for rule in triggered_rules]

    if 'compliance' in rule_types or 'privacy' in rule_types:
        flags.append(GovernanceFlag.PRIVACY_REVIEW_REQUIRED)

    if 'financial' in rule_types:
        flags.append(GovernanceFlag.FINANCIAL_THRESHOLD_EXCEEDED)

    if 'strategic' in rule_types:
        flags.append(GovernanceFlag.STRATEGIC_CRITICAL)

    # Check for critical severity consequences
    for rule in triggered_rules:
        consequence = rule.get('consequence', {})
        if consequence.get('severity') == 'critical':
            flags.append(GovernanceFlag.CRITICAL_CONFLICT)
            break

    return flags


def evaluate_governance(decision: Decision, company_context: dict = None, use_o1: bool = True) -> GovernanceResult:
    """
    Main governance evaluation function with o1 reasoning.

    Args:
        decision: Decision object to evaluate
        company_context: Optional company-specific context (policies, thresholds, etc.)
        use_o1: Whether to use o1 for conflict resolution (default: True)

    Returns:
        GovernanceResult with approval_chain, flags, requires_human_review, triggered_rules
    """
    if company_context is None:
        company_context = {}

    # Load rules
    rules_data = load_rules()

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

    # Detect flags (passing triggered_rules for rule-based flags)
    flags = detect_flags(decision, company_context, computed_risk_score, triggered_rules)

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
    o1_reasoner = O1Reasoner(model="o1-mini")

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


def apply_governance_to_decision(decision: Decision, company_context: dict = None) -> Decision:
    """
    Apply governance evaluation and update decision object.

    Args:
        decision: Decision object to evaluate
        company_context: Optional company-specific context

    Returns:
        Updated Decision object with governance fields populated
    """
    result = evaluate_governance(decision, company_context)

    # Update decision with governance results
    decision.risk_score = result.computed_risk_score
    decision.approval_chain = result.approval_chain

    return decision
