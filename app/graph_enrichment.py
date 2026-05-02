"""
Graph Enrichment - Build Ontology-Level Governance Graph

Adds strategic goals, rules, alignment edges, and threshold violations
to create a true governance knowledge graph.
"""

from typing import Optional
from app.ontology.models import Node, Edge
from app.ontology.node_types import NodeType
from app.ontology.edge_predicates import EdgePredicate
import logging

logger = logging.getLogger(__name__)


# Goal categories that encode the ontological type of a strategic goal.
# These are structural config values set in company JSON — NOT semantic keyword classifiers.
_COMPLIANCE_GOAL_CATEGORIES = {"regulatory_compliance", "data_privacy", "compliance"}
_COST_STABILITY_CATEGORIES = {"cost_stability", "cost_efficiency", "cost_reduction"}
_REVENUE_GROWTH_CATEGORIES = {"revenue_growth", "revenue", "growth"}


def _build_goal_node(goal_id: str, goal: dict) -> Node:
    """Build a GOAL node from a strategic goal dict. Used by add_strategic_goals and add_cost_goal_edges."""
    goal_name = goal.get("name", "")
    goal_props: dict = {"name": goal_name}
    if goal.get("priority"):
        goal_props["priority"] = goal["priority"]
    if goal.get("owner_id"):
        goal_props["owner_id"] = goal["owner_id"]
    return Node(id=f"goal_{goal_id}", type=NodeType.GOAL, label=goal_name, properties=goal_props)


def _extract_kpi_keywords(kpis: list) -> set:
    """Extract keywords from a list of KPI dicts or strings. Used for SUPPORTS matching."""
    keywords = set()
    for kpi in kpis:
        kpi_name = kpi.get("name", "") if isinstance(kpi, dict) else str(kpi)
        for w in kpi_name.replace("-", " ").replace("%", " ").split():
            if len(w) >= 2 and not w.isdigit():
                keywords.add(w)
    return keywords


