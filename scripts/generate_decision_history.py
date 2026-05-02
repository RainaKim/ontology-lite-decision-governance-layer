"""
Generate synthetic decision history for Nexus Analytics.

Creates 20 past Decision nodes in Neo4j with embeddings for vector search.
Uses get_llm("capable") for LLM generation and embed_text() for embeddings.

Decision nodes use CREATE semantics (never MERGE) per CLAUDE.md.

Usage:
    python scripts/generate_decision_history.py

Requires:
    NEO4J_URI, OPENAI_API_KEY (for embeddings), LLM_PROVIDER env vars.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM prompt
# ---------------------------------------------------------------------------

DECISION_GENERATION_PROMPT = """\
Generate {n} realistic past business decisions for Nexus Analytics, a 120-person B2B SaaS company (Series B, data analytics platform).

Company rules:
- R1: CFO approval required for spend > $50,000
- R2: Board approval required for spend > $200,000
- R3: Legal sign-off required for customer data processing (PII)
- R4: Procurement review required for vendor contracts > $100,000
- R5: HR + department head approval for all hiring
- R6: Q4 spending freeze (informal)
- R7: CTO can bypass procurement for dev tools under $20K

Generate decisions as a JSON array. Each decision:
{{
  "id": "DEC-<3-digit number>",
  "date": "YYYY-MM-DD",
  "description": "Detailed description of what was decided",
  "decision_type": "budget|hiring|vendor|compliance|other",
  "amount": null or number,
  "status": "approved|rejected",
  "triggered_rule_ids": ["R1", "R3"],
  "approver_role": "CFO|CEO|General Counsel|CTO|VP Sales",
  "outcome_notes": "Brief outcome description"
}}

Requirements:
- Mix of approved (70%) and rejected (30%)
- Different rules triggered across decisions
- Amounts ranging from $5K to $500K
- Dates spanning 2023-01-01 to 2025-12-31
- At least 3 hiring decisions, 3 compliance decisions, 5 budget decisions, 3 vendor decisions
- Some decisions should trigger multiple rules

