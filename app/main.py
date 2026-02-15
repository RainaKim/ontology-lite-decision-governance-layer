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
from app.governance import evaluate_governance
from app.decision_pack import build_decision_pack
from app.graph_repository import InMemoryGraphRepository

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
        logger.info("Application initialized successfully (LLM + Graph Repository)")
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
    graph_stats = {}
    if graph_repo:
        # Simple stats without async call
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


@app.post("/extract")
async def extract_decision(request: DecisionExtractionRequest):
    """
    Extract structured decision from free-form text and generate Decision Pack.

    Flow:
    1. Extract decision using LLM (OpenAI GPT-4o)
    2. Validate with Pydantic and retry up to 2 times on failure
    3. Apply governance rules (if requested)
    4. Build Decision Pack with approval chain, flags, and next steps
    5. Return comprehensive response

    Behavior:
    - Extraction failures return fallback decision with confidence=0.1
    - Governance evaluation is optional (controlled by apply_governance_rules)
    - Decision Pack is always generated, even on extraction failure
    - Never crashes - graceful degradation at every step

    Request body:
    ```json
    {
        "decision_text": "We should launch a new mobile app to increase user engagement...",
        "apply_governance_rules": true
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
        "governance_applied": true,
        "approval_chain": [...],
        "flags": [...],
        "triggered_rules": [...],
        "requires_human_review": true,
        "decision_pack": {
            "title": "Decision Title",
            "summary": {
                "decision_statement": "...",
                "governance_status": "needs_review",
                "risk_level": "medium"
            },
            "approval_chain": [...],
            "missing_items": [...],
            "recommended_next_actions": [...]
        }
    }
    ```
    """
    request_id = create_request_id()

    try:
        logger.info(f"[{request_id}] Received extraction request")
        logger.debug(f"[{request_id}] Decision text: {request.decision_text[:100]}...")

        # Step 1: Extract decision with retry logic
        response = extractor.extract(
            decision_text=request.decision_text,
            request_id=request_id
        )

        # Check if extraction was successful
        extraction_success = response.extraction_metadata.get("success", True)
        if extraction_success:
            logger.info(f"[{request_id}] Extraction successful (confidence={response.decision.confidence})")
        else:
            logger.warning(f"[{request_id}] Extraction failed - returned fallback decision")

        # Step 2: Apply governance evaluation (if requested or by default)
        governance_result = None
        if request.apply_governance_rules:
            logger.info(f"[{request_id}] Applying governance rules...")
            try:
                governance_result = evaluate_governance(
                    decision=response.decision,
                    company_context={}
                )

                # Update response with governance fields
                response.governance_applied = True
                response.approval_chain = governance_result.approval_chain
                response.flags = [flag.value for flag in governance_result.flags]
                response.triggered_rules = governance_result.triggered_rules
                response.requires_human_review = governance_result.requires_human_review

                logger.info(f"[{request_id}] Governance evaluation complete "
                           f"(triggered_rules={len(governance_result.triggered_rules)}, "
                           f"flags={len(governance_result.flags)})")
            except Exception as e:
                logger.error(f"[{request_id}] Governance evaluation failed: {e}", exc_info=True)
                # Continue without governance - don't fail the request

        # Step 3: Build graph and upsert to repository (graph-native pipeline)
        graph_payload = None
        subgraph = None
        if governance_result:
            logger.info(f"[{request_id}] Building decision graph...")
            try:
                # Convert decision and governance to dicts
                decision_dict = response.decision.model_dump()
                governance_dict = governance_result.to_dict()

                # Upsert decision graph to repository (builds graph internally)
                decision_graph = await graph_repo.upsert_decision_graph(
                    decision=decision_dict,
                    governance=governance_dict,
                    decision_id=request_id
                )

                logger.info(f"[{request_id}] Graph upserted "
                           f"(nodes={decision_graph.metadata.get('node_count', 0)}, "
                           f"edges={decision_graph.metadata.get('edge_count', 0)})")

                # Step 4: Get governance context subgraph
                subgraph = await graph_repo.get_governance_context(decision_id=request_id)

                logger.info(f"[{request_id}] Retrieved governance subgraph "
                           f"(nodes={subgraph['metadata']['node_count']}, "
                           f"edges={subgraph['metadata']['edge_count']})")

                # Build graph payload for response
                graph_payload = {
                    "decision_id": decision_graph.decision_id,
                    "nodes": [node.model_dump() for node in decision_graph.nodes],
                    "edges": [edge.model_dump() for edge in decision_graph.edges],
                    "metadata": decision_graph.metadata
                }

            except Exception as e:
                logger.error(f"[{request_id}] Graph operation failed: {e}", exc_info=True)
                # Continue without graph - don't fail the request

        # Step 5: Build decision pack (FINAL - uses decision + governance + subgraph)
        logger.info(f"[{request_id}] Building decision pack...")
        try:
            # Convert Decision object to dict for decision_pack builder
            decision_dict = response.decision.model_dump()

            # Convert governance result to dict
            governance_dict = governance_result.to_dict() if governance_result else {}

            # Build decision pack
            decision_pack = build_decision_pack(
                decision=decision_dict,
                governance=governance_dict,
                company={}
            )

            logger.info(f"[{request_id}] Decision pack built successfully "
                       f"(status={decision_pack.get('summary', {}).get('governance_status', 'unknown')})")
        except Exception as e:
            logger.error(f"[{request_id}] Decision pack build failed: {e}", exc_info=True)
            # Create minimal fallback decision pack
            decision_pack = {
                "title": "Decision Pack Build Failed",
                "summary": {
                    "decision_statement": response.decision.decision_statement,
                    "human_approval_required": True,
                    "risk_level": "unknown",
                    "governance_status": "error",
                    "confidence_score": response.decision.confidence
                },
                "missing_items": ["Failed to build complete decision pack"],
                "recommended_next_actions": ["Manual review required"]
            }

        # Build final response with decision_pack and graph_payload
        response_dict = response.model_dump()
        response_dict["decision_pack"] = decision_pack

        # Add graph payload if available
        if graph_payload:
            response_dict["graph_payload"] = graph_payload

        # Add subgraph summary
        if subgraph:
            response_dict["subgraph_summary"] = subgraph.get("summary", {})

        return response_dict

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
