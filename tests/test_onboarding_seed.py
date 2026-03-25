"""
Tests for Step 6 — onboarding seed + InMemoryGraphRepository.

All tests use InMemoryGraphRepository (no Neo4j connection required).

Validates:
  - seed_company_graph writes correct node types and counts
  - Node IDs follow the stable ID scheme
  - MEASURED_BY edges connect Goals → KPIs
  - REQUIRES_APPROVAL_FROM edges connect Rules → Actors
  - REQUIRES_REVIEW_FROM edges connect review-action rules
  - ESCALATES_TO edges connect approval hierarchy
  - Jurisdiction nodes are created
  - Re-running seed is idempotent (node count stays the same)
  - InMemoryGraphRepository.get_governance_context traversal works
"""

import pytest
import pytest_asyncio

from app.config.company_config import (
    ApprovalHierarchyEntry,
    CompanyConfig,
    ConditionOperator,
    GovernanceRule,
    KPIConfig,
    RuleAction,
    RuleCondition,
    RuleConsequence,
    StrategicGoal,
)
from app.graph.in_memory_repository import InMemoryGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import DecisionGraph, Edge, Node, make_node_id
from app.ontology.node_types import NodeType
from app.onboarding.seed import seed_company_graph


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(
    company_id: str = "test_co",
    extra_rules: list | None = None,
    extra_goals: list | None = None,
    extra_hierarchy: list | None = None,
) -> CompanyConfig:
    """Minimal but valid CompanyConfig for test use."""
    goals = [
        StrategicGoal(
            goal_id="G1",
            label="Revenue Growth",
            priority="high",
            kpis=[
                KPIConfig(kpi_id="K1", label="ARR", unit="USD", target="> 5M"),
                KPIConfig(kpi_id="K2", label="Churn Rate", unit="%", target="< 5%"),
            ],
        ),
        StrategicGoal(
            goal_id="G2",
            label="Cost Stability",
            priority="medium",
            kpis=[
                KPIConfig(kpi_id="K3", label="OpEx", unit="USD"),
            ],
        ),
    ]
    if extra_goals:
        goals.extend(extra_goals)

    rules = [
        GovernanceRule(
            rule_id="R1",
            name="CFO approval for large spend",
            conditions=[RuleCondition(field="cost", operator=ConditionOperator.GT, value=50000)],
            consequence=RuleConsequence(action=RuleAction.REQUIRE_APPROVAL, approver_role="CFO"),
            source="documented",
            confidence="high",
        ),
        GovernanceRule(
            rule_id="R2",
            name="Legal review for data usage",
            conditions=[RuleCondition(field="uses_customer_data", operator=ConditionOperator.IS_TRUE)],
            consequence=RuleConsequence(action=RuleAction.REQUIRE_REVIEW, approver_role="Legal Counsel"),
            source="documented",
            confidence="high",
        ),
    ]
    if extra_rules:
        rules.extend(extra_rules)

    hierarchy = [
        ApprovalHierarchyEntry(role="CEO", approval_limit=None),
        ApprovalHierarchyEntry(role="CFO", reports_to="CEO", approval_limit=500000.0),
        ApprovalHierarchyEntry(role="Legal Counsel", reports_to="CEO"),
    ]
    if extra_hierarchy:
        hierarchy.extend(extra_hierarchy)

    return CompanyConfig(
        company_id=company_id,
        company_name="Test Company",
        industry="b2b_saas",
        jurisdiction=["US", "GDPR"],
        currency="USD",
        decision_dimensions=[
            {"key": "cost", "type": "number", "unit": "USD"},
            {"key": "uses_customer_data", "type": "boolean"},
        ],
        strategic_goals=goals,
        governance_rules=rules,
        approval_hierarchy=hierarchy,
    )


@pytest.fixture
def config() -> CompanyConfig:
    return _make_config()


@pytest.fixture
def repo() -> InMemoryGraphRepository:
    return InMemoryGraphRepository()


# ---------------------------------------------------------------------------
# Basic seeding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_returns_summary(config, repo):
    summary = await seed_company_graph(config, repo)
    assert summary["company_id"] == "test_co"
    assert summary["nodes_written"] > 0
    assert summary["edges_written"] > 0


@pytest.mark.asyncio
async def test_seed_creates_goal_nodes(config, repo):
    await seed_company_graph(config, repo)
    goals = repo.get_nodes_by_type(NodeType.GOAL)
    assert len(goals) == 2
    goal_ids = {g.id for g in goals}
    assert make_node_id("test_co", NodeType.GOAL, "G1") in goal_ids
    assert make_node_id("test_co", NodeType.GOAL, "G2") in goal_ids


