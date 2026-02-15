"""
Deterministic Governance Engine - Pure rule enforcement, NO LLMs.

Philosophy: Same input → same output. Governance is deterministic rule enforcement.

Pipeline:
1. Completeness checks (missing fields)
2. Derived attributes (normalize budget, detect EU/PII)
3. Rule enforcement (condition → consequence)
4. Transitive approval logic (escalation chains)
5. Final status calculation (approved/needs_approval/blocked)
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from enum import Enum

from app.schemas import Decision

logger = logging.getLogger(__name__)


class GovernanceStatus(str, Enum):
    """Final governance decision status."""
    APPROVED = "approved"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"


class GovernanceResult:
    """Result of deterministic governance evaluation."""

    def __init__(self, approval_chain: List[Dict], flags: List[str],
                 triggered_rules: List[Dict], requires_human_review: bool,
                 governance_status: GovernanceStatus, derived_attributes: Dict,
                 completeness_issues: List[str]):
        self.approval_chain = approval_chain
        self.flags = flags
        self.triggered_rules = triggered_rules
        self.requires_human_review = requires_human_review
        self.governance_status = governance_status
        self.derived_attributes = derived_attributes
        self.completeness_issues = completeness_issues

    def to_dict(self) -> Dict:
        return {
            "approval_chain": self.approval_chain,
            "flags": self.flags,
            "triggered_rules": self.triggered_rules,
            "requires_human_review": self.requires_human_review,
            "governance_status": self.governance_status.value,
            "derived_attributes": self.derived_attributes,
            "completeness_issues": self.completeness_issues
        }


def load_company_data(company_data_path: str = "mock_company.json") -> Dict:
    """Load company governance data."""
    path = Path(company_data_path)
    with open(path, 'r') as f:
        return json.load(f)


# ==================== STEP 1: COMPLETENESS CHECKS ====================

def check_completeness(decision: Decision) -> Tuple[bool, List[str]]:
    """
    Check if decision has all required fields.

    Returns:
        (is_complete, list_of_issues)
    """
    issues = []

    # Required: decision statement
    if not decision.decision_statement or len(decision.decision_statement.strip()) == 0:
        issues.append("MISSING_DECISION_STATEMENT")

    # Required: at least one owner
    if not decision.owners or len(decision.owners) == 0:
        issues.append("MISSING_OWNER")

    # Recommended: KPIs
    if not decision.kpis or len(decision.kpis) == 0:
        issues.append("MISSING_KPI")

    # Recommended: Risks
    if not decision.risks or len(decision.risks) == 0:
        issues.append("MISSING_RISK")

    # Recommended: Goals
    if not decision.goals or len(decision.goals) == 0:
        issues.append("MISSING_GOALS")

    # Check risk severity
    if decision.risks:
        risks_without_severity = [r for r in decision.risks if not r.severity]
        if risks_without_severity:
            issues.append("RISKS_MISSING_SEVERITY")

    is_complete = len(issues) == 0
    return is_complete, issues


# ==================== STEP 2: DERIVED ATTRIBUTES ====================

def derive_attributes(decision: Decision) -> Dict:
    """
    Derive normalized attributes from decision text and fields.

    Deterministic extraction of:
    - normalized_budget (int)
    - has_eu_scope (bool)
    - has_pii_usage (bool)
    - has_deployment (bool)
    - is_strategic (bool)
    - estimated_risk_level (low/medium/high/critical)
    """
    text = f"{decision.decision_statement} {' '.join([g.description for g in decision.goals])}"
    text_lower = text.lower()

    # Budget normalization
    import re
    normalized_budget = 0

    # Pattern matching for $ amounts
    budget_patterns = [
        (r'\$(\d+)k', 1000),
        (r'\$(\d+),(\d+)', 1),
        (r'\$(\d+)m', 1000000),
        (r'\$(\d+)\s*million', 1000000),
        (r'(\d+)k', 1000),
        (r'(\d+)\s*million', 1000000)
    ]

    for pattern, multiplier in budget_patterns:
        match = re.search(pattern, text_lower)
        if match:
            if ',' in pattern:
                # Handle $123,456 format
                num_str = match.group(1) + match.group(2)
                normalized_budget = int(num_str)
            else:
                normalized_budget = int(match.group(1)) * multiplier
            break

    # If no explicit amount but mentions budget/cost/investment
    if normalized_budget == 0:
        financial_keywords = ['budget', 'cost', 'investment', 'expense']
        strategic_keywords = ['strategic', 'major', 'initiative', 'expansion']

        if any(kw in text_lower for kw in financial_keywords):
            # Infer medium budget
            normalized_budget = 50000

        if any(kw in text_lower for kw in strategic_keywords):
            # Strategic initiatives likely higher budget
            normalized_budget = max(normalized_budget, 75000)

    # EU scope detection
    eu_keywords = ['eu', 'europe', 'european', 'gdpr', 'germany', 'france', 'uk']
    has_eu_scope = any(kw in text_lower for kw in eu_keywords)

    # PII usage detection
    pii_keywords = ['pii', 'personal data', 'user data', 'privacy', 'gdpr', 'data protection']
    has_pii_usage = any(kw in text_lower for kw in pii_keywords)

    # Deployment detection
    deployment_keywords = ['launch', 'deploy', 'release', 'go live', 'rollout', 'ship']
    has_deployment = any(kw in text_lower for kw in deployment_keywords)

    # Strategic detection
    strategic_keywords = ['strategic', 'company-wide', 'major initiative', 'expansion',
                         'acquisition', 'merger', 'market', 'g1', 'g2', 'g3', 'goal']
    is_strategic = any(kw in text_lower for kw in strategic_keywords)

    # Risk level estimation (from risk fields)
    if decision.risks:
        severity_weights = {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}
        total_weight = sum(severity_weights.get(r.severity.lower() if r.severity else 'medium', 2)
                          for r in decision.risks)
        avg_weight = total_weight / len(decision.risks)

        if avg_weight >= 3.5:
            estimated_risk_level = 'critical'
        elif avg_weight >= 2.5:
            estimated_risk_level = 'high'
        elif avg_weight >= 1.5:
            estimated_risk_level = 'medium'
        else:
            estimated_risk_level = 'low'
    else:
        estimated_risk_level = 'unknown'

    return {
        'normalized_budget': normalized_budget,
        'has_eu_scope': has_eu_scope,
        'has_pii_usage': has_pii_usage,
        'has_deployment': has_deployment,
        'is_strategic': is_strategic,
        'estimated_risk_level': estimated_risk_level
    }


# ==================== STEP 3: RULE ENFORCEMENT ====================

def evaluate_rule(rule: Dict, derived_attrs: Dict, decision: Decision) -> Tuple[bool, Optional[Dict]]:
    """
    Evaluate a single governance rule deterministically.

    Returns:
        (triggered, consequence_or_none)
    """
    condition = rule.get('condition', {})

    # Handle OR conditions
    if 'operator' in condition and condition['operator'] == 'OR':
        for sub_condition in condition.get('conditions', []):
            if evaluate_condition(sub_condition, derived_attrs, decision):
                return True, rule.get('consequence')
        return False, None

    # Single condition
    if evaluate_condition(condition, derived_attrs, decision):
        return True, rule.get('consequence')

    return False, None


def evaluate_condition(condition: Dict, derived_attrs: Dict, decision: Decision) -> bool:
    """Evaluate a single condition against derived attributes."""
    field = condition.get('field')
    operator = condition.get('operator')
    value = condition.get('value')

    # Map field to actual value
    if field == 'cost':
        actual_value = derived_attrs['normalized_budget']
    elif field == 'target_market':
        # Check if value is in decision text
        text = f"{decision.decision_statement} {' '.join([g.description for g in decision.goals])}"
        actual_value = text.lower()
        if operator == 'contains':
            return value.lower() in actual_value
    elif field == 'uses_pii':
        actual_value = derived_attrs['has_pii_usage']
    elif field == 'launch_date':
        actual_value = derived_attrs['has_deployment']
        if operator == 'overlaps_with':
            return actual_value  # Return True if has deployment
    else:
        # Unknown field
        return False

    # Numeric comparisons
    if operator == '>':
        return actual_value > value
    elif operator == '>=':
        return actual_value >= value
    elif operator == '<':
        return actual_value < value
    elif operator == '<=':
        return actual_value <= value
    elif operator == '==':
        return actual_value == value

    return False


def enforce_rules(rules: List[Dict], derived_attrs: Dict, decision: Decision,
                 company_data: Dict) -> Tuple[List[Dict], List[Dict]]:
    """
    Enforce all active governance rules.

    Returns:
        (triggered_rules, approval_requirements)
    """
    triggered = []
    approvals = []

    for rule in rules:
        if not rule.get('active', True):
            continue

        rule_triggered, consequence = evaluate_rule(rule, derived_attrs, decision)

        if rule_triggered:
            triggered.append({
                'rule_id': rule['rule_id'],
                'rule_name': rule['name'],
                'rule_type': rule.get('type'),
                'description': rule['description']
            })

            # Process consequence
            if consequence:
                action = consequence.get('action')

                if action in ['require_approval', 'require_review']:
                    approver_roles = consequence.get('approver_roles') or [consequence.get('approver_role')]
                    approver_ids = consequence.get('approver_ids') or [consequence.get('approver_id')]

                    for role, approver_id in zip(approver_roles, approver_ids):
                        approvals.append({
                            'approver_id': approver_id,
                            'approver_role': role,
                            'rule_id': rule['rule_id'],
                            'reason': rule['description'],
                            'severity': consequence.get('severity', 'medium')
                        })

                elif action == 'require_goal_mapping':
                    # Strategic decisions require CEO
                    ceo = find_person_by_role(company_data, 'CEO')
                    if ceo:
                        approvals.append({
                            'approver_id': ceo['id'],
                            'approver_role': 'CEO',
                            'rule_id': rule['rule_id'],
                            'reason': rule['description'],
                            'severity': consequence.get('severity', 'medium')
                        })

    return triggered, approvals


def find_person_by_role(company_data: Dict, role: str) -> Optional[Dict]:
    """Find person in company hierarchy by role."""
    personnel = company_data.get('approval_hierarchy', {}).get('personnel', [])
    for person in personnel:
        if person.get('role', '').upper() == role.upper():
            return person
    return None


# ==================== STEP 4: TRANSITIVE APPROVAL LOGIC ====================

def build_approval_chain(approval_requirements: List[Dict], company_data: Dict) -> List[Dict]:
    """
    Build approval chain with transitive logic and deduplication.

    Handles:
    - Deduplication (same person required by multiple rules)
    - Level ordering (highest level first)
    - Sequential vs parallel approval
    """
    # Deduplicate by approver_id
    unique_approvals = {}

    for approval in approval_requirements:
        approver_id = approval['approver_id']

        if approver_id not in unique_approvals:
            # Get person details
            person = get_person_by_id(company_data, approver_id)
            if person:
                unique_approvals[approver_id] = {
                    'approver_id': approver_id,
                    'approver_name': person.get('name'),
                    'approver_role': approval['approver_role'],
                    'level': person.get('level', 1),
                    'reasons': [approval['reason']],
                    'triggered_rules': [approval['rule_id']],
                    'severity': approval['severity']
                }
        else:
            # Add additional reason
            unique_approvals[approver_id]['reasons'].append(approval['reason'])
            unique_approvals[approver_id]['triggered_rules'].append(approval['rule_id'])
            # Escalate severity if needed
            severities = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
            current_severity = severities.get(unique_approvals[approver_id]['severity'], 2)
            new_severity = severities.get(approval['severity'], 2)
            if new_severity > current_severity:
                unique_approvals[approver_id]['severity'] = approval['severity']

    # Sort by level (highest first)
    approval_chain = sorted(unique_approvals.values(), key=lambda x: x['level'], reverse=True)

    return approval_chain


def get_person_by_id(company_data: Dict, person_id: str) -> Optional[Dict]:
    """Get person from company hierarchy by ID."""
    personnel = company_data.get('approval_hierarchy', {}).get('personnel', [])
    for person in personnel:
        if person.get('id') == person_id:
            return person
    return None


# ==================== STEP 5: FINAL STATUS CALCULATION ====================

def calculate_governance_status(approval_chain: List[Dict], completeness_issues: List[str],
                               flags: List[str]) -> GovernanceStatus:
    """
    Calculate final governance status deterministically.

    Logic:
    - BLOCKED: Critical completeness issues (missing owner)
    - NEEDS_APPROVAL: Has approval chain or significant flags
    - APPROVED: No approvals needed, all checks pass
    """
    # BLOCKED conditions
    critical_issues = ['MISSING_OWNER', 'MISSING_DECISION_STATEMENT']
    if any(issue in completeness_issues for issue in critical_issues):
        return GovernanceStatus.BLOCKED

    # NEEDS_APPROVAL conditions
    if len(approval_chain) > 0:
        return GovernanceStatus.NEEDS_APPROVAL

    significant_flags = ['CRITICAL_RISK', 'MISSING_KPI', 'RISKS_MISSING_SEVERITY']
    if any(flag in flags for flag in significant_flags):
        return GovernanceStatus.NEEDS_APPROVAL

    # APPROVED: No blockers, no approvals needed
    return GovernanceStatus.APPROVED


# ==================== MAIN GOVERNANCE FUNCTION ====================

def evaluate_governance(decision: Decision, mock_company: Optional[Dict] = None,
                       rules: Optional[List[Dict]] = None) -> GovernanceResult:
    """
    DETERMINISTIC GOVERNANCE EVALUATION.

    Same input → same output. NO LLM calls.

    Args:
        decision: Extracted decision object
        mock_company: Company data (loaded from file if None)
        rules: Governance rules (extracted from mock_company if None)

    Returns:
        GovernanceResult with approval_chain, flags, triggered_rules,
        requires_human_review, governance_status
    """
    logger.info("Starting deterministic governance evaluation")

    # Load company data if not provided
    if mock_company is None:
        mock_company = load_company_data()

    if rules is None:
        rules = mock_company.get('governance_rules', [])

    # STEP 1: Completeness checks
    is_complete, completeness_issues = check_completeness(decision)
    logger.info(f"Completeness check: {is_complete}, issues: {completeness_issues}")

    # STEP 2: Derive attributes
    derived_attrs = derive_attributes(decision)
    logger.info(f"Derived attributes: budget=${derived_attrs['normalized_budget']}, "
               f"EU={derived_attrs['has_eu_scope']}, PII={derived_attrs['has_pii_usage']}, "
               f"strategic={derived_attrs['is_strategic']}")

    # STEP 3: Rule enforcement
    triggered_rules, approval_requirements = enforce_rules(rules, derived_attrs, decision, mock_company)
    logger.info(f"Triggered {len(triggered_rules)} rules, {len(approval_requirements)} approval requirements")

    # STEP 4: Build approval chain
    approval_chain = build_approval_chain(approval_requirements, mock_company)
    logger.info(f"Built approval chain with {len(approval_chain)} approvers")

    # Generate flags
    flags = []
    flags.extend(completeness_issues)

    if derived_attrs['estimated_risk_level'] in ['high', 'critical']:
        flags.append('HIGH_RISK')

    if derived_attrs['is_strategic'] and not approval_chain:
        flags.append('STRATEGIC_NO_APPROVAL')

    if derived_attrs['has_pii_usage']:
        flags.append('PII_DETECTED')

    # STEP 5: Calculate final status
    governance_status = calculate_governance_status(approval_chain, completeness_issues, flags)

    # Determine if human review required
    requires_human_review = (
        governance_status in [GovernanceStatus.NEEDS_APPROVAL, GovernanceStatus.BLOCKED] or
        decision.confidence < 0.7 or
        len(flags) > 2
    )

    logger.info(f"Governance status: {governance_status.value}, human review: {requires_human_review}")

    return GovernanceResult(
        approval_chain=approval_chain,
        flags=flags,
        triggered_rules=triggered_rules,
        requires_human_review=requires_human_review,
        governance_status=governance_status,
        derived_attributes=derived_attrs,
        completeness_issues=completeness_issues
    )