async def add_strategic_goals(
    decision_id: str,
    decision: dict,
    company_context: dict,
    add_node_fn,
    add_edge_fn
) -> tuple[list[Node], list[Edge]]:
    """
    Add Strategic Goal nodes (G1, G2, G3) from company context and create alignment edges.

    Edge types:
    - SUPPORTS: decision KPIs overlap with goal KPIs (positive alignment)
    - CONFLICTS_WITH: decision involves a compliance risk that threatens a
      compliance/regulatory goal (e.g. unauthorized PII access → G2)

    Returns:
        (nodes, edges) tuple
    """
    nodes = []
    edges = []

    strategic_goals = company_context.get("strategic_goals", [])
    if not strategic_goals:
        return nodes, edges

    # LLM-extracted boolean signals — NOT keyword tables.
    # These are structured outputs from the extractor, used here as classifiers.
    decision_violates_compliance = (
        decision.get("involves_compliance_risk") is True and
        decision.get("uses_pii") is True
    )
    involves_hiring = decision.get("involves_hiring") is True
    # Revenue-growth support signal: hiring is explicitly justified by strategic growth
    # when strategic_impact is medium or higher (not null/low).
    has_strategic_rationale = decision.get("strategic_impact") not in (None, "low", "none")

    # Extract decision KPI keywords for SUPPORTS matching (fallback for uncategorised goals)
    decision_kpi_keywords = _extract_kpi_keywords(decision.get("kpis", []))

    for goal in strategic_goals:
        goal_id = goal.get("goal_id", "")
        if not goal_id:
            continue

        goal_name = goal.get("name", "")
        goal_category = goal.get("category", "")
        goal_node_id = f"goal_{goal_id}"

        edge_predicate = None
        reasoning = None

        # ── Priority 1: compliance violation → CONFLICTS_WITH compliance goal ──
        if decision_violates_compliance and goal_category in _COMPLIANCE_GOAL_CATEGORIES:
            edge_predicate = EdgePredicate.CONFLICTS_WITH
            reasoning = "Compliance violation: unauthorized PII access conflicts with regulatory compliance goal"

        # ── Priority 2: hiring → CONFLICTS_WITH cost_stability goal ──────────
        # Hiring increases fixed operating costs (salary, benefits) regardless of
        # whether an explicit cost value was extracted. Category-based, not keyword.
        elif involves_hiring and goal_category in _COST_STABILITY_CATEGORIES:
            edge_predicate = EdgePredicate.CONFLICTS_WITH
            reasoning = "Hiring increases fixed operating costs, conflicting with cost stability goal"

        # ── Priority 3: hiring with strategic rationale → SUPPORTS growth goal ─
        elif involves_hiring and has_strategic_rationale and goal_category in _REVENUE_GROWTH_CATEGORIES:
            edge_predicate = EdgePredicate.SUPPORTS
            reasoning = "Hiring for revenue growth rationale — strategically aligned with revenue growth goal"

        # ── Fallback: KPI keyword overlap → SUPPORTS ─────────────────────────
        # Used for goals without a category or when none of the above signals fire.
        else:
            sg_kpi_keywords = set()
            for w in goal_name.replace("-", " ").replace("%", " ").split():
                if len(w) >= 2 and not w.isdigit():
                    sg_kpi_keywords.add(w)
            sg_kpi_keywords |= _extract_kpi_keywords(goal.get("kpis", []))
            if decision_kpi_keywords & sg_kpi_keywords:
                edge_predicate = EdgePredicate.SUPPORTS
                reasoning = "KPI alignment: decision KPIs match strategic goal KPIs"

        if edge_predicate is None:
            continue

        goal_node = _build_goal_node(goal_id, goal)
        try:
            await add_node_fn(goal_node)
            nodes.append(goal_node)
        except ValueError:
            nodes.append(goal_node)

        edge = Edge(from_node=decision_id, to_node=goal_node_id, predicate=edge_predicate, properties={"reasoning": reasoning})
        await add_edge_fn(edge)
        edges.append(edge)

        # For CONFLICTS_WITH, add a Risk node so the graph shows the downstream consequence
        if edge_predicate == EdgePredicate.CONFLICTS_WITH:
            risk_id = f"{decision_id}_goal_conflict_risk_{goal_id}"
            risk_node = Node(
                id=risk_id,
                type=NodeType.RISK,
                label=f"Strategic conflict: {goal_name}",
                properties={
                    "description": reasoning,
                    "severity": "medium",
                    "source": "strategic_conflict",
                    "goal_id": goal_id,
                }
            )
            try:
                await add_node_fn(risk_node)
                nodes.append(risk_node)
            except ValueError:
                pass
            risk_edge = Edge(
                from_node=goal_node_id, to_node=risk_id,
                predicate=EdgePredicate.GENERATES_RISK,
                properties={"reason": "Strategic conflict generates downstream risk"},
            )
            await add_edge_fn(risk_edge)
            edges.append(risk_edge)

    logger.info(f"Added {len(nodes)} strategic goal nodes, {len(edges)} alignment edges")
    return nodes, edges


