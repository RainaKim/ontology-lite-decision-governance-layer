"""
app/routers — v1 API routers.

All routers use prefix="/v1" so routes resolve to:
  /v1/companies
  /v1/decisions
  /v1/fixtures
  /v1/auth/signup
  /v1/auth/login
  /v1/me
  /v1/auth/google
  /v1/auth/google/callback
  /v1/auth/sso/google/authorize
  /v1/auth/sso/google/callback
  /v1/auth/sso/azure/authorize
  /v1/auth/sso/azure/callback
"""

from app.routers.auth import router as auth_router
from app.routers.companies import router as companies_router
from app.routers.decisions import router as decisions_router
from app.routers.fixtures import router as fixtures_router
from app.routers.sso import router as sso_router
from app.routers.workspace import router as workspace_router
from app.routers.analysis import router as analysis_router
from app.routers.agents import router as agents_router

__all__ = [
    "auth_router",
    "companies_router",
    "decisions_router",
    "fixtures_router",
    "sso_router",
    "workspace_router",
    "analysis_router",
    "agents_router",
]