Return ONLY the JSON array, no other text.
"""


# ---------------------------------------------------------------------------
# Core logic (importable for testing)
# ---------------------------------------------------------------------------


async def generate_decisions_via_llm(n: int = 20) -> list[dict]:
    """
    Generate synthetic decisions using the configured LLM.

    Returns a list of decision dicts, or an empty list on failure.
    """
    from app.config.llm import get_llm

    llm = get_llm("capable")
    prompt = DECISION_GENERATION_PROMPT.format(n=n)

    try:
        response = await llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Strip markdown fences if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            parts = content.split("```")
            if len(parts) >= 3:
                content = parts[1].strip()

        decisions = json.loads(content)
        if not isinstance(decisions, list):
            logger.error("LLM did not return a list")
            return []

        logger.info(f"Generated {len(decisions)} synthetic decisions")
        return decisions

    except Exception as exc:
        logger.error(f"LLM decision generation failed: {exc}", exc_info=True)
        return []


def get_fallback_decisions() -> list[dict]:
    """
    Return a hardcoded set of 20 synthetic decisions as fallback
    when the LLM is unavailable.
    """
    return [
        {"id": "DEC-001", "date": "2023-02-15", "description": "Hire 2 senior backend engineers for the data pipeline team at $160K each", "decision_type": "hiring", "amount": 320000, "status": "approved", "triggered_rule_ids": ["R5", "R2"], "approver_role": "CEO", "outcome_notes": "Both engineers onboarded by April 2023"},
        {"id": "DEC-002", "date": "2023-03-10", "description": "Purchase Snowflake enterprise license for data warehousing at $85K/year", "decision_type": "vendor", "amount": 85000, "status": "approved", "triggered_rule_ids": ["R1"], "approver_role": "CFO", "outcome_notes": "License activated, reduced query costs by 40%"},
        {"id": "DEC-003", "date": "2023-04-22", "description": "Implement customer data anonymization pipeline for GDPR compliance", "decision_type": "compliance", "amount": 45000, "status": "approved", "triggered_rule_ids": ["R3"], "approver_role": "General Counsel", "outcome_notes": "Pipeline deployed, passed SOC2 audit"},
        {"id": "DEC-004", "date": "2023-05-18", "description": "Expand to EU market with dedicated sales team and local data center", "decision_type": "budget", "amount": 450000, "status": "approved", "triggered_rule_ids": ["R1", "R2", "R3"], "approver_role": "CEO", "outcome_notes": "EU launch completed Q3 2023, $2M ARR within 6 months"},
        {"id": "DEC-005", "date": "2023-06-05", "description": "Replace legacy monitoring with Datadog enterprise at $120K/year", "decision_type": "vendor", "amount": 120000, "status": "approved", "triggered_rule_ids": ["R1", "R4"], "approver_role": "CFO", "outcome_notes": "Migration completed, MTTR reduced by 65%"},
        {"id": "DEC-006", "date": "2023-07-20", "description": "Hire VP of Engineering to lead platform team", "decision_type": "hiring", "amount": 280000, "status": "approved", "triggered_rule_ids": ["R5", "R2"], "approver_role": "CEO", "outcome_notes": "VP started September 2023, restructured engineering org"},
        {"id": "DEC-007", "date": "2023-08-14", "description": "Build customer health scoring model using PII data", "decision_type": "compliance", "amount": 30000, "status": "rejected", "triggered_rule_ids": ["R3"], "approver_role": "General Counsel", "outcome_notes": "Rejected due to insufficient data handling safeguards"},
        {"id": "DEC-008", "date": "2023-09-30", "description": "Allocate $75K for Q4 marketing campaign at SaaStr Annual", "decision_type": "budget", "amount": 75000, "status": "rejected", "triggered_rule_ids": ["R1", "R6"], "approver_role": "CFO", "outcome_notes": "Rejected due to Q4 spending freeze"},
        {"id": "DEC-009", "date": "2023-10-12", "description": "Purchase JetBrains team licenses for 15 developers at $12K", "decision_type": "vendor", "amount": 12000, "status": "approved", "triggered_rule_ids": ["R7"], "approver_role": "CTO", "outcome_notes": "CTO bypassed procurement per dev tool exception"},
        {"id": "DEC-010", "date": "2023-11-28", "description": "Engage external penetration testing firm for annual security audit at $55K", "decision_type": "compliance", "amount": 55000, "status": "approved", "triggered_rule_ids": ["R1"], "approver_role": "CFO", "outcome_notes": "Audit completed, 3 critical findings remediated"},
        {"id": "DEC-011", "date": "2024-01-15", "description": "Hire 3 junior data analysts for customer success team", "decision_type": "hiring", "amount": 210000, "status": "approved", "triggered_rule_ids": ["R5", "R2"], "approver_role": "CEO", "outcome_notes": "All three analysts productive within 2 months"},
        {"id": "DEC-012", "date": "2024-02-20", "description": "Sign 2-year contract with AWS for reserved instances at $180K/year", "decision_type": "vendor", "amount": 360000, "status": "approved", "triggered_rule_ids": ["R1", "R2", "R4"], "approver_role": "CEO", "outcome_notes": "Saved 35% vs on-demand pricing"},
        {"id": "DEC-013", "date": "2024-03-18", "description": "Implement real-time PII detection in analytics pipeline", "decision_type": "compliance", "amount": 65000, "status": "approved", "triggered_rule_ids": ["R1", "R3"], "approver_role": "General Counsel", "outcome_notes": "Reduced PII exposure incidents by 90%"},
        {"id": "DEC-014", "date": "2024-05-01", "description": "Acquire small ML startup for $500K to accelerate AI features", "decision_type": "budget", "amount": 500000, "status": "rejected", "triggered_rule_ids": ["R1", "R2"], "approver_role": "CEO", "outcome_notes": "Rejected by board — insufficient due diligence on IP"},
        {"id": "DEC-015", "date": "2024-06-15", "description": "Upgrade office lease to larger space at $25K/month additional", "decision_type": "budget", "amount": 300000, "status": "approved", "triggered_rule_ids": ["R1", "R2"], "approver_role": "CEO", "outcome_notes": "New office accommodates growth to 150 employees"},
        {"id": "DEC-016", "date": "2024-08-10", "description": "Launch customer data export feature requiring PII handling", "decision_type": "compliance", "amount": 40000, "status": "approved", "triggered_rule_ids": ["R3"], "approver_role": "General Counsel", "outcome_notes": "Feature launched with encryption and audit logging"},
        {"id": "DEC-017", "date": "2024-09-22", "description": "Hire contract DevOps engineer for 6-month infrastructure migration", "decision_type": "hiring", "amount": 90000, "status": "approved", "triggered_rule_ids": ["R1", "R5"], "approver_role": "CTO", "outcome_notes": "Migration completed ahead of schedule"},
        {"id": "DEC-018", "date": "2024-11-05", "description": "Purchase GitHub Enterprise for improved code review workflow at $18K", "decision_type": "vendor", "amount": 18000, "status": "approved", "triggered_rule_ids": ["R7"], "approver_role": "CTO", "outcome_notes": "PR review time reduced by 30%"},
        {"id": "DEC-019", "date": "2025-01-20", "description": "Allocate $200K budget for Series C preparation expenses", "decision_type": "budget", "amount": 200000, "status": "rejected", "triggered_rule_ids": ["R1", "R2"], "approver_role": "CFO", "outcome_notes": "Rejected — board wanted to delay fundraising to Q3"},
        {"id": "DEC-020", "date": "2025-03-15", "description": "Implement SOC2 Type II compliance program with external auditor", "decision_type": "compliance", "amount": 95000, "status": "approved", "triggered_rule_ids": ["R1", "R3"], "approver_role": "General Counsel", "outcome_notes": "Audit in progress, expected completion Q2 2025"},
    ]


async def write_decisions_to_neo4j(
    decisions: list[dict],
    company_id: str = "nexus_analytics",
    repo=None,
) -> int:
    """
    Write Decision nodes to Neo4j with embeddings.

    Uses CREATE semantics (instance-layer, never MERGE).
    Embeds each decision description and stores the embedding on the node.

    Args:
        decisions: List of decision dicts from LLM or fallback.
        company_id: Company ID for Neo4j database routing.
        repo: Optional repository instance (for testing).

    Returns:
        Number of decisions successfully written.
    """
    if repo is None:
        from app.graph.neo4j_repository import Neo4jGraphRepository
        repo = Neo4jGraphRepository()

    from app.onboarding.transform.embedder import embed_chunks
    from app.ontology.models import Node
    from app.ontology.node_types import NodeType

    # Batch embed all descriptions in a single API call
    descriptions = [d.get("description", "") for d in decisions]
    all_embeddings = await embed_chunks(descriptions)  # single API call

    written = 0
    for i, decision in enumerate(decisions):
        decision_id = decision.get("id", f"DEC-{written:03d}")
        description = decision.get("description", "")
        node_id = f"{company_id}:decision:{decision_id.lower().replace('-', '_')}"

        # Use pre-computed embedding from batch call
        embedding = all_embeddings[i] if all_embeddings else None

        node = Node(
            id=node_id,
            type=NodeType.DECISION,
            label=description[:80],
            properties={
                "decision_id": decision_id,
                "date": decision.get("date", ""),
                "description": description,
                "decision_type": decision.get("decision_type", "other"),
                "amount": decision.get("amount"),
                "status": decision.get("status", "approved"),
                "triggered_rule_ids": decision.get("triggered_rule_ids", []),
                "approver_role": decision.get("approver_role", ""),
                "outcome_notes": decision.get("outcome_notes", ""),
                "source": "synthetic_history",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            },
            embedding=embedding,
        )

        try:
            await repo.write_node(node, company_id)
            written += 1
            logger.info(
                "[%d/%d] Wrote decision %s (%s) — embedding=%s",
                i + 1, len(decisions), decision_id,
                decision.get("decision_type"), "yes" if embedding else "no",
            )
        except Exception as exc:
            logger.error("Failed to write decision %s: %s", decision_id, exc)

    return written


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


async def main():
    """Generate and write synthetic decision history."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    company_id = "nexus_analytics"
    n = 20

    # Check for existing synthetic decisions to avoid duplicates
    try:
        from app.graph.neo4j_repository import Neo4jGraphRepository
        _check_repo = Neo4jGraphRepository()
        existing_check = await _check_repo.safe_cypher_read(
            "MATCH (d:Decision) WHERE d.source = 'synthetic_history' RETURN count(d) AS cnt",
            company_id=company_id,
        )
        await _check_repo.close()
        if existing_check and existing_check[0].get("cnt", 0) > 0:
            print(f"WARNING: {existing_check[0]['cnt']} synthetic Decision nodes already exist.")
            print("Delete them first or re-running will create duplicates.")
            print("To delete: MATCH (d:Decision) WHERE d.source = 'synthetic_history' DETACH DELETE d")
            sys.exit(1)
    except Exception as exc:
        logger.warning("Could not check for existing decisions: %s", exc)

    logger.info(f"Generating {n} synthetic decisions for {company_id}...")

    # Try LLM generation first, fall back to hardcoded
    decisions = await generate_decisions_via_llm(n)
    if not decisions:
        logger.info("LLM unavailable — using fallback decisions")
        decisions = get_fallback_decisions()

    logger.info(f"Writing {len(decisions)} decisions to Neo4j...")
    written = await write_decisions_to_neo4j(decisions, company_id)
    logger.info(f"Done. {written}/{len(decisions)} decisions written successfully.")


if __name__ == "__main__":
    asyncio.run(main())
