"""
Governance agent tools — Step 9.

Each tool wraps an existing repository method. All tools are:
- Decorated with @tool from langchain_core.tools
- Multi-tenant safe (accept company_id)
- Read-only (never mutate graph state)
- Non-fatal (catch exceptions, return empty/error result)

Tools are created by a factory function that captures the repo instance
via closure, so they have access to the repository at runtime.
"""

from __future__ import annotations

import logging
from typing import Optional

from langchain_core.tools import tool

from app.graph.base import BaseGraphRepository

logger = logging.getLogger(__name__)


def create_tools(repo: BaseGraphRepository) -> list:
    """
    Create tool instances bound to a specific repository.

    Args:
        repo: Graph repository to query (Neo4j or InMemory).

    Returns:
        List of LangChain tool functions.
    """

    @tool
    async def search_governance_rules(company_id: str) -> list[dict]:
        """Search for all active governance rules for a company.

        Returns a list of rules with their conditions, consequences,
        governed goals, and required approvers.
        """
        try:
            return await repo.get_all_rules(company_id)
        except Exception as exc:
            logger.warning("search_governance_rules failed: %s", exc)
            return []

    @tool
    async def search_similar_decisions(
        company_id: str,
        query_text: str,
    ) -> list[dict]:
        """Search for similar past decisions using vector similarity.

        Embeds the query text and finds the most similar past decisions
        in the knowledge graph, enriched with their triggered rules,
        approvers, and outcomes.
        """
        try:
            from app.onboarding.transform.embedder import embed_text

            embedding = await embed_text(query_text)
            if embedding is None:
                return [{"note": "Embedding unavailable -- cannot search past decisions"}]
            return await repo.search_similar_decisions(embedding, company_id, top_k=5)
        except NotImplementedError:
            return [{"note": "Vector search not available in this environment"}]
        except Exception as exc:
            logger.warning("search_similar_decisions failed: %s", exc)
            return []

    @tool
    async def get_goal_conflicts(
        company_id: str,
        goal_ids: list[str],
    ) -> list[dict]:
        """Find conflicts between strategic goals.

        Takes a list of goal IDs and returns any CONFLICTS_WITH
        relationships between them.
        """
        try:
            return await repo.get_goal_conflicts(goal_ids, company_id)
        except Exception as exc:
            logger.warning("get_goal_conflicts failed: %s", exc)
            return []

    @tool
    async def get_governance_gaps(
        company_id: str,
        rule_ids: list[str],
    ) -> list[dict]:
        """Find governance gaps associated with triggered rules.

        Takes a list of triggered rule IDs and returns any HAS_GAP
        edges from those rules to Gap nodes.
        """
        try:
            return await repo.get_gaps_for_rules(rule_ids, company_id)
        except Exception as exc:
            logger.warning("get_governance_gaps failed: %s", exc)
            return []

    @tool
    async def query_graph(
        company_id: str,
        cypher_query: str,
        params: Optional[dict] = None,
    ) -> list[dict]:
        """Execute a safe read-only Cypher query against the governance graph.

        The query is validated for safety -- mutating operations (CREATE,
        MERGE, SET, DELETE) are rejected. Results are limited to 50 rows.
        Use this for ad-hoc graph queries not covered by other tools.
        """
        try:
            return await repo.safe_cypher_read(
                cypher_query,
                params=params,
                company_id=company_id,
                result_limit=50,
            )
        except NotImplementedError:
            return [{"note": "Cypher queries not available in this environment"}]
        except ValueError as exc:
            return [{"error": str(exc)}]
        except Exception as exc:
            logger.warning("query_graph failed: %s", exc)
            return []

    @tool
    async def get_operational_context(company_id: str) -> dict:
        """Get the current Tier 2 operational context snapshot for a company.

        Returns budget remaining, headcount vs plan, active risk flags,
        and other operational data. Currently returns mock data --
        will be replaced by a real API call in Phase 3.
        """
        # Mock Tier 2 snapshot -- Phase 3 will wire this to
        # POST /v1/companies/{id}/context
        return {
            "company_id": company_id,
            "source": "mock",
            "budget": {
                "annual_total": 5_000_000,
                "spent_ytd": 3_200_000,
                "remaining": 1_800_000,
                "fiscal_quarter": "Q3",
            },
            "headcount": {
                "current": 120,
                "plan": 135,
                "open_positions": 8,
                "hiring_freeze": False,
            },
            "active_risk_flags": [],
            "last_updated": "2026-03-25T00:00:00Z",
        }

    return [
        search_governance_rules,
        search_similar_decisions,
        get_goal_conflicts,
        get_governance_gaps,
        query_graph,
        get_operational_context,
    ]
