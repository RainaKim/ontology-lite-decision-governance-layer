"""
Decision Pack Generator - Template-based, Deterministic

Generates execution-ready Decision Packs from evaluated decisions.
Pure Python logic, no LLM, no freeform text.
"""

from typing import Optional


def build_decision_pack(
    decision: dict,
    governance: dict,
    company: dict = None
) -> dict:
    """
    Build a Decision Pack from decision and governance evaluation results.

    Args:
        decision: Decision object as dict (from schemas.Decision)
        governance: Governance evaluation result as dict (from GovernanceResult.to_dict())
        company: Optional company context

    Returns:
        Decision Pack as structured dict with fixed sections
    """
    if company is None:
        company = {}

    # Extract core fields
    decision_statement = decision.get("decision_statement", "")
    goals = decision.get("goals", [])
    kpis = decision.get("kpis", [])
    risks = decision.get("risks", [])
    owners = decision.get("owners", [])
    assumptions = decision.get("assumptions", [])
    confidence = decision.get("confidence", 0.0)
    strategic_impact = decision.get("strategic_impact")

    # Extract governance fields
    flags = governance.get("flags", [])
    requires_human_review = governance.get("requires_human_review", True)
    approval_chain = governance.get("approval_chain", [])
    triggered_rules = governance.get("triggered_rules", [])
    computed_risk_score = governance.get("computed_risk_score", 0.0)

    # Detect missing items
    missing_items = _detect_missing_items(decision, governance, flags)

    # Determine risk level and governance status
    risk_level, governance_status = _determine_risk_and_status(
        flags, requires_human_review, computed_risk_score
    )

    # Generate recommended next actions
    recommended_next_actions = _generate_next_actions(
        missing_items, approval_chain, flags, governance_status, triggered_rules
    )

    # Extract rationales from triggered rules and approval chain
    rationales = _extract_rationales(triggered_rules, approval_chain)

    # Build title
    title = _generate_title(decision_statement, strategic_impact)

    # Assemble Decision Pack
    decision_pack = {
        "title": title,
        "summary": {
            "decision_statement": decision_statement,
            "human_approval_required": requires_human_review,
            "risk_level": risk_level,
            "governance_status": governance_status,
            "confidence_score": confidence,
            "strategic_impact": strategic_impact or "not_specified"
        },
        "goals_kpis": {
            "goals": [
                {
                    "description": g.get("description", ""),
                    "metric": g.get("metric")
                }
                for g in goals
            ],
            "kpis": [
                {
                    "name": k.get("name", ""),
                    "target": k.get("target"),
                    "measurement_frequency": k.get("measurement_frequency")
                }
                for k in kpis
            ]
        },
        "risks": [
            {
                "description": r.get("description", ""),
                "severity": r.get("severity", "medium"),
                "mitigation": r.get("mitigation")
            }
            for r in risks
        ],
        "owners": [
            {
                "name": o.get("name", ""),
                "role": o.get("role"),
                "responsibility": o.get("responsibility")
            }
            for o in owners
        ],
        "assumptions": [
            {
                "description": a.get("description", ""),
                "criticality": a.get("criticality")
            }
            for a in assumptions
        ],
        "missing_items": missing_items,
        "approval_chain": [
            {
                "level": step.get("level", ""),
                "role": step.get("role", ""),
                "required": step.get("required", True),
                "rationale": step.get("rationale")
            }
            for step in approval_chain
        ],
        "recommended_next_actions": recommended_next_actions,
        "audit": {
            "flags": flags,
            "triggered_rules": [
                {
                    "rule_id": r.get("rule_id", ""),
                    "name": r.get("name", ""),
                    "description": r.get("description", "")
                }
                for r in triggered_rules
            ],
            "rationales": rationales,
            "computed_risk_score": computed_risk_score
        }
    }

    return decision_pack


