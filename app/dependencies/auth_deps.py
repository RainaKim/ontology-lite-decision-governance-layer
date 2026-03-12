from fastapi import HTTPException
from app.services.rbac_service import UserRole

def require_tenant_isolation(current_user, company_id: str) -> None:
    """Raises 403 if non-admin user targets another company."""
    if current_user.role != UserRole.ADMIN and current_user.company_id != company_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot submit decisions for a different company.",
        )