async def add_governance_rules(
    decision_id: str,
    decision: dict,
    governance: dict,
    company_context: dict,
    add_node_fn,
    add_edge_fn
) -> tuple[list[Node], list[Edge]]:
    """
    Add RULE nodes for governance rules that are graph-visible.

    Only includes rules with visible_in_graph=true:
    - TRIGGERED: rule was triggered and took action
    - UNSATISFIED: rule requirements not met (violation)

    IMPORTANT: Does NOT create Decision → Rule edges for financial rules,
    because those go through Cost → EXCEEDS_THRESHOLD → Rule chains.
    Only creates Decision → TRIGGERS_RULE edges for non-financial rules.

    Returns:
        (nodes, edges) tuple
    """
    nodes = []
    edges = []

    # Get rules from company context - note: field is "governance_rules" not "governance.rules"
    rules_data = company_context.get("governance_rules", [])
    if not rules_data:
        return nodes, edges

    # Build rule lookup map and visible rule map
    rule_lookup = {r.get("rule_id"): r for r in rules_data}
    triggered_rules_list = governance.get("triggered_rules", [])

    # Filter to only visible_in_graph=true rules
    visible_rules = {
        r.get("rule_id"): r for r in triggered_rules_list
        if r.get("visible_in_graph", False)
    }

    for rule in rules_data:
        rule_id = rule.get("rule_id", "")
        if not rule_id:
            continue

        # Only add RULE nodes that are visible in graph (TRIGGERED or UNSATISFIED)
        if rule_id not in visible_rules:
            continue

        visible_rule = visible_rules[rule_id]

        # Create RULE node with status from governance evaluation
        rule_status = visible_rule.get("status", "TRIGGERED")
        rule_reason = visible_rule.get("reason", "")

        rule_props: dict = {"name": rule.get("name", ""), "status": rule_status, "reason": rule_reason}
        if rule.get("type"):
            rule_props["type"] = rule["type"]
        if rule.get("description"):
            rule_props["description"] = rule["description"]
        rule_node = Node(
            id=f"rule_{rule_id}",
            type=NodeType.RULE,
            label=f"{rule_id}: {rule.get('name', '')}",
            properties=rule_props,
        )

        try:
            await add_node_fn(rule_node)
            nodes.append(rule_node)
        except ValueError:
            # Rule node already exists (shared across decisions)
            nodes.append(rule_node)  # Still add to return list

        # Only create Decision → TRIGGERS_RULE edge for NON-financial, TRIGGERED rules
        # Financial rules get their edges through Cost → EXCEEDS_THRESHOLD → Rule chain
        # UNSATISFIED rules get edge with different semantics (violation, not trigger)
        rule_type = rule.get("type", "")

        if rule_status == "TRIGGERED" and rule_type not in ["financial", "capital_expenditure"]:
            edge = Edge(
                from_node=decision_id,
                to_node=f"rule_{rule_id}",
                predicate=EdgePredicate.GOVERNED_BY,
            )
            await add_edge_fn(edge)
            edges.append(edge)
        elif rule_status == "UNSATISFIED":
            edge = Edge(
                from_node=decision_id,
                to_node=f"rule_{rule_id}",
                predicate=EdgePredicate.GOVERNED_BY,
                properties={"violation_type": "UNSATISFIED", "reason": rule_reason},
            )
            await add_edge_fn(edge)
            edges.append(edge)

    logger.info(f"Added {len(nodes)} rule nodes, {len(edges)} trigger edges")
    return nodes, edges


async def add_cost_threshold_edges(
    decision_id: str,
    decision: dict,
    governance: dict,
    cost_node_id: Optional[str],
    company_context: dict,
    add_edge_fn
) -> list[Edge]:
    """
    Add EXCEEDS_THRESHOLD edges when cost exceeds rule thresholds.

    Args:
        cost_node_id: ID of the cost node (if exists)
        company_context: Company data with governance_rules

    Returns:
        list of edges
    """
    edges = []

    if not cost_node_id:
        return edges

    cost = decision.get("cost")
    if not cost or not isinstance(cost, (int, float)):
        return edges

    # Build rule lookup map from company context
    company_rules = {r.get("rule_id"): r for r in company_context.get("governance_rules", [])}

    # Check triggered rules for financial threshold violations
    for rule in governance.get("triggered_rules", []):
        rule_id = rule.get("rule_id", "")
        if not rule_id:
            continue

        # Only create edge if rule is visible in graph (node exists)
        if not rule.get("visible_in_graph", False):
            continue

        # Look up full rule definition from company context
        company_rule = company_rules.get(rule_id)
        if not company_rule:
            continue

        rule_type = company_rule.get("type", "")
        condition = company_rule.get("condition", {})

        # If it's a financial rule (R1, R2) and triggered, add threshold edge
        if rule_type in ["financial", "capital_expenditure"]:
            edge = Edge(
                from_node=cost_node_id,
                to_node=f"rule_{rule_id}",
                predicate=EdgePredicate.EXCEEDS_THRESHOLD,
                properties={
                    "operator": condition.get("operator", ">"),
                    "threshold": condition.get("value"),
                    "observed": cost,
                },
            )
            await add_edge_fn(edge)
            edges.append(edge)

    logger.info(f"Added {len(edges)} cost threshold edges")
    return edges


