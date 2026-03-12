"""Generic Bedrock → Pydantic extractor.

Intended to replace decision_context_service and risk_evidence_llm,
which share the same call-validate-return-None skeleton.

Migration is blocked until test_decision_context_extraction.py and
test_risk_semantics.py are updated — both directly import the old
service modules as the unit-under-test. See AGENT_TASKS.md for details.
"""
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from app.bedrock_client import BedrockClient
from app.utils.llm_utils import extract_json

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class BedrockStructuredExtractor:
    def __init__(self, _client: Optional[BedrockClient] = None):
        self._client = _client or BedrockClient()

    def extract(
        self,
        prompt: str,
        output_model: Type[T],
        system_prompt: Optional[str] = None,
    ) -> Optional[T]:
        """Call Bedrock, parse JSON, validate against output_model.

        Returns None on any failure (network, parse, validation).
        """
        try:
            raw = self._client.invoke(prompt, system_prompt=system_prompt)
            data = extract_json(raw)
            if data is None:
                logger.warning("BedrockStructuredExtractor: no JSON in response")
                return None
            return output_model.model_validate(data)
        except Exception as exc:
            logger.warning("BedrockStructuredExtractor: %s", exc, exc_info=True)
            return None
