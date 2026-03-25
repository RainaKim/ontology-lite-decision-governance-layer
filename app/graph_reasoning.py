"""
Graph Reasoning — Deterministic Contradiction Detection

Analyzes decision graph structure to find:
- Logical contradictions (conflicting goals/KPIs)
- Ownership inconsistencies
- Risk coverage gaps
- Policy conflicts

LangGraph-based reasoning agent will replace _deterministic_graph_analysis in Step 9.
"""

from typing import Optional
from app.graph_repository import BaseGraphRepository
from app.ontology.node_types import NodeType
from app.ontology.edge_predicates import EdgePredicate
import asyncio
import logging as _logging

_logger = _logging.getLogger(__name__)


async def analyze_decision_graph(
    decision_id: str,
    governance: dict,
    repository: BaseGraphRepository,
    decision_data: dict = None,
    company_data: dict = None,
) -> dict:
    """
    Analyze a decision graph for contradictions and governance insights.

    Flow:
    1. Retrieve stored graph context from repository (policies, actors, risks)
    2. Serialize graph structure for analysis
    3. Run deterministic contradiction detection
       (LangGraph governance agent replaces this in Step 9)

    Args:
        decision_id: Current decision ID
        governance: Governance evaluation result
        repository: Graph repository instance
        decision_data: Decision dict (statement, goals, KPIs, owners, risks)
        company_data: Company context (strategic_goals, personnel, risk_tolerance)

    Returns:
        Dict with graph insights and analysis results
    """
    # Step 1: Retrieve stored graph context from repository
    graph_context = await repository.get_governance_context(
        decision_id=decision_id,
        depth=2  # 2-hop traversal
    )

    # Step 2: Deterministic analysis
    graph_structure = _serialize_graph_for_analysis(graph_context, governance)
    graph_insights = _deterministic_graph_analysis(graph_structure)

    # Step 3: Extract subgraph metadata
    subgraph_meta = graph_insights.get("subgraph_metadata", {})
    nodes_analyzed = subgraph_meta.get("nodes_total", graph_context.get("metadata", {}).get("node_count", 0))
    edges_analyzed = subgraph_meta.get("edges_total", graph_context.get("metadata", {}).get("edge_count", 0))

    # Step 4: Format for Decision Pack
    insights = {
        "graph_context": {
            "nodes_analyzed": nodes_analyzed,
            "edges_analyzed": edges_analyzed,
            "traversal_depth": 2,
            "subgraph_source": subgraph_meta.get("source", "repository_only"),
            "matched_personnel": subgraph_meta.get("matched_personnel", []),
            "selection_criteria": subgraph_meta.get("selection_criteria", []),
        },
        "logical_analysis": graph_insights.get("contradictions", []),
        "strategic_goal_conflicts": graph_insights.get("strategic_goal_conflicts", []),
        "inferred_owners": graph_insights.get("inferred_owners", []),
        "ownership_validation": graph_insights.get("ownership_issues", []),
        "risk_coverage": graph_insights.get("risk_gaps", []),
        "policy_conflicts": graph_insights.get("policy_conflicts", []),
        "recommendations": graph_insights.get("recommendations", []),
        "next_actions": graph_insights.get("next_actions", []),
        "confidence": graph_insights.get("confidence", 0.0),
        "analysis_method": "deterministic"
    }

    return insights


