"""
Companies Router — GET /v1/companies, GET /v1/companies/{id}

Contract-compliant endpoints for listing and retrieving company contexts.
All routes are mounted under /v1 via APIRouter prefix.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
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


def _attach_name_en(response: CompanySummaryResponse, db: Session) -> CompanySummaryResponse:
    """Look up company_name_en from DB and attach to response."""
    db_company = company_repository.get_by_id(db, response.id)
    if db_company and db_company.company_name_en:
        response.name_en = db_company.company_name_en
    return response


@router.get("/companies", response_model=CompanyListResponse)
async def list_companies(_: object = Depends(require_any), db: Session = Depends(get_db)):
    """
    GET /v1/companies — List all available company governance contexts.

    Returns lightweight summaries of all 3 mock companies.
    """
    summaries = [_attach_name_en(s, db) for s in company_service.list_companies_v1()]
    return CompanyListResponse(companies=summaries, total=len(summaries))


@router.get("/companies/{company_id}", response_model=CompanyDetailResponse)
async def get_company(company_id: str, _: object = Depends(require_any), db: Session = Depends(get_db)):
    """
    GET /v1/companies/{company_id} — Full company context.

    Path params:
        company_id: nexus_dynamics | mayo_central

    Returns full company data including approval hierarchy and governance rules.
    """
    detail = company_service.get_company_v1(company_id)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail=f"Company '{company_id}' not found",
        )
    return _attach_name_en(detail, db)
