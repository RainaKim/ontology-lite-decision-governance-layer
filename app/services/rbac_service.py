"""
app/services/rbac_service.py — Role-based access control dependencies.

Usage in routers:
    from app.services.rbac_service import require_manager_up, require_any

    @router.post("/decisions", dependencies=[Depends(require_manager_up)])
    async def submit_decision(...): ...
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.models.user import User
from app.services.user_service import get_current_user


class UserRole:
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    USER = "USER"


# Permission config table — add rows here to extend access without code changes.
_ROLE_PERMISSIONS: dict[str, list[str]] = {
    UserRole.ADMIN: [
        "decisions:read",
        "decisions:write",
        "companies:read",
        "admin:manage_users",
    ],
    UserRole.MANAGER: [
        "decisions:read",
        "decisions:write",
        "companies:read",
    ],
    UserRole.USER: [
        "decisions:read",
        "companies:read",
    ],
}


def get_permissions(role: str) -> list[str]:
    """Return the permission list for the given role. Unknown roles → []."""
    return list(_ROLE_PERMISSIONS.get(role, []))


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory — enforce that the authenticated user holds
    one of the specified roles.

    Raises HTTPException 403 if the role is insufficient.
    """
    def _dep(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _dep


# Convenience shortcuts
require_admin = require_role(UserRole.ADMIN)
require_manager_up = require_role(UserRole.ADMIN, UserRole.MANAGER)
require_any = require_role(UserRole.ADMIN, UserRole.MANAGER, UserRole.USER)
