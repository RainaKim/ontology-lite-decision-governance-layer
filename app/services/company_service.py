"""
Company Service - Load and cache mock company data.

Contract-compliant company IDs (api_contract_v1.md):
  nexus_dynamics    → mock_company_nexus.json           (Nexus Dynamics)
  mayo_central      → mock_company_healthcare_merged.json (Mayo Central Hospital)
  sool_sool_icecream → sool_sool_icecream_merged.json

No DB. In-memory cache loaded once at startup.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.schemas.responses import CompanySummaryResponse, CompanyDetailResponse
from app.config.company_registry import COMPANY_RULES_FILES as _REGISTRY_BY_COMPANY

logger = logging.getLogger(__name__)

_cache: dict[str, dict] = {}           # key: "{lang}:{company_id}"
_summaries_v1: dict[str, list[CompanySummaryResponse]] = {"ko": [], "en": []}
_details_v1: dict[str, dict[str, CompanyDetailResponse]] = {"ko": {}, "en": {}}


def _load_all() -> None:
    """Load all companies (both langs) into cache. Called once at startup."""
    root = Path(__file__).parent.parent.parent  # project root

    for company_id, files in _REGISTRY_BY_COMPANY.items():
        filename = files.get("merged")
        if not filename:
            logger.warning(f"No 'merged' file for {company_id} — skipping")
            continue

        path = root / filename
        try:
            with open(path, "r") as f:
                raw = json.load(f)
        except FileNotFoundError:
            logger.warning(f"Company file not found: {path} — skipping {company_id}")
            continue
        except Exception as e:
            logger.error(f"Failed to load {filename}: {e}")
            continue

        for lang in ("ko", "en"):
            translation = raw.get("translations", {}).get(lang, {})

            # Build a lang-specific view: translation fields override top-level
            data = {**raw, **translation}
            # Map 'rules' key back to 'governance_rules' for backward compatibility
            if "rules" in translation:
                data["governance_rules"] = translation["rules"]
            data["_id"] = company_id
            _cache[f"{lang}:{company_id}"] = data

            company_meta = data.get("company", {})
            company_metadata = data.get("metadata", {})

            governance_framework = (
                company_metadata.get("governance_framework")
                or company_meta.get("industry", "")
            )

            _summaries_v1[lang].append(CompanySummaryResponse(
                id=company_id,
                name=company_meta.get("name", company_id),
                industry=company_meta.get("industry", ""),
                size=company_meta.get("size", ""),
                governance_framework=governance_framework,
            ))

            approval_hierarchy = data.get("approval_hierarchy", {})
            governance_rules = data.get("governance_rules", [])
            strategic_goals = data.get("strategic_goals", [])
            levels = approval_hierarchy.get("levels", [])
            chain_summary = " > ".join([lvl.get("title", "") for lvl in levels[:4]])

            _details_v1[lang][company_id] = CompanyDetailResponse(
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

            logger.info(f"Loaded company [{lang}]: {company_id} ({company_meta.get('name')})")


def init() -> None:
    """Initialize company cache. Call from app lifespan."""
    _load_all()
    logger.info(f"Company service ready: {list(_cache.keys())}")


def list_companies_v1(lang: str = "ko") -> list[CompanySummaryResponse]:
    """Return contract-compliant company summaries for GET /v1/companies."""
    return _summaries_v1.get(lang, _summaries_v1["ko"])


def get_company_v1(company_id: str, lang: str = "ko") -> Optional[CompanyDetailResponse]:
    """Return contract-compliant CompanyDetailResponse for GET /v1/companies/{id}."""
    return _details_v1.get(lang, _details_v1["ko"]).get(company_id)


def get_company_data(company_id: str, lang: str = "ko") -> Optional[dict]:
    """Return raw company data dict (for internal pipeline use)."""
    return _cache.get(f"{lang}:{company_id}")


def get_governance_rules(company_id: str, lang: str = "ko") -> list[dict]:
    """Return governance_rules list for a company, empty list if missing."""
    company = _cache.get(f"{lang}:{company_id}")
    if not company:
        return []
    return company.get("governance_rules", [])
