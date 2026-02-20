"""
Graph Mapper - Deterministic mapping from Decision + Governance to Graph structure.

Converts decision governance results into graph nodes and edges.

Node Types:
- Action: The decision itself
- Actor: Owners and approvers
- Policy: Triggered governance rules
- Risk: Identified risks and flags

Edge Types:
- OWNS: Actor owns Action
- REQUIRES_APPROVAL_BY: Action requires approval by Actor
- GOVERNED_BY: Action governed by Policy
- TRIGGERS: Action triggers Risk

Architecture:
- Pure Python, deterministic mapping
- No LLM, no inference
- Graph-ready structure for future visualization
"""

from typing import List, Dict, Any, Tuple
from app.schemas import Decision
from app.governance import GovernanceResult
import hashlib


def generate_node_id(node_type: str, identifier: str) -> str:
    """
    Generate deterministic node ID.

    Args:
        node_type: Type of node (action, actor, policy, risk)
        identifier: Unique identifier for the node

    Returns:
        Node ID string
    """
    # Create deterministic hash-based ID
    hash_input = f"{node_type}_{identifier}".encode('utf-8')
    hash_digest = hashlib.md5(hash_input).hexdigest()[:12]
    return f"{node_type.lower()}_{hash_digest}"


def build_graph_from_decision(
    decision: Decision,
    governance_result: GovernanceResult,
    decision_id: str
) -> Tuple[List[dict], List[dict]]:
    """
    Build graph nodes and edges from decision and governance evaluation.

    Args:
        decision: Decision object
        governance_result: Governance evaluation result
        decision_id: Unique decision identifier

    Returns:
        Tuple of (nodes, edges) as lists of dicts
    """
    nodes = []
    edges = []

    # 1. Create Action node (the decision itself)
    action_node_id = f"action_{decision_id}"
    action_node = {
        "node_id": action_node_id,
        "node_type": "Action",
        "properties": {
            "decision_id": decision_id,
            "statement": decision.decision_statement,
            "confidence": decision.confidence,
            "risk_score": decision.risk_score,
            "strategic_impact": decision.strategic_impact.value if decision.strategic_impact else None,
            "goals_count": len(decision.goals),
            "kpis_count": len(decision.kpis),
            "risks_count": len(decision.risks)
        }
    }
    nodes.append(action_node)

    # 2. Create Actor nodes (Owners)
    for idx, owner in enumerate(decision.owners):
        actor_id = generate_node_id("actor", f"{owner.name}_{owner.role}_{idx}")
        actor_node = {
            "node_id": actor_id,
            "node_type": "Actor",
            "properties": {
                "name": owner.name,
                "role": owner.role or "Unknown",
                "responsibility": owner.responsibility,
                "actor_type": "owner"
            }
        }
        nodes.append(actor_node)

        # Create OWNS edge: Actor OWNS Action
        owns_edge = {
            "edge_type": "OWNS",
            "from_node": actor_id,
            "to_node": action_node_id,
            "properties": {
                "responsibility": owner.responsibility
            }
        }
        edges.append(owns_edge)

    # 3. Create Actor nodes (Approvers from approval chain)
    if governance_result.approval_chain:
        for idx, approval_step in enumerate(governance_result.approval_chain):
            approver_id = generate_node_id("actor", f"{approval_step.role}_approver_{idx}")
            approver_node = {
                "node_id": approver_id,
                "node_type": "Actor",
                "properties": {
                    "name": approval_step.role,
                    "role": approval_step.role,
                    "approval_level": approval_step.level.value if hasattr(approval_step.level, 'value') else str(approval_step.level),
                    "required": approval_step.required,
                    "actor_type": "approver"
                }
            }
            nodes.append(approver_node)

            # Create REQUIRES_APPROVAL_BY edge: Action REQUIRES_APPROVAL_BY Actor
            approval_edge = {
                "edge_type": "REQUIRES_APPROVAL_BY",
                "from_node": action_node_id,
                "to_node": approver_id,
                "properties": {
                    "rationale": approval_step.rationale,
                    "required": approval_step.required,
                    "approval_level": approval_step.level.value if hasattr(approval_step.level, 'value') else str(approval_step.level)
                }
            }
            edges.append(approval_edge)

    # 4. Create Policy nodes (Triggered governance rules)
    if governance_result.triggered_rules:
        for rule in governance_result.triggered_rules:
            rule_id = rule.get("rule_id", "unknown")
            policy_id = generate_node_id("policy", rule_id)
            policy_node = {
                "node_id": policy_id,
                "node_type": "Policy",
                "properties": {
                    "rule_id": rule_id,
                    "name": rule.get("name", ""),
                    "description": rule.get("description", ""),
                    "rule_type": rule.get("rule_type", "unknown")
                }
            }
            nodes.append(policy_node)

            # Create GOVERNED_BY edge: Action GOVERNED_BY Policy
            governed_edge = {
                "edge_type": "GOVERNED_BY",
                "from_node": action_node_id,
                "to_node": policy_id,
                "properties": {
                    "rule_name": rule.get("name", ""),
                    "rule_type": rule.get("rule_type", "unknown")
                }
            }
            edges.append(governed_edge)

    # 5. Create Risk nodes (From governance flags)
    if governance_result.flags:
        for idx, flag in enumerate(governance_result.flags):
            flag_value = flag.value if hasattr(flag, 'value') else str(flag)
            risk_id = generate_node_id("risk", f"{flag_value}_{idx}")
            risk_node = {
                "node_id": risk_id,
                "node_type": "Risk",
                "properties": {
                    "flag": flag_value,
                    "severity": _determine_flag_severity(flag_value),
                    "source": "governance_evaluation",
                    "risk_type": "governance_flag"
                }
            }
            nodes.append(risk_node)

            # Create TRIGGERS edge: Action TRIGGERS Risk
            triggers_edge = {
                "edge_type": "TRIGGERS",
                "from_node": action_node_id,
                "to_node": risk_id,
                "properties": {
                    "flag": flag_value,
                    "severity": _determine_flag_severity(flag_value)
                }
            }
            edges.append(triggers_edge)

    # 6. Create Risk nodes (From decision risks)
    for idx, risk in enumerate(decision.risks):
        risk_id = generate_node_id("risk", f"decision_risk_{risk.description[:20]}_{idx}")
        risk_node = {
            "node_id": risk_id,
            "node_type": "Risk",
            "properties": {
                "description": risk.description,
                "severity": risk.severity or "medium",
                "mitigation": risk.mitigation,
                "source": "decision_extraction",
                "risk_type": "identified_risk"
            }
        }
        nodes.append(risk_node)

        # Create TRIGGERS edge: Action TRIGGERS Risk
        triggers_edge = {
            "edge_type": "TRIGGERS",
            "from_node": action_node_id,
            "to_node": risk_id,
            "properties": {
                "severity": risk.severity or "medium",
                "has_mitigation": risk.mitigation is not None
            }
        }
        edges.append(triggers_edge)

    return nodes, edges


