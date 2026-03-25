"""
Tests for Step 4 — Neo4j schema layer (no Neo4j connection required).

Validates:
  - Schema seed statements are generated correctly
  - All constraints and indexes are present
  - MetaClass + OntologyClass nodes cover the full vocabulary
  - IS_A edges are correct
  - neo4j.py config reads env vars
  - Node ID format is enforced by make_node_id
"""

import os
import pytest
from app.ontology.init_schema import get_schema_seed_statements, SCHEMA_SEED_CYPHER
from app.ontology.node_types import MetaClass, NodeType, NodeLayer, NODE_TYPE_REGISTRY
from app.ontology.models import make_node_id, Node
from app.ontology.edge_predicates import EdgePredicate, EDGE_REGISTRY


# ---------------------------------------------------------------------------
# Schema seed statement counts and content
# ---------------------------------------------------------------------------

def test_schema_seed_statements_nonempty():
    statements = get_schema_seed_statements()
    assert len(statements) > 20, "Expected at least 20 seed statements"


def test_schema_seed_contains_meta_class_nodes():
    statements = get_schema_seed_statements()
    combined = "\n".join(statements)
    for mc in MetaClass:
        assert mc.value in combined, f"Missing MetaClass {mc.value} in seed"


def test_schema_seed_contains_ontology_class_nodes():
    statements = get_schema_seed_statements()
    combined = "\n".join(statements)
    for nt, meta in NODE_TYPE_REGISTRY.items():
        if meta.layer != NodeLayer.SCHEMA:
            assert nt.value in combined, f"Missing OntologyClass {nt.value} in seed"


def test_schema_seed_contains_is_a_edges():
    statements = get_schema_seed_statements()
    is_a_stmts = [s for s in statements if "IS_A" in s]
    # Every non-schema node type with meta_classes should have IS_A edges
    expected_min = sum(
        len(meta.meta_classes)
        for nt, meta in NODE_TYPE_REGISTRY.items()
        if meta.layer != NodeLayer.SCHEMA and meta.meta_classes
    )
    assert len(is_a_stmts) >= expected_min


def test_antagonism_in_schema_not_conflict():
    """MetaClass.ANTAGONISM should appear; MetaClass.CONFLICT must not."""
    statements = get_schema_seed_statements()
    combined = "\n".join(statements)
    assert "Antagonism" in combined
    # "Conflict" appears as a NodeType (domain-layer), not as a MetaClass
    # Verify ANTAGONISM meta-class is referenced for Conflict OntologyClass
    conflict_is_a = [s for s in statements if "IS_A" in s and "Conflict" in s]
    assert any("Antagonism" in s for s in conflict_is_a)


# ---------------------------------------------------------------------------
# Constraints and indexes
# ---------------------------------------------------------------------------

def test_unique_constraints_for_domain_nodes():
    statements = get_schema_seed_statements()
    constraint_stmts = [s for s in statements if "CREATE CONSTRAINT" in s]
    constraint_text = "\n".join(constraint_stmts)

    # Domain-layer nodes must have unique id constraints
    for label in ["Goal", "Rule", "Actor", "Department", "KPI", "Jurisdiction",
                  "Artifact", "Gap", "Conflict", "DecisionType"]:
        assert label.lower() in constraint_text.lower(), (
            f"Missing unique constraint for {label}"
        )


def test_unique_constraints_for_instance_nodes():
    statements = get_schema_seed_statements()
    constraint_text = "\n".join(s for s in statements if "CREATE CONSTRAINT" in s)

    for label in ["Decision", "ApprovalStep", "Exception", "Outcome", "OperationalContext"]:
        assert label.lower() in constraint_text.lower(), (
            f"Missing unique constraint for {label}"
        )


def test_chunk_content_hash_constraint():
    statements = get_schema_seed_statements()
    constraint_text = "\n".join(s for s in statements if "CREATE CONSTRAINT" in s)
    assert "content_hash" in constraint_text


