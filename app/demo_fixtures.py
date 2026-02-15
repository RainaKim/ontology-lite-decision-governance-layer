"""
Demo Fixtures - Test scenarios for governance validation

Four core scenarios for demo stability:
1. Compliant decision (low risk, passes all checks)
2. Budget violation (triggers financial rules)
3. Privacy violation (requires privacy review)
4. Blocked decision (critical conflicts)
"""

import json
from pathlib import Path
from typing import Optional

from app.schemas import (
    Decision, Owner, Goal, KPI, Risk, Assumption,
    StrategicImpact
)

# ---------------------------------------------------------------------------
# Company context loader
# ---------------------------------------------------------------------------

_COMPANY_DATA_CACHE: Optional[dict] = None


def load_mock_company_data(path: Optional[str] = None) -> dict:
    """
    Load mock company data from JSON file.

    Used by:
    - e2e_runner for passing company_data through the pipeline
    - subgraph extraction (owner matching, KPI overlap, reporting chain)

    Args:
        path: Optional override path. Defaults to project-root mock_company.json.

    Returns:
        Parsed company data dict (personnel, strategic_goals, risk_tolerance, etc.)
    """
    global _COMPANY_DATA_CACHE
    if _COMPANY_DATA_CACHE is not None and path is None:
        return _COMPANY_DATA_CACHE

    if path is None:
        path = str(Path(__file__).parent.parent / "mock_company.json")

    with open(path, "r") as f:
        data = json.load(f)

    if path is None or path == str(Path(__file__).parent.parent / "mock_company.json"):
        _COMPANY_DATA_CACHE = data

    return data


def get_company_context() -> dict:
    """
    Get company context dict suitable for pipeline consumption.

    Returns the full mock_company.json contents. The pipeline and
    O1Reasoner._extract_mock_subgraph use keys like:
    - approval_hierarchy.personnel (owner matching, reporting chain)
    - strategic_goals (KPI overlap, goal alignment)
    - risk_tolerance (risk gap analysis)
    - governance_rules (policy context)
    """
    return load_mock_company_data()


def create_compliant_decision() -> Decision:
    """
    Low-risk, compliant decision.
    Expected: Low risk, standard approval chain, no flags.
    """
    return Decision(
        decision_statement="Upgrade development tools to latest versions for improved productivity",
        goals=[
            Goal(
                description="Improve developer productivity",
                metric="Deployment frequency"
            ),
            Goal(
                description="Reduce technical debt",
                metric="Code quality score"
            )
        ],
        kpis=[
            KPI(
                name="Deployment frequency",
                target="10% increase within 3 months",
                measurement_frequency="Weekly"
            ),
            KPI(
                name="Developer satisfaction",
                target="4.5/5 rating",
                measurement_frequency="Quarterly"
            )
        ],
        risks=[
            Risk(
                description="Learning curve for new tools",
                severity="low",
                mitigation="Provide training sessions and documentation"
            ),
            Risk(
                description="Temporary productivity dip during transition",
                severity="low",
                mitigation="Phased rollout over 2 weeks"
            )
        ],
        owners=[
            Owner(
                name="Alex Johnson",
                role="Engineering Manager",
                responsibility="Tool selection and rollout"
            )
        ],
        required_approvals=["Engineering Manager"],
        assumptions=[
            Assumption(
                description="Team has capacity for training",
                criticality="medium"
            )
        ],
        confidence=0.85,
        strategic_impact=StrategicImpact.LOW
    )


def create_budget_violation_decision() -> Decision:
    """
    Decision triggering financial threshold rules.
    Expected: Financial flags, CFO approval required.
    """
    return Decision(
        decision_statement="Strategic acquisition of DataCorp for $3.5M to expand our data analytics capabilities",
        goals=[
            Goal(
                description="Expand data analytics offerings",
                metric="New analytics features"
            ),
            Goal(
                description="Acquire data engineering talent",
                metric="Team size increase"
            ),
            Goal(
                description="Enter new market segment",
                metric="Revenue from analytics"
            )
        ],
        kpis=[
            KPI(
                name="Revenue from analytics products",
                target="$8M ARR within 24 months",
                measurement_frequency="Quarterly"
            ),
            KPI(
                name="Customer acquisition in analytics",
                target="50 enterprise customers",
                measurement_frequency="Monthly"
            )
        ],
        risks=[
            Risk(
                description="Integration complexity with existing data infrastructure",
                severity="high",
                mitigation="Dedicated integration team for 9 months"
            ),
            Risk(
                description="Key data scientists may leave post-acquisition",
                severity="critical",
                mitigation="Retention packages and equity grants"
            ),
            Risk(
                description="Market demand uncertainty for analytics products",
                severity="medium",
                mitigation="Pre-acquisition customer validation"
            )
        ],
        owners=[
            Owner(
                name="Maria Rodriguez",
                role="VP of Product",
                responsibility="Product integration and strategy"
            ),
            Owner(
                name="David Chen",
                role="VP of M&A",
                responsibility="Acquisition execution"
            )
        ],
        required_approvals=["CFO", "CEO", "Board"],
        assumptions=[
            Assumption(
                description="DataCorp valuation is accurate",
                criticality="high"
            ),
            Assumption(
                description="No major regulatory hurdles",
                criticality="high"
            )
        ],
        confidence=0.72,
        strategic_impact=StrategicImpact.HIGH,
        risk_score=7.5  # High risk score
    )


