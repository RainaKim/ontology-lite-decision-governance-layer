"""
Companies Router — GET /v1/companies, GET /v1/companies/{id}

Company list is driven from the DB companies table (seeded via migration 0008).
Governance context (rules, hierarchy, goals) still loads from mock JSON via
company_service, keyed by the governance id (= DB company PK).
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.company import Company
from app.repositories import company_repository
from app.services import company_service
from app.services.rbac_service import require_any
from app.schemas.responses import (
    CompanyListResponse,
    CompanySummaryResponse,
    CompanyDetailResponse,
)

router = APIRouter(
    prefix="/v1",
    tags=["companies"],
)


def _summary_from_db(company: Company, lang: str) -> CompanySummaryResponse:
    """
    Build a CompanySummaryResponse from a DB Company row.

    - name: Korean (company_name) by default; English (company_name_en) when lang="en"
      and an English name is stored, falling back to company_name otherwise.
    - name_en always carries the English name when available so frontends can render
      both languages without a second request.
    """
    # Resolve display name based on requested language
    if lang == "en" and company.company_name_en:
        display_name = company.company_name_en
    else:
        display_name = company.company_name

    # Pull governance metadata from the JSON cache (non-fatal — defaults to empty)
    governance_meta = company_service.get_company_data(company.id, lang=lang) or {}
    company_meta = governance_meta.get("company", {})
    metadata = governance_meta.get("metadata", {})

    industry = company_meta.get("industry", "")
    size = company_meta.get("size", "")
    governance_framework = (
        metadata.get("governance_framework") or company_meta.get("industry", "")
    )

    return CompanySummaryResponse(
        id=company.id,
        name=display_name,
        name_en=company.company_name_en,
        industry=industry,
        size=size,
        governance_framework=governance_framework,
    )


@router.get("/companies", response_model=CompanyListResponse)
async def list_companies(
    lang: str = Query(default="ko", pattern="^(ko|en)$"),
    _: object = Depends(require_any),
    db: Session = Depends(get_db),
):
    """
    GET /v1/companies — List all active companies from the DB.

    Query params:
        lang: "ko" (default) | "en" — controls the primary display name in `name`.

    Both `name` (localised) and `name_en` are always returned so the frontend can
    switch languages client-side without a second request.
    """
    companies = company_repository.list_all(db)
    summaries = [_summary_from_db(c, lang) for c in companies]
    return CompanyListResponse(companies=summaries, total=len(summaries))


@router.get("/companies/{company_id}", response_model=CompanyDetailResponse)
async def get_company(
    company_id: str,
    lang: str = Query(default="ko", pattern="^(ko|en)$"),
    _: object = Depends(require_any),
    db: Session = Depends(get_db),
):
    """
    GET /v1/companies/{company_id} — Full company governance context.

    Path params:
        company_id: nexus_dynamics | mayo_central | sool_sool_icecream

    Returns full company data including approval hierarchy and governance rules.
    """
    db_company = company_repository.get_by_id(db, company_id)
    if not db_company:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    detail = company_service.get_company_v1(company_id, lang=lang)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Company '{company_id}' not found")

    # Apply DB names (authoritative) over whatever the JSON cache returned
    if lang == "en" and db_company.company_name_en:
        detail.name = db_company.company_name_en
    else:
        detail.name = db_company.company_name
    detail.name_en = db_company.company_name_en

    return detail
