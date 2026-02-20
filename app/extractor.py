"""
Decision Extractor - LLM-based structured extraction with validation and retry logic.

Handles:
- Structured extraction via OpenAI (gpt-4o)
- JSON parsing
- Pydantic validation
- Retry logic (max 2 retries)
- Graceful fallback (never crash)
- Deterministic governance evaluation (NO LLMs)
"""

import json
import logging
import uuid
from typing import Tuple
from pydantic import ValidationError

from app.schemas import Decision, DecisionExtractionResponse
from app.llm_client import LLMClient
from app.governance import evaluate_governance

logger = logging.getLogger(__name__)


class DecisionExtractor:
    """
    Handles decision extraction with robust error handling.

    Core behavior:
    1. Call LLM to extract structured JSON
    2. Parse JSON response
    3. Validate with Pydantic
    4. Retry up to 2 times on failure
    5. Return fallback on total failure (never crash)
    """

    def __init__(self, llm_client: LLMClient, max_retries: int = 2):
        """
        Initialize extractor.

        Args:
            llm_client: LLM client for extraction
            max_retries: Maximum retry attempts (default: 2)
        """
        self.llm_client = llm_client
        self.max_retries = max_retries
        logger.info(f"Initialized DecisionExtractor with max_retries={max_retries}")

    def extract(self, decision_text: str, request_id: str, company_id: str) -> DecisionExtractionResponse:
        """
        Extract structured decision from text with retry logic.

        Args:
            decision_text: Free-form decision description
            request_id: Unique request identifier for tracking
            company_id: Identifier for the company context

        Returns:
            DecisionExtractionResponse with extracted decision and metadata
        """
        logger.info(f"[{request_id}] Starting extraction for text ({len(decision_text)} chars)")

        retry_count = 0
        last_error = None

        for attempt in range(self.max_retries + 1):
            retry_count = attempt
            logger.info(f"[{request_id}] Extraction attempt {attempt + 1}/{self.max_retries + 1}")

            try:
                # Step 1: Call LLM to extract JSON
                raw_json = self.llm_client.extract_decision_json(decision_text)
                logger.info(f"[{request_id}] Received raw JSON response")

                # Step 2: Parse JSON
                parsed_json = json.loads(raw_json)
                logger.info(
                    f"[{request_id}] LLM extracted: "
                    f"cost={parsed_json.get('cost')} "
                    f"uses_pii={parsed_json.get('uses_pii')} "
                    f"involves_hiring={parsed_json.get('involves_hiring')} "
                    f"involves_compliance_risk={parsed_json.get('involves_compliance_risk')} "
                    f"strategic_impact={parsed_json.get('strategic_impact')} "
                    f"headcount_change={parsed_json.get('headcount_change')}"
                )
                logger.info(f"[{request_id}] Successfully parsed JSON")

                # Step 3: Validate with Pydantic
                decision = Decision(**parsed_json)
                logger.info(f"[{request_id}] Successfully validated Decision object (confidence={decision.confidence})")

                # Step 4: Deterministic governance evaluation
                logger.info(f"[{request_id}] Running deterministic governance evaluation")
                governance_result = evaluate_governance(decision, company_context=None, use_o1=False, company_id=company_id)

                # Success!
                return DecisionExtractionResponse(
                    decision=decision,
                    extraction_metadata={
                        "request_id": request_id,
                        "retry_count": retry_count,
                        "model": self.llm_client.model,
                        "success": True
                    },
                    governance_applied=True,
                    approval_chain=[step.model_dump() for step in governance_result.approval_chain],
                    flags=[f.value for f in governance_result.flags],
                    triggered_rules=governance_result.triggered_rules,
                    requires_human_review=governance_result.requires_human_review,
                    governance_status="review_required",
                    derived_attributes={},
                    completeness_issues=[]
                )

            except json.JSONDecodeError as e:
                last_error = f"JSON parsing failed: {str(e)}"
                logger.warning(f"[{request_id}] Attempt {attempt + 1} - {last_error}")
                logger.debug(f"[{request_id}] Raw response: {raw_json[:500]}")

            except ValidationError as e:
                last_error = f"Pydantic validation failed: {str(e)}"
                logger.warning(f"[{request_id}] Attempt {attempt + 1} - {last_error}")
                logger.debug(f"[{request_id}] Parsed JSON: {json.dumps(parsed_json, indent=2)[:500]}")

            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                logger.error(f"[{request_id}] Attempt {attempt + 1} - {last_error}")

        # All retries exhausted - return fallback
        logger.error(f"[{request_id}] All {self.max_retries + 1} attempts failed. Returning fallback decision.")
        fallback_decision = self._create_fallback_decision(decision_text, request_id, last_error)

        # Still evaluate deterministic governance on fallback
        governance_result = evaluate_governance(fallback_decision, company_context=None, use_o1=False, company_id=company_id)

        return DecisionExtractionResponse(
            decision=fallback_decision,
            extraction_metadata={
                "request_id": request_id,
                "retry_count": retry_count,
                "model": self.llm_client.model,
                "success": False,
                "error": last_error,
                "fallback_used": True
            },
            governance_applied=True,
            approval_chain=[step.model_dump() for step in governance_result.approval_chain],
            flags=[f.value for f in governance_result.flags],
            triggered_rules=governance_result.triggered_rules,
            requires_human_review=True,  # Always require review for fallback
            governance_status="blocked",  # Fallback is always blocked
            derived_attributes={},
            completeness_issues=[]
        )

    def _create_fallback_decision(self, decision_text: str, request_id: str, error_message: str) -> Decision:
        """
        Create a fallback Decision object when extraction fails completely.

        Args:
            decision_text: Original decision text
            request_id: Request ID for tracking
            error_message: Last error that occurred

        Returns:
            Minimal valid Decision object with confidence=0.1
        """
        logger.info(f"[{request_id}] Creating fallback decision (confidence=0.1)")

        # Create minimal valid decision — no fabricated owner; ownership inference
        # happens in the graph/reasoning step if needed.
        fallback = Decision(
            decision_statement=f"[EXTRACTION FAILED] {decision_text[:100]}...",
            goals=[],
            kpis=[],
            risks=[],
            owners=[],
            required_approvals=["Manual Review Required"],
            assumptions=[],
            confidence=0.1  # Very low confidence
        )

        return fallback


def create_request_id() -> str:
    """Generate unique request ID for tracking."""
    return str(uuid.uuid4())
