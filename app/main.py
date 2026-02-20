"""
Decision Governance Layer - FastAPI Application

All public API routes are mounted under /v1 prefix via routers.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from app.llm_client import LLMClient
from app.extractor import DecisionExtractor
from app.graph_repository import InMemoryGraphRepository
from app.services import company_service
from app.routers import companies_router, decisions_router, fixtures_router

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan, exported for routers)
llm_client = None
extractor = None
graph_repo = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown.
    """
    # Startup
    global llm_client, extractor, graph_repo
    logger.info("Initializing Decision Governance Layer...")

    try:
        llm_client = LLMClient()
        extractor = DecisionExtractor(llm_client=llm_client, max_retries=2)
        graph_repo = InMemoryGraphRepository()
        company_service.init()
        logger.info("Application initialized successfully (LLM + Graph Repository + Company Service)")
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down Decision Governance Layer...")


# Initialize FastAPI app
app = FastAPI(
    title="Decision Governance Layer",
    description="Ontology-lite system for enterprise decision structuring and governance",
    version="1.0.0",
    lifespan=lifespan
)

# ── CORS Middleware ──────────────────────────────────────────────────────────
# Allow frontend dev server and production origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://decisiongovernance.ai",
        "https://www.decisiongovernance.ai",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount v1 routers ─────────────────────────────────────────────────────────
# All routes are under /v1 prefix (defined in each router)
app.include_router(companies_router)
app.include_router(decisions_router)
app.include_router(fixtures_router)


# ── Root-level endpoints (no /v1 prefix) ─────────────────────────────────────

@app.get("/")
async def root():
    """Root — lists available v1 endpoints."""
    return {
        "service": "Decision Governance Layer",
        "status": "operational",
        "version": "1.0.0",
        "api_version": "v1",
        "endpoints": {
            "list_companies": "GET /v1/companies",
            "get_company": "GET /v1/companies/{company_id}",
            "submit_decision": "POST /v1/decisions",
            "stream_decision": "GET /v1/decisions/{decision_id}/stream",
            "get_decision": "GET /v1/decisions/{decision_id}",
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    graph_stats = {}
    if graph_repo:
        graph_stats = {
            "nodes_count": len(graph_repo._nodes),
            "edges_count": len(graph_repo._edges)
        }
    return {
        "status": "healthy",
        "llm_client": "initialized" if llm_client else "not_initialized",
        "extractor": "initialized" if extractor else "not_initialized",
        "graph_repository": "initialized" if graph_repo else "not_initialized",
        "graph_stats": graph_stats
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler to prevent crashes."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc),
            "detail": "The service encountered an unexpected error but remains operational"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
