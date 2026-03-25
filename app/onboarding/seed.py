"""
Company domain graph seeder — Step 6.

Converts a CompanyConfig (Tier 1 governance data) into domain-layer nodes
and writes them to the graph via any BaseGraphRepository implementation.

This runs once per company during onboarding, before any decision validation
or scout processing.  It is idempotent: all nodes use MERGE semantics, so
re-running updates properties without creating duplicates.

What gets seeded
----------------
  Goal nodes          one per CompanyConfig.strategic_goals entry
  KPI nodes           one per KPIConfig inside each StrategicGoal
  Rule nodes          one per CompanyConfig.governance_rules entry
  Actor nodes         one per unique role in approval_hierarchy + rule consequences
  Jurisdiction nodes  one per CompanyConfig.jurisdiction entry

Edges seeded
------------
  Goal  -[MEASURED_BY]->     KPI        (for each goal.kpis entry)
  Rule  -[REQUIRES_APPROVAL_FROM]-> Actor  (when consequence.action == require_approval)
  Rule  -[REQUIRES_REVIEW_FROM]->   Actor  (when consequence.action == require_review)
  Actor -[ESCALATES_TO]->    Actor      (for approval_hierarchy.reports_to)
  Goal  -[CONFLICTS_WITH]->  Goal       (for each goal_conflicts entry, both directions)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from app.config.company_config import CompanyConfig, RuleAction
from app.graph.base import BaseGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import Edge, Node, make_node_id
from app.ontology.node_types import NodeType

logger = logging.getLogger(__name__)

_CONFIDENCE_MAP = {"high": 0.95, "medium": 0.70, "low": 0.40}


async def seed_company_graph(
    config: CompanyConfig,
    repo: BaseGraphRepository,
) -> dict:
    """
    Write all domain-layer nodes from *config* to the repository.

    Args
    ----
    config  CompanyConfig instance (already validated by Pydantic)
    repo    Any BaseGraphRepository implementation

    Returns
    -------
    Summary dict::

        {
            "company_id":   str,
            "nodes_written": int,
            "edges_written": int,
            "goals":        int,
            "kpis":         int,
            "rules":        int,
            "actors":       int,
            "jurisdictions": int,
        }
    """
    cid = config.company_id
    nodes_written = 0
    edges_written = 0

    # Track actors already written so we don't duplicate nodes
    actor_ids_written: set[str] = set()

    # ------------------------------------------------------------------
    # 1. Jurisdiction nodes
    # ------------------------------------------------------------------
    for jcode in config.jurisdiction:
        node = Node(
            id=make_node_id(cid, NodeType.JURISDICTION, jcode),
            type=NodeType.JURISDICTION,
            label=jcode,
            properties={"code": jcode},
            confidence=1.0,
        )
        await repo.write_node(node, cid)
        nodes_written += 1

    # ------------------------------------------------------------------
    # 2. Actor nodes (from approval_hierarchy)
    # ------------------------------------------------------------------
    # Index by role slug so we can look them up when wiring edges
    actor_id_by_role: dict[str, str] = {}

    for entry in config.approval_hierarchy:
        role_slug = _role_slug(entry.role)
        actor_id = make_node_id(cid, NodeType.ACTOR, role_slug)
        actor_id_by_role[entry.role] = actor_id

        if actor_id not in actor_ids_written:
            props: dict = {"role": entry.role}
            if entry.approval_limit is not None:
                props["approval_limit"] = entry.approval_limit
            if entry.approval_limit_note:
                props["approval_limit_note"] = entry.approval_limit_note
            if entry.reports_to:
                props["reports_to"] = entry.reports_to

            node = Node(
                id=actor_id,
                type=NodeType.ACTOR,
                label=entry.role,
                properties=props,
                confidence=1.0,
            )
            await repo.write_node(node, cid)
            actor_ids_written.add(actor_id)
            nodes_written += 1

    # ------------------------------------------------------------------
    # 3. Actor nodes referenced by rules (but not in approval_hierarchy)
    # ------------------------------------------------------------------
    for rule in config.governance_rules:
        for role in _rule_actor_roles(rule):
            if role not in actor_id_by_role:
                actor_id = make_node_id(cid, NodeType.ACTOR, _role_slug(role))
                actor_id_by_role[role] = actor_id
                if actor_id not in actor_ids_written:
                    node = Node(
                        id=actor_id,
                        type=NodeType.ACTOR,
                        label=role,
                        properties={"role": role},
                        confidence=1.0,
                    )
                    await repo.write_node(node, cid)
                    actor_ids_written.add(actor_id)
                    nodes_written += 1

    # ------------------------------------------------------------------
    # 4. ESCALATES_TO edges (approval_hierarchy.reports_to)
    # ------------------------------------------------------------------
    for entry in config.approval_hierarchy:
        if entry.reports_to and entry.reports_to in actor_id_by_role:
            edge = Edge(
                from_node=actor_id_by_role[entry.role],
                to_node=actor_id_by_role[entry.reports_to],
                predicate=EdgePredicate.ESCALATES_TO,
                confidence=1.0,  # seeded edges are always certain
            )
            await repo.write_edge(edge, cid)
            edges_written += 1

    # ------------------------------------------------------------------
    # 5. KPI nodes (all KPIs across all goals)
    # ------------------------------------------------------------------
    kpi_count = 0
    kpi_id_map: dict[str, str] = {}  # kpi_id → node_id

    for goal in config.strategic_goals:
        for kpi in goal.kpis:
            kpi_node_id = make_node_id(cid, NodeType.KPI, kpi.kpi_id)
            kpi_id_map[kpi.kpi_id] = kpi_node_id
            props = {"kpi_id": kpi.kpi_id, "label": kpi.label}
            if kpi.unit:
                props["unit"] = kpi.unit
            if kpi.target:
                props["target"] = kpi.target
            node = Node(
                id=kpi_node_id,
                type=NodeType.KPI,
                label=kpi.label,
                properties=props,
                confidence=1.0,
            )
            await repo.write_node(node, cid)
            nodes_written += 1
            kpi_count += 1

    # ------------------------------------------------------------------
    # 6. Goal nodes + MEASURED_BY edges
    # ------------------------------------------------------------------
    for goal in config.strategic_goals:
        goal_node_id = make_node_id(cid, NodeType.GOAL, goal.goal_id)
        props = {
            "goal_id": goal.goal_id,
            "label": goal.label,
            "priority": goal.priority,
        }
        if goal.description:
            props["description"] = goal.description
        if goal.owner_role:
            props["owner_role"] = goal.owner_role
        # Temporal fields (Change 4.4)
        if goal.effective_date:
            props["effective_date"] = goal.effective_date
        if goal.expiry_date:
            props["expiry_date"] = goal.expiry_date
        if goal.temporal_scope:
            props["temporal_scope"] = goal.temporal_scope
        if goal.recurring is not None:
            props["recurring"] = goal.recurring

        node = Node(
            id=goal_node_id,
            type=NodeType.GOAL,
            label=goal.label,
            properties=props,
            confidence=1.0,
        )
        await repo.write_node(node, cid)
        nodes_written += 1

        # MEASURED_BY edges
        for kpi in goal.kpis:
            kpi_node_id = kpi_id_map.get(kpi.kpi_id)
            if kpi_node_id:
                edge = Edge(
                    from_node=goal_node_id,
                    to_node=kpi_node_id,
                    predicate=EdgePredicate.MEASURED_BY,
                    confidence=1.0,  # seeded edges are always certain
                )
                await repo.write_edge(edge, cid)
                edges_written += 1

    # ------------------------------------------------------------------
    # 7. Rule nodes + REQUIRES_APPROVAL_FROM / REQUIRES_REVIEW_FROM edges
    # ------------------------------------------------------------------
    for rule in config.governance_rules:
        rule_node_id = make_node_id(cid, NodeType.RULE, rule.rule_id)
        # Normalize confidence: may be a string ("high"/"medium"/"low") or float
        raw_confidence = rule.confidence
        if isinstance(raw_confidence, str):
            confidence_val = _CONFIDENCE_MAP.get(raw_confidence.lower(), 0.70)
        else:
            confidence_val = float(raw_confidence) if raw_confidence else 0.70

        props = {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "source": rule.source,
            "confidence": confidence_val,
            "priority": rule.priority,
            "conditions": json.dumps([c.model_dump() for c in rule.conditions]),
            "consequence": json.dumps(rule.consequence.model_dump()),
            "source_excerpt": f"Governance config: {rule.name}",
        }
        if rule.description:
            props["description"] = rule.description
        if rule.source_chunk_ids:
            props["source_chunk_ids"] = rule.source_chunk_ids
        # Temporal fields (Change 4.4)
        if rule.effective_date:
            props["effective_date"] = rule.effective_date
        if rule.expiry_date:
            props["expiry_date"] = rule.expiry_date
        if rule.temporal_scope:
            props["temporal_scope"] = rule.temporal_scope
        if rule.recurring is not None:
            props["recurring"] = rule.recurring

        node = Node(
            id=rule_node_id,
            type=NodeType.RULE,
            label=rule.name,
            properties=props,
            confidence=1.0,
        )
        await repo.write_node(node, cid)
        nodes_written += 1

        # Edge: Rule → REQUIRES_APPROVAL_FROM → Actor
        if (
            rule.consequence.action == RuleAction.REQUIRE_APPROVAL
            and rule.consequence.approver_role
        ):
            actor_id = actor_id_by_role.get(rule.consequence.approver_role)
            if actor_id:
                edge = Edge(
                    from_node=rule_node_id,
                    to_node=actor_id,
                    predicate=EdgePredicate.REQUIRES_APPROVAL_FROM,
                    properties={"requires_sequential": rule.consequence.requires_sequential},
                    confidence=1.0,  # seeded edges are always certain
                )
                await repo.write_edge(edge, cid)
                edges_written += 1

        # Edge: Rule → REQUIRES_REVIEW_FROM → Actor
        if (
            rule.consequence.action == RuleAction.REQUIRE_REVIEW
            and rule.consequence.approver_role
        ):
            actor_id = actor_id_by_role.get(rule.consequence.approver_role)
            if actor_id:
                edge = Edge(
                    from_node=rule_node_id,
                    to_node=actor_id,
                    predicate=EdgePredicate.REQUIRES_REVIEW_FROM,
                    confidence=1.0,  # seeded edges are always certain
                )
                await repo.write_edge(edge, cid)
                edges_written += 1

    # ------------------------------------------------------------------
    # 8. GOVERNED_BY edges (Rule → Goal) from governed_by_goal_ids
    # ------------------------------------------------------------------
    goal_node_ids: dict[str, str] = {
        g.goal_id: make_node_id(cid, NodeType.GOAL, g.goal_id)
        for g in config.strategic_goals
    }
    for rule in config.governance_rules:
        if rule.governed_by_goal_ids:
            rule_node_id = make_node_id(cid, NodeType.RULE, rule.rule_id)
            for goal_id in rule.governed_by_goal_ids:
                goal_nid = goal_node_ids.get(goal_id)
                if goal_nid:
                    edge = Edge(
                        from_node=rule_node_id,
                        to_node=goal_nid,
                        predicate=EdgePredicate.GOVERNED_BY,
                        confidence=1.0,
                    )
                    await repo.write_edge(edge, cid)
                    edges_written += 1
                else:
                    logger.warning(
                        "Rule '%s' references unknown goal_id '%s' in governed_by_goal_ids",
                        rule.rule_id, goal_id,
                    )

    # ------------------------------------------------------------------
    # 8b. CONFLICTS_WITH edges (Goal ↔ Goal) from goal_conflicts
    # ------------------------------------------------------------------
    for conflict in config.goal_conflicts:
        a_nid = goal_node_ids.get(conflict.goal_id_a)
        b_nid = goal_node_ids.get(conflict.goal_id_b)
        if a_nid and b_nid:
            # Write both directions for symmetric conflict
            for from_nid, to_nid in [(a_nid, b_nid), (b_nid, a_nid)]:
                edge = Edge(
                    from_node=from_nid,
                    to_node=to_nid,
                    predicate=EdgePredicate.CONFLICTS_WITH,
                    properties={"description": conflict.description} if conflict.description else None,
                    confidence=1.0,
                )
                await repo.write_edge(edge, cid)
                edges_written += 1
        else:
            logger.warning(
                "GoalConflict references unknown goal_id: a=%s (found=%s), b=%s (found=%s)",
                conflict.goal_id_a, bool(a_nid),
                conflict.goal_id_b, bool(b_nid),
            )

    # ------------------------------------------------------------------
    # 9. Department nodes + BELONGS_TO edges (Actor → Department)
    # ------------------------------------------------------------------
    dept_count = 0
    for dept in config.departments:
        dept_node_id = make_node_id(cid, NodeType.DEPARTMENT, dept.dept_id)
        props = {"dept_id": dept.dept_id, "label": dept.label}
        if dept.parent_dept_id:
            props["parent_dept_id"] = dept.parent_dept_id

        node = Node(
            id=dept_node_id,
            type=NodeType.DEPARTMENT,
            label=dept.label,
            properties=props,
            confidence=1.0,
        )
        await repo.write_node(node, cid)
        nodes_written += 1
        dept_count += 1

        # Create BELONGS_TO edges from matching Actors
        for role in dept.member_roles:
            actor_id = actor_id_by_role.get(role)
            if actor_id:
                edge = Edge(
                    from_node=actor_id,
                    to_node=dept_node_id,
                    predicate=EdgePredicate.BELONGS_TO,
                    confidence=1.0,
                )
                await repo.write_edge(edge, cid)
                edges_written += 1
            else:
                logger.warning(
                    "Department '%s' references role '%s' not found in actors",
                    dept.dept_id, role,
                )

    # ------------------------------------------------------------------
    # 10. GovernanceRisk nodes + GENERATES_RISK / MITIGATES edges
    # ------------------------------------------------------------------
    risk_count = 0
    rule_node_ids: dict[str, str] = {
        r.rule_id: make_node_id(cid, NodeType.RULE, r.rule_id)
        for r in config.governance_rules
    }

    for risk in config.governance_risks:
        risk_node_id = make_node_id(cid, NodeType.GOVERNANCE_RISK, risk.risk_id)
        props = {
            "risk_id": risk.risk_id,
            "label": risk.label,
            "risk_category": risk.risk_category,
            "severity": risk.severity,
        }
        if risk.description:
            props["description"] = risk.description

        node = Node(
            id=risk_node_id,
            type=NodeType.GOVERNANCE_RISK,
            label=risk.label,
            properties=props,
            confidence=1.0,
        )
        await repo.write_node(node, cid)
        nodes_written += 1
        risk_count += 1

        # GENERATES_RISK edges (Rule → GovernanceRisk)
        for rule_id in risk.generated_by_rule_ids:
            rule_nid = rule_node_ids.get(rule_id)
            if rule_nid:
                edge = Edge(
                    from_node=rule_nid,
                    to_node=risk_node_id,
                    predicate=EdgePredicate.GENERATES_RISK,
                    confidence=1.0,
                )
                await repo.write_edge(edge, cid)
                edges_written += 1
            else:
                logger.warning(
                    "GovernanceRisk '%s' references unknown rule_id '%s' in generated_by_rule_ids",
                    risk.risk_id, rule_id,
                )

        # MITIGATES edges (Rule → GovernanceRisk)
        for rule_id in risk.mitigated_by_rule_ids:
            rule_nid = rule_node_ids.get(rule_id)
            if rule_nid:
                edge = Edge(
                    from_node=rule_nid,
                    to_node=risk_node_id,
                    predicate=EdgePredicate.MITIGATES,
                    confidence=1.0,
                )
                await repo.write_edge(edge, cid)
                edges_written += 1
            else:
                logger.warning(
                    "GovernanceRisk '%s' references unknown rule_id '%s' in mitigated_by_rule_ids",
                    risk.risk_id, rule_id,
                )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    summary = {
        "company_id": cid,
        "nodes_written": nodes_written,
        "edges_written": edges_written,
        "goals": len(config.strategic_goals),
        "kpis": kpi_count,
        "rules": len(config.governance_rules),
        "actors": len(actor_ids_written),
        "jurisdictions": len(config.jurisdiction),
        "departments": dept_count,
        "governance_risks": risk_count,
        "goal_conflicts": len(config.goal_conflicts),
    }
    logger.info(
        f"Seeded company graph: company={cid!r} "
        f"nodes={nodes_written} edges={edges_written}"
    )
    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def serialize_seeded_nodes(seed_result: dict, config: CompanyConfig) -> str:
    """
    Serialize the seeded node inventory into a compact markdown table.

    Scouts receive this table so the LLM knows which nodes already exist
    in the graph and can reference their semantic_ids in edges instead of
    inventing new nodes.

    Args
    ----
    seed_result  Summary dict returned by seed_company_graph()
    config       The CompanyConfig used during seeding

    Returns
    -------
    Markdown table string listing all seeded nodes by type, semantic_id, and label.
    Empty string if no nodes were seeded.
    """
    rows: list[tuple[str, str, str]] = []

    # Goals
    for goal in config.strategic_goals:
        rows.append(("Goal", goal.goal_id, goal.label))
        # KPIs nested under goals
        for kpi in goal.kpis:
            rows.append(("KPI", kpi.kpi_id, kpi.label))

    # Rules
    for rule in config.governance_rules:
        rows.append(("Rule", rule.rule_id, rule.name))

    # Actors — collect from approval_hierarchy + rule consequences (same logic as seed)
    actor_roles_seen: set[str] = set()
    for entry in config.approval_hierarchy:
        if entry.role not in actor_roles_seen:
            actor_roles_seen.add(entry.role)
            rows.append(("Actor", _role_slug(entry.role), entry.role))

    for rule in config.governance_rules:
        for role in _rule_actor_roles(rule):
            if role not in actor_roles_seen:
                actor_roles_seen.add(role)
                rows.append(("Actor", _role_slug(role), role))

    # Departments
    for dept in config.departments:
        rows.append(("Department", dept.dept_id, dept.label))

    # Governance risks
    for risk in config.governance_risks:
        rows.append(("GovernanceRisk", risk.risk_id, risk.label))

    # Jurisdictions
    for jcode in config.jurisdiction:
        rows.append(("Jurisdiction", jcode, jcode))

    if not rows:
        return ""

    lines = ["| Type | Semantic ID | Label |", "|------|------------|-------|"]
    for node_type, semantic_id, label in rows:
        lines.append(f"| {node_type} | {semantic_id} | {label} |")

    return "\n".join(lines)


def _role_slug(role: str) -> str:
    """Convert a role name to a stable slug for use in node IDs."""
    return role.strip().lower().replace(" ", "_").replace("-", "_")


def _rule_actor_roles(rule) -> list[str]:
    """Return all actor roles referenced by a governance rule."""
    roles = []
    if rule.consequence.approver_role:
        roles.append(rule.consequence.approver_role)
    if rule.consequence.escalation_role:
        roles.append(rule.consequence.escalation_role)
    return roles
