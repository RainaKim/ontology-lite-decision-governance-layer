"""
Decision Governance Layer - FastAPI Application

Day 1-2 Scope: /extract endpoint for reliable decision objectization.
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from app.schemas import DecisionExtractionRequest, DecisionExtractionResponse
from app.llm_client import LLMClient
from app.extractor import DecisionExtractor, create_request_id

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances (initialized in lifespan)
llm_client = None
extractor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown.
    """
    # Startup
    global llm_client, extractor
    logger.info("Initializing Decision Governance Layer...")

    try:
        llm_client = LLMClient()
        extractor = DecisionExtractor(llm_client=llm_client, max_retries=2)
        logger.info("Application initialized successfully")
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
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Decision Governance Layer",
        "status": "operational",
        "version": "0.1.0",
        "endpoints": {
            "extract": "/extract"
        }
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "llm_client": "initialized" if llm_client else "not_initialized",
        "extractor": "initialized" if extractor else "not_initialized"
    }


@app.post("/extract", response_model=DecisionExtractionResponse)
async def extract_decision(request: DecisionExtractionRequest):
    """
    Extract structured decision from free-form text.

    Behavior:
    - Calls LLM (OpenAI GPT-4o) to output JSON
    - Validates with Pydantic
    - Retries up to 2 times if parsing/validation fails
    - Returns fallback Decision (confidence=0.1) if all attempts fail
    - Never crashes

    Request body:
    ```json
    {
        "decision_text": "We should launch a new mobile app to increase user engagement...",
        "apply_governance_rules": false
    }
    ```

    Response:
    ```json
    {
        "decision": { ... },
        "extraction_metadata": {
            "request_id": "uuid",
            "retry_count": 0,
            "model": "gpt-4o",
            "success": true
        },
        "governance_applied": false
    }
    ```
    """
    request_id = create_request_id()

    try:
        logger.info(f"[{request_id}] Received extraction request")
        logger.debug(f"[{request_id}] Decision text: {request.decision_text[:100]}...")

        # Extract decision with retry logic
        response = extractor.extract(
            decision_text=request.decision_text,
            request_id=request_id
        )

        # Check if extraction was successful
        if response.extraction_metadata.get("success", True):
            logger.info(f"[{request_id}] Extraction successful (confidence={response.decision.confidence})")
        else:
            logger.warning(f"[{request_id}] Extraction failed - returned fallback decision")

        return response

    except Exception as e:
        logger.error(f"[{request_id}] Unexpected error in /extract endpoint: {e}", exc_info=True)

        # Even on catastrophic failure, return a valid response (never crash)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error during extraction",
                "request_id": request_id,
                "message": str(e)
            }
        )


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
