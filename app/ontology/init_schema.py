"""
Schema layer seed script for DecisionGovernance AI.

Generates Cypher MERGE statements that seed the meta-layer into a Neo4j database:
  - MetaClass nodes  (Entity, Process, Authority, Compliance, ...)
  - OntologyClass nodes  (Goal, Rule, Actor, Decision, ...)
  - IS_A edges from OntologyClass to MetaClass

These statements are idempotent (MERGE, not CREATE) and safe to re-run.
They must be executed once per company database before any onboarding runs.

Usage (called by Neo4jGraphRepository.initialize() in Step 6):
    from app.ontology.init_schema import get_schema_seed_statements
    for statement in get_schema_seed_statements():
        session.run(statement)
"""

from __future__ import annotations

from app.ontology.node_types import (
    MetaClass,
    NodeType,
    NodeLayer,
    NODE_TYPE_REGISTRY,
)


# ---------------------------------------------------------------------------
# MetaClass seed statements
# ---------------------------------------------------------------------------

_META_CLASS_DESCRIPTIONS: dict[MetaClass, str] = {
    MetaClass.ENTITY: "Identifiable thing that persists through time",
    MetaClass.PROCESS: "Thing that unfolds over time",
    MetaClass.INFORMATION: "Knowledge artifact or text fragment",
    MetaClass.QUALITY: "Property-bearing entity",
    MetaClass.AUTHORITY: "Entity with power to permit, block, or require action",
    MetaClass.COMPLIANCE: "Requirement arising from external mandate or regulation",
    MetaClass.RISK: "Potential negative consequence of a decision or action",
    MetaClass.RESOLUTION: "Outcome or resolution of a governance process",
    MetaClass.ANTAGONISM: "Incompatibility between two governance entities",
}


def _meta_class_statements() -> list[str]:
    """Generate MERGE statements for all MetaClass nodes."""
    statements = []
    for mc, description in _META_CLASS_DESCRIPTIONS.items():
        escaped_desc = description.replace("'", "\\'")
        statements.append(
            f"MERGE (:MetaClass {{id: '{mc.value}', description: '{escaped_desc}'}})"
        )
    return statements


# ---------------------------------------------------------------------------
# OntologyClass seed statements
# ---------------------------------------------------------------------------

def _ontology_class_statements() -> list[str]:
    """Generate MERGE statements for all domain + instance OntologyClass nodes."""
    statements = []
    for node_type, meta in NODE_TYPE_REGISTRY.items():
        # Skip schema-layer types — MetaClass and OntologyClass are not self-referential
        if meta.layer == NodeLayer.SCHEMA:
            continue

        labels_str = ":".join(["OntologyClass"] + meta.neo4j_labels)
        merge_strategy = meta.merge_strategy.value
        layer = meta.layer.value
        description = meta.description.replace("'", "\\'")
        neo4j_labels_csv = ",".join(meta.neo4j_labels)

        statements.append(
            f"MERGE (:{labels_str} {{"
            f"id: '{node_type.value}', "
            f"label: '{node_type.value}', "
            f"layer: '{layer}', "
            f"merge_strategy: '{merge_strategy}', "
            f"neo4j_labels: '{neo4j_labels_csv}', "
            f"description: '{description}'"
            f"}})"
        )
    return statements


# ---------------------------------------------------------------------------
# IS_A edge statements
# ---------------------------------------------------------------------------

def _is_a_statements() -> list[str]:
    """Generate MERGE statements for OntologyClass -[:IS_A]-> MetaClass edges."""
    statements = []
    for node_type, meta in NODE_TYPE_REGISTRY.items():
        if meta.layer == NodeLayer.SCHEMA:
            continue
        for mc in meta.meta_classes:
            statements.append(
                f"MATCH (c:OntologyClass {{id: '{node_type.value}'}}), "
                f"(m:MetaClass {{id: '{mc.value}'}}) "
                f"MERGE (c)-[:IS_A]->(m)"
            )
    return statements


# ---------------------------------------------------------------------------
# Constraint / index statements
# ---------------------------------------------------------------------------

