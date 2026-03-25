"""
Node type vocabulary for the DecisionGovernance AI ontology.

Three-layer architecture:
  SCHEMA   — MetaClass + OntologyClass nodes, seeded once at system init
  DOMAIN   — Company governance vocabulary, MERGEd at onboarding
  INSTANCE — Runtime data, CREATEd each validation run

Each NodeType carries metadata (NodeTypeMetadata) that records:
  - which layer it belongs to
  - which meta-classes it inherits from (for Neo4j multi-label assignment)
  - its merge strategy
  - the exact Neo4j labels to apply when writing to the graph
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------

class NodeLayer(str, Enum):
    SCHEMA = "schema"      # OntologyClass + MetaClass seed nodes
    DOMAIN = "domain"      # Company governance vocab (MERGE)
    INSTANCE = "instance"  # Runtime decision data (CREATE)


# ---------------------------------------------------------------------------
# Meta-classes (governance upper ontology)
# ---------------------------------------------------------------------------

class MetaClass(str, Enum):
    # Pure meta-ontological categories
    ENTITY = "Entity"           # Identifiable thing that persists through time
    PROCESS = "Process"         # Thing that unfolds over time
    INFORMATION = "Information" # Knowledge artifact
    QUALITY = "Quality"         # Property-bearing entity

    # Governance upper ontology
    AUTHORITY = "Authority"     # Entity with power to permit/block/require
    COMPLIANCE = "Compliance"   # Requirement from external mandate
    RISK = "Risk"               # Potential negative consequence
    RESOLUTION = "Resolution"   # Outcome of a governance process
    ANTAGONISM = "Antagonism"   # Incompatibility between governance entities (formerly CONFLICT)


# ---------------------------------------------------------------------------
# Merge strategy
# ---------------------------------------------------------------------------

class MergeStrategy(str, Enum):
    MERGE = "merge"             # Company nodes — exist once, MERGE on stable ID
    CREATE = "create"           # Decision nodes — always new, timestamped
    MERGE_ON_HASH = "merge_hash"  # Chunk nodes — same content = same node


# ---------------------------------------------------------------------------
# Node type metadata
# ---------------------------------------------------------------------------

@dataclass
class NodeTypeMetadata:
    """Carries ontological metadata for a NodeType."""
    layer: NodeLayer
    meta_classes: list[MetaClass]
    merge_strategy: MergeStrategy
    neo4j_labels: list[str]  # Multi-labels applied when writing to Neo4j
    description: str = ""


# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    # --- Schema-layer (seeded at system init) ---
    META_CLASS = "MetaClass"
    ONTOLOGY_CLASS = "OntologyClass"

    # --- Domain-layer (company governance vocab, MERGE) ---
    GOAL = "Goal"
    RULE = "Rule"
    ACTOR = "Actor"
    DEPARTMENT = "Department"
    KPI = "KPI"
    JURISDICTION = "Jurisdiction"
    ARTIFACT = "Artifact"
    CHUNK = "Chunk"
    GAP = "Gap"
    CONFLICT = "Conflict"
    DECISION_TYPE = "DecisionType"   # Category of decision (Spend, Hiring, DataUsage, ...)
    GOVERNANCE_RISK = "GovernanceRisk"  # Standing governance risk category (domain-layer, MERGE)

    # --- Instance-layer (runtime, CREATE) ---
    DECISION = "Decision"
    RISK = "Risk"
    APPROVAL_STEP = "ApprovalStep"
    EXCEPTION = "Exception"
    OUTCOME = "Outcome"
    OPERATIONAL_CONTEXT = "OperationalContext"  # Tier 2 snapshot (budget, headcount, risk flags)


# ---------------------------------------------------------------------------
# Registry — canonical metadata for each NodeType
# ---------------------------------------------------------------------------

NODE_TYPE_REGISTRY: dict[NodeType, NodeTypeMetadata] = {

    # -- Schema layer --
    NodeType.META_CLASS: NodeTypeMetadata(
        layer=NodeLayer.SCHEMA,
        meta_classes=[],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["MetaClass"],
        description="Upper ontology primitive (Entity, Authority, Risk, ...)",
    ),
    NodeType.ONTOLOGY_CLASS: NodeTypeMetadata(
        layer=NodeLayer.SCHEMA,
        meta_classes=[],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["OntologyClass"],
        description="Domain class definition (Goal, Rule, Actor, ...) — IS_A MetaClass",
    ),

    # -- Domain layer --
    NodeType.GOAL: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.ENTITY, MetaClass.AUTHORITY],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Goal", "Entity", "Authority"],
        description="Strategic goal derived from company artifacts",
    ),
    NodeType.RULE: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.AUTHORITY, MetaClass.COMPLIANCE],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Rule", "Authority", "Compliance"],
        description="Governance rule (documented, inferred, or from interview)",
    ),
    NodeType.ACTOR: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.ENTITY, MetaClass.AUTHORITY],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Actor", "Entity", "Authority"],
        description="Person or role with governance authority",
    ),
    NodeType.DEPARTMENT: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.ENTITY],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Department", "Entity"],
        description="Organizational unit",
    ),
    NodeType.KPI: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.QUALITY],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["KPI", "Quality"],
        description="Key performance indicator measuring a strategic goal",
    ),
    NodeType.JURISDICTION: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.ENTITY, MetaClass.COMPLIANCE],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Jurisdiction", "Entity", "Compliance"],
        description="Legal or regulatory jurisdiction (US, EU, GDPR, HIPAA, ...)",
    ),
    NodeType.ARTIFACT: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.INFORMATION],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Artifact", "Information"],
        description="Source document ingested during onboarding (PDF, email, Slack, ...)",
    ),
    NodeType.CHUNK: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.INFORMATION],
        merge_strategy=MergeStrategy.MERGE_ON_HASH,
        neo4j_labels=["Chunk", "Information"],
        description="Text chunk from an artifact, carries 1536d embedding for vector search",
    ),
    NodeType.GAP: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.INFORMATION],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Gap", "Information"],
        description="Detected governance gap (missing rule, missing authority, ...) — knowledge about what is absent",
    ),
    NodeType.CONFLICT: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.ANTAGONISM],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["Conflict"],
        description="Reified conflict between two governance entities (Goal vs Goal)",
    ),
    NodeType.DECISION_TYPE: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.ENTITY],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["DecisionType", "Entity"],
        description="Category of decision (Spend, Hiring, DataUsage, VendorContract, ...)",
    ),
    NodeType.GOVERNANCE_RISK: NodeTypeMetadata(
        layer=NodeLayer.DOMAIN,
        meta_classes=[MetaClass.RISK, MetaClass.QUALITY],
        merge_strategy=MergeStrategy.MERGE,
        neo4j_labels=["GovernanceRisk", "Risk", "Quality"],
        description="Standing governance risk category (e.g., budget overrun, compliance violation) — exists before any decision",
    ),

    # -- Instance layer --
    NodeType.DECISION: NodeTypeMetadata(
        layer=NodeLayer.INSTANCE,
        meta_classes=[MetaClass.PROCESS, MetaClass.QUALITY],
        merge_strategy=MergeStrategy.CREATE,
        neo4j_labels=["Decision", "Process", "Quality"],
        description="AI-proposed decision submitted for governance validation",
    ),
    NodeType.RISK: NodeTypeMetadata(
        layer=NodeLayer.INSTANCE,
        meta_classes=[MetaClass.QUALITY],
        merge_strategy=MergeStrategy.CREATE,
        neo4j_labels=["Risk", "Quality"],
        description="Risk identified for a specific decision",
    ),
    NodeType.APPROVAL_STEP: NodeTypeMetadata(
        layer=NodeLayer.INSTANCE,
        meta_classes=[MetaClass.PROCESS, MetaClass.AUTHORITY],
        merge_strategy=MergeStrategy.CREATE,
        neo4j_labels=["ApprovalStep", "Process", "Authority"],
        description="Individual approval action in a multi-step approval chain",
    ),
    NodeType.EXCEPTION: NodeTypeMetadata(
        layer=NodeLayer.INSTANCE,
        meta_classes=[MetaClass.RESOLUTION],
        merge_strategy=MergeStrategy.CREATE,
        neo4j_labels=["Exception", "Resolution"],
        description="Authorized deviation from a governance rule",
    ),
    NodeType.OUTCOME: NodeTypeMetadata(
        layer=NodeLayer.INSTANCE,
        meta_classes=[MetaClass.RESOLUTION],
        merge_strategy=MergeStrategy.CREATE,
        neo4j_labels=["Outcome", "Resolution"],
        description="Final verdict on a decision (approved, rejected, escalated)",
    ),
    NodeType.OPERATIONAL_CONTEXT: NodeTypeMetadata(
        layer=NodeLayer.INSTANCE,
        meta_classes=[MetaClass.INFORMATION],
        merge_strategy=MergeStrategy.CREATE,
        neo4j_labels=["OperationalContext", "Information"],
        description="Tier 2 operational snapshot (budget remaining, headcount, risk flags) pushed by client",
    ),
}


# ---------------------------------------------------------------------------
# Helper: get all NodeTypes for a given layer or meta-class
# ---------------------------------------------------------------------------

def get_types_by_layer(layer: NodeLayer) -> list[NodeType]:
    return [nt for nt, meta in NODE_TYPE_REGISTRY.items() if meta.layer == layer]


def get_types_by_meta_class(meta_class: MetaClass) -> list[NodeType]:
    return [
        nt for nt, meta in NODE_TYPE_REGISTRY.items()
        if meta_class in meta.meta_classes
    ]


def get_neo4j_labels(node_type: NodeType) -> list[str]:
    """Return the Neo4j multi-labels to apply for this node type."""
    return NODE_TYPE_REGISTRY[node_type].neo4j_labels


def get_merge_strategy(node_type: NodeType) -> MergeStrategy:
    return NODE_TYPE_REGISTRY[node_type].merge_strategy