def _determine_flag_severity(flag_value: str) -> str:
    """
    Determine severity level from governance flag.

    Args:
        flag_value: Flag name

    Returns:
        Severity level (critical, high, medium, low)
    """
    flag_upper = flag_value.upper()

    if "CRITICAL" in flag_upper:
        return "critical"
    elif any(kw in flag_upper for kw in ["HIGH_RISK", "MISSING_APPROVAL", "PRIVACY"]):
        return "high"
    elif any(kw in flag_upper for kw in ["FINANCIAL", "STRATEGIC"]):
        return "high"
    elif "MISSING" in flag_upper:
        return "medium"
    else:
        return "medium"


def build_graph_payload(nodes: List[dict], edges: List[dict]) -> dict:
    """
    Build graph payload for API response.

    Args:
        nodes: List of graph nodes
        edges: List of graph edges

    Returns:
        Graph payload dict with nodes, edges, and summary
    """
    # Count nodes by type
    node_counts = {}
    for node in nodes:
        node_type = node["node_type"]
        node_counts[node_type] = node_counts.get(node_type, 0) + 1

    # Count edges by type
    edge_counts = {}
    for edge in edges:
        edge_type = edge["edge_type"]
        edge_counts[edge_type] = edge_counts.get(edge_type, 0) + 1

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "node_counts": node_counts,
            "edge_counts": edge_counts
        },
        "graph_schema": {
            "node_types": ["Action", "Actor", "Policy", "Risk"],
            "edge_types": ["OWNS", "REQUIRES_APPROVAL_BY", "GOVERNED_BY", "TRIGGERS"]
        }
    }
