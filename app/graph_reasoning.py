"""
Graph Reasoning with o1 - Logical Contradiction Detection

Uses o1 to analyze graph structure and find:
- Logical contradictions (conflicting goals/KPIs)
- Ownership inconsistencies
- Risk coverage gaps
- Policy conflicts
- Historical patterns
"""

from typing import Optional
from app.graph_repository import BaseGraphRepository
from app.graph_ontology import NodeType, EdgePredicate
from app.o1_reasoner import O1Reasoner
import asyncio


async def analyze_decision_graph_with_o1(
    decision_id: str,
    governance: dict,
    repository: BaseGraphRepository,
    decision_data: dict = None,
    company_data: dict = None,
    use_o1: bool = True
) -> dict:
    """
    Use o1 to analyze decision graph for contradictions and insights.

    Flow:
    1. Retrieve stored graph context from repository (policies, actors, risks)
    2. O1Reasoner._extract_mock_subgraph builds a rich subgraph by combining:
       - decision_data + company_data (owner matching, KPI overlap, goal alignment)
       - graph_context from repository (stored policies, approval actors)
    3. O1Reasoner._build_contradiction_prompt serializes the subgraph for o1
    4. o1 reasons about contradictions, ownership issues, risk gaps

    When Neo4j replaces InMemoryGraphRepository, step 2 becomes a real
    Cypher traversal and the mock matching logic can be removed.

    Args:
        decision_id: Current decision ID
        governance: Governance evaluation result
        repository: Graph repository instance
        decision_data: Decision dict (statement, goals, KPIs, owners, risks)
        company_data: Company context (strategic_goals, personnel, risk_tolerance)
        use_o1: Whether to use o1 for deep analysis

    Returns:
        Dict with graph insights and o1 reasoning
    """
    # Step 1: Retrieve stored graph context from repository
    graph_context = await repository.get_governance_context(
        decision_id=decision_id,
        depth=2  # 2-hop traversal
    )

    # Step 2: Use o1 with mock subgraph extraction (if enabled)
    if use_o1:
        try:
            o1_insights = await _reason_about_graph_with_o1(
                decision_id=decision_id,
                decision_data=decision_data or {},
                company_data=company_data or {},
                graph_context=graph_context,
                governance=governance
            )
        except Exception as e:
            # Fallback to deterministic analysis if o1 fails
            o1_insights = {
                "error": str(e),
                "fallback": True,
                "contradictions": [],
                "warnings": ["o1 analysis unavailable - using deterministic fallback"]
            }
    else:
        # Deterministic fallback uses the serialized graph structure
        graph_structure = _serialize_graph_for_o1(graph_context, governance)
        o1_insights = _deterministic_graph_analysis(graph_structure)

    # Step 3: Extract subgraph metadata (from o1 result or graph_context)
    subgraph_meta = o1_insights.get("subgraph_metadata", {})
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
        "logical_analysis": o1_insights.get("contradictions", []),
        "ownership_validation": o1_insights.get("ownership_issues", []),
        "risk_coverage": o1_insights.get("risk_gaps", []),
        "policy_conflicts": o1_insights.get("policy_conflicts", []),
        "recommendations": o1_insights.get("recommendations", []),
        "next_actions": o1_insights.get("next_actions", []),
        "confidence": o1_insights.get("confidence", 0.0),
        "analysis_method": "o1-reasoning" if use_o1 and not o1_insights.get("fallback") else "deterministic"
    }

    return insights


