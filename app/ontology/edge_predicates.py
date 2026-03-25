"""
Edge predicate vocabulary for the DecisionGovernance AI ontology.

Each EdgePredicate is a typed relation with defined domain (source) and range (target)
node types. The EDGE_REGISTRY carries this metadata for validation and documentation.

Mapping to Neo4j: EdgePredicate → relationship type  (e.g. -[:SUPPORTS]->)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.ontology.node_types import NodeType


# ---------------------------------------------------------------------------
# Edge predicate metadata
# ---------------------------------------------------------------------------

@dataclass
class EdgePredicateMetadata:
    """Domain/range constraints and human description for an edge predicate."""
    domain_types: list[NodeType]   # valid source node types
    range_types: list[NodeType]    # valid target node types
    description: str
    allows_properties: bool = True  # whether the edge can carry properties


# ---------------------------------------------------------------------------
# Edge predicates
# ---------------------------------------------------------------------------

class EdgePredicate(str, Enum):

    # --- Strategic alignment ---
    SUPPORTS = "SUPPORTS"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    MEASURED_BY = "MEASURED_BY"
    HAS_CONFLICT = "HAS_CONFLICT"

    # --- Approval / authority ---
    REQUIRES_APPROVAL_FROM = "REQUIRES_APPROVAL_FROM"
    REQUIRES_REVIEW_FROM = "REQUIRES_REVIEW_FROM"
    ESCALATES_TO = "ESCALATES_TO"
    SUBMITTED_BY = "SUBMITTED_BY"
    BELONGS_TO = "BELONGS_TO"
    HAS_APPROVAL_STEP = "HAS_APPROVAL_STEP"

    # --- Governance structure ---
    GOVERNED_BY = "GOVERNED_BY"
    EXCEEDS_THRESHOLD = "EXCEEDS_THRESHOLD"
    HAS_GAP = "HAS_GAP"
    OVERRIDES = "OVERRIDES"
    AUTHORIZED_BY = "AUTHORIZED_BY"
    APPLIES_TO = "APPLIES_TO"

    # --- Risk ---
    GENERATES_RISK = "GENERATES_RISK"
    HAS_RISK = "HAS_RISK"
    MITIGATES = "MITIGATES"

    # --- Provenance (onboarding) ---
    DERIVED_FROM = "DERIVED_FROM"
    CONTAINS = "CONTAINS"

    # --- Decision classification ---
    HAS_DECISION_TYPE = "HAS_DECISION_TYPE"
    EVALUATED_AGAINST = "EVALUATED_AGAINST"

    # --- Decision history ---
    RESULTED_IN = "RESULTED_IN"
    TRIGGERED = "TRIGGERED"
    APPROVED_BY = "APPROVED_BY"

    # --- Schema layer ---
    IS_A = "IS_A"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_N = NodeType  # alias for brevity in registry below

EDGE_REGISTRY: dict[EdgePredicate, EdgePredicateMetadata] = {

    # Strategic alignment
    EdgePredicate.SUPPORTS: EdgePredicateMetadata(
        domain_types=[_N.DECISION, _N.GOAL],
        range_types=[_N.GOAL],
        description="Decision or goal advances this strategic goal",
    ),
    EdgePredicate.CONFLICTS_WITH: EdgePredicateMetadata(
        domain_types=[_N.DECISION, _N.GOAL],
        range_types=[_N.GOAL],
        description="Decision or goal conflicts with this strategic goal",
    ),
    EdgePredicate.MEASURED_BY: EdgePredicateMetadata(
        domain_types=[_N.GOAL],
        range_types=[_N.KPI],
        description="Goal is measured by this KPI",
    ),
    EdgePredicate.HAS_CONFLICT: EdgePredicateMetadata(
        domain_types=[_N.GOAL],
        range_types=[_N.CONFLICT],
        description="Goal participates in this reified conflict node",
    ),

    # Approval / authority
    EdgePredicate.REQUIRES_APPROVAL_FROM: EdgePredicateMetadata(
        domain_types=[_N.RULE],
        range_types=[_N.ACTOR],
        description="Rule mandates full approval from this role",
        allows_properties=True,  # carries: required(bool), rationale(str)
    ),
    EdgePredicate.REQUIRES_REVIEW_FROM: EdgePredicateMetadata(
        domain_types=[_N.RULE],
        range_types=[_N.ACTOR],
        description="Rule mandates advisory review (not binding approval) from this role",
    ),
    EdgePredicate.ESCALATES_TO: EdgePredicateMetadata(
        domain_types=[_N.ACTOR],
        range_types=[_N.ACTOR],
        description="Approval escalates to this higher-authority role",
    ),
    EdgePredicate.SUBMITTED_BY: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.ACTOR],
        description="Decision was submitted by this actor",
    ),
    EdgePredicate.BELONGS_TO: EdgePredicateMetadata(
        domain_types=[_N.ACTOR],
        range_types=[_N.DEPARTMENT],
        description="Actor is a member of this department",
    ),
    EdgePredicate.HAS_APPROVAL_STEP: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.APPROVAL_STEP],
        description="Decision has this approval step in its chain",
        allows_properties=True,  # carries: sequential_order(int)
    ),

    # Governance structure
    EdgePredicate.GOVERNED_BY: EdgePredicateMetadata(
        domain_types=[_N.DECISION, _N.RULE],
        range_types=[_N.RULE, _N.GOAL],
        description="Decision is governed by this rule, or rule serves this goal",
    ),
    EdgePredicate.EXCEEDS_THRESHOLD: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.RULE],
        description="Decision's dimension value exceeds the rule's threshold condition",
        allows_properties=True,  # carries: field(str), actual_value, threshold_value
    ),
    EdgePredicate.HAS_GAP: EdgePredicateMetadata(
        domain_types=[_N.RULE, _N.GOAL],
        range_types=[_N.GAP],
        description="Governance gap associated with this rule or goal",
    ),
    EdgePredicate.OVERRIDES: EdgePredicateMetadata(
        domain_types=[_N.EXCEPTION],
        range_types=[_N.RULE],
        description="Exception authorizes a deviation from this rule",
    ),
    EdgePredicate.AUTHORIZED_BY: EdgePredicateMetadata(
        domain_types=[_N.EXCEPTION],
        range_types=[_N.ACTOR],
        description="Exception was authorized by this actor",
    ),
    EdgePredicate.APPLIES_TO: EdgePredicateMetadata(
        domain_types=[_N.EXCEPTION],
        range_types=[_N.DECISION],
        description="Exception covers this specific decision",
    ),

    # Risk
    EdgePredicate.GENERATES_RISK: EdgePredicateMetadata(
        domain_types=[_N.RULE],
        range_types=[_N.RISK, _N.GOVERNANCE_RISK],
        description="Triggering this rule generates this governance risk",
    ),
    EdgePredicate.HAS_RISK: EdgePredicateMetadata(
        domain_types=[_N.DECISION, _N.GOAL],
        range_types=[_N.RISK, _N.GOVERNANCE_RISK],
        description="Decision or goal has this risk (direct or standing governance risk)",
    ),
    EdgePredicate.MITIGATES: EdgePredicateMetadata(
        domain_types=[_N.DECISION, _N.RULE],
        range_types=[_N.RISK, _N.GOVERNANCE_RISK],
        description="Decision or rule mitigates this identified risk",
    ),

    # Provenance (onboarding)
    EdgePredicate.DERIVED_FROM: EdgePredicateMetadata(
        domain_types=[_N.GOAL, _N.RULE, _N.ACTOR, _N.CONFLICT, _N.GAP, _N.DECISION],
        range_types=[_N.CHUNK],
        description="Ontology node was derived from this text chunk during onboarding",
        allows_properties=True,  # carries: confidence(float), scout(str)
    ),
    EdgePredicate.CONTAINS: EdgePredicateMetadata(
        domain_types=[_N.ARTIFACT],
        range_types=[_N.CHUNK],
        description="Artifact contains this text chunk",
        allows_properties=True,  # carries: chunk_index(int), page(int)
    ),

    # Decision classification
    EdgePredicate.HAS_DECISION_TYPE: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.DECISION_TYPE],
        description="Decision belongs to this category (Spend, Hiring, DataUsage, ...)",
    ),
    EdgePredicate.EVALUATED_AGAINST: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.OPERATIONAL_CONTEXT],
        description="Decision was evaluated against this Tier 2 operational snapshot",
        allows_properties=True,  # carries: evaluated_at(str)
    ),

    # Decision history
    EdgePredicate.RESULTED_IN: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.OUTCOME],
        description="Decision led to this outcome",
    ),
    EdgePredicate.TRIGGERED: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.RULE],
        description="Past decision triggered or was evaluated under this governance rule",
    ),
    EdgePredicate.APPROVED_BY: EdgePredicateMetadata(
        domain_types=[_N.DECISION],
        range_types=[_N.ACTOR],
        description="Past decision was approved by this actor/role",
    ),

    # Schema layer
    EdgePredicate.IS_A: EdgePredicateMetadata(
        domain_types=[_N.ONTOLOGY_CLASS],
        range_types=[_N.META_CLASS],
        description="OntologyClass inherits from this MetaClass (class hierarchy)",
        allows_properties=False,
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_predicates_from(node_type: NodeType) -> list[EdgePredicate]:
    """Return all predicates that can originate from the given node type."""
    return [
        pred for pred, meta in EDGE_REGISTRY.items()
        if node_type in meta.domain_types
    ]


def get_predicates_to(node_type: NodeType) -> list[EdgePredicate]:
    """Return all predicates that can target the given node type."""
    return [
        pred for pred, meta in EDGE_REGISTRY.items()
        if node_type in meta.range_types
    ]
