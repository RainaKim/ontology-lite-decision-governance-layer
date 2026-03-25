"""
LLM Client — Structured decision extraction.

NOTE: BedrockClient has been removed. This module is a stub that raises
NotImplementedError until a LangChain-based replacement is implemented
(via app/config/llm.py get_llm()).

The DecisionExtractor in app/extractor.py uses this client for extraction.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Placeholder model name for metadata/logging
_STUB_MODEL = "stub-pending-langchain"


class LLMClient:
    """Stub LLM client — Bedrock removed, LangChain replacement pending."""

    def __init__(self, api_key: Optional[str] = None, model: str = _STUB_MODEL):
        self.model = model
        logger.warning(
            "LLMClient: BedrockClient has been removed. "
            "extract_decision_json will raise NotImplementedError until LangChain replacement is implemented."
        )

    def extract_decision_json(self, decision_text: str) -> str:
        """
        Stub: previously called BedrockClient to extract structured decision JSON.

        Raises NotImplementedError — LangChain replacement is pending.
        """
        raise NotImplementedError(
            "LLMClient.extract_decision_json: BedrockClient has been removed. "
            "Implement via app/config/llm.py get_llm() before using this method."
        )
