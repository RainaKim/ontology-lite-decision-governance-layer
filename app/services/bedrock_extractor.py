"""Generic Bedrock → Pydantic extractor — I/O adapter only, no scoring or governance logic.

Extension: to add a new LLM extraction step to the pipeline:
  1. Define a Pydantic output schema in app/schemas/
  2. Write the prompt string or builder function
  3. Call extractor.extract(prompt=..., output_model=MySchema) in pipeline_service.py
  No new service file needed.

Do not catch auth failures silently — only suppress transient errors (parse, validation).
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
