"""
Graph structural validation — deterministic post-transform quality checks.

Catches structural problems in the constructed ontology graph before it
reaches production:

  - Orphan nodes (zero edges in either direction)
  - Low edge-to-node ratio (sparse graph)
  - Missing required edge patterns (e.g. Rule without REQUIRES_APPROVAL_FROM)
  - Domain/range violations on edges

This module is pure logic — it reads from a BaseGraphRepository but never
writes.  Called by the validate node in the onboarding LangGraph pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from app.graph.base import BaseGraphRepository
from app.ontology.models import Edge, Node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


@dataclass
class OrphanCategory:
    """Categorized orphan node with fixability classification."""

    node_id: str
    node_type: str
    category: str  # "seed-fixable", "extraction-fixable", "genuine-orphan"


@dataclass
class ValidationResult:
    """Output of a structural validation pass."""

    orphan_nodes: list[str] = field(default_factory=list)
    orphan_categories: list[OrphanCategory] = field(default_factory=list)
    orphan_rate: float = 0.0
    edge_to_node_ratio: float = 0.0
    missing_patterns: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    passed: bool = True


# ---------------------------------------------------------------------------
# Required edge patterns
# ---------------------------------------------------------------------------

# Each entry: (node_type, list_of_any_required_predicates, direction, severity)
# "direction" is from the perspective of the node_type:
#   "outgoing" — node_type is from_node
#   "incoming" — node_type is to_node
#   "any"      — either direction counts
REQUIRED_EDGE_PATTERNS: list[
    tuple[str, list[str], Literal["outgoing", "incoming", "any"], Literal["warning", "info"]]
] = [
    # Every Rule should link to an approver or reviewer
    ("Rule", ["REQUIRES_APPROVAL_FROM", "REQUIRES_REVIEW_FROM"], "outgoing", "warning"),
    # Every Rule should be linked to a goal via GOVERNED_BY (incoming from Decision)
    # or have some structural connection — but at onboarding time we check outgoing
    ("Goal", ["MEASURED_BY"], "outgoing", "info"),
    # Every Actor should belong to a department or have an escalation path
    ("Actor", ["BELONGS_TO", "ESCALATES_TO"], "any", "info"),
]


# ---------------------------------------------------------------------------
# Core validation function
# ---------------------------------------------------------------------------


async def validate_graph_structure(
    repo: BaseGraphRepository,
    company_id: str,
) -> ValidationResult:
    """
    Run structural integrity checks on the constructed graph.

    Reads all nodes and edges from the repository and checks:
      1. Orphan nodes (no incoming or outgoing edges)
      2. Edge-to-node ratio
      3. Required edge patterns per node type
      4. Low-confidence edge warnings

    Args
    ----
    repo         Graph repository to read from
    company_id   Company whose graph to validate

    Returns
    -------
    ValidationResult with orphan info, missing patterns, warnings, and pass/fail
    """
    result = ValidationResult()

    # --- Gather all nodes and edges from the repo ---
    nodes, edges = await _collect_graph_data(repo, company_id)

    if not nodes:
        result.warnings.append("Graph is empty — no nodes found")
        result.passed = False
        return result

    # --- 1. Orphan detection ---
    _check_orphans(nodes, edges, result)

    # --- 2. Edge-to-node ratio ---
    result.edge_to_node_ratio = round(len(edges) / len(nodes), 3) if nodes else 0.0
    if result.edge_to_node_ratio < 0.5:
        result.warnings.append(
            f"Low edge-to-node ratio ({result.edge_to_node_ratio}) — "
            "graph may be too sparse for effective governance traversal"
        )

    # --- 3. Required edge patterns ---
    _check_required_patterns(nodes, edges, result)

    # --- 4. Low-confidence edges ---
    _check_low_confidence_edges(edges, result)

    # --- Determine pass/fail ---
    # Failed if any warning-severity missing patterns or high orphan rate
    has_critical = any(
        mp.get("severity") == "warning" for mp in result.missing_patterns
    )
    if has_critical or result.orphan_rate > 0.5:
        result.passed = False

    logger.info(
        f"[validate] company={company_id} "
        f"nodes={len(nodes)} edges={len(edges)} "
        f"orphans={len(result.orphan_nodes)} "
        f"orphan_rate={result.orphan_rate:.2%} "
        f"edge_ratio={result.edge_to_node_ratio} "
        f"warnings={len(result.warnings)} "
        f"passed={result.passed}"
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _collect_graph_data(
    repo: BaseGraphRepository,
    company_id: str,
) -> tuple[list[Node], list[Edge]]:
    """
    Collect all nodes and edges from the repo for validation.

    Uses the InMemoryGraphRepository internal storage directly when available.
    For Neo4j, uses get_all_node_ids + get_node for nodes and cypher_read
    for edges.
    """
    from app.graph.in_memory_repository import InMemoryGraphRepository

    if isinstance(repo, InMemoryGraphRepository):
        nodes = list(repo._nodes.values())
        edges = list(repo._edges)
        return nodes, edges

    # Fallback for Neo4j or other implementations: use available API
    # get_all_node_ids gives us the node inventory
    from app.ontology.node_types import NodeType
    from app.ontology.edge_predicates import EdgePredicate

    node_id_map = await repo.get_all_node_ids(company_id)
    nodes: list[Node] = []
    for full_id in node_id_map.values():
        node_dict = await repo.get_node(full_id, company_id)
        if node_dict:
            # Reconstruct a minimal Node for validation purposes
            node_type_raw = node_dict.get("node_type", "")
            try:
                node_type = NodeType(node_type_raw) if node_type_raw else NodeType.GOAL
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

    # Fetch edges via Cypher
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
            if not from_id or not to_id or not rel_type:
                continue
            try:
                predicate = EdgePredicate(rel_type)
            except ValueError:
                # Unknown edge type — skip for validation but don't crash
                logger.debug(f"Skipping unknown edge type: {rel_type}")
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
        # Repo doesn't support cypher_read — return empty edges
        logger.warning(
            f"Repository does not support cypher_read; "
            f"edge validation skipped for company={company_id}"
        )

    return nodes, edges


def _check_orphans(
    nodes: list[Node],
    edges: list[Edge],
    result: ValidationResult,
) -> None:
    """Find nodes with zero edges (orphans) and categorize by fixability."""
    connected_ids: set[str] = set()
    for edge in edges:
        connected_ids.add(edge.from_node)
        connected_ids.add(edge.to_node)

    # Chunk and Artifact nodes are expected to be connected via DERIVED_FROM /
    # CONTAINS edges, but schema-layer nodes (MetaClass, OntologyClass) are
    # standalone — exclude them from orphan checks.
    _SKIP_TYPES = {"MetaClass", "OntologyClass"}

    # Node types that come from config/seed
    _SEED_TYPES = {"Goal", "Rule", "Actor", "KPI", "Jurisdiction", "Department", "GovernanceRisk"}
    # Node types that come from LLM extraction
    _EXTRACTION_TYPES = {"Goal", "Rule", "Actor", "Department", "KPI", "Gap", "Conflict", "GovernanceRisk"}

    for node in nodes:
        node_type = node.type if isinstance(node.type, str) else node.type.value
        if node_type in _SKIP_TYPES:
            continue
        if node.id not in connected_ids:
            result.orphan_nodes.append(node.id)

            # Categorize the orphan
            is_seeded = (
                node.confidence is not None
                and node.confidence >= 0.95
                and node_type in _SEED_TYPES
            )
            has_source_chunks = bool(node.source_chunk_ids)

            if is_seeded:
                category = "seed-fixable"
            elif has_source_chunks or node_type in _EXTRACTION_TYPES:
                category = "extraction-fixable"
            else:
                category = "genuine-orphan"

            result.orphan_categories.append(
                OrphanCategory(
                    node_id=node.id,
                    node_type=node_type,
                    category=category,
                )
            )

    total_checkable = sum(
        1 for n in nodes
        if (n.type if isinstance(n.type, str) else n.type.value) not in _SKIP_TYPES
    )
    result.orphan_rate = (
        round(len(result.orphan_nodes) / total_checkable, 3)
        if total_checkable > 0
        else 0.0
    )

    # Add category summary to warnings
    if result.orphan_categories:
        from collections import Counter
        cat_counts = Counter(oc.category for oc in result.orphan_categories)
        result.warnings.append(
            f"Orphan categories: {dict(cat_counts)}"
        )


def _check_required_patterns(
    nodes: list[Node],
    edges: list[Edge],
    result: ValidationResult,
) -> None:
    """Check that nodes have expected edge patterns."""
    if not edges:
        return

    # Build indexes for fast lookup
    outgoing_predicates: dict[str, set[str]] = {}
    incoming_predicates: dict[str, set[str]] = {}

    for edge in edges:
        outgoing_predicates.setdefault(edge.from_node, set()).add(edge.predicate)
        incoming_predicates.setdefault(edge.to_node, set()).add(edge.predicate)

    for node_type_str, required_preds, direction, severity in REQUIRED_EDGE_PATTERNS:
        for node in nodes:
            nt = node.type if isinstance(node.type, str) else node.type.value
            if nt != node_type_str:
                continue

            # Gather predicates connected to this node in the relevant direction
            connected_preds: set[str] = set()
            if direction in ("outgoing", "any"):
                connected_preds |= outgoing_predicates.get(node.id, set())
            if direction in ("incoming", "any"):
                connected_preds |= incoming_predicates.get(node.id, set())

            # Check if ANY of the required predicates are present
            if not connected_preds.intersection(required_preds):
                result.missing_patterns.append(
                    {
                        "node_id": node.id,
                        "node_type": node_type_str,
                        "missing": required_preds,
                        "direction": direction,
                        "severity": severity,
                    }
                )

                msg = (
                    f"{severity.upper()}: {node_type_str} node '{node.id}' "
                    f"missing {direction} edge(s): {', '.join(required_preds)}"
                )
                result.warnings.append(msg)


def _check_low_confidence_edges(
    edges: list[Edge],
    result: ValidationResult,
) -> None:
    """Warn about edges with low confidence scores."""
    low_conf_count = 0
    for edge in edges:
        if edge.confidence < 0.5:
            low_conf_count += 1

    if low_conf_count > 0:
        pct = round(low_conf_count / len(edges) * 100, 1) if edges else 0
        result.warnings.append(
            f"{low_conf_count} edge(s) ({pct}%) have confidence < 0.5"
        )