@pytest.mark.asyncio
async def test_seed_creates_kpi_nodes(config, repo):
    await seed_company_graph(config, repo)
    kpis = repo.get_nodes_by_type(NodeType.KPI)
    assert len(kpis) == 3  # K1, K2, K3
    kpi_labels = {k.label for k in kpis}
    assert "ARR" in kpi_labels
    assert "Churn Rate" in kpi_labels
    assert "OpEx" in kpi_labels


@pytest.mark.asyncio
async def test_seed_creates_rule_nodes(config, repo):
    await seed_company_graph(config, repo)
    rules = repo.get_nodes_by_type(NodeType.RULE)
    assert len(rules) == 2
    rule_ids = {r.id for r in rules}
    assert make_node_id("test_co", NodeType.RULE, "R1") in rule_ids
    assert make_node_id("test_co", NodeType.RULE, "R2") in rule_ids


@pytest.mark.asyncio
async def test_seed_creates_actor_nodes(config, repo):
    await seed_company_graph(config, repo)
    actors = repo.get_nodes_by_type(NodeType.ACTOR)
    # CEO, CFO, Legal Counsel = 3 unique actors
    assert len(actors) == 3
    roles = {a.label for a in actors}
    assert "CEO" in roles
    assert "CFO" in roles
    assert "Legal Counsel" in roles


@pytest.mark.asyncio
async def test_seed_creates_jurisdiction_nodes(config, repo):
    await seed_company_graph(config, repo)
    jurisdictions = repo.get_nodes_by_type(NodeType.JURISDICTION)
    assert len(jurisdictions) == 2
    codes = {j.label for j in jurisdictions}
    assert "US" in codes
    assert "GDPR" in codes


# ---------------------------------------------------------------------------
# Node ID scheme
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_goal_node_ids_follow_stable_scheme(config, repo):
    await seed_company_graph(config, repo)
    goals = repo.get_nodes_by_type(NodeType.GOAL)
    for g in goals:
        parts = g.id.split(":")
        assert len(parts) == 3
        assert parts[0] == "test_co"
        assert parts[1] == "goal"


@pytest.mark.asyncio
async def test_rule_node_ids_are_lowercase(config, repo):
    await seed_company_graph(config, repo)
    rules = repo.get_nodes_by_type(NodeType.RULE)
    for r in rules:
        assert r.id == r.id.lower()


@pytest.mark.asyncio
async def test_actor_node_id_uses_role_slug(config, repo):
    await seed_company_graph(config, repo)
    actor_ids = {a.id for a in repo.get_nodes_by_type(NodeType.ACTOR)}
    assert make_node_id("test_co", NodeType.ACTOR, "Legal Counsel") in actor_ids


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_measured_by_edges_connect_goals_to_kpis(config, repo):
    await seed_company_graph(config, repo)
    measured_by = repo.get_edges_by_predicate(EdgePredicate.MEASURED_BY)
    assert len(measured_by) == 3  # K1+K2 for G1, K3 for G2

    g1_id = make_node_id("test_co", NodeType.GOAL, "G1")
    g1_targets = {e.to_node for e in measured_by if e.from_node == g1_id}
    assert len(g1_targets) == 2


@pytest.mark.asyncio
async def test_requires_approval_from_edge_for_r1(config, repo):
    await seed_company_graph(config, repo)
    approval_edges = repo.get_edges_by_predicate(EdgePredicate.REQUIRES_APPROVAL_FROM)
    assert len(approval_edges) == 1

    r1_id = make_node_id("test_co", NodeType.RULE, "R1")
    cfo_id = make_node_id("test_co", NodeType.ACTOR, "CFO")
    assert any(e.from_node == r1_id and e.to_node == cfo_id for e in approval_edges)


@pytest.mark.asyncio
async def test_requires_review_from_edge_for_r2(config, repo):
    await seed_company_graph(config, repo)
    review_edges = repo.get_edges_by_predicate(EdgePredicate.REQUIRES_REVIEW_FROM)
    assert len(review_edges) == 1

    r2_id = make_node_id("test_co", NodeType.RULE, "R2")
    legal_id = make_node_id("test_co", NodeType.ACTOR, "Legal_Counsel")
    # Legal Counsel slug → "legal_counsel"
    legal_id_correct = make_node_id("test_co", NodeType.ACTOR, "Legal Counsel")
    assert any(e.from_node == r2_id and e.to_node == legal_id_correct for e in review_edges)


@pytest.mark.asyncio
async def test_escalates_to_edges_follow_reports_to(config, repo):
    await seed_company_graph(config, repo)
    escalates = repo.get_edges_by_predicate(EdgePredicate.ESCALATES_TO)
    # CFO → CEO, Legal Counsel → CEO = 2 edges
    assert len(escalates) == 2

    cfo_id = make_node_id("test_co", NodeType.ACTOR, "CFO")
    ceo_id = make_node_id("test_co", NodeType.ACTOR, "CEO")
    assert any(e.from_node == cfo_id and e.to_node == ceo_id for e in escalates)


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_summary_node_counts(config, repo):
    summary = await seed_company_graph(config, repo)
    assert summary["goals"] == 2
    assert summary["kpis"] == 3
    assert summary["rules"] == 2
    assert summary["actors"] == 3
    assert summary["jurisdictions"] == 2


