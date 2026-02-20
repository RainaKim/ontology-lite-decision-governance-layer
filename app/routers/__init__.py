"""
app/routers — v1 API routers.

All routers use prefix="/v1" so routes resolve to:
  /v1/companies
  /v1/decisions
  /v1/fixtures
  etc.
"""

from app.routers.companies import router as companies_router
from app.routers.decisions import router as decisions_router
from app.routers.fixtures import router as fixtures_router

__all__ = ["companies_router", "decisions_router", "fixtures_router"]