def _detect_missing_items(decision: dict, governance: dict, flags: list[str]) -> list[str]:
    """
    Detect missing required items in the decision.

    Returns list of missing item descriptions.
    """
    missing = []

    # Check for missing owner
    owners = decision.get("owners", [])
    if not owners or len(owners) == 0:
        missing.append("Missing owner")

    # Check for missing KPIs
    kpis = decision.get("kpis", [])
    if not kpis or len(kpis) == 0:
        missing.append("Missing KPI")

    # Check for missing risks
    risks = decision.get("risks", [])
    if not risks or len(risks) == 0:
        missing.append("Missing risk")

    # Check for missing approvals flag
    if "MISSING_APPROVAL" in flags:
        missing.append("Missing required approvals")

    # Check for any MISSING_* flags
    for flag in flags:
        if flag.startswith("MISSING_") and flag != "MISSING_APPROVAL":
            # Convert flag to readable format
            field_name = flag.replace("MISSING_", "").replace("_", " ").lower()
            item_text = f"Missing {field_name}"
            if item_text not in missing:
                missing.append(item_text)

    # Check for missing goals
    goals = decision.get("goals", [])
    if not goals or len(goals) == 0:
        missing.append("Missing goals")

    return missing


def _determine_risk_and_status(
    flags: list[str],
    requires_human_review: bool,
    computed_risk_score: float
) -> tuple[str, str]:
    """
    Determine risk level and governance status.

    Returns (risk_level, governance_status).
    """
    # Check for critical flags
    has_critical_flag = any("CRITICAL" in flag for flag in flags)

    if has_critical_flag:
        return "high", "blocked"

    # Check for high risk score
    if computed_risk_score >= 7.0:
        return "high", "needs_review"

    # Check for medium risk
    if requires_human_review or len(flags) > 0 or computed_risk_score >= 4.0:
        return "medium", "needs_review"

    # Low risk, compliant
    return "low", "compliant"


def _generate_next_actions(
    missing_items: list[str],
    approval_chain: list[dict],
    flags: list[str],
    governance_status: str,
    triggered_rules: list[dict]
) -> list[str]:
    """
    Generate deterministic recommended next actions.

    Returns list of action items.
    """
    actions = []

    # Handle blocked status first
    if governance_status == "blocked":
        actions.append("Resolve blocking conflicts before proceeding")

    # Missing item actions
    if "Missing owner" in missing_items:
        actions.append("Assign an accountable owner")

    if "Missing KPI" in missing_items:
        actions.append("Define measurable KPI and target")

    if "Missing risk" in missing_items:
        actions.append("Add risk assessment and mitigation")

    if "Missing goals" in missing_items:
        actions.append("Define organizational goals for this decision")

    if "Missing required approvals" in missing_items:
        actions.append("Identify and document required approvals")

    # Approval chain actions
    if approval_chain and len(approval_chain) > 0:
        required_approvals = [
            step["role"] for step in approval_chain if step.get("required", True)
        ]
        if required_approvals:
            roles_str = ", ".join(required_approvals)
            actions.append(f"Request approvals: {roles_str}")

    # Flag-specific actions
    if "PRIVACY_REVIEW_REQUIRED" in flags:
        actions.append("Initiate privacy/security review with CTO")

    if "FINANCIAL_THRESHOLD_EXCEEDED" in flags:
        actions.append("Confirm budget justification with CFO")

    # Rule-specific actions
    for rule in triggered_rules:
        rule_id = rule.get("rule_id", "")
        if rule_id == "R006":  # Financial threshold rule
            if "Confirm budget justification with CFO" not in actions:
                actions.append("Prepare financial impact analysis")

    # Default action if nothing else
    if not actions and governance_status == "compliant":
        actions.append("Proceed with execution after final review")

    return actions


