"""
Fixtures Router — GET /v1/fixtures

Returns demo decision scenarios for the selected company.
Frontend randomly selects from returned list (no server-side randomization).
"""

from fastapi import APIRouter, HTTPException, Query

from app.demo_fixtures import get_fixtures, get_all_company_ids, Fixture

router = APIRouter(
    prefix="/v1",
    tags=["fixtures"],
)


@router.get("/fixtures", response_model=list[Fixture])
async def list_fixtures(
    company_id: str = Query(
        ...,
        description="Company ID to fetch fixtures for (nexus_dynamics, mayo_central, delaware_gsa)",
    ),
):
    """
    GET /v1/fixtures?company_id={company_id}

    Returns demo decision scenarios for the selected company.
    Frontend should randomly pick from the returned list.

    Query params:
        company_id: nexus_dynamics | mayo_central | delaware_gsa (required)

    Returns:
        List of Fixture objects with id, company_id, title, text, tags.

    Errors:
        400: Missing company_id
        404: Unknown company_id
    """
    # Validate company_id exists
    valid_ids = get_all_company_ids()
    if company_id not in valid_ids:
        raise HTTPException(
            status_code=404,
            detail=f"Company '{company_id}' not found. Valid IDs: {', '.join(valid_ids)}",
        )

    fixtures = get_fixtures(company_id)

    # Should never be None given the check above, but be defensive
    if fixtures is None:
        return []

    return fixtures
