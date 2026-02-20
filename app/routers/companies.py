"""
Companies Router — GET /v1/companies, GET /v1/companies/{id}

Contract-compliant endpoints for listing and retrieving company contexts.
All routes are mounted under /v1 via APIRouter prefix.
"""

from fastapi import APIRouter, HTTPException

from app.services import company_service
from app.schemas.responses import (
    CompanyListResponse,
    CompanySummaryResponse,
    CompanyDetailResponse,
)

router = APIRouter(
    prefix="/v1",
    tags=["companies"],
)


@router.get("/companies", response_model=CompanyListResponse)
async def list_companies():
    """
    GET /v1/companies — List all available company governance contexts.

    Returns lightweight summaries of all 3 mock companies.
    """
    summaries = company_service.list_companies_v1()
    return CompanyListResponse(
        companies=summaries,
        total=len(summaries),
    )


@router.get("/companies/{company_id}", response_model=CompanyDetailResponse)
async def get_company(company_id: str):
    """
    GET /v1/companies/{company_id} — Full company context.

    Path params:
        company_id: nexus_dynamics | mayo_central | delaware_gsa

    Returns full company data including approval hierarchy and governance rules.
    """
    detail = company_service.get_company_v1(company_id)
    if not detail:
        raise HTTPException(
            status_code=404,
            detail=f"Company '{company_id}' not found",
        )
    return detail