def _extract_rationales(triggered_rules: list[dict], approval_chain: list[dict]) -> list[str]:
    """
    Extract rationales from triggered rules and approval chain.

    Returns list of rationale strings.
    """
    rationales = []

    # Extract from triggered rules
    for rule in triggered_rules:
        name = rule.get("name", "")
        description = rule.get("description", "")
        if description:
            rationales.append(f"{name}: {description}")
        elif name:
            rationales.append(name)

    # Extract from approval chain
    for step in approval_chain:
        rationale = step.get("rationale")
        if rationale:
            role = step.get("role", "")
            if rationale not in rationales:
                rationales.append(f"{role} - {rationale}")

    return rationales


def _generate_title(decision_statement: str, strategic_impact: Optional[str]) -> str:
    """
    Generate a title for the decision pack.

    Returns title string.
    """
    # Truncate decision statement if too long
    max_length = 80
    truncated = decision_statement[:max_length]
    if len(decision_statement) > max_length:
        truncated += "..."

    # Add strategic impact prefix if critical or high
    if strategic_impact in ["critical", "high"]:
        prefix = f"[{strategic_impact.upper()}] "
        return prefix + truncated

    return truncated


# Example usage and demo
def demo_decision_pack():
    """
    Demo case: High-risk acquisition decision
    """
    # Example decision (as dict)
    decision = {
        "decision_statement": "Acquire TechStartup Inc for $2.5M to expand our AI capabilities",
        "goals": [
            {
                "description": "Expand AI/ML product offerings",
                "metric": "Number of AI features launched"
            },
            {
                "description": "Acquire engineering talent",
                "metric": "Team size increase"
            }
        ],
        "kpis": [
            {
                "name": "Revenue from AI products",
                "target": "$5M ARR within 18 months",
                "measurement_frequency": "Quarterly"
            }
        ],
        "risks": [
            {
                "description": "Integration challenges with existing systems",
                "severity": "high",
                "mitigation": "Dedicated integration team and 6-month timeline"
            },
            {
                "description": "Key personnel may leave post-acquisition",
                "severity": "critical",
                "mitigation": "Retention bonuses and equity grants"
            },
            {
                "description": "Cultural mismatch between organizations",
                "severity": "medium",
                "mitigation": "Cultural assessment and integration planning"
            }
        ],
        "owners": [
            {
                "name": "Sarah Chen",
                "role": "VP of Strategy",
                "responsibility": "Overall acquisition execution"
            }
        ],
        "assumptions": [
            {
                "description": "TechStartup's tech stack is compatible",
                "criticality": "high"
            }
        ],
        "required_approvals": ["CFO", "CEO", "Board"],
        "confidence": 0.75,
        "strategic_impact": "high",
        "risk_score": 7.5
    }

    # Example governance result (as dict)
    governance = {
        "approval_chain": [
            {
                "level": "department_head",
                "role": "Budget Owner",
                "required": True,
                "rationale": "Budget accountability"
            },
            {
                "level": "vp",
                "role": "VP of Finance",
                "required": True,
                "rationale": "Financial review and approval"
            },
            {
                "level": "c_level",
                "role": "CFO",
                "required": True,
                "rationale": "Major financial decision approval"
            },
            {
                "level": "c_level",
                "role": "CEO",
                "required": True,
                "rationale": "Executive approval for major investments"
            }
        ],
        "flags": ["HIGH_RISK", "FINANCIAL_THRESHOLD_EXCEEDED"],
        "requires_human_review": True,
        "triggered_rules": [
            {
                "rule_id": "R006",
                "name": "Financial Threshold - Major Investment",
                "description": "Decisions implying budget > $1M or containing 'acquisition', 'investment', 'capital' require CFO approval",
                "priority": 1
            }
        ],
        "computed_risk_score": 7.5
    }

    # Build decision pack
    pack = build_decision_pack(decision, governance)

    return pack


if __name__ == "__main__":
    """
    Run demo to show example input/output
    """
    import json

    print("=" * 80)
    print("DECISION PACK GENERATOR - DEMO")
    print("=" * 80)
    print()

    pack = demo_decision_pack()

    print(json.dumps(pack, indent=2))
    print()
    print("=" * 80)