async def add_approval_hierarchy_edges(
    decision_id: str,
    governance: dict,
    add_edge_fn
) -> list[Edge]:
    """
    Add ESCALATES_TO edges to show approval chain hierarchy.

    Returns:
        list of edges
    """
    edges = []

    approval_chain = governance.get("approval_chain", [])
    if len(approval_chain) < 2:
        return edges

    # Level ordering for escalation (low to high)
    level_order = {
        "team_lead": 1,
        "department_head": 2,
        "vp": 3,
        "c_level": 4
    }

    # Create lookup: (level, role) -> original index
    # Approver node IDs use original index from approval_chain
    original_indices = {}
    for idx, step in enumerate(approval_chain):
        key = (step.get("level"), step.get("role"))
        original_indices[key] = idx

    # Sort by level to ensure correct escalation order (low to high)
    sorted_chain = sorted(
        approval_chain,
        key=lambda x: level_order.get(x.get("level", "team_lead"), 0)
    )

    for i in range(len(sorted_chain) - 1):
        current_step = sorted_chain[i]
        next_step = sorted_chain[i + 1]

        # Get original indices for ID generation
        current_idx = original_indices.get((current_step.get("level"), current_step.get("role")), i)
        next_idx = original_indices.get((next_step.get("level"), next_step.get("role")), i+1)

        current_approver_id = f"{decision_id}_approver_{current_step.get('level')}_{current_idx}"
        next_approver_id = f"{decision_id}_approver_{next_step.get('level')}_{next_idx}"

        edge = Edge(
            from_node=current_approver_id,
            to_node=next_approver_id,
            predicate=EdgePredicate.ESCALATES_TO,
            properties={"escalation_reason": f"{current_step.get('role')} → {next_step.get('role')}"},
        )
        await add_edge_fn(edge)
        edges.append(edge)

    logger.info(f"Added {len(edges)} escalation edges")
    return edges


async def add_cost_goal_edges(
    decision_id: str,
    decision: dict,
    company_context: dict,
    cost_node_id: Optional[str],
    add_node_fn,
    add_edge_fn
) -> tuple[list[Node], list[Edge]]:
    """
    Add Cost → SUPPORTS/CONFLICTS_WITH → Strategic Goal edges.
    Add Goal → GENERATES_RISK → Risk edges for conflicts.

    Returns:
        (nodes, edges) tuple
    """
    nodes = []
    edges = []

    if not cost_node_id:
        return nodes, edges

    cost = decision.get("cost")
    if not cost or not isinstance(cost, (int, float)) or cost <= 0:
        return nodes, edges

    strategic_goals = company_context.get("strategic_goals", [])
    if not strategic_goals:
        return nodes, edges

    # Extract decision KPI keywords for matching
    decision_kpi_keywords = _extract_kpi_keywords(decision.get("kpis", []))

    for goal in strategic_goals:
        goal_id = goal.get("goal_id", "")
        if not goal_id:
            continue

        goal_name = goal.get("name", "")

        # Check for KPI alignment (SUPPORTS)
        sg_kpi_keywords = set()
        name_keywords = [w for w in goal_name.replace("-", " ").replace("%", " ").split()
                        if len(w) >= 2 and not w.isdigit()]
        sg_kpi_keywords.update(name_keywords)
        sg_kpi_keywords |= _extract_kpi_keywords(goal.get("kpis", []))

        # Check for conflicts: cost-incurring decision vs. cost-stability goal.
        # Uses goal category (structural config) — not keyword matching.
        has_conflict = goal.get("category") in _COST_STABILITY_CATEGORIES and cost > 0

        # Cost only creates CONFLICTS_WITH edges (not SUPPORTS)
        # SUPPORTS edges come from Decision node
        if not has_conflict:
            continue

        edge_predicate = EdgePredicate.CONFLICTS_WITH
        edge_reasoning = f"Cost expenditure ({cost:,}) conflicts with {goal_name} goal"

        goal_node = _build_goal_node(goal_id, goal)

        try:
            await add_node_fn(goal_node)
            nodes.append(goal_node)
        except ValueError:
            nodes.append(goal_node)  # Already exists

        # Cost → CONFLICTS_WITH → Goal
        edge = Edge(
            from_node=cost_node_id,
            to_node=f"goal_{goal_id}",
            predicate=edge_predicate,
            properties={"reasoning": edge_reasoning},
        )
        await add_edge_fn(edge)
        edges.append(edge)

        # Goal → GENERATES_RISK → Risk
        risk_id = f"{decision_id}_strategic_conflict_risk_{goal_id}"
        risk_node = Node(
            id=risk_id,
            type=NodeType.RISK,
            label=f"Strategic conflict: {goal_name}",
            properties={
                "description": f"Cost expenditure conflicts with '{goal_name}' goal, generating strategic risk",
                "severity": "medium",
                "source": "strategic_conflict",
                "goal_id": goal_id,
            }
        )

        try:
            await add_node_fn(risk_node)
            nodes.append(risk_node)
        except ValueError:
            pass

        risk_edge = Edge(
            from_node=f"goal_{goal_id}",
            to_node=risk_id,
            predicate=EdgePredicate.GENERATES_RISK,
            properties={"reason": "Strategic conflict generates risk"},
        )
        await add_edge_fn(risk_edge)
        edges.append(risk_edge)

    logger.info(f"Added {len(edges)} cost-goal edges")
    return nodes, edges


