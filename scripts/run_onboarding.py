"""
Run the full onboarding pipeline for Nexus Analytics against a local Neo4j instance.

Prerequisites:
    docker compose up -d          # start Neo4j on localhost:7687
    source venv/bin/activate
    pip install -r requirements.txt

Usage:
    python scripts/run_onboarding.py                          # seed + scout pipeline
    python scripts/run_onboarding.py --seed-only              # seed domain nodes only (no LLM)
    python scripts/run_onboarding.py --company nexus_analytics
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.config.company_config import (
    ApprovalHierarchyEntry,
    CompanyConfig,
    DecisionDimension,
    DepartmentConfig,
    GoalConflict,
    GovernanceRiskConfig,
    GovernanceRule,
    KPIConfig,
    RuleCondition,
    RuleConsequence,
    StrategicGoal,
)
from app.graph.neo4j_repository import Neo4jGraphRepository
from app.onboarding.onboarding_graph import run_onboarding
from app.onboarding.seed import seed_company_graph, serialize_seeded_nodes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_onboarding")


# ---------------------------------------------------------------------------
# Ground truth JSON → CompanyConfig adapter
# ---------------------------------------------------------------------------

def load_nexus_config() -> CompanyConfig:
    """
    Build a CompanyConfig for Nexus Analytics from the ground truth JSON.

    The ground truth JSON is an evaluation artifact (what scouts should find),
    not a direct CompanyConfig. This adapter converts it to the proper schema.
    """
    gt_path = Path(__file__).parent.parent / "dev" / "simulate" / "ground_truth" / "nexus_analytics.json"
    with open(gt_path) as f:
        gt = json.load(f)

    return CompanyConfig(
        company_id="nexus_analytics",
        company_name="Nexus Analytics",
        industry="b2b_saas",
        jurisdiction=["US"],
        currency="USD",
        decision_dimensions=[
            DecisionDimension(key="cost", type="number", unit="USD", description="Financial cost of the decision"),
            DecisionDimension(key="headcount_change", type="number", unit="headcount", description="Net headcount impact"),
            DecisionDimension(key="affects_compliance", type="boolean", description="Whether the decision has compliance implications"),
            DecisionDimension(key="vendor_contract_value", type="number", unit="USD", description="Total contract value for vendor decisions"),
            DecisionDimension(key="discount_pct", type="number", unit="%", description="Discount percentage for sales decisions"),
            DecisionDimension(key="involves_customer_data", type="boolean", description="Whether customer data is accessed or processed"),
        ],
        strategic_goals=[
            StrategicGoal(
                goal_id="G1", label="Revenue Growth", priority="high",
                description="Grow ARR through new customer acquisition and expansion",
                kpis=[
                    KPIConfig(kpi_id="arr", label="Annual Recurring Revenue", unit="USD", target="$10M"),
                    KPIConfig(kpi_id="nrr", label="Net Revenue Retention", unit="%", target=">120%"),
                ],
            ),
            StrategicGoal(
                goal_id="G2", label="Cost Stability", priority="high",
                description="Maintain operating costs within budget while supporting growth",
                kpis=[
                    KPIConfig(kpi_id="burn_rate", label="Monthly Burn Rate", unit="USD", target="<$800K"),
                    KPIConfig(kpi_id="cac", label="Customer Acquisition Cost", unit="USD", target="<$5K"),
                ],
            ),
            StrategicGoal(
                goal_id="G3", label="Data Compliance", priority="critical",
                description="Full compliance with data protection regulations",
                kpis=[
                    KPIConfig(kpi_id="compliance_score", label="Compliance Audit Score", unit="%", target="100%"),
                ],
            ),
            StrategicGoal(
                goal_id="G4", label="Engineering Velocity", priority="medium",
                description="Ship features faster with higher quality",
                owner_role="CTO",
                kpis=[
                    KPIConfig(kpi_id="deploy_freq", label="Deploy Frequency", unit="deploys/week", target=">5"),
                    KPIConfig(kpi_id="lead_time", label="Lead Time", unit="days", target="<3"),
                ],
            ),
        ],
        governance_rules=[
            GovernanceRule(
                rule_id="R1", name="CFO approval for large spend",
                description="Spend > $50K requires CFO approval",
                conditions=[RuleCondition(field="cost", operator=">", value=50000)],
                consequence=RuleConsequence(action="require_approval", approver_role="CFO"),
                source="documented", confidence="high", priority=10,
                governed_by_goal_ids=["G2"],
            ),
            GovernanceRule(
                rule_id="R2", name="Board approval for major spend",
                description="Spend > $200K requires board approval",
                conditions=[RuleCondition(field="cost", operator=">", value=200000)],
                consequence=RuleConsequence(
                    action="require_approval", approver_role="CEO",
                    escalation_role="Board", requires_sequential=True,
                ),
                source="documented", confidence="high", priority=20,
                governed_by_goal_ids=["G2"],
            ),
            GovernanceRule(
                rule_id="R3", name="Legal sign-off for customer data",
                description="Customer data usage requires Legal sign-off",
                conditions=[RuleCondition(field="involves_customer_data", operator="is_true")],
                consequence=RuleConsequence(action="require_approval", approver_role="General Counsel"),
                source="documented", confidence="high", priority=15,
                governed_by_goal_ids=["G3"],
            ),
            GovernanceRule(
                rule_id="R4", name="Procurement review for vendor contracts",
                description="Vendor contracts > $100K require procurement review",
                conditions=[RuleCondition(field="vendor_contract_value", operator=">", value=100000)],
                consequence=RuleConsequence(action="require_review", approver_role="CFO"),
                source="documented", confidence="high", priority=5,
                governed_by_goal_ids=["G2"],
            ),
            GovernanceRule(
                rule_id="R5", name="HR and department head for hiring",
                description="Hiring requires HR + department head approval",
                conditions=[RuleCondition(field="headcount_change", operator=">", value=0)],
                consequence=RuleConsequence(
                    action="require_approval", approver_role="HR Director",
                    requires_sequential=True,
                ),
                source="documented", confidence="high", priority=5,
                governed_by_goal_ids=["G4", "G2"],
            ),
            GovernanceRule(
                rule_id="R6", name="Q4 spending freeze",
                description="No new spend after Oct 15 in Q4",
                conditions=[RuleCondition(field="cost", operator=">", value=0)],
                consequence=RuleConsequence(action="flag", message="Q4 spending freeze — verify with CFO"),
                source="inferred", confidence="medium", priority=1,
                governed_by_goal_ids=["G2"],
                temporal_scope="Q4", recurring=True,
            ),
            GovernanceRule(
                rule_id="R7", name="CTO dev tool bypass",
                description="CTO can bypass procurement for dev tools < $20K",
                conditions=[RuleCondition(field="cost", operator="<", value=20000)],
                consequence=RuleConsequence(action="flag", message="CTO bypass pattern detected — may not require procurement"),
                source="inferred", confidence="low", priority=0,
                governed_by_goal_ids=["G4"],
            ),
        ],
        approval_hierarchy=[
            ApprovalHierarchyEntry(role="CEO", reports_to=None, approval_limit=None, approval_limit_note="Unlimited"),
            ApprovalHierarchyEntry(role="CFO", reports_to="CEO", approval_limit=200000),
            ApprovalHierarchyEntry(role="CTO", reports_to="CEO", approval_limit=None, approval_limit_note="Technical decisions"),
            ApprovalHierarchyEntry(role="VP Sales", reports_to="CEO", approval_limit=None, approval_limit_note="15% discount authority"),
            ApprovalHierarchyEntry(role="General Counsel", reports_to="CEO", approval_limit=None, approval_limit_note="Compliance gatekeeper"),
            ApprovalHierarchyEntry(role="HR Director", reports_to="CFO", approval_limit=None, approval_limit_note="Hiring decisions"),
        ],
        departments=[
            DepartmentConfig(dept_id="executive", label="Executive", member_roles=["CEO"]),
            DepartmentConfig(dept_id="finance", label="Finance", member_roles=["CFO"], parent_dept_id="executive"),
            DepartmentConfig(dept_id="engineering", label="Engineering", member_roles=["CTO"], parent_dept_id="executive"),
            DepartmentConfig(dept_id="sales", label="Sales", member_roles=["VP Sales"], parent_dept_id="executive"),
            DepartmentConfig(dept_id="legal", label="Legal", member_roles=["General Counsel"], parent_dept_id="executive"),
            DepartmentConfig(dept_id="hr", label="Human Resources", member_roles=["HR Director"], parent_dept_id="finance"),
        ],
        goal_conflicts=[
            GoalConflict(
                goal_id_a="G4", goal_id_b="G2",
                description="Engineering hiring velocity vs budget stability",
            ),
            GoalConflict(
                goal_id_a="G1", goal_id_b="G3",
                description="Sales revenue growth vs data compliance requirements",
            ),
            GoalConflict(
                goal_id_a="G4", goal_id_b="G3",
                description="Fast engineering shipping vs privacy review requirements",
            ),
        ],
        governance_risks=[
            GovernanceRiskConfig(
                risk_id="budget_overrun_risk",
                label="Budget Overrun Risk",
                risk_category="financial",
                severity="high",
                description="Risk of exceeding planned budget due to uncontrolled spending",
                generated_by_rule_ids=["R1", "R2"],
                mitigated_by_rule_ids=["R4"],
            ),
            GovernanceRiskConfig(
                risk_id="compliance_violation_risk",
                label="Compliance Violation Risk",
                risk_category="compliance",
                severity="critical",
                description="Risk of regulatory non-compliance due to improper data handling",
                generated_by_rule_ids=["R3"],
                mitigated_by_rule_ids=["R3"],
            ),
            GovernanceRiskConfig(
                risk_id="key_person_dependency_risk",
                label="Key Person Dependency Risk",
                risk_category="operational",
                severity="medium",
                description="Risk of critical bottleneck when key approvers are unavailable",
                generated_by_rule_ids=["R1", "R5"],
                mitigated_by_rule_ids=["R7"],
            ),
            GovernanceRiskConfig(
                risk_id="vendor_lock_in_risk",
                label="Vendor Lock-in Risk",
                risk_category="strategic",
                severity="medium",
                description="Risk of over-dependence on single vendor for critical infrastructure",
                generated_by_rule_ids=["R4"],
                mitigated_by_rule_ids=["R4"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(company_id: str, seed_only: bool = False) -> None:
    import time as _time
    t0 = _time.time()

    config = load_nexus_config()
    artifact_dir = str(Path(__file__).parent.parent / "dev" / "simulate" / "output" / company_id)

    if not Path(artifact_dir).exists():
        logger.error(f"Artifact directory not found: {artifact_dir}")
        sys.exit(1)

    repo = Neo4jGraphRepository()

    try:
        # Step 0: Initialize schema layer (MetaClass, OntologyClass, constraints, indexes)
        logger.info("=" * 60)
        logger.info("STEP 0: Initializing Neo4j schema layer")
        logger.info("=" * 60)
        await repo.initialize(company_id)

        # Step 1: Seed domain nodes from CompanyConfig
        logger.info("=" * 60)
        logger.info("STEP 1: Seeding domain layer from CompanyConfig")
        logger.info("=" * 60)
        seed_result = await seed_company_graph(config, repo)
        logger.info(f"Seed complete: {seed_result}")

        # Step 1b: Serialize seeded nodes context for scouts
        seeded_nodes_ctx = serialize_seeded_nodes(seed_result, config)
        logger.info(f"Seeded nodes context ({len(seeded_nodes_ctx)} chars)")

        if seed_only:
            logger.info("--seed-only: skipping scout pipeline")
            return

        # Step 2: Run scout pipeline on artifacts
        logger.info("=" * 60)
        logger.info(f"STEP 2: Running onboarding pipeline on {artifact_dir}")
        logger.info("=" * 60)
        # Collect seeded rule IDs for deduplication (Change 3.2)
        seeded_rule_ids = [r.rule_id for r in config.governance_rules]
        seeded_goal_ids = [g.goal_id for g in config.strategic_goals]
        seeded_goal_labels = {g.goal_id: g.label for g in config.strategic_goals}

        report = await run_onboarding(
            company_id=company_id,
            artifact_dir=artifact_dir,
            repo=repo,
            seeded_nodes_context=seeded_nodes_ctx,
            seeded_rule_ids=seeded_rule_ids,
            seeded_goal_ids=seeded_goal_ids,
            seeded_goal_labels=seeded_goal_labels,
        )

        elapsed = _time.time() - t0

        # Print report
        logger.info("=" * 60)
        logger.info("ONBOARDING REPORT")
        logger.info("=" * 60)
        logger.info(f"  Company:              {report.company_id}")
        logger.info(f"  Artifacts processed:  {report.total_artifacts_processed}")
        logger.info(f"  Confidence:           {report.confidence:.3f}")
        logger.info(f"  Completed:            {report.completed}")
        logger.info(f"  Orphan rate:          {report.orphan_rate:.3f}")
        logger.info(f"  Edge-to-node ratio:   {report.edge_to_node_ratio:.3f}")
        logger.info(f"  Edges dropped:        {report.edges_dropped}")
        logger.info(f"  Nodes by type:        {report.nodes_by_type}")
        logger.info(f"  Edges by type:        {report.edges_by_type}")
        logger.info(f"  Elapsed:              {elapsed:.1f}s")
        if report.gaps:
            logger.warning(f"  Gaps:                 {report.gaps}")
        if report.warnings:
            logger.warning(f"  Warnings:             {report.warnings}")
        if report.structural_warnings:
            logger.warning(f"  Structural warnings:  {report.structural_warnings}")

        # Query Neo4j for total counts
        from neo4j import GraphDatabase as _GD
        _driver = _GD.driver('bolt://localhost:7687', auth=('neo4j', 'password'))
        db = os.getenv(f"NEO4J_DB_{company_id.upper()}", f"{company_id}_governance")
        with _driver.session(database=db) as s:
            n_count = s.run("MATCH (n) RETURN count(n) as c").single()["c"]
            e_count = s.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
        _driver.close()
        logger.info(f"  Neo4j totals:         {n_count} nodes, {e_count} edges")

    finally:
        await repo.close()
        logger.info("Neo4j connection closed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run onboarding pipeline against local Neo4j")
    parser.add_argument("--company", default="nexus_analytics", help="Company ID (default: nexus_analytics)")
    parser.add_argument("--seed-only", action="store_true", help="Only seed domain nodes, skip scout pipeline")
    args = parser.parse_args()

    asyncio.run(main(args.company, seed_only=args.seed_only))
