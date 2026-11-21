"""
Company Service - Load and cache company governance data from CompanyConfig JSON.

Source of truth: configs/{config_id}.json (CompanyConfig). The API company_id
(DB primary key, e.g. "nexus_dynamics") maps to a config file via
app.config.company_registry.COMPANY_CONFIG_IDS.

No DB. In-memory cache loaded once at startup. English only.
"""

import json
import logging
from pathlib import Path
from typing import Optional

from app.schemas.responses import CompanySummaryResponse, CompanyDetailResponse
from app.config.company_config import CompanyConfig
from app.config.company_registry import COMPANY_CONFIG_IDS as _CONFIG_IDS

logger = logging.getLogger(__name__)

_cache: dict[str, dict] = {}           # key: "{lang}:{company_id}"
_summaries_v1: dict[str, list[CompanySummaryResponse]] = {"ko": [], "en": []}
_details_v1: dict[str, dict[str, CompanyDetailResponse]] = {"ko": {}, "en": {}}

_CONFIGS_DIR = Path(__file__).parent.parent.parent / "configs"


def _to_context(company_id: str, config: CompanyConfig) -> dict:
    """Adapt a CompanyConfig into the dict shape the routers/pipeline consume."""
    raw = config.model_dump(mode="json")
    hierarchy = raw.get("approval_hierarchy", [])
    return {
        **raw,
        "_id": company_id,
        "company": {
            "id": company_id,
            "name": config.company_name,
            "industry": config.industry,
            "size": "",
            "description": "",
        },
        "metadata": {"governance_framework": config.industry},
        "approval_hierarchy": {
            "levels": [
                {
                    "level": i + 1,
                    "title": e["role"],
                    "max_budget_authority": e.get("approval_limit"),
                    "note": e.get("approval_limit_note"),
                }
                for i, e in enumerate(hierarchy)
            ],
            "personnel": [],
        },
    }


def _load_all() -> None:
    """Load all registered companies into cache. Called once at startup."""
    for company_id, config_id in _CONFIG_IDS.items():
        path = _CONFIGS_DIR / f"{config_id}.json"
        try:
            with open(path, "r") as f:
                config = CompanyConfig.model_validate(json.load(f))
        except FileNotFoundError:
            logger.warning(f"Company config not found: {path} — skipping {company_id}")
            continue
        except Exception as e:
            logger.error(f"Failed to load {path.name}: {e}")
            continue

        data = _to_context(company_id, config)
        levels = data["approval_hierarchy"]["levels"]
        chain_summary = " > ".join(lvl["title"] for lvl in levels[:4])

        summary = CompanySummaryResponse(
            id=company_id,
            name=config.company_name,
            industry=config.industry,
            size="",
            governance_framework=config.industry,
        )
        detail = CompanyDetailResponse(
            **summary.model_dump(),
            description="",
            approval_chain_summary=chain_summary,
            total_governance_rules=len(config.governance_rules),
            strategic_goals=[
                {
                    "goal_id": g.goal_id,
                    "name": g.label,
                    "owner_id": g.owner_role,
                    "priority": g.priority,
                }
                for g in config.strategic_goals
            ],
            approval_hierarchy=data["approval_hierarchy"],
        )

        # English only: both lang keys point at the same data (callers still pass lang).
        for lang in ("ko", "en"):
            _cache[f"{lang}:{company_id}"] = data
            _summaries_v1[lang].append(summary)
            _details_v1[lang][company_id] = detail

        logger.info(f"Loaded company: {company_id} <- configs/{config_id}.json ({config.company_name})")


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
