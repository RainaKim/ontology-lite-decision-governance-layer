"""
Company Service - Load and cache mock company data.

Contract-compliant company IDs (api_contract_v1.md):
  nexus_dynamics    → mock_company.json           (Nexus Dynamics)
  mayo_central      → mock_company_healthcare.json (Mayo Central Hospital)
  delaware_gsa      → mock_company_public.json    (State of Delaware GSA)

No DB. In-memory cache loaded once at startup.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.schemas.responses import CompanySummaryResponse, CompanyDetailResponse

logger = logging.getLogger(__name__)

# ── Company registry ─────────────────────────────────────────────────────────
# Maps contract-compliant ID → JSON file path
_REGISTRY: dict[str, str] = {
    "nexus_dynamics": "mock_company.json",
    "mayo_central": "mock_company_healthcare.json",
    "delaware_gsa": "mock_company_public.json",
}

_cache: dict[str, dict] = {}
_summaries_v1: list[CompanySummaryResponse] = []
_details_v1: dict[str, CompanyDetailResponse] = {}


def _load_all() -> None:
    """Load all companies into cache. Called once at startup."""
    global _summaries_v1, _details_v1
    root = Path(__file__).parent.parent.parent  # project root

    for company_id, filename in _REGISTRY.items():
        path = root / filename
        try:
            with open(path, "r") as f:
                data = json.load(f)
            # Attach stable id so consumers don't have to guess
            data["_id"] = company_id
            _cache[company_id] = data

            company_meta = data.get("company", {})
            company_metadata = data.get("metadata", {})

            # governance_framework: read from metadata.governance_framework,
            # fall back to company.industry only if metadata key is absent
            governance_framework = (
                company_metadata.get("governance_framework")
                or company_meta.get("industry", "")
            )

            # Build v1-compliant summary
            _summaries_v1.append(CompanySummaryResponse(
                id=company_id,
                name=company_meta.get("name", company_id),
                industry=company_meta.get("industry", ""),
                size=company_meta.get("size", ""),
                governance_framework=governance_framework,
            ))

            # Build v1-compliant detail
            approval_hierarchy = data.get("approval_hierarchy", {})
            governance_rules = data.get("governance_rules", [])
            strategic_goals = data.get("strategic_goals", [])

            # Build approval chain summary from levels
            levels = approval_hierarchy.get("levels", [])
            chain_summary = " > ".join([lvl.get("title", "") for lvl in levels[:4]])

            _details_v1[company_id] = CompanyDetailResponse(
                id=company_id,
                name=company_meta.get("name", company_id),
                industry=company_meta.get("industry", ""),
                size=company_meta.get("size", ""),
                governance_framework=governance_framework,
                description=company_meta.get("description", ""),
                approval_chain_summary=chain_summary,
                total_governance_rules=len(governance_rules),
                strategic_goals=[
                    {
                        "goal_id": g.get("goal_id"),
                        "name": g.get("name"),
                        "owner_id": g.get("owner_id"),
                        "priority": g.get("priority"),
                    }
                    for g in strategic_goals
                ],
                approval_hierarchy=approval_hierarchy,
            )

            logger.info(f"Loaded company: {company_id} ({company_meta.get('name')})")
        except FileNotFoundError:
            logger.warning(f"Company file not found: {path} — skipping {company_id}")
        except Exception as e:
            logger.error(f"Failed to load {filename}: {e}")


def init() -> None:
    """Initialize company cache. Call from app lifespan."""
    _load_all()
    logger.info(f"Company service ready: {list(_cache.keys())}")


def list_companies_v1() -> list[CompanySummaryResponse]:
    """Return contract-compliant company summaries for GET /v1/companies."""
    return _summaries_v1


def get_company_v1(company_id: str) -> Optional[CompanyDetailResponse]:
    """Return contract-compliant CompanyDetailResponse for GET /v1/companies/{id}."""
    return _details_v1.get(company_id)


def get_company_data(company_id: str) -> Optional[dict]:
    """Return raw company data dict (for internal pipeline use)."""
    return _cache.get(company_id)


def get_governance_rules(company_id: str) -> list[dict]:
    """Return governance_rules list for a company, empty list if missing."""
    company = _cache.get(company_id)
    if not company:
        return []
    return company.get("governance_rules", [])