async def add_rule_risk_edges(
    decision_id: str,
    decision: dict,
    governance: dict,
    add_node_fn,
    add_edge_fn,
    has_structural_conflicts: bool = False,
) -> tuple[list[Node], list[Edge]]:
    """
    Add Rule → GENERATES_RISK → Risk edges for LLM-extracted risks.

    Matches risks to rules by keyword matching.

    Returns:
        (nodes, edges) tuple
    """
    nodes = []
    edges = []

    risks = decision.get("risks", [])
    if not risks:
        return nodes, edges

    # Get visible triggered rules
    triggered_rules = governance.get("triggered_rules", [])
    visible_rules = [r for r in triggered_rules if r.get("visible_in_graph", False)]

    if not visible_rules:
        return nodes, edges

    # Match each risk to a rule
    for idx, risk in enumerate(risks):
        risk_id = f"{decision_id}_risk_{idx}"
        risk_desc = risk.get("description", "") if isinstance(risk, dict) else str(risk)

        # Skip strategic risks (handled in add_cost_goal_edges)
        if "strategic" in risk_desc.lower():
            continue

        # Keyword matching to find related rule
        matched_rule_id = None

        # Check for budget/financial keywords
        if any(kw in risk_desc for kw in ["budget", "cost", "financial", "expenditure"]):
            # Find financial rule
            for r in visible_rules:
                if r.get("rule_type") in ["financial", "capital_expenditure"]:
                    matched_rule_id = r.get("rule_id")
                    break

        # Check for compliance keywords
        elif any(kw in risk_desc for kw in ["compliance", "legal", "ethics", "regulatory", "privacy"]):
            # Find compliance rule
            for r in visible_rules:
                if r.get("rule_type") == "compliance":
                    matched_rule_id = r.get("rule_id")
                    break

        # Default: use first visible rule — but skip when structural conflict risks
        # already exist (those default-fallback connections duplicate goal conflicts)
        if not matched_rule_id and visible_rules and not has_structural_conflicts:
            matched_rule_id = visible_rules[0].get("rule_id")

        # Create Rule → GENERATES_RISK → Risk edge
        if matched_rule_id:
            edge = Edge(
                from_node=f"rule_{matched_rule_id}",
                to_node=risk_id,
                predicate=EdgePredicate.GENERATES_RISK,
                properties={"risk_description": risk_desc[:100]},
            )
            await add_edge_fn(edge)
            edges.append(edge)

    logger.info(f"Added {len(edges)} rule-risk edges")
    return nodes, edges
