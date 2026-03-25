"""
Tests for Step 8: Deterministic Governance Core — Graph RAG, Risk Scoring, Approval Chain.

Covers:
  8a. Risk scoring wired to CompanyConfig.risk_weights + graph context
  8b. enrich_approval_chain_from_graph
  8c. Graph RAG query methods on InMemoryGraphRepository
  8d. safe_cypher_read + search_similar_decisions on Neo4jGraphRepository (mocked)
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.graph.in_memory_repository import InMemoryGraphRepository
from app.graph.neo4j_repository import Neo4jGraphRepository
from app.ontology.models import Node, Edge
from app.ontology.node_types import NodeType
from app.ontology.edge_predicates import EdgePredicate
from app.services.risk_scoring_service import RiskScoringService
from app.config.company_config import RiskWeightConfig, CompanyConfig
from app.governance import enrich_approval_chain_from_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node(node_id: str, node_type: NodeType, label: str, **props) -> Node:
    return Node(id=node_id, type=node_type, label=label, properties=props)


def _make_edge(from_node: str, to_node: str, predicate: EdgePredicate, **props) -> Edge:
    return Edge(from_node=from_node, to_node=to_node, predicate=predicate, properties=props or None)


@pytest.fixture
def repo():
    return InMemoryGraphRepository()


@pytest.fixture
def seeded_repo(repo):
    """Seed a repo with rules, goals, actors, gaps, and edges."""
    # Goals
    g1 = _make_node("nexus:goal:g1", NodeType.GOAL, "Revenue Growth", priority="high")
    g2 = _make_node("nexus:goal:g2", NodeType.GOAL, "Cost Stability", priority="high")
    g3 = _make_node("nexus:goal:g3", NodeType.GOAL, "Data Compliance", priority="critical")

    # Rules
    r1 = _make_node("nexus:rule:r1", NodeType.RULE, "CFO Approval for Spend Over $50K")
    r2 = _make_node("nexus:rule:r2", NodeType.RULE, "Board Approval for Spend Over $200K")
    r3 = _make_node("nexus:rule:r3", NodeType.RULE, "Legal Sign-off for PII")

    # Actors
    cfo = _make_node("nexus:actor:cfo", NodeType.ACTOR, "CFO")
    ceo = _make_node("nexus:actor:ceo", NodeType.ACTOR, "CEO")
    counsel = _make_node("nexus:actor:general_counsel", NodeType.ACTOR, "General Counsel")

    # Gaps
    gap1 = _make_node("nexus:gap:gap1", NodeType.GAP, "Missing GDPR coverage", severity="high")

    loop = asyncio.get_event_loop()

    # Write all nodes
    for node in [g1, g2, g3, r1, r2, r3, cfo, ceo, counsel, gap1]:
        loop.run_until_complete(repo.write_node(node, "nexus"))

    # Edges: Rule -> Goal (GOVERNED_BY)
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r1", "nexus:goal:g2", EdgePredicate.GOVERNED_BY), "nexus"
    ))
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r2", "nexus:goal:g2", EdgePredicate.GOVERNED_BY), "nexus"
    ))
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r3", "nexus:goal:g3", EdgePredicate.GOVERNED_BY), "nexus"
    ))

    # Edges: Rule -> Actor (REQUIRES_APPROVAL_FROM)
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r1", "nexus:actor:cfo", EdgePredicate.REQUIRES_APPROVAL_FROM), "nexus"
    ))
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r2", "nexus:actor:ceo", EdgePredicate.REQUIRES_APPROVAL_FROM), "nexus"
    ))
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r3", "nexus:actor:general_counsel", EdgePredicate.REQUIRES_APPROVAL_FROM), "nexus"
    ))

    # Edge: Actor -> Actor (ESCALATES_TO)
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:actor:cfo", "nexus:actor:ceo", EdgePredicate.ESCALATES_TO), "nexus"
    ))

    # Edge: Goal <-> Goal (CONFLICTS_WITH)
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:goal:g1", "nexus:goal:g3", EdgePredicate.CONFLICTS_WITH), "nexus"
    ))

    # Edge: Rule -> Gap (HAS_GAP)
    loop.run_until_complete(repo.write_edge(
        _make_edge("nexus:rule:r3", "nexus:gap:gap1", EdgePredicate.HAS_GAP), "nexus"
    ))

    return repo


# ===========================================================================
# 8c. Graph RAG query methods on InMemoryGraphRepository
# ===========================================================================


class TestGetAllRules:
    def test_returns_rules_with_goals_and_approvers(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_all_rules("nexus")
        )
        assert len(results) == 3
        rule_ids = {r["rule_id"] for r in results}
        assert "nexus:rule:r1" in rule_ids
        assert "nexus:rule:r2" in rule_ids
        assert "nexus:rule:r3" in rule_ids

        # R1 should have goal G2 and approver CFO
        r1 = next(r for r in results if r["rule_id"] == "nexus:rule:r1")
        assert any(g["id"] == "nexus:goal:g2" for g in r1["goals"])
        assert any(a["id"] == "nexus:actor:cfo" for a in r1["approvers"])

    def test_returns_empty_for_unknown_company(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_all_rules("unknown_company")
        )
        assert results == []


class TestGetApprovalChainForRules:
    def test_returns_chain_with_escalation(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_approval_chain_for_rules(["nexus:rule:r1"], "nexus")
        )
        assert len(results) == 1
        assert results[0]["rule_id"] == "nexus:rule:r1"
        assert results[0]["actor_label"] == "CFO"
        assert "CEO" in results[0]["escalation_chain"]

    def test_returns_chain_without_escalation(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_approval_chain_for_rules(["nexus:rule:r2"], "nexus")
        )
        assert len(results) == 1
        assert results[0]["actor_label"] == "CEO"
        assert results[0]["escalation_chain"] == []

    def test_returns_empty_for_nonexistent_rule(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_approval_chain_for_rules(["nexus:rule:r999"], "nexus")
        )
        assert results == []


class TestGetGoalConflicts:
    def test_finds_conflict(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_goal_conflicts(["nexus:goal:g1"], "nexus")
        )
        assert len(results) == 1
        ids = {results[0]["goal1_id"], results[0]["goal2_id"]}
        assert "nexus:goal:g1" in ids
        assert "nexus:goal:g3" in ids

    def test_no_conflict_for_unconnected_goal(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_goal_conflicts(["nexus:goal:g2"], "nexus")
        )
        assert results == []


class TestGetGapsForRules:
    def test_finds_gap(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_gaps_for_rules(["nexus:rule:r3"], "nexus")
        )
        assert len(results) == 1
        assert results[0]["rule_id"] == "nexus:rule:r3"
        assert results[0]["gap_label"] == "Missing GDPR coverage"

    def test_no_gap_for_rule_without_gap(self, seeded_repo):
        results = asyncio.get_event_loop().run_until_complete(
            seeded_repo.get_gaps_for_rules(["nexus:rule:r1"], "nexus")
        )
        assert results == []


class TestSearchSimilarDecisions:
    def test_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                repo.search_similar_decisions([0.1] * 1536, "nexus")
            )


class TestSafeCypherReadInMemory:
    def test_raises_not_implemented(self, repo):
        with pytest.raises(NotImplementedError):
            asyncio.get_event_loop().run_until_complete(
                repo.safe_cypher_read("MATCH (n) RETURN n", company_id="nexus")
            )


# ===========================================================================
# 8d. safe_cypher_read + search_similar_decisions on Neo4jGraphRepository (mocked)
# ===========================================================================


class TestSafeCypherReadNeo4j:
    """Unit tests for Neo4jGraphRepository.safe_cypher_read using mocked driver."""

    def _make_repo(self):
        """Create a Neo4jGraphRepository with a mocked driver (bypass __init__)."""
        repo = object.__new__(Neo4jGraphRepository)
        repo._driver = AsyncMock()
        return repo

    def test_rejects_create(self):
        repo = self._make_repo()
        with pytest.raises(ValueError, match="Mutating"):
            asyncio.get_event_loop().run_until_complete(
                repo.safe_cypher_read("CREATE (n:Test {id: 'x'})", company_id="nexus")
            )

    def test_rejects_merge(self):
        repo = self._make_repo()
        with pytest.raises(ValueError, match="Mutating"):
            asyncio.get_event_loop().run_until_complete(
                repo.safe_cypher_read("MERGE (n:Test {id: 'x'})", company_id="nexus")
            )

    def test_rejects_delete(self):
        repo = self._make_repo()
        with pytest.raises(ValueError, match="Mutating"):
            asyncio.get_event_loop().run_until_complete(
                repo.safe_cypher_read("MATCH (n) DELETE n", company_id="nexus")
            )

    def test_rejects_set(self):
        repo = self._make_repo()
        with pytest.raises(ValueError, match="Mutating"):
            asyncio.get_event_loop().run_until_complete(
                repo.safe_cypher_read("MATCH (n) SET n.x = 1", company_id="nexus")
            )

    def test_rejects_drop(self):
        repo = self._make_repo()
        with pytest.raises(ValueError, match="Mutating"):
            asyncio.get_event_loop().run_until_complete(
                repo.safe_cypher_read("DROP INDEX chunk_embeddings", company_id="nexus")
            )

    def test_appends_limit_when_missing(self):
        repo = self._make_repo()
        captured = {}

        async def mock_cypher_read(query, params, company_id):
            captured["query"] = query
            return []

        repo.cypher_read = mock_cypher_read

        asyncio.get_event_loop().run_until_complete(
            repo.safe_cypher_read("MATCH (n) RETURN n", company_id="nexus")
        )
        assert "LIMIT 50" in captured["query"]

    def test_clamps_large_limit(self):
        repo = self._make_repo()
        captured = {}

        async def mock_cypher_read(query, params, company_id):
            captured["query"] = query
            return []

        repo.cypher_read = mock_cypher_read

        asyncio.get_event_loop().run_until_complete(
            repo.safe_cypher_read(
                "MATCH (n) RETURN n LIMIT 9999",
                company_id="nexus",
                result_limit=50,
            )
        )
        assert "LIMIT 50" in captured["query"]
        assert "LIMIT 9999" not in captured["query"]

    def test_preserves_small_limit(self):
        repo = self._make_repo()
        captured = {}

        async def mock_cypher_read(query, params, company_id):
            captured["query"] = query
            return []

        repo.cypher_read = mock_cypher_read

        asyncio.get_event_loop().run_until_complete(
            repo.safe_cypher_read(
                "MATCH (n) RETURN n LIMIT 10",
                company_id="nexus",
                result_limit=50,
            )
        )
        assert "LIMIT 10" in captured["query"]

    def test_passes_params_through(self):
        repo = self._make_repo()
        captured = {}

        async def mock_cypher_read(query, params, company_id):
            captured["params"] = params
            captured["company_id"] = company_id
            return []

        repo.cypher_read = mock_cypher_read

        asyncio.get_event_loop().run_until_complete(
            repo.safe_cypher_read(
                "MATCH (n) RETURN n",
                params={"foo": "bar"},
                company_id="nexus",
            )
        )
        # Tenant isolation is via database routing, not query params
        assert "_company_id" not in captured["params"]
        assert captured["params"]["foo"] == "bar"
        assert captured["company_id"] == "nexus"


# ===========================================================================
# 8a. Risk scoring — CompanyConfig.risk_weights + graph context
# ===========================================================================


class TestGetRiskWeights:
    def test_uses_company_config_when_provided(self):
        mock_config = MagicMock()
        mock_config.risk_weights = RiskWeightConfig(
            financial=0.25, compliance=0.50, strategic=0.25
        )
        weights = RiskScoringService._get_risk_weights(mock_config)
        assert weights["financial"] == 0.25
        assert weights["compliance"] == 0.50
        assert weights["strategic"] == 0.25

    def test_falls_back_to_defaults_when_no_config(self):
        weights = RiskScoringService._get_risk_weights(None)
        assert weights["financial"] == 0.40
        assert weights["compliance"] == 0.35
        assert weights["strategic"] == 0.25

    def test_falls_back_when_config_has_no_risk_weights(self):
        mock_config = MagicMock()
        mock_config.risk_weights = None
        weights = RiskScoringService._get_risk_weights(mock_config)
        assert weights["financial"] == 0.40


class TestScoreWithGraphContext:
    def test_accepts_graph_context_parameter(self):
        """Ensure score() works with graph_context without breaking."""
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 100000},
            company_payload={"strategic_goals": []},
            governance_result={"triggered_rules": []},
            graph_payload=None,
            graph_context={"edges": [], "nodes": []},
        )
        assert result.aggregate is not None

    def test_score_with_company_config(self):
        """Ensure score() uses CompanyConfig weights via company_config param."""
        svc = RiskScoringService()
        mock_config = MagicMock()
        mock_config.risk_weights = RiskWeightConfig(
            financial=0.25, compliance=0.50, strategic=0.25
        )
        result = svc.score(
            decision_payload={"cost": 100000, "uses_pii": True},
            company_payload={"strategic_goals": []},
            governance_result={"triggered_rules": []},
            graph_payload=None,
            company_config=mock_config,
        )
        assert result.aggregate is not None
        # Compliance weight is 0.50, so the aggregate should reflect heavier compliance weighting
        assert result.aggregate.score >= 0

    def test_backward_compat_without_new_params(self):
        """Ensure existing callers without graph_context/company_config still work."""
        svc = RiskScoringService()
        result = svc.score(
            decision_payload={"cost": 50000},
            company_payload={"strategic_goals": []},
            governance_result={"triggered_rules": []},
            graph_payload=None,
        )
        assert result.aggregate.band in ("LOW", "MEDIUM", "HIGH", "CRITICAL")


# ===========================================================================
# 8b. enrich_approval_chain_from_graph
# ===========================================================================


class TestEnrichApprovalChainFromGraph:
    def test_returns_original_chain_on_exception(self):
        mock_repo = AsyncMock()
        mock_repo.get_approval_chain_for_rules.side_effect = Exception("DB down")

        original_chain = [MagicMock(role="CFO")]
        result = asyncio.get_event_loop().run_until_complete(
            enrich_approval_chain_from_graph(
                approval_chain=original_chain,
                triggered_rule_ids=["R1"],
                company_id="nexus",
                repo=mock_repo,
            )
        )
        assert result is original_chain

    def test_returns_original_chain_when_no_results(self):
        mock_repo = AsyncMock()
        mock_repo.get_approval_chain_for_rules.return_value = []

        original_chain = [MagicMock(role="CFO")]
        result = asyncio.get_event_loop().run_until_complete(
            enrich_approval_chain_from_graph(
                approval_chain=original_chain,
                triggered_rule_ids=["R1"],
                company_id="nexus",
                repo=mock_repo,
            )
        )
        assert result is original_chain

    def test_merges_new_actor_from_graph(self):
        mock_repo = AsyncMock()
        mock_repo.get_approval_chain_for_rules.return_value = [
            {
                "rule_id": "nexus:rule:r1",
                "actor_id": "nexus:actor:vp_eng",
                "actor_label": "VP Engineering",
                "escalation_chain": ["CTO"],
            }
        ]

        original_chain = [MagicMock(role="CFO")]
        result = asyncio.get_event_loop().run_until_complete(
            enrich_approval_chain_from_graph(
                approval_chain=original_chain,
                triggered_rule_ids=["nexus:rule:r1"],
                company_id="nexus",
                repo=mock_repo,
            )
        )
        # Should now have 2 items
        assert len(result) == 2
        assert result[1].role == "VP Engineering"

    def test_does_not_duplicate_existing_actor(self):
        mock_repo = AsyncMock()
        mock_repo.get_approval_chain_for_rules.return_value = [
            {
                "rule_id": "nexus:rule:r1",
                "actor_id": "nexus:actor:cfo",
                "actor_label": "CFO",
                "escalation_chain": ["CEO"],
            }
        ]

        original_chain = [MagicMock(role="CFO")]
        result = asyncio.get_event_loop().run_until_complete(
            enrich_approval_chain_from_graph(
                approval_chain=original_chain,
                triggered_rule_ids=["nexus:rule:r1"],
                company_id="nexus",
                repo=mock_repo,
            )
        )
        # Should still have 1 item (CFO already present)
        assert len(result) == 1


# ===========================================================================
# Neo4jGraphRepository method tests (mocked driver)
# ===========================================================================


class TestNeo4jGetAllRules:
    def _make_repo_with_session(self):
        """Create a Neo4jGraphRepository with a properly mocked async session."""
        repo = object.__new__(Neo4jGraphRepository)
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        # Make driver.session() return an async context manager
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_driver.session.return_value = mock_ctx

        repo._driver = mock_driver
        return repo, mock_session

    def test_returns_rules(self):
        repo, mock_session = self._make_repo_with_session()

        mock_record = {
            "rule_id": "nexus:rule:r1",
            "label": "CFO Approval",
            "properties": {"id": "nexus:rule:r1", "label": "CFO Approval"},
            "goals": [{"id": "nexus:goal:g2", "label": "Cost Stability"}],
            "approvers": [{"id": "nexus:actor:cfo", "label": "CFO"}],
        }

        async def aiter_records():
            for item in [mock_record]:
                yield item

        async def mock_run_fn(*args, **kwargs):
            result = MagicMock()
            result.__aiter__ = lambda _: aiter_records()
            return result

        mock_session.run = mock_run_fn

        results = asyncio.get_event_loop().run_until_complete(
            repo.get_all_rules("nexus")
        )
        assert len(results) == 1
        assert results[0]["rule_id"] == "nexus:rule:r1"
        assert len(results[0]["goals"]) == 1
        assert len(results[0]["approvers"]) == 1


class TestNeo4jSearchSimilarDecisions:
    def _make_repo_with_session(self):
        """Create a Neo4jGraphRepository with a properly mocked async session."""
        repo = object.__new__(Neo4jGraphRepository)
        mock_driver = MagicMock()
        mock_session = AsyncMock()

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_driver.session.return_value = mock_ctx

        repo._driver = mock_driver
        return repo, mock_session

    def test_calls_vector_search_and_batch_context(self):
        repo, mock_session = self._make_repo_with_session()

        async def mock_vector_search(embedding, top_k, company_id, label, index_name):
            return [{"node": {"id": "nexus:decision:d1", "label": "Test"}, "score": 0.95}]

        repo.vector_search = mock_vector_search

        # Mock the batch context query
        mock_record = {
            "decision_id": "nexus:decision:d1",
            "context": [{"rel": "TRIGGERED", "node_id": "nexus:rule:r1", "label": "R1", "node_type": "Rule"}],
        }

        async def aiter_records():
            for item in [mock_record]:
                yield item

        async def mock_run_fn(*args, **kwargs):
            result = MagicMock()
            result.__aiter__ = lambda _: aiter_records()
            return result

        mock_session.run = mock_run_fn

        results = asyncio.get_event_loop().run_until_complete(
            repo.search_similar_decisions([0.1] * 1536, "nexus", top_k=1)
        )
        assert len(results) == 1
        assert results[0]["id"] == "nexus:decision:d1"
        assert results[0]["score"] == 0.95
        assert "context" in results[0]
        assert len(results[0]["context"]) == 1
