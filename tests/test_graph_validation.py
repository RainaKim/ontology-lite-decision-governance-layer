"""
Tests for graph structural validation — app/onboarding/validation.py.

Covers:
  - Orphan node detection
  - Edge-to-node ratio calculation
  - Required edge pattern checking
  - Low-confidence edge warnings
  - Pass/fail determination
  - Edge model confidence and source_chunk_id fields
  - Confidence propagation through ontologize_edges
  - Integration with OnboardingReport
"""

import pytest

from app.graph.in_memory_repository import InMemoryGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import Edge, Node, make_node_id
from app.ontology.node_types import NodeType
from app.onboarding.validation import (
    REQUIRED_EDGE_PATTERNS,
    ValidationResult,
    validate_graph_structure,
)
from app.onboarding.schemas import (
    ExtractedEdge,
    OnboardingReport,
    ScoutResult,
    TransformSummary,
)
from app.onboarding.transform.ontologizer import (
    build_node_confidence_map,
    ontologize_edges,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CID = "test_co"


def _node(ntype: NodeType, sem: str, label: str = "", confidence: float = None) -> Node:
    """Shortcut to create a Node with proper ID."""
    return Node(
        id=make_node_id(CID, ntype, sem),
        type=ntype,
        label=label or sem,
        confidence=confidence,
    )


def _edge(
    from_id: str,
    to_id: str,
    pred: EdgePredicate,
    confidence: float = 1.0,
    source_chunk_id: str = None,
) -> Edge:
    """Shortcut to create an Edge."""
    return Edge(
        from_node=from_id,
        to_node=to_id,
        predicate=pred,
        confidence=confidence,
        source_chunk_id=source_chunk_id,
    )


@pytest.fixture
def repo():
    return InMemoryGraphRepository()


# ---------------------------------------------------------------------------
# Edge model: confidence and source_chunk_id fields
# ---------------------------------------------------------------------------


class TestEdgeModelFields:
    """Tests for the new confidence and source_chunk_id fields on Edge."""

    def test_edge_default_confidence(self):
        edge = Edge(
            from_node="a:goal:g1",
            to_node="a:kpi:k1",
            predicate=EdgePredicate.MEASURED_BY,
        )
        assert edge.confidence == 1.0
        assert edge.source_chunk_id is None

    def test_edge_custom_confidence(self):
        edge = Edge(
            from_node="a:goal:g1",
            to_node="a:kpi:k1",
            predicate=EdgePredicate.MEASURED_BY,
            confidence=0.75,
            source_chunk_id="a:chunk:abc123",
        )
        assert edge.confidence == 0.75
        assert edge.source_chunk_id == "a:chunk:abc123"

    def test_edge_confidence_bounds(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(Exception):
            Edge(
                from_node="a:goal:g1",
                to_node="a:kpi:k1",
                predicate=EdgePredicate.MEASURED_BY,
                confidence=1.5,
            )
        with pytest.raises(Exception):
            Edge(
                from_node="a:goal:g1",
                to_node="a:kpi:k1",
                predicate=EdgePredicate.MEASURED_BY,
                confidence=-0.1,
            )

    def test_edge_backward_compat(self):
        """Existing code that creates Edge without confidence still works."""
        edge = Edge(
            from_node="a:rule:r1",
            to_node="a:actor:cfo",
            predicate=EdgePredicate.REQUIRES_APPROVAL_FROM,
            properties={"requires_sequential": True},
        )
        assert edge.confidence == 1.0
        assert edge.source_chunk_id is None
        assert edge.properties == {"requires_sequential": True}


# ---------------------------------------------------------------------------
# Orphan detection
# ---------------------------------------------------------------------------


class TestOrphanDetection:
    """Tests for orphan node detection in validate_graph_structure."""

    async def test_no_orphans(self, repo):
        """All nodes connected via edges — zero orphans."""
        goal = _node(NodeType.GOAL, "g1")
        kpi = _node(NodeType.KPI, "k1")
        await repo.write_node(goal, CID)
        await repo.write_node(kpi, CID)
        await repo.write_edge(
            _edge(goal.id, kpi.id, EdgePredicate.MEASURED_BY), CID
        )

        result = await validate_graph_structure(repo, CID)
        assert result.orphan_nodes == []
        assert result.orphan_rate == 0.0

    async def test_single_orphan(self, repo):
        """One node has no edges — detected as orphan."""
        goal = _node(NodeType.GOAL, "g1")
        kpi = _node(NodeType.KPI, "k1")
        actor = _node(NodeType.ACTOR, "cfo")  # orphan
        await repo.write_node(goal, CID)
        await repo.write_node(kpi, CID)
        await repo.write_node(actor, CID)
        await repo.write_edge(
            _edge(goal.id, kpi.id, EdgePredicate.MEASURED_BY), CID
        )

        result = await validate_graph_structure(repo, CID)
        assert actor.id in result.orphan_nodes
        assert len(result.orphan_nodes) == 1
        assert result.orphan_rate == pytest.approx(1 / 3, abs=0.01)

    async def test_all_orphans(self, repo):
        """No edges at all — all domain nodes are orphans."""
        for i in range(3):
            await repo.write_node(_node(NodeType.GOAL, f"g{i}"), CID)

        result = await validate_graph_structure(repo, CID)
        assert len(result.orphan_nodes) == 3
        assert result.orphan_rate == 1.0
        assert not result.passed  # high orphan rate fails validation

    async def test_schema_nodes_excluded_from_orphan_check(self, repo):
        """MetaClass and OntologyClass nodes should not be flagged as orphans."""
        meta = Node(
            id=f"{CID}:metaclass:entity",
            type=NodeType.META_CLASS,
            label="Entity",
        )
        goal = _node(NodeType.GOAL, "g1")
        kpi = _node(NodeType.KPI, "k1")
        await repo.write_node(meta, CID)
        await repo.write_node(goal, CID)
        await repo.write_node(kpi, CID)
        await repo.write_edge(
            _edge(goal.id, kpi.id, EdgePredicate.MEASURED_BY), CID
        )

        result = await validate_graph_structure(repo, CID)
        assert meta.id not in result.orphan_nodes
        assert result.orphan_nodes == []


# ---------------------------------------------------------------------------
# Edge-to-node ratio
# ---------------------------------------------------------------------------


class TestEdgeToNodeRatio:
    async def test_ratio_calculation(self, repo):
        """Ratio should be edges / nodes."""
        g = _node(NodeType.GOAL, "g1")
        k1 = _node(NodeType.KPI, "k1")
        k2 = _node(NodeType.KPI, "k2")
        for n in [g, k1, k2]:
            await repo.write_node(n, CID)
        await repo.write_edge(_edge(g.id, k1.id, EdgePredicate.MEASURED_BY), CID)
        await repo.write_edge(_edge(g.id, k2.id, EdgePredicate.MEASURED_BY), CID)

        result = await validate_graph_structure(repo, CID)
        assert result.edge_to_node_ratio == pytest.approx(2 / 3, abs=0.01)

    async def test_sparse_graph_warning(self, repo):
        """Low ratio triggers a warning."""
        # 4 nodes, 1 edge => ratio = 0.25 < 0.5
        for i in range(4):
            await repo.write_node(_node(NodeType.GOAL, f"g{i}"), CID)
        await repo.write_edge(
            _edge(
                make_node_id(CID, NodeType.GOAL, "g0"),
                make_node_id(CID, NodeType.GOAL, "g1"),
                EdgePredicate.CONFLICTS_WITH,
            ),
            CID,
        )

        result = await validate_graph_structure(repo, CID)
        assert result.edge_to_node_ratio == 0.25
        assert any("sparse" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Required edge patterns
# ---------------------------------------------------------------------------


class TestRequiredPatterns:
    async def test_rule_without_approval_edge(self, repo):
        """Rule without REQUIRES_APPROVAL_FROM or REQUIRES_REVIEW_FROM triggers warning."""
        rule = _node(NodeType.RULE, "r1")
        goal = _node(NodeType.GOAL, "g1")
        await repo.write_node(rule, CID)
        await repo.write_node(goal, CID)
        # Only GOVERNED_BY edge, no approval edge
        await repo.write_edge(
            _edge(goal.id, rule.id, EdgePredicate.GOVERNED_BY), CID
        )

        result = await validate_graph_structure(repo, CID)
        rule_missing = [
            mp for mp in result.missing_patterns if mp["node_id"] == rule.id
        ]
        assert len(rule_missing) >= 1
        assert any(
            "REQUIRES_APPROVAL_FROM" in mp["missing"] for mp in rule_missing
        )

    async def test_rule_with_approval_edge_passes(self, repo):
        """Rule with REQUIRES_APPROVAL_FROM satisfies the pattern."""
        rule = _node(NodeType.RULE, "r1")
        actor = _node(NodeType.ACTOR, "cfo")
        await repo.write_node(rule, CID)
        await repo.write_node(actor, CID)
        await repo.write_edge(
            _edge(rule.id, actor.id, EdgePredicate.REQUIRES_APPROVAL_FROM), CID
        )

        result = await validate_graph_structure(repo, CID)
        rule_missing = [
            mp for mp in result.missing_patterns
            if mp["node_id"] == rule.id
            and "REQUIRES_APPROVAL_FROM" in mp["missing"]
        ]
        assert len(rule_missing) == 0

    async def test_actor_any_direction(self, repo):
        """Actor pattern checks 'any' direction — incoming ESCALATES_TO counts."""
        actor1 = _node(NodeType.ACTOR, "mgr")
        actor2 = _node(NodeType.ACTOR, "cfo")
        await repo.write_node(actor1, CID)
        await repo.write_node(actor2, CID)
        # actor1 ESCALATES_TO actor2 — actor1 has outgoing, actor2 has incoming
        await repo.write_edge(
            _edge(actor1.id, actor2.id, EdgePredicate.ESCALATES_TO), CID
        )

        result = await validate_graph_structure(repo, CID)
        # Both actors should have the ESCALATES_TO pattern satisfied
        actor_missing = [
            mp for mp in result.missing_patterns
            if mp["node_type"] == "Actor"
            and "ESCALATES_TO" in mp["missing"]
        ]
        assert len(actor_missing) == 0


# ---------------------------------------------------------------------------
# Low-confidence edge warnings
# ---------------------------------------------------------------------------


class TestLowConfidenceEdges:
    async def test_low_confidence_warning(self, repo):
        """Edges with confidence < 0.5 trigger a warning."""
        g = _node(NodeType.GOAL, "g1")
        k = _node(NodeType.KPI, "k1")
        await repo.write_node(g, CID)
        await repo.write_node(k, CID)
        await repo.write_edge(
            _edge(g.id, k.id, EdgePredicate.MEASURED_BY, confidence=0.3), CID
        )

        result = await validate_graph_structure(repo, CID)
        assert any("confidence" in w.lower() for w in result.warnings)

    async def test_high_confidence_no_warning(self, repo):
        """All edges with confidence >= 0.5 — no confidence warning."""
        g = _node(NodeType.GOAL, "g1")
        k = _node(NodeType.KPI, "k1")
        await repo.write_node(g, CID)
        await repo.write_node(k, CID)
        await repo.write_edge(
            _edge(g.id, k.id, EdgePredicate.MEASURED_BY, confidence=0.8), CID
        )

        result = await validate_graph_structure(repo, CID)
        assert not any("confidence" in w.lower() for w in result.warnings)


# ---------------------------------------------------------------------------
# Pass/fail determination
# ---------------------------------------------------------------------------


class TestPassFail:
    async def test_well_formed_graph_passes(self, repo):
        """A graph with proper structure passes validation."""
        rule = _node(NodeType.RULE, "r1")
        actor = _node(NodeType.ACTOR, "cfo")
        goal = _node(NodeType.GOAL, "g1")
        kpi = _node(NodeType.KPI, "k1")
        dept = _node(NodeType.DEPARTMENT, "finance")

        for n in [rule, actor, goal, kpi, dept]:
            await repo.write_node(n, CID)

        await repo.write_edge(_edge(rule.id, actor.id, EdgePredicate.REQUIRES_APPROVAL_FROM), CID)
        await repo.write_edge(_edge(goal.id, kpi.id, EdgePredicate.MEASURED_BY), CID)
        await repo.write_edge(_edge(actor.id, dept.id, EdgePredicate.BELONGS_TO), CID)

        result = await validate_graph_structure(repo, CID)
        assert result.passed is True

    async def test_empty_graph_fails(self, repo):
        """Empty graph fails validation."""
        result = await validate_graph_structure(repo, CID)
        assert result.passed is False
        assert any("empty" in w.lower() for w in result.warnings)

    async def test_high_orphan_rate_fails(self, repo):
        """More than 50% orphans fails validation."""
        # 3 orphans, 2 connected = 60% orphan rate
        for i in range(3):
            await repo.write_node(_node(NodeType.GOAL, f"orphan{i}"), CID)
        g = _node(NodeType.GOAL, "connected1")
        k = _node(NodeType.KPI, "connected2")
        await repo.write_node(g, CID)
        await repo.write_node(k, CID)
        await repo.write_edge(_edge(g.id, k.id, EdgePredicate.MEASURED_BY), CID)

        result = await validate_graph_structure(repo, CID)
        assert result.orphan_rate > 0.5
        assert result.passed is False


# ---------------------------------------------------------------------------
# Confidence propagation through ontologize_edges
# ---------------------------------------------------------------------------


class TestConfidencePropagation:
    def test_build_node_confidence_map(self):
        """build_node_confidence_map extracts confidence from nodes."""
        nodes = [
            _node(NodeType.GOAL, "g1", confidence=0.8),
            _node(NodeType.RULE, "r1", confidence=0.6),
            _node(NodeType.ACTOR, "cfo"),  # None confidence → 1.0
        ]
        conf_map = build_node_confidence_map(nodes)
        assert conf_map[make_node_id(CID, NodeType.GOAL, "g1")] == 0.8
        assert conf_map[make_node_id(CID, NodeType.RULE, "r1")] == 0.6
        assert conf_map[make_node_id(CID, NodeType.ACTOR, "cfo")] == 1.0

    def test_edge_confidence_from_min_nodes(self):
        """Edge confidence = min(from_conf, to_conf)."""
        nodes = [
            _node(NodeType.GOAL, "g1", confidence=0.8),
            _node(NodeType.KPI, "k1", confidence=0.6),
        ]
        conf_map = build_node_confidence_map(nodes)
        node_id_map = {
            "g1": make_node_id(CID, NodeType.GOAL, "g1"),
            "k1": make_node_id(CID, NodeType.KPI, "k1"),
        }

        extracted = [
            ExtractedEdge(
                from_semantic_id="g1",
                to_semantic_id="k1",
                predicate="MEASURED_BY",
            )
        ]

        edges, dropped = ontologize_edges(
            extracted=extracted,
            company_id=CID,
            node_id_map=node_id_map,
            node_confidence_map=conf_map,
        )
        assert dropped == 0
        assert len(edges) == 1
        # min(0.8, 0.6) = 0.6, then * 0.9 for empty evidence = 0.54
        assert edges[0].confidence == pytest.approx(0.54, abs=0.01)

    def test_edge_confidence_default_without_map(self):
        """Without a confidence map, edges default to 1.0."""
        node_id_map = {
            "g1": make_node_id(CID, NodeType.GOAL, "g1"),
            "k1": make_node_id(CID, NodeType.KPI, "k1"),
        }
        extracted = [
            ExtractedEdge(
                from_semantic_id="g1",
                to_semantic_id="k1",
                predicate="MEASURED_BY",
            )
        ]

        edges, _ = ontologize_edges(
            extracted=extracted,
            company_id=CID,
            node_id_map=node_id_map,
        )
        # 1.0 * 0.9 for empty evidence = 0.9
        assert edges[0].confidence == pytest.approx(0.9, abs=0.01)

    def test_edge_confidence_partial_map(self):
        """When only one endpoint is in the confidence map, use that confidence."""
        conf_map = {
            make_node_id(CID, NodeType.GOAL, "g1"): 0.7,
            # k1 not in map (e.g. seeded node)
        }
        node_id_map = {
            "g1": make_node_id(CID, NodeType.GOAL, "g1"),
            "k1": make_node_id(CID, NodeType.KPI, "k1"),
        }
        extracted = [
            ExtractedEdge(
                from_semantic_id="g1",
                to_semantic_id="k1",
                predicate="MEASURED_BY",
            )
        ]

        edges, _ = ontologize_edges(
            extracted=extracted,
            company_id=CID,
            node_id_map=node_id_map,
            node_confidence_map=conf_map,
        )
        # 0.7 * 0.9 for empty evidence = 0.63
        assert edges[0].confidence == pytest.approx(0.63, abs=0.01)


# ---------------------------------------------------------------------------
# OnboardingReport structural fields
# ---------------------------------------------------------------------------


class TestOnboardingReportFields:
    def test_default_structural_fields(self):
        """New structural fields have sensible defaults."""
        report = OnboardingReport(company_id="test")
        assert report.orphan_rate == 0.0
        assert report.edge_to_node_ratio == 0.0
        assert report.structural_warnings == []
        assert report.edges_dropped == 0

    def test_structural_fields_populated(self):
        """Structural fields can be set explicitly."""
        report = OnboardingReport(
            company_id="test",
            orphan_rate=0.25,
            edge_to_node_ratio=1.5,
            structural_warnings=["orphan detected"],
            edges_dropped=3,
        )
        assert report.orphan_rate == 0.25
        assert report.edge_to_node_ratio == 1.5
        assert report.structural_warnings == ["orphan detected"]
        assert report.edges_dropped == 3


# ---------------------------------------------------------------------------
# ValidationResult dataclass
# ---------------------------------------------------------------------------


class TestValidationResult:
    def test_defaults(self):
        result = ValidationResult()
        assert result.orphan_nodes == []
        assert result.orphan_rate == 0.0
        assert result.edge_to_node_ratio == 0.0
        assert result.missing_patterns == []
        assert result.warnings == []
        assert result.passed is True

    def test_required_edge_patterns_defined(self):
        """Ensure REQUIRED_EDGE_PATTERNS has expected structure."""
        assert len(REQUIRED_EDGE_PATTERNS) > 0
        for node_type, preds, direction, severity in REQUIRED_EDGE_PATTERNS:
            assert isinstance(node_type, str)
            assert isinstance(preds, list)
            assert direction in ("outgoing", "incoming", "any")
            assert severity in ("warning", "info")


# ---------------------------------------------------------------------------
# _collect_graph_data: cypher_read fallback for non-InMemory repos
# ---------------------------------------------------------------------------


class TestCollectGraphDataCypherFallback:
    """
    Verify that _collect_graph_data uses cypher_read to fetch edges
    when the repository is not InMemoryGraphRepository (e.g. Neo4j).
    """

    async def test_cypher_fallback_fetches_edges(self):
        """Non-InMemory repo should use cypher_read for edges."""
        from unittest.mock import AsyncMock, MagicMock
        from app.onboarding.validation import _collect_graph_data

        mock_repo = AsyncMock()
        # Make isinstance(repo, InMemoryGraphRepository) return False
        mock_repo.__class__ = MagicMock

        # get_all_node_ids returns two nodes
        mock_repo.get_all_node_ids.return_value = {
            "g1": "test:goal:g1",
            "r1": "test:rule:r1",
        }
        # get_node returns property dicts
        mock_repo.get_node.side_effect = [
            {"id": "test:goal:g1", "node_type": "Goal", "label": "Goal 1"},
            {"id": "test:rule:r1", "node_type": "Rule", "label": "Rule 1"},
        ]
        # cypher_read returns one edge
        mock_repo.cypher_read.return_value = [
            {
                "from_id": "test:goal:g1",
                "to_id": "test:rule:r1",
                "rel_type": "GOVERNED_BY",
                "props": {},
            }
        ]

        nodes, edges = await _collect_graph_data(mock_repo, "test")

        assert len(nodes) == 2
        assert len(edges) == 1
        assert edges[0].from_node == "test:goal:g1"
        assert edges[0].to_node == "test:rule:r1"
        assert edges[0].predicate == "GOVERNED_BY"
        mock_repo.cypher_read.assert_called_once()

    async def test_cypher_fallback_handles_not_implemented(self):
        """If cypher_read raises NotImplementedError, edges should be empty."""
        from unittest.mock import AsyncMock, MagicMock
        from app.onboarding.validation import _collect_graph_data

        mock_repo = AsyncMock()
        mock_repo.__class__ = MagicMock
        mock_repo.get_all_node_ids.return_value = {
            "g1": "test:goal:g1",
        }
        mock_repo.get_node.return_value = {
            "id": "test:goal:g1",
            "node_type": "Goal",
            "label": "Goal 1",
        }
        mock_repo.cypher_read.side_effect = NotImplementedError("not supported")

        nodes, edges = await _collect_graph_data(mock_repo, "test")

        assert len(nodes) == 1
        assert len(edges) == 0

    async def test_cypher_fallback_orphan_detection_works(self):
        """
        End-to-end: validate_graph_structure with a mock non-InMemory repo
        should correctly detect connected vs orphan nodes via cypher_read edges.
        """
        from unittest.mock import AsyncMock, MagicMock

        mock_repo = AsyncMock()
        mock_repo.__class__ = MagicMock

        mock_repo.get_all_node_ids.return_value = {
            "g1": "test:goal:g1",
            "k1": "test:kpi:k1",
            "orphan": "test:actor:orphan",
        }
        mock_repo.get_node.side_effect = [
            {"id": "test:goal:g1", "node_type": "Goal", "label": "Goal 1"},
            {"id": "test:kpi:k1", "node_type": "KPI", "label": "KPI 1"},
            {"id": "test:actor:orphan", "node_type": "Actor", "label": "Orphan"},
        ]
        mock_repo.cypher_read.return_value = [
            {
                "from_id": "test:goal:g1",
                "to_id": "test:kpi:k1",
                "rel_type": "MEASURED_BY",
                "props": {},
            }
        ]

        result = await validate_graph_structure(mock_repo, "test")

        # g1 and k1 are connected; orphan actor should be detected
        assert "test:actor:orphan" in result.orphan_nodes
        assert len(result.orphan_nodes) == 1
        assert result.orphan_rate == pytest.approx(1 / 3, abs=0.01)
        assert result.edge_to_node_ratio == pytest.approx(1 / 3, abs=0.01)
