"""
Edge audit scout — second-pass LangGraph node for structural edge repair.

Runs AFTER transform but BEFORE validation. Identifies domain nodes that are
missing expected edges and proposes new edges via a targeted LLM call.

Checks performed:
  1. Rule nodes with no GOVERNED_BY edge → propose which goal(s) each rule serves
  2. Actor nodes with no BELONGS_TO edge → propose which department
  3. Goal pairs with no CONFLICTS_WITH/SUPPORTS → propose inter-goal edges
  4. Rule nodes with no risk edges → propose GENERATES_RISK edges
  5. GOVERNED_BY distribution check → flag if any goal has > 60% of edges

This is a targeted repair pass, not a full re-extraction. The LLM receives
a compact summary (node IDs + labels) and returns only edge proposals.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate

from app.config.llm import get_llm
from app.graph.base import BaseGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import Edge, Node
from app.ontology.node_types import NodeType
from app.onboarding.schemas import OnboardingState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt for edge proposals
# ---------------------------------------------------------------------------

_EDGE_AUDIT_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert governance ontology auditor. Given a list of graph nodes and "
        "their current edges, propose MISSING edges that should exist based on governance logic.\n\n"
        "Valid edge predicates you may propose:\n"
        "  GOVERNED_BY — Rule → Goal (rule serves/protects this goal)\n"
        "  BELONGS_TO — Actor → Department (actor is member of department)\n"
        "  SUPPORTS — Goal → Goal (sub-goal advances parent goal)\n"
        "  CONFLICTS_WITH — Goal ↔ Goal (goals create tension)\n"
        "  GENERATES_RISK — Rule → GovernanceRisk (triggering rule generates risk)\n"
        "  HAS_RISK — Goal → GovernanceRisk (goal is exposed to risk)\n\n"
        "Rules:\n"
        "- Only propose edges with high confidence (0.7+)\n"
        "- Use exact node IDs from the input\n"
        "- Do NOT invent new nodes\n"
        "- Return a JSON object with a single key \"edges\" containing a list of edge objects\n"
        "- Each edge: {{\"from_id\": \"...\", \"to_id\": \"...\", \"predicate\": \"...\", "
        "\"evidence\": \"...\", \"confidence\": 0.0-1.0}}\n"
        "- Return {{\"edges\": []}} if no edges should be added"
    ),
    (
        "human",
        "Audit this governance graph for missing edges.\n\n"
        "## Orphan Rules (no GOVERNED_BY edge to any Goal)\n{orphan_rules}\n\n"
        "## Orphan Actors (no BELONGS_TO edge to any Department)\n{orphan_actors}\n\n"
        "## Goals (check for missing SUPPORTS/CONFLICTS_WITH between pairs)\n{goals}\n\n"
        "## Rules without risk edges\n{rules_no_risk}\n\n"
        "## Available GovernanceRisk nodes\n{risk_nodes}\n\n"
        "## Available Department nodes\n{department_nodes}\n\n"
        "Propose missing edges. Be conservative — only propose edges you are confident about."
    ),
])


# ---------------------------------------------------------------------------
# Dedicated conflict detection prompt (V4 Fix #1)
# ---------------------------------------------------------------------------

_CONFLICT_DETECTION_PROMPT = ChatPromptTemplate.from_messages([
    (
        "system",
        "You are an expert governance analyst. Your task is to identify CONFLICTS_WITH "
        "relationships between strategic goals.\n\n"
        "Two goals CONFLICT when pursuing one actively hinders, creates tension with, or "
        "requires trade-offs against the other. Common conflict patterns:\n"
        "  - Speed vs compliance (moving fast vs following process)\n"
        "  - Growth vs cost control (spending to grow vs staying within budget)\n"
        "  - Revenue vs compliance (revenue pressure vs regulatory constraints)\n"
        "  - Velocity vs quality (shipping fast vs thorough review)\n\n"
        "Rules:\n"
        "- Only propose conflicts with genuine strategic tension supported by evidence\n"
        "- CONFLICTS_WITH is symmetric — if A conflicts with B, B conflicts with A\n"
        "- Return both directions for each conflict pair\n"
        "- Use exact node IDs from the input\n"
        "- Return a JSON object: {{\"edges\": [...]}}\n"
        "- Each edge: {{\"from_id\": \"...\", \"to_id\": \"...\", \"predicate\": \"CONFLICTS_WITH\", "
        "\"evidence\": \"...\", \"confidence\": 0.0-1.0}}\n"
        "- Return {{\"edges\": []}} if no conflicts exist"
    ),
    (
        "human",
        "Analyze these strategic goals for pairwise conflicts.\n\n"
        "## Strategic Goals\n{goal_details}\n\n"
        "## Existing CONFLICTS_WITH edges (already in graph)\n{existing_conflicts}\n\n"
        "## Evidence from extracted text that may indicate goal tensions\n{conflict_evidence}\n\n"
        "Identify ALL goal pairs that have genuine strategic tension. "
        "Do NOT propose conflicts that already exist in the graph."
    ),
])


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


async def run_edge_audit(
    repo: BaseGraphRepository,
    company_id: str,
) -> dict:
    """
    Run the edge audit pass: identify missing edges and propose repairs.

    Returns a dict with:
      - edges_proposed: int
      - edges_written: int
      - distribution_warnings: list[str]
      - errors: list[str]
    """
    result = {
        "edges_proposed": 0,
        "edges_written": 0,
        "distribution_warnings": [],
        "errors": [],
    }

    try:
        nodes, edges = await _collect_graph_data(repo, company_id)
    except Exception as exc:
        result["errors"].append(f"Failed to collect graph data: {exc}")
        return result

    if not nodes:
        return result

    # --- Build indexes ---
    nodes_by_type: dict[str, list[Node]] = {}
    for node in nodes:
        nt = node.type if isinstance(node.type, str) else node.type.value
        nodes_by_type.setdefault(nt, []).append(node)

    outgoing: dict[str, set[str]] = {}  # node_id → set of predicate values
    incoming: dict[str, set[str]] = {}
    governed_by_targets: Counter = Counter()  # goal_id → count

    for edge in edges:
        pred = edge.predicate if isinstance(edge.predicate, str) else edge.predicate.value
        outgoing.setdefault(edge.from_node, set()).add(pred)
        incoming.setdefault(edge.to_node, set()).add(pred)
        if pred == "GOVERNED_BY":
            governed_by_targets[edge.to_node] += 1

    # --- Identify orphans ---
    orphan_rules = []
    for node in nodes_by_type.get("Rule", []):
        if "GOVERNED_BY" not in outgoing.get(node.id, set()):
            orphan_rules.append(node)

    orphan_actors = []
    for node in nodes_by_type.get("Actor", []):
        if "BELONGS_TO" not in outgoing.get(node.id, set()):
            orphan_actors.append(node)

    rules_no_risk = []
    for node in nodes_by_type.get("Rule", []):
        node_out = outgoing.get(node.id, set())
        if "GENERATES_RISK" not in node_out and "MITIGATES" not in node_out:
            rules_no_risk.append(node)

    goals = nodes_by_type.get("Goal", [])
    risk_nodes = nodes_by_type.get("GovernanceRisk", [])
    dept_nodes = nodes_by_type.get("Department", [])

    # --- GOVERNED_BY distribution check ---
    total_gov_by = sum(governed_by_targets.values())
    if total_gov_by > 0:
        for goal_id, count in governed_by_targets.most_common():
            ratio = count / total_gov_by
            if ratio > 0.60:
                goal_label = goal_id.split(":")[-1] if ":" in goal_id else goal_id
                msg = (
                    f"GOVERNED_BY distribution skew: goal '{goal_label}' has "
                    f"{count}/{total_gov_by} edges ({ratio:.0%}). "
                    f"Consider distributing rules across more goals."
                )
                result["distribution_warnings"].append(msg)
                logger.warning(msg)

    # --- Explicit conflict detection pass (V4 Fix #1) ---
    # Always run this if we have 2+ goals, regardless of orphan state
    if len(goals) >= 2:
        conflict_result = await _run_conflict_detection(
            goals=goals,
            edges=edges,
            nodes=nodes,
            repo=repo,
            company_id=company_id,
        )
        result["edges_proposed"] += conflict_result.get("edges_proposed", 0)
        result["edges_written"] += conflict_result.get("edges_written", 0)
        result["errors"].extend(conflict_result.get("errors", []))

    # --- Skip main LLM call if nothing to audit ---
    if not orphan_rules and not orphan_actors and not rules_no_risk:
        logger.info("[edge_audit] No orphans found — skipping main LLM call")
        return result

    # --- Format node summaries for prompt ---
    def _format_nodes(node_list: list[Node]) -> str:
        if not node_list:
            return "(none)"
        return "\n".join(
            f"  - {n.id} | {n.label}"
            for n in node_list[:30]  # cap at 30 to stay within context
        )

    try:
        llm = get_llm("fast")
        prompt_input = {
            "orphan_rules": _format_nodes(orphan_rules),
            "orphan_actors": _format_nodes(orphan_actors),
            "goals": _format_nodes(goals),
            "rules_no_risk": _format_nodes(rules_no_risk),
            "risk_nodes": _format_nodes(risk_nodes),
            "department_nodes": _format_nodes(dept_nodes),
        }

        chain = _EDGE_AUDIT_PROMPT | llm
        response = await chain.ainvoke(prompt_input)

        # Parse response
        content = response.content if hasattr(response, "content") else str(response)
        # Strip markdown fences if present
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        proposed = json.loads(content)
        proposed_edges = proposed.get("edges", [])
        result["edges_proposed"] = len(proposed_edges)

        # --- Write proposed edges ---
        valid_node_ids = {n.id for n in nodes}
        valid_predicates = {ep.value for ep in EdgePredicate}

        for prop in proposed_edges:
            from_id = prop.get("from_id", "")
            to_id = prop.get("to_id", "")
            pred_str = prop.get("predicate", "")
            evidence = prop.get("evidence", "")
            confidence = float(prop.get("confidence", 0.7))

            if from_id not in valid_node_ids:
                logger.debug(f"[edge_audit] Skipping proposed edge: unknown from_id '{from_id}'")
                continue
            if to_id not in valid_node_ids:
                logger.debug(f"[edge_audit] Skipping proposed edge: unknown to_id '{to_id}'")
                continue
            if pred_str not in valid_predicates:
                logger.debug(f"[edge_audit] Skipping proposed edge: unknown predicate '{pred_str}'")
                continue

            edge = Edge(
                from_node=from_id,
                to_node=to_id,
                predicate=EdgePredicate(pred_str),
                properties={
                    "evidence": evidence,
                    "source": "edge_audit_scout",
                    "confidence": round(confidence, 4),
                },
                confidence=confidence,
            )
            try:
                await repo.write_edge(edge, company_id)
                result["edges_written"] += 1
            except Exception as exc:
                result["errors"].append(
                    f"Failed to write audit edge {from_id}->{to_id}: {exc}"
                )

    except Exception as exc:
        msg = f"[edge_audit] LLM edge proposal failed: {exc}"
        logger.error(msg)
        result["errors"].append(msg)

    logger.info(
        f"[edge_audit] company={company_id} "
        f"proposed={result['edges_proposed']} written={result['edges_written']} "
        f"dist_warnings={len(result['distribution_warnings'])}"
    )
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _run_conflict_detection(
    goals: list[Node],
    edges: list[Edge],
    nodes: list[Node],
    repo: BaseGraphRepository,
    company_id: str,
) -> dict:
    """
    Dedicated conflict detection pass (V4 Fix #1).

    Examines all goal pairs and uses LLM to identify CONFLICTS_WITH edges
    that are missing from the graph. Only proposes new conflicts — skips
    pairs that already have CONFLICTS_WITH edges.
    """
    result = {"edges_proposed": 0, "edges_written": 0, "errors": []}

    if len(goals) < 2:
        return result

    # Collect existing CONFLICTS_WITH pairs
    existing_conflict_pairs: set[tuple[str, str]] = set()
    for edge in edges:
        pred = edge.predicate if isinstance(edge.predicate, str) else edge.predicate.value
        if pred == "CONFLICTS_WITH":
            existing_conflict_pairs.add((edge.from_node, edge.to_node))

    # Format goal details with descriptions
    goal_lines = []
    for g in goals:
        desc = ""
        if g.properties and isinstance(g.properties, dict):
            desc = g.properties.get("description", "")
        goal_lines.append(f"  - {g.id} | {g.label} | {desc}")
    goal_details = "\n".join(goal_lines) if goal_lines else "(none)"

    # Format existing conflicts
    existing_lines = []
    for (f, t) in existing_conflict_pairs:
        existing_lines.append(f"  - {f} ↔ {t}")
    existing_conflicts = "\n".join(existing_lines) if existing_lines else "(none)"

    # Collect text evidence that might indicate tensions between goals
    # Look for chunks that mention multiple goals or contain tension keywords
    evidence_snippets = []
    for node in nodes:
        if node.properties and isinstance(node.properties, dict):
            excerpt = node.properties.get("source_excerpt", "")
            if excerpt and len(excerpt) > 20:
                evidence_snippets.append(f"  - [{node.id}]: {excerpt[:150]}")
    conflict_evidence = "\n".join(evidence_snippets[:20]) if evidence_snippets else "(no extracted evidence available)"

    try:
        llm = get_llm("fast")
        chain = _CONFLICT_DETECTION_PROMPT | llm
        response = await chain.ainvoke({
            "goal_details": goal_details,
            "existing_conflicts": existing_conflicts,
            "conflict_evidence": conflict_evidence,
        })

        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
        if content.endswith("```"):
            content = content.rsplit("```", 1)[0]
        content = content.strip()

        proposed = json.loads(content)
        proposed_edges = proposed.get("edges", [])
        result["edges_proposed"] = len(proposed_edges)

        valid_node_ids = {n.id for n in nodes}

        for prop in proposed_edges:
            from_id = prop.get("from_id", "")
            to_id = prop.get("to_id", "")
            pred_str = prop.get("predicate", "")
            evidence = prop.get("evidence", "")
            confidence = float(prop.get("confidence", 0.7))

            if pred_str != "CONFLICTS_WITH":
                continue
            if from_id not in valid_node_ids or to_id not in valid_node_ids:
                continue
            if (from_id, to_id) in existing_conflict_pairs:
                continue

            edge = Edge(
                from_node=from_id,
                to_node=to_id,
                predicate=EdgePredicate.CONFLICTS_WITH,
                properties={
                    "evidence": evidence,
                    "source": "conflict_detection_pass",
                    "confidence": round(confidence, 4),
                },
                confidence=confidence,
            )
            try:
                await repo.write_edge(edge, company_id)
                result["edges_written"] += 1
                existing_conflict_pairs.add((from_id, to_id))
            except Exception as exc:
                result["errors"].append(
                    f"Failed to write conflict edge {from_id}->{to_id}: {exc}"
                )

    except Exception as exc:
        msg = f"[edge_audit] Conflict detection failed: {exc}"
        logger.error(msg)
        result["errors"].append(msg)

    logger.info(
        f"[edge_audit:conflict_detection] company={company_id} "
        f"proposed={result['edges_proposed']} written={result['edges_written']}"
    )
    return result


async def _collect_graph_data(
    repo: BaseGraphRepository,
    company_id: str,
) -> tuple[list[Node], list[Edge]]:
    """Collect all nodes and edges from the repo for audit."""
    from app.graph.in_memory_repository import InMemoryGraphRepository

    if isinstance(repo, InMemoryGraphRepository):
        return list(repo._nodes.values()), list(repo._edges)

    # Fallback: use get_all_node_ids + get_node
    node_id_map = await repo.get_all_node_ids(company_id)
    nodes: list[Node] = []
    for full_id in node_id_map.values():
        node_dict = await repo.get_node(full_id, company_id)
        if node_dict:
            node_type_raw = node_dict.get("node_type", "")
            try:
                node_type = NodeType(node_type_raw)
            except ValueError:
                continue
            nodes.append(
                Node(
                    id=node_dict["id"],
                    type=node_type,
                    label=node_dict.get("label", ""),
                    confidence=node_dict.get("confidence"),
                )
            )

    edges: list[Edge] = []
    try:
        edge_records = await repo.cypher_read(
            "MATCH (a)-[r]->(b) "
            "WHERE a.id IS NOT NULL AND b.id IS NOT NULL "
            "RETURN a.id AS from_id, b.id AS to_id, type(r) AS rel_type, "
            "properties(r) AS props",
            params={},
            company_id=company_id,
        )
        for record in edge_records:
            from_id = record.get("from_id", "")
            to_id = record.get("to_id", "")
            rel_type = record.get("rel_type", "")
            if not all([from_id, to_id, rel_type]):
                continue
            try:
                predicate = EdgePredicate(rel_type)
            except ValueError:
                continue
            props = dict(record.get("props") or {})
            confidence = props.pop("confidence", 1.0)
            if not isinstance(confidence, (int, float)):
                confidence = 1.0
            edges.append(
                Edge(
                    from_node=from_id,
                    to_node=to_id,
                    predicate=predicate,
                    properties=props if props else None,
                    confidence=float(confidence),
                )
            )
    except NotImplementedError:
        logger.warning("Repository does not support cypher_read; edge audit limited")

    return nodes, edges