def _serialize_graph_for_o1(graph_context: dict, governance: dict) -> dict:
    """
    Convert graph context into structured format for o1 analysis.

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


async def _reason_about_graph_with_o1(
    decision_id: str,
    decision_data: dict,
    company_data: dict,
    graph_context: dict,
    governance: dict
) -> dict:
    """
    Use o1 to reason about graph structure and find contradictions.

    Delegates to O1Reasoner.reason_about_graph_contradictions which:
    1. Builds a mock subgraph from decision_data + company_data
    2. Enriches it with graph_context from the repository
    3. Serializes the subgraph into a structured prompt
    4. Calls o1 for deep reasoning

    Args:
        decision_id: Decision identifier (root of subgraph)
        decision_data: Decision dict (statement, goals, KPIs, owners, risks)
        company_data: Company context (strategic_goals, personnel, risk_tolerance)
        graph_context: Pre-fetched context from graph repository (policies, actors, edges)
        governance: Governance evaluation result (for logging/fallback)

    Returns:
        o1 analysis with contradictions, ownership issues, risk gaps, recommendations
    """
    reasoner = O1Reasoner(model="o4-mini")

    # o1 API is sync, run in executor
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: reasoner.reason_about_graph_contradictions(
            decision_id=decision_id,
            decision_data=decision_data,
            company_data=company_data,
            graph_context=_normalize_graph_context(graph_context)
        )
    )

    return result


def _normalize_graph_context(graph_context: dict) -> dict:
    """
    Normalize graph_context from repository into plain dicts.

    The repository returns Pydantic Node/Edge objects but the
    O1Reasoner._merge_graph_context expects either objects with
    .id/.label/.properties attributes or plain dicts. This normalizer
    ensures compatibility regardless of the source.
    """
    if not graph_context or graph_context.get("metadata", {}).get("error"):
        return None

    def _node_to_dict(node):
        if node is None:
            return None
        if isinstance(node, dict):
            return node
        return {
            "id": node.id,
            "label": node.label,
            "type": node.type.value if hasattr(node.type, 'value') else str(node.type),
            "properties": node.properties if hasattr(node, 'properties') else {}
        }

    def _edge_to_dict(edge):
        if isinstance(edge, dict):
            return edge
        return {
            "from_node": edge.from_node,
            "to_node": edge.to_node,
            "predicate": edge.predicate.value if hasattr(edge.predicate, 'value') else str(edge.predicate),
            "properties": edge.properties if hasattr(edge, 'properties') else {}
        }

    return {
        "decision": _node_to_dict(graph_context.get("decision")),
        "actors": [_node_to_dict(a) for a in graph_context.get("actors", [])],
        "policies": [_node_to_dict(p) for p in graph_context.get("policies", [])],
        "risks": [_node_to_dict(r) for r in graph_context.get("risks", [])],
        "edges": [_edge_to_dict(e) for e in graph_context.get("edges", [])],
        "metadata": graph_context.get("metadata", {})
    }


def _format_graph_for_prompt(graph_structure: dict) -> str:
    """
    Format graph structure as readable text for prompt construction.

    Note: Previously used for building the o1 prompt directly in this module.
    Now kept as a utility for debugging / deterministic fallback logging.
    The o1 prompt is built by O1Reasoner._build_contradiction_prompt instead.
    """
    lines = []

    # Decision
    decision = graph_structure.get("decision", {})
    lines.append(f"DECISION: {decision.get('statement', 'N/A')}")
    lines.append(f"  Risk Score: {decision.get('properties', {}).get('risk_score', 'N/A')}")
    lines.append(f"  Strategic Impact: {decision.get('properties', {}).get('strategic_impact', 'N/A')}")
    lines.append("")

    # Actors (Owners & Approvers)
    actors = graph_structure.get("actors", [])
    if actors:
        lines.append("ACTORS (Owners & Approvers):")
        for actor in actors:
            lines.append(f"  - {actor.get('name')} ({actor.get('role', 'N/A')})")
        lines.append("")

    # Policies (Triggered Rules)
    policies = graph_structure.get("policies", [])
    if policies:
        lines.append("POLICIES (Governance Rules Triggered):")
        for policy in policies:
            lines.append(f"  - {policy.get('name')}: {policy.get('description', 'N/A')}")
        lines.append("")

    # Risks
    risks = graph_structure.get("risks", [])
    if risks:
        lines.append("RISKS:")
        for risk in risks:
            lines.append(f"  - [{risk.get('severity', 'N/A')}] {risk.get('description')}")
            if risk.get('mitigation'):
                lines.append(f"    Mitigation: {risk.get('mitigation')}")
        lines.append("")

    # Relationships
    relationships = graph_structure.get("relationships", [])
    if relationships:
        lines.append("RELATIONSHIPS:")
        for rel in relationships:
            lines.append(f"  - {rel.get('from')} --[{rel.get('type')}]--> {rel.get('to')}")
        lines.append("")

    return "\n".join(lines)


def _deterministic_graph_analysis(graph_structure: dict) -> dict:
    """
    Fallback deterministic analysis when o1 is not available.

    Returns basic contradiction detection without deep reasoning.
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
        "ownership_validation": insights.get("ownership_validation", []),
        "risk_coverage_gaps": insights.get("risk_coverage", []),
        "policy_conflicts": insights.get("policy_conflicts", []),
        "graph_based_recommendations": insights.get("recommendations", []),
        "next_actions": insights.get("next_actions", [])
    }
