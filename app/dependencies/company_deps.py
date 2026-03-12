from fastapi import HTTPException
from app.services import company_service

def validate_company_exists(company_id: str, lang: str = "ko") -> None:
    """Raises 422 if company_id is unknown."""
    if not company_service.get_company_v1(company_id, lang=lang):
        valid_ids = sorted(company_service.list_companies_v1(lang="en"), key=lambda c: c.id)
        valid_str = ", ".join(c.id for c in valid_ids)
        raise HTTPException(
            status_code=422,
            detail=f"Unknown company_id '{company_id}'. Valid: {valid_str}",
        )