_CONSTRAINT_STATEMENTS: list[str] = [
    # ── Schema layer: unique id on MetaClass and OntologyClass ──────────────
    "CREATE CONSTRAINT meta_class_id IF NOT EXISTS FOR (n:MetaClass) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT ontology_class_id IF NOT EXISTS FOR (n:OntologyClass) REQUIRE n.id IS UNIQUE",

    # ── Domain layer: unique id enforces MERGE idempotency ──────────────────
    # Format: {company_id}:{node_type}:{semantic_id}
    "CREATE CONSTRAINT goal_id IF NOT EXISTS FOR (n:Goal) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (n:Rule) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT actor_id IF NOT EXISTS FOR (n:Actor) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT department_id IF NOT EXISTS FOR (n:Department) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT kpi_id IF NOT EXISTS FOR (n:KPI) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT jurisdiction_id IF NOT EXISTS FOR (n:Jurisdiction) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT artifact_id IF NOT EXISTS FOR (n:Artifact) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT gap_id IF NOT EXISTS FOR (n:Gap) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT conflict_id IF NOT EXISTS FOR (n:Conflict) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT decision_type_id IF NOT EXISTS FOR (n:DecisionType) REQUIRE n.id IS UNIQUE",

    # ── Instance layer: unique id on CREATE nodes (decision, approval, etc) ─
    # Timestamp-namespaced so collisions are impossible, but unique constraint
    # ensures no accidental duplicates from retried pipeline runs.
    "CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (n:Decision) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT approval_step_id IF NOT EXISTS FOR (n:ApprovalStep) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT exception_id IF NOT EXISTS FOR (n:Exception) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT outcome_id IF NOT EXISTS FOR (n:Outcome) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT operational_context_id IF NOT EXISTS FOR (n:OperationalContext) REQUIRE n.id IS UNIQUE",

    # ── Chunk: MERGE on content_hash (same content = same node) ─────────────
    "CREATE CONSTRAINT chunk_content_hash IF NOT EXISTS FOR (n:Chunk) REQUIRE n.content_hash IS UNIQUE",

    # ── Vector index: Chunk embeddings (text-embedding-3-small, 1536d) ──────
    """CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
FOR (c:Chunk) ON c.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
}""",

    # ── Vector index: Decision embeddings (for semantic similarity lookup) ──
    """CREATE VECTOR INDEX decision_embeddings IF NOT EXISTS
FOR (d:Decision) ON d.embedding
OPTIONS {
  indexConfig: {
    `vector.dimensions`: 1536,
    `vector.similarity_function`: 'cosine'
  }
}""",

    # ── B-tree indexes for common Cypher traversal patterns ─────────────────
    "CREATE INDEX chunk_artifact IF NOT EXISTS FOR (n:Chunk) ON (n.artifact_id)",
    "CREATE INDEX artifact_company IF NOT EXISTS FOR (n:Artifact) ON (n.content_hash)",
    "CREATE INDEX decision_company_idx IF NOT EXISTS FOR (n:Decision) ON (n.company_id)",
    "CREATE INDEX decision_status IF NOT EXISTS FOR (n:Decision) ON (n.status)",
    "CREATE INDEX rule_company_idx IF NOT EXISTS FOR (n:Rule) ON (n.company_id)",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_schema_seed_statements() -> list[str]:
    """
    Return all idempotent Cypher statements needed to seed the schema layer.

    Order matters:
    1. Constraints + indexes (fast fail if Neo4j version incompatible)
    2. MetaClass nodes
    3. OntologyClass nodes (must reference MetaClass values)
    4. IS_A edges (must run after both node types exist)
    """
    return (
        _CONSTRAINT_STATEMENTS
        + _meta_class_statements()
        + _ontology_class_statements()
        + _is_a_statements()
    )


# Full script as a single semicolon-separated string (for CLI / migration tools)
SCHEMA_SEED_CYPHER: str = ";\n".join(get_schema_seed_statements()) + ";"


if __name__ == "__main__":
    # Print the full seed script for inspection or manual execution
    statements = get_schema_seed_statements()
    print(f"// DecisionGovernance AI — Schema Layer Seed ({len(statements)} statements)")
    print()
    for stmt in statements:
        print(stmt + ";")
        print()