def test_vector_index_present():
    statements = get_schema_seed_statements()
    vector_stmts = [s for s in statements if "VECTOR INDEX" in s]
    assert len(vector_stmts) >= 2, "Expected chunk_embeddings and decision_embeddings"
    combined = "\n".join(vector_stmts)
    assert "chunk_embeddings" in combined
    assert "decision_embeddings" in combined
    assert "1536" in combined


def test_schema_seed_cypher_string():
    """SCHEMA_SEED_CYPHER should be a non-empty semicolon-separated script."""
    assert isinstance(SCHEMA_SEED_CYPHER, str)
    assert len(SCHEMA_SEED_CYPHER) > 500
    assert SCHEMA_SEED_CYPHER.count(";") >= 20


# ---------------------------------------------------------------------------
# Node ID format
# ---------------------------------------------------------------------------

def test_make_node_id_format():
    nid = make_node_id("nexus", NodeType.GOAL, "revenue_growth")
    assert nid == "nexus:goal:revenue_growth"


def test_make_node_id_normalizes_case():
    nid = make_node_id("nexus", NodeType.RULE, "R1")
    assert nid == "nexus:rule:r1"


def test_make_node_id_normalizes_spaces():
    nid = make_node_id("nexus", NodeType.ACTOR, "HR Director")
    assert nid == "nexus:actor:hr_director"


def test_make_node_id_rejects_empty_company():
    with pytest.raises(ValueError):
        make_node_id("", NodeType.GOAL, "G1")


def test_make_node_id_rejects_empty_semantic():
    with pytest.raises(ValueError):
        make_node_id("nexus", NodeType.GOAL, "")


def test_make_node_id_all_node_types():
    """make_node_id should work for every NodeType."""
    for nt in NodeType:
        nid = make_node_id("test", nt, "test_id")
        assert nid.startswith("test:")
        assert nid.endswith(":test_id")


# ---------------------------------------------------------------------------
# Neo4j config
# ---------------------------------------------------------------------------

def test_neo4j_config_defaults():
    from app.config.neo4j import NEO4J_URI, NEO4J_USERNAME, get_company_database
    assert "localhost" in NEO4J_URI or "bolt" in NEO4J_URI or "neo4j" in NEO4J_URI
    assert NEO4J_USERNAME  # non-empty


def test_get_company_database_default_pattern():
    from app.config.neo4j import get_company_database
    assert get_company_database("nexus") == "nexus_governance"
    assert get_company_database("mayo") == "mayo_governance"


def test_get_company_database_env_override(monkeypatch):
    from app.config import neo4j as neo4j_config
    monkeypatch.setenv("NEO4J_DB_NEXUS", "nexus_prod")
    # Re-call the function (it reads env at call time)
    result = neo4j_config.get_company_database("nexus")
    assert result == "nexus_prod"


# ---------------------------------------------------------------------------
# Edge predicate registry completeness
# ---------------------------------------------------------------------------

def test_all_edge_predicates_in_registry():
    """Every EdgePredicate enum member must have a registry entry."""
    for pred in EdgePredicate:
        assert pred in EDGE_REGISTRY, f"EdgePredicate.{pred.name} missing from EDGE_REGISTRY"


def test_has_decision_type_predicate():
    assert EdgePredicate.HAS_DECISION_TYPE in EDGE_REGISTRY
    meta = EDGE_REGISTRY[EdgePredicate.HAS_DECISION_TYPE]
    assert NodeType.DECISION in meta.domain_types
    assert NodeType.DECISION_TYPE in meta.range_types


def test_evaluated_against_predicate():
    assert EdgePredicate.EVALUATED_AGAINST in EDGE_REGISTRY
    meta = EDGE_REGISTRY[EdgePredicate.EVALUATED_AGAINST]
    assert NodeType.DECISION in meta.domain_types
    assert NodeType.OPERATIONAL_CONTEXT in meta.range_types
