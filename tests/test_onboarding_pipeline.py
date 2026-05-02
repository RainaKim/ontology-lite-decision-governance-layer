"""
Tests for Step 7 — onboarding pipeline.

All tests use mocked LLM responses (no real API calls required).
The InMemoryGraphRepository is used instead of Neo4j.

Test coverage:
  - classify_artifact() routing
  - chunk_text() behavior
  - read_artifact() for each file type
  - ontologize_nodes() validation and ID generation
  - ontologize_edges() predicate resolution and node map lookup
  - build_node_id_map()
  - make_chunk_nodes()
  - transform_scout_results() writes correct node/edge counts
  - Full graph: plan → scouts → transform → validate with mocked LLM
  - collect_artifact_paths() discovers files correctly
  - OnboardingReport gap detection
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from app.graph.in_memory_repository import InMemoryGraphRepository
from app.onboarding.onboarding_graph import (
    _build_report,
    build_onboarding_graph,
    collect_artifact_paths,
    route_to_scouts,
)
from app.onboarding.schemas import (
    ArtifactExtraction,
    ExtractedEdge,
    ExtractedNode,
    OnboardingState,
    ScoutResult,
    TransformSummary,
)
from app.onboarding.scouts.base import (
    chunk_text,
    classify_artifact,
    merge_extractions,
    read_artifact,
)
from app.onboarding.transform.chunker import make_chunk_nodes, _hash_chunk
from app.onboarding.transform.ontologizer import (
    _canonical_semantic_id,
    build_node_id_map,
    ontologize_edges,
    ontologize_nodes,
)
from app.onboarding.transform.writer import transform_scout_results
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import make_node_id
from app.ontology.node_types import NodeType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo():
    return InMemoryGraphRepository()


@pytest.fixture
def sample_extracted_nodes():
    return [
        ExtractedNode(
            node_type="Goal",
            semantic_id="revenue_growth",
            label="Revenue Growth",
            properties={"priority": "high"},
            confidence=0.9,
            source_excerpt="Grow ARR to $10M",
        ),
        ExtractedNode(
            node_type="Rule",
            semantic_id="R1",
            label="CFO approval for large spend",
            properties={
                "conditions": [{"field": "cost", "operator": ">", "value": 50000}],
                "consequence": {"action": "require_approval", "approver_role": "CFO"},
            },
            confidence=1.0,
            source_excerpt="Spend > $50K requires CFO approval",
        ),
        ExtractedNode(
            node_type="Actor",
            semantic_id="cfo",
            label="CFO",
            properties={"role": "CFO", "approval_limit": 500000},
            confidence=0.95,
        ),
    ]


@pytest.fixture
def sample_extracted_edges(sample_extracted_nodes):
    return [
        ExtractedEdge(
            from_semantic_id="R1",
            to_semantic_id="cfo",
            predicate="REQUIRES_APPROVAL_FROM",
            evidence="Rule R1 requires CFO approval",
        ),
    ]


# ---------------------------------------------------------------------------
# classify_artifact()
# ---------------------------------------------------------------------------


def test_classify_document_md():
    assert classify_artifact("docs/expense_policy.md") == "document"


def test_classify_document_txt():
    assert classify_artifact("meeting_minutes/q1_planning.txt") == "document"


def test_classify_conversation_eml():
    assert classify_artifact("email/cfo_budget.eml") == "conversation"


def test_classify_conversation_slack():
    assert classify_artifact("slack/general.json") == "conversation"


def test_classify_data_csv():
    assert classify_artifact("spreadsheets/budget.csv") == "data"


def test_classify_data_json_structure():
    assert classify_artifact("structure/org_chart.json") == "data"


def test_classify_data_decisions():
    assert classify_artifact("decisions/approval_logs.csv") == "data"


# ---------------------------------------------------------------------------
# chunk_text()
# ---------------------------------------------------------------------------


def test_chunk_text_short_text():
    text = "Short text."
    chunks = chunk_text(text, chunk_size=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_splits_long_text():
    text = "A" * 2000
    chunks = chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c) <= 550  # chunk_size + some buffer


def test_chunk_text_empty():
    assert chunk_text("") == []


def test_chunk_text_whitespace_only():
    assert chunk_text("   ") == []


# ---------------------------------------------------------------------------
# read_artifact()
# ---------------------------------------------------------------------------


def test_read_artifact_markdown(tmp_path):
    f = tmp_path / "policy.md"
    f.write_text("# Policy\n\nRule: spend > $50K needs CFO approval.")
    result = read_artifact(str(f))
    assert "CFO" in result


def test_read_artifact_csv(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("role,limit\nCFO,500000\nCEO,unlimited\n")
    result = read_artifact(str(f))
    assert "CFO" in result
    assert "500000" in result


def test_read_artifact_json(tmp_path):
    f = tmp_path / "org.json"
    f.write_text(json.dumps({"ceo": {"name": "Alice", "title": "CEO"}}))
    result = read_artifact(str(f))
    assert "Alice" in result


def test_read_artifact_missing():
    result = read_artifact("/nonexistent/path/file.txt")
    assert result == ""


def test_read_artifact_eml(tmp_path):
    eml = tmp_path / "email.eml"
    eml.write_text(
        "From: cfo@co.com\nTo: ceo@co.com\nSubject: Budget\nDate: Mon\n\nBody text here."
    )
    result = read_artifact(str(eml))
    assert "Budget" in result
    assert "Body text here" in result


# ---------------------------------------------------------------------------
# merge_extractions()
# ---------------------------------------------------------------------------


def test_merge_extractions_deduplicates():
    e1 = ArtifactExtraction(
        nodes=[ExtractedNode(node_type="Goal", semantic_id="G1", label="Revenue", properties={})],
        edges=[],
    )
    e2 = ArtifactExtraction(
        nodes=[
            ExtractedNode(node_type="Goal", semantic_id="G1", label="Revenue", properties={}),  # dup
            ExtractedNode(node_type="Rule", semantic_id="R1", label="Rule", properties={}),
        ],
        edges=[],
    )
    nodes, edges = merge_extractions([e1, e2])
    assert len(nodes) == 2  # G1 deduped


def test_merge_extractions_empty():
    nodes, edges = merge_extractions([])
    assert nodes == []
    assert edges == []


# ---------------------------------------------------------------------------
# ontologize_nodes()
# ---------------------------------------------------------------------------


def test_ontologize_nodes_generates_correct_ids(sample_extracted_nodes):
    nodes, _ = ontologize_nodes(sample_extracted_nodes, "nexus")
    ids = {n.id for n in nodes}
    assert "nexus:goal:revenue_growth" in ids
    assert "nexus:rule:r1" in ids
    assert "nexus:actor:cfo" in ids


def test_ontologize_nodes_skips_invalid_type():
    # Use model_construct to bypass Pydantic validation — simulates raw LLM output
    # with a completely invalid type that the schema doesn't allow
    extracted = [
        ExtractedNode.model_construct(node_type="FakeType", semantic_id="f1", label="Bad type", properties={}, confidence=0.7, source_excerpt=""),
        ExtractedNode(node_type="Goal", semantic_id="g1", label="Good goal", properties={}),
    ]
    nodes, _ = ontologize_nodes(extracted, "nexus")
    assert len(nodes) == 1  # FakeType is invalid, skipped
    assert nodes[0].type == NodeType.GOAL


def test_ontologize_nodes_accepts_decision_type():
    """Decision is now an allowed instance-layer node type for onboarding extraction."""
    extracted = [
        ExtractedNode(node_type="Decision", semantic_id="dec-001", label="Q2 Hire Decision", properties={"decision_id": "DEC-001"}),
    ]
    nodes, _ = ontologize_nodes(extracted, "nexus")
    assert len(nodes) == 1
    assert nodes[0].type == NodeType.DECISION


def test_ontologize_nodes_preserves_confidence(sample_extracted_nodes):
    nodes, _ = ontologize_nodes(sample_extracted_nodes, "nexus")
    rule_node = next(n for n in nodes if n.type == NodeType.RULE)
    assert rule_node.confidence == 1.0


def test_ontologize_nodes_deduplicates():
    extracted = [
        ExtractedNode(node_type="Actor", semantic_id="cfo", label="CFO v1", properties={}, confidence=0.8),
        ExtractedNode(node_type="Actor", semantic_id="cfo", label="CFO v2", properties={}, confidence=0.7),
    ]
    nodes, deduped = ontologize_nodes(extracted, "co")
    assert len(nodes) == 1
    assert deduped == 1
    assert nodes[0].label == "CFO v1"  # higher confidence wins


# ---------------------------------------------------------------------------
# _canonical_semantic_id() — deterministic dedup normalization
# ---------------------------------------------------------------------------


def test_canonical_strips_department_suffix():
    assert _canonical_semantic_id("Department", "engineering_dept") == "engineering"
    assert _canonical_semantic_id("Department", "engineering_department") == "engineering"
    assert _canonical_semantic_id("Department", "engineering_team") == "engineering"
    assert _canonical_semantic_id("Department", "engineering_group") == "engineering"
    assert _canonical_semantic_id("Department", "engineering_division") == "engineering"


def test_canonical_does_not_strip_suffix_for_non_department():
    # _dept suffix should NOT be stripped for non-Department node types
    assert _canonical_semantic_id("Actor", "engineering_dept") == "engineering_dept"


def test_canonical_expands_kpi_abbreviations():
    assert _canonical_semantic_id("KPI", "nrr") == "net_revenue_retention"
    assert _canonical_semantic_id("KPI", "arr") == "annual_recurring_revenue"
    assert _canonical_semantic_id("KPI", "mrr") == "monthly_recurring_revenue"
    assert _canonical_semantic_id("KPI", "cac") == "customer_acquisition_cost"
    assert _canonical_semantic_id("KPI", "ltv") == "lifetime_value"


def test_canonical_does_not_expand_for_non_kpi():
    # Abbreviation should NOT be expanded for non-KPI node types
    assert _canonical_semantic_id("Goal", "nrr") == "nrr"


def test_canonical_collapses_underscore_digit():
    assert _canonical_semantic_id("Rule", "soc_2_compliance") == "soc2_compliance"
    assert _canonical_semantic_id("Rule", "iso_27001") == "iso27001"


def test_canonical_strips_filler_and():
    assert _canonical_semantic_id("Goal", "research_and_development") == "research_development"


def test_canonical_dedup_department_variants():
    """Two extracted nodes with _dept vs bare name should produce the same canonical ID."""
    extracted = [
        ExtractedNode(
            node_type="Department",
            semantic_id="engineering_dept",
            label="Engineering Department",
            properties={},
            confidence=0.8,
        ),
        ExtractedNode(
            node_type="Department",
            semantic_id="engineering",
            label="Engineering",
            properties={},
            confidence=0.9,
        ),
    ]
    nodes, deduped = ontologize_nodes(extracted, "co")
    assert len(nodes) == 1
    assert deduped == 1
    # Higher confidence (0.9) wins
    assert nodes[0].label == "Engineering"
    assert nodes[0].confidence == 0.9


def test_canonical_dedup_kpi_abbreviation():
    """NRR and net_revenue_retention should resolve to the same node."""
    extracted = [
        ExtractedNode(
            node_type="KPI",
            semantic_id="nrr",
            label="NRR",
            properties={},
            confidence=0.7,
        ),
        ExtractedNode(
            node_type="KPI",
            semantic_id="net_revenue_retention",
            label="Net Revenue Retention",
            properties={},
            confidence=0.85,
        ),
    ]
    nodes, deduped = ontologize_nodes(extracted, "co")
    assert len(nodes) == 1
    assert deduped == 1
    assert nodes[0].label == "Net Revenue Retention"


def test_canonical_dedup_underscore_variant():
    """soc2_compliance and soc_2_compliance should resolve to the same node."""
    extracted = [
        ExtractedNode(
            node_type="Rule",
            semantic_id="soc2_compliance",
            label="SOC 2 Compliance",
            properties={},
            confidence=0.9,
        ),
        ExtractedNode(
            node_type="Rule",
            semantic_id="soc_2_compliance",
            label="SOC-2 Compliance",
            properties={},
            confidence=0.8,
        ),
    ]
    nodes, deduped = ontologize_nodes(extracted, "co")
    assert len(nodes) == 1
    assert deduped == 1
    assert nodes[0].confidence == 0.9


def test_canonical_no_false_dedup():
    """Distinct nodes should NOT be deduped."""
    extracted = [
        ExtractedNode(node_type="Department", semantic_id="engineering", label="Eng", properties={}),
        ExtractedNode(node_type="Department", semantic_id="marketing", label="Mkt", properties={}),
    ]
    nodes, deduped = ontologize_nodes(extracted, "co")
    assert len(nodes) == 2
    assert deduped == 0


# ---------------------------------------------------------------------------
# ontologize_edges()
# ---------------------------------------------------------------------------


def test_ontologize_edges_resolves_node_ids(
    sample_extracted_nodes, sample_extracted_edges
):
    nodes, _ = ontologize_nodes(sample_extracted_nodes, "nexus")
    node_id_map = build_node_id_map(nodes)
    edges, dropped = ontologize_edges(sample_extracted_edges, "nexus", node_id_map)

    assert len(edges) == 1
    assert dropped == 0
    assert edges[0].predicate == EdgePredicate.REQUIRES_APPROVAL_FROM.value
    assert edges[0].from_node == "nexus:rule:r1"
    assert edges[0].to_node == "nexus:actor:cfo"


def test_ontologize_edges_skips_missing_node():
    extracted = [
        ExtractedEdge(
            from_semantic_id="nonexistent",
            to_semantic_id="cfo",
            predicate="REQUIRES_APPROVAL_FROM",
        )
    ]
    edges, dropped = ontologize_edges(extracted, "nexus", {"cfo": "nexus:actor:cfo"})
    assert len(edges) == 0
    assert dropped == 1


def test_ontologize_edges_skips_unknown_predicate(sample_extracted_nodes):
    nodes, _ = ontologize_nodes(sample_extracted_nodes, "nexus")
    node_id_map = build_node_id_map(nodes)
    extracted = [
        ExtractedEdge(
            from_semantic_id="r1",
            to_semantic_id="cfo",
            predicate="INVENTED_PREDICATE",
        )
    ]
    edges, dropped = ontologize_edges(extracted, "nexus", node_id_map)
    assert len(edges) == 0
    assert dropped == 1


# ---------------------------------------------------------------------------
# make_chunk_nodes()
# ---------------------------------------------------------------------------


def test_make_chunk_nodes_basic():
    chunks = ["First chunk text here.", "Second chunk text here."]
    nodes = make_chunk_nodes(chunks, "nexus", "docs/policy.md")
    assert len(nodes) == 2
    for node in nodes:
        assert node.type == NodeType.CHUNK
        assert node.id.startswith("nexus:chunk:")
        assert node.properties["source_path"] == "docs/policy.md"


def test_make_chunk_nodes_with_embeddings():
    chunks = ["text"]
    embeddings = [[0.1] * 1536]
    nodes = make_chunk_nodes(chunks, "nexus", "file.md", embeddings=embeddings)
    assert nodes[0].embedding is not None
    assert len(nodes[0].embedding) == 1536


def test_make_chunk_nodes_content_hash_is_deterministic():
    chunks = ["same text"]
    n1 = make_chunk_nodes(chunks, "a", "f.md")
    n2 = make_chunk_nodes(chunks, "a", "f.md")
    assert n1[0].id == n2[0].id  # same hash → same ID (MERGE behavior)


# ---------------------------------------------------------------------------
# transform_scout_results()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transform_writes_nodes_and_chunks(repo, sample_extracted_nodes):
    results = [
        ScoutResult(
            scout_type="document",
            artifact_path="docs/policy.md",
            extracted_nodes=sample_extracted_nodes,
            extracted_edges=[],
            raw_chunks=["chunk one text", "chunk two text"],
        )
    ]
    summary = await transform_scout_results(results, "nexus", repo)

    assert summary.chunks_written == 2
    assert summary.nodes_written == 4  # goal + rule + actor + 1 Artifact node
    assert summary.errors == []


@pytest.mark.asyncio
async def test_transform_writes_derived_from_edges(repo, sample_extracted_nodes):
    results = [
        ScoutResult(
            scout_type="document",
            artifact_path="docs/policy.md",
            extracted_nodes=sample_extracted_nodes,
            extracted_edges=[],
            raw_chunks=["some text"],
        )
    ]
    await transform_scout_results(results, "nexus", repo)

    derived = repo.get_edges_by_predicate(EdgePredicate.DERIVED_FROM)
    assert len(derived) == 3  # one per domain node → chunk


@pytest.mark.asyncio
async def test_transform_empty_scout_results(repo):
    summary = await transform_scout_results([], "nexus", repo)
    assert summary.nodes_written == 0
    assert summary.chunks_written == 0


# ---------------------------------------------------------------------------
# OnboardingReport gap detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_flags_missing_rule_nodes():
    state: OnboardingState = {
        "company_id": "co",
        "artifact_paths": ["f.md"],
        "seeded_nodes_context": "",
        "scout_results": [
            ScoutResult(
                scout_type="document",
                artifact_path="f.md",
                extracted_nodes=[
                    ExtractedNode(
                        node_type="Goal",
                        semantic_id="G1",
                        label="Revenue",
                        properties={},
                    )
                ],
                extracted_edges=[],
            )
        ],
        "transform_summary": None,
        "report": None,
        "errors": [],
    }
    repo = InMemoryGraphRepository()
    report = await _build_report(state, repo)

    assert "Rule" in " ".join(report.gaps)
    assert report.confidence > 0.0


@pytest.mark.asyncio
async def test_report_no_gaps_when_all_classes_present():
    nodes = [
        ExtractedNode(node_type="Goal", semantic_id="g1", label="G", properties={}),
        ExtractedNode(node_type="Rule", semantic_id="R1", label="R", properties={}),
        ExtractedNode(node_type="Actor", semantic_id="cfo", label="CFO", properties={}),
        ExtractedNode(node_type="KPI", semantic_id="k1", label="ARR", properties={}),
    ]
    state: OnboardingState = {
        "company_id": "co",
        "artifact_paths": ["f.md"],
        "seeded_nodes_context": "",
        "scout_results": [
            ScoutResult(
                scout_type="document",
                artifact_path="f.md",
                extracted_nodes=nodes,
                extracted_edges=[],
            )
        ],
        "transform_summary": None,
        "report": None,
        "errors": [],
    }
    repo = InMemoryGraphRepository()
    report = await _build_report(state, repo)
    assert report.gaps == []
    assert report.completed is True


# ---------------------------------------------------------------------------
# collect_artifact_paths()
# ---------------------------------------------------------------------------


def test_collect_artifact_paths(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "email").mkdir()
    (tmp_path / "docs" / "policy.md").write_text("content")
    (tmp_path / "email" / "msg.eml").write_text("content")
    (tmp_path / "docs" / "hidden.md").write_text("")
    # Hidden file should be included (not hidden by our filter — only __pycache__ and dot-prefix)
    paths = collect_artifact_paths(str(tmp_path))
    assert any("policy.md" in p for p in paths)
    assert any("msg.eml" in p for p in paths)


def test_collect_artifact_paths_excludes_pycache(tmp_path):
    pycache = tmp_path / "__pycache__"
    pycache.mkdir()
    (pycache / "module.json").write_text("{}")
    paths = collect_artifact_paths(str(tmp_path))
    assert not any("__pycache__" in p for p in paths)


# ---------------------------------------------------------------------------
# Full graph with mocked scouts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_graph_with_mocked_scouts(tmp_path):
    """
    End-to-end test: run the full onboarding graph with mocked LLM.
    Verifies the graph executes all nodes and returns an OnboardingReport.
    """
    # Create one artifact file of each type
    (tmp_path / "docs").mkdir()
    (tmp_path / "email").mkdir()
    (tmp_path / "spreadsheets").mkdir()
    doc = tmp_path / "docs" / "policy.md"
    eml = tmp_path / "email" / "msg.eml"
    csv_f = tmp_path / "spreadsheets" / "budget.csv"
    doc.write_text("# Policy\nSpend > $50K requires CFO approval.\n")
    eml.write_text("From: cfo@co.com\nTo: ceo@co.com\nSubject: Budget\n\nBody.")
    csv_f.write_text("role,limit\nCFO,500000\n")

    artifact_paths = collect_artifact_paths(str(tmp_path))

    # Mock the LLM to return a minimal ArtifactExtraction
    mock_extraction = ArtifactExtraction(
        nodes=[
            ExtractedNode(
                node_type="Rule",
                semantic_id="r1",
                label="CFO approval rule",
                properties={},
                confidence=0.9,
            ),
            ExtractedNode(
                node_type="Goal",
                semantic_id="g1",
                label="Revenue",
                properties={},
                confidence=0.8,
            ),
            ExtractedNode(
                node_type="Actor",
                semantic_id="cfo",
                label="CFO",
                properties={},
                confidence=0.95,
            ),
            ExtractedNode(
                node_type="KPI",
                semantic_id="k1",
                label="ARR",
                properties={},
                confidence=0.85,
            ),
        ],
        edges=[],
    )

    # Patch run_extraction in each scout's local namespace (already imported via
    # 'from ... import run_extraction', so patching the source module is insufficient)
    _patch = lambda module: patch(module, new_callable=AsyncMock, return_value=mock_extraction)
    with (
        _patch("app.onboarding.scouts.document_scout.run_extraction"),
        _patch("app.onboarding.scouts.conversation_scout.run_extraction"),
        _patch("app.onboarding.scouts.data_scout.run_extraction"),
    ):
        repo = InMemoryGraphRepository()
        compiled = build_onboarding_graph(repo)
        result = await compiled.ainvoke(
            {
                "company_id": "test_co",
                "artifact_paths": artifact_paths,
                "seeded_nodes_context": "",
                "seeded_rule_ids": [],
                "seeded_goal_ids": [],
                "scout_results": [],
                "errors": [],
                "transform_summary": None,
                "report": None,
            }
        )

    report = result.get("report")
    assert report is not None
    assert report.company_id == "test_co"
    assert report.total_artifacts_processed == len(artifact_paths)
    # With all 4 classes present, should be completed
    assert report.completed is True