def _serialize_graph_for_analysis(graph_context: dict, governance: dict) -> dict:
    """
    Convert graph context into structured format for analysis.

    Returns serialized graph with nodes, edges, and governance context.
    """
    decision_node = graph_context.get("decision")
    actors = graph_context.get("actors", [])
    policies = graph_context.get("policies", [])
    risks = graph_context.get("risks", [])
    edges = graph_context.get("edges", [])

    return {
        "decision": {
            "id": decision_node.id if decision_node else None,
            "statement": decision_node.label if decision_node else "",
            "properties": decision_node.properties if decision_node else {}
        },
        "actors": [
            {
                "id": actor.id,
                "name": actor.label,
                "role": actor.properties.get("role"),
                "type": actor.type.value if hasattr(actor.type, 'value') else str(actor.type)
            }
            for actor in actors
        ],
        "policies": [
            {
                "id": policy.id,
                "name": policy.label,
                "description": policy.properties.get("description")
            }
            for policy in policies
        ],
        "risks": [
            {
                "id": risk.id,
                "description": risk.label,
                "severity": risk.properties.get("severity"),
                "mitigation": risk.properties.get("mitigation")
            }
            for risk in risks
        ],
        "relationships": [
            {
                "from": edge.from_node,
                "to": edge.to_node,
                "type": edge.predicate.value if hasattr(edge.predicate, 'value') else str(edge.predicate),
                "properties": edge.properties
            }
            for edge in edges
        ],
        "governance": {
            "flags": governance.get("flags", []),
            "triggered_rules": governance.get("triggered_rules", []),
            "risk_score": governance.get("computed_risk_score", 0.0),
            "requires_review": governance.get("requires_human_review", False)
        }
    }


def _deterministic_graph_analysis(graph_structure: dict) -> dict:
    """
    Deterministic graph analysis — structural contradiction detection.

    Returns basic contradiction detection without deep reasoning.
    LangGraph-based governance agent will replace this in Step 9.
    """
    contradictions = []
    warnings = []
    recommendations = []

    # Basic checks
    decision = graph_structure.get("decision", {})
    actors = graph_structure.get("actors", [])
    risks = graph_structure.get("risks", [])

    # Check for missing owners
    if not actors or len(actors) == 0:
        contradictions.append({
            "type": "ownership_missing",
            "severity": "critical",
            "description": "No owners identified for this decision",
            "recommendation": "Assign at least one accountable owner"
        })

    # Check for missing risk mitigation
    for risk in risks:
        if not risk.get("mitigation"):
            warnings.append({
                "type": "missing_mitigation",
                "severity": "medium",
                "description": f"Risk '{risk.get('description')}' has no mitigation plan",
                "recommendation": "Add specific mitigation actions"
            })

    # Check for high risk + low confidence
    risk_score = decision.get("properties", {}).get("risk_score", 0)
    if risk_score >= 7.0 and len(risks) < 2:
        contradictions.append({
            "type": "risk_coverage_gap",
            "severity": "high",
            "description": f"Risk score is {risk_score} but only {len(risks)} risks identified",
            "recommendation": "Conduct thorough risk assessment"
        })

    return {
        "contradictions": contradictions,
        "ownership_issues": [],
        "risk_gaps": warnings,
        "policy_conflicts": [],
        "recommendations": recommendations,
        "confidence": 0.6,
        "fallback": True
    }


def format_graph_insights_for_pack(insights: dict) -> dict:
    """
    Format graph insights for Decision Pack inclusion.

    Returns structured insights section for pack.
    """
    return {
        "analysis_method": insights.get("analysis_method", "deterministic"),
        "graph_analysis": {
            "method": insights.get("analysis_method", "deterministic"),
            "nodes_analyzed": insights.get("graph_context", {}).get("nodes_analyzed", 0),
            "edges_analyzed": insights.get("graph_context", {}).get("edges_analyzed", 0),
            "confidence": insights.get("confidence", 0.0)
        },
        "graph_context": insights.get("graph_context", {}),
        "contradictions_found": insights.get("logical_analysis", []),
        "strategic_goal_conflicts": insights.get("strategic_goal_conflicts", []),
        "inferred_owners": insights.get("inferred_owners", []),
        "ownership_validation": insights.get("ownership_validation", []),
        "risk_coverage_gaps": insights.get("risk_coverage", []),
        "policy_conflicts": insights.get("policy_conflicts", []),
        "graph_based_recommendations": insights.get("recommendations", []),
        "next_actions": insights.get("next_actions", [])
    }