@pytest.mark.asyncio
async def test_summary_total_nodes_written_matches_repo(config, repo):
    summary = await seed_company_graph(config, repo)
    # goals(2) + kpis(3) + rules(2) + actors(3) + jurisdictions(2) = 12
    assert summary["nodes_written"] == repo.node_count()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_is_idempotent(config, repo):
    """Re-seeding should not increase node count (MERGE semantics)."""
    await seed_company_graph(config, repo)
    count_after_first = repo.node_count()

    await seed_company_graph(config, repo)
    count_after_second = repo.node_count()

    assert count_after_first == count_after_second


# ---------------------------------------------------------------------------
# InMemoryGraphRepository — write_graph + get_governance_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_graph_then_get_governance_context():
    """
    write_graph stores nodes/edges; get_governance_context returns the
    correct subgraph within 2 hops.
    """
    repo = InMemoryGraphRepository()
    cid = "nexus"

    decision_id = make_node_id(cid, NodeType.DECISION, "d001")
    rule_id = make_node_id(cid, NodeType.RULE, "R1")
    actor_id = make_node_id(cid, NodeType.ACTOR, "cfo")
    risk_id = make_node_id(cid, NodeType.RISK, "r001")

    nodes = [
        Node(id=decision_id, type=NodeType.DECISION, label="Hire 5 engineers", properties={}),
        Node(id=rule_id, type=NodeType.RULE, label="Headcount rule", properties={}),
        Node(id=actor_id, type=NodeType.ACTOR, label="CFO", properties={"role": "CFO"}),
        Node(id=risk_id, type=NodeType.RISK, label="Budget risk", properties={"severity": "high"}),
    ]
    edges = [
        Edge(from_node=decision_id, to_node=rule_id, predicate=EdgePredicate.GOVERNED_BY),
        Edge(from_node=rule_id, to_node=actor_id, predicate=EdgePredicate.REQUIRES_APPROVAL_FROM),
        Edge(from_node=decision_id, to_node=risk_id, predicate=EdgePredicate.HAS_RISK),
    ]
    graph = DecisionGraph(decision_id=decision_id, nodes=nodes, edges=edges)
    await repo.write_graph(graph, cid)

    ctx = await repo.get_governance_context(decision_id, depth=2)

    assert ctx["decision"].id == decision_id
    assert len(ctx["policies"]) == 1          # rule_id
    assert ctx["policies"][0].id == rule_id
    assert len(ctx["actors"]) == 1             # cfo (2 hops via rule)
    assert ctx["actors"][0].id == actor_id
    assert len(ctx["risks"]) == 1
    assert ctx["risks"][0].id == risk_id


@pytest.mark.asyncio
async def test_get_governance_context_missing_decision():
    repo = InMemoryGraphRepository()
    ctx = await repo.get_governance_context("nexus:decision:nonexistent")
    assert ctx["decision"] is None
    assert ctx["actors"] == []


@pytest.mark.asyncio
async def test_get_node_returns_property_dict():
    repo = InMemoryGraphRepository()
    node_id = make_node_id("acme", NodeType.GOAL, "G1")
    node = Node(
        id=node_id,
        type=NodeType.GOAL,
        label="Revenue",
        properties={"priority": "high"},
    )
    await repo.write_node(node, "acme")

    result = await repo.get_node(node_id, "acme")
    assert result is not None
    assert result["id"] == node_id
    assert result["label"] == "Revenue"
    assert result["priority"] == "high"


@pytest.mark.asyncio
async def test_get_node_returns_none_for_missing():
    repo = InMemoryGraphRepository()
    result = await repo.get_node("acme:goal:nonexistent", "acme")
    assert result is None


# ---------------------------------------------------------------------------
# Multi-company isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_two_companies_isolated():
    """Seeding two companies into the same in-memory repo uses different node IDs."""
    config_a = _make_config("company_a")
    config_b = _make_config("company_b")
    repo = InMemoryGraphRepository()

    await seed_company_graph(config_a, repo)
    await seed_company_graph(config_b, repo)

    all_goals = repo.get_nodes_by_type(NodeType.GOAL)
    a_goals = [g for g in all_goals if g.id.startswith("company_a:")]
    b_goals = [g for g in all_goals if g.id.startswith("company_b:")]

    assert len(a_goals) == 2
    assert len(b_goals) == 2
    # No ID collisions
    a_ids = {g.id for g in a_goals}
    b_ids = {g.id for g in b_goals}
    assert a_ids.isdisjoint(b_ids)