def create_privacy_violation_decision() -> Decision:
    """
    Decision requiring privacy review.
    Expected: PRIVACY_REVIEW_REQUIRED flag, CTO involvement.
    """
    return Decision(
        decision_statement="Implement user behavior tracking to collect personal data for ML model training and GDPR-compliant analytics",
        goals=[
            Goal(
                description="Improve product recommendations",
                metric="Click-through rate"
            ),
            Goal(
                description="Enable personalization features",
                metric="User engagement score"
            )
        ],
        kpis=[
            KPI(
                name="Recommendation accuracy",
                target="25% improvement",
                measurement_frequency="Weekly"
            ),
            KPI(
                name="User engagement",
                target="15% increase in session duration",
                measurement_frequency="Daily"
            )
        ],
        risks=[
            Risk(
                description="GDPR compliance violations if not properly implemented",
                severity="critical",
                mitigation="Legal review and privacy-by-design architecture"
            ),
            Risk(
                description="User privacy concerns and potential backlash",
                severity="high",
                mitigation="Transparent privacy policy and opt-in mechanism"
            ),
            Risk(
                description="Data breach exposure of PII",
                severity="critical",
                mitigation="End-to-end encryption and minimal data collection"
            )
        ],
        owners=[
            Owner(
                name="Sarah Kim",
                role="VP of Product",
                responsibility="Feature requirements and user experience"
            ),
            Owner(
                name="James Lee",
                role="Head of Data Science",
                responsibility="ML model development"
            )
        ],
        required_approvals=["CTO", "Legal", "Privacy Officer"],
        assumptions=[
            Assumption(
                description="Users will consent to data collection",
                criticality="high"
            ),
            Assumption(
                description="Privacy infrastructure is scalable",
                criticality="medium"
            )
        ],
        confidence=0.68,
        strategic_impact=StrategicImpact.MEDIUM,
        risk_score=8.0  # High risk due to privacy concerns
    )


def create_blocked_decision() -> Decision:
    """
    Decision with critical conflicts that should be blocked.
    Expected: CRITICAL_CONFLICT flag, blocked status, high risk.
    """
    return Decision(
        decision_statement="Launch new product in 2 weeks without QA testing to meet arbitrary deadline",
        goals=[
            Goal(description="Meet marketing deadline", metric="Launch date"),
            Goal(description="Increase revenue", metric="Sales"),
            Goal(description="Beat competitor", metric="Market share"),
            Goal(description="Satisfy investors", metric="Growth rate"),
            Goal(description="Improve brand", metric="Brand awareness"),
            Goal(description="Expand market", metric="Customer base"),
            Goal(description="Reduce costs", metric="Budget"),  # Conflicting with quality
            Goal(description="Maximize quality", metric="Defect rate"),  # Conflicts with speed
        ],
        kpis=[
            KPI(name="Launch by target date", target="2 weeks"),
            KPI(name="Zero defects", target="0 bugs"),  # Impossible given timeline
            KPI(name="Cost reduction", target="50% below budget"),
            KPI(name="Revenue target", target="$10M in month 1"),
            KPI(name="Customer satisfaction", target="5/5 rating"),
            KPI(name="Market share", target="25% capture"),
            KPI(name="Feature completeness", target="100% of backlog"),
        ],
        risks=[
            Risk(
                description="Critical production bugs due to no QA",
                severity="critical",
                mitigation="None - skipping QA"
            ),
            Risk(
                description="Customer data loss from untested code",
                severity="critical",
                mitigation="None planned"
            ),
            Risk(
                description="System downtime and outages",
                severity="critical",
                mitigation="Hope for the best"
            ),
            Risk(
                description="Regulatory violations from compliance gaps",
                severity="critical",
                mitigation="Deal with it later"
            ),
        ],
        owners=[
            Owner(
                name="Unknown",
                role="Product Manager",
                responsibility="Unclear"
            )
        ],
        required_approvals=[],  # No approvals identified - red flag
        assumptions=[
            Assumption(
                description="Nothing will go wrong",
                criticality="critical"
            ),
            Assumption(
                description="Customers won't notice bugs",
                criticality="critical"
            )
        ],
        confidence=0.15,  # Very low confidence + high risk = blocked
        strategic_impact=StrategicImpact.CRITICAL,
        risk_score=9.5  # Nearly maximum risk
    )


# Demo fixture dictionary for easy access
DEMO_FIXTURES = {
    "compliant": create_compliant_decision,
    "budget_violation": create_budget_violation_decision,
    "privacy_violation": create_privacy_violation_decision,
    "blocked": create_blocked_decision,
}


def get_demo_fixture(name: str) -> Decision:
    """
    Get a demo fixture by name.

    Args:
        name: One of "compliant", "budget_violation", "privacy_violation", "blocked"

    Returns:
        Decision object

    Raises:
        ValueError if name not found
    """
    if name not in DEMO_FIXTURES:
        available = ", ".join(DEMO_FIXTURES.keys())
        raise ValueError(f"Unknown fixture '{name}'. Available: {available}")

    return DEMO_FIXTURES[name]()


def get_all_fixtures() -> dict[str, Decision]:
    """Get all demo fixtures as a dictionary."""
    return {name: factory() for name, factory in DEMO_FIXTURES.items()}
