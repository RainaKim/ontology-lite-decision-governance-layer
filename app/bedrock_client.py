"""
app/bedrock_client.py — Shared AWS Bedrock Runtime HTTP client.

Used by all LLM call sites: extraction (llm_client), reasoning (nova_reasoner),
risk semantics (risk_evidence_llm), and scenario proposals (nova_scenario_proposer).

Authentication: BEDROCK_API_KEY from .env — passed as Bearer token.
System prompts use the Nova top-level "system" field (not a messages role).

Extension — dependency injection:
  Inject http_client at construction time for tests (httpx.MockTransport).
  api_key still defaults to os.environ.get("BEDROCK_API_KEY") for production.
  Do not inject per-method — constructor injection only.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.config.bedrock_config import NOVA_MODEL_ID, NOVA_PRO_MODEL_ID, BEDROCK_REGION, BEDROCK_TIMEOUT

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = NOVA_MODEL_ID
_DEFAULT_REGION = BEDROCK_REGION
_TIMEOUT = BEDROCK_TIMEOUT


class BedrockClient:
    """
    Thin httpx wrapper for Amazon Nova on Bedrock Runtime.

    Usage::

        client = BedrockClient()
        text = client.invoke("user message here", system_prompt="system context")
    """

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL,
        region: str = _DEFAULT_REGION,
    ) -> None:
        self.model_id = model_id
        self._endpoint = (
            f"https://bedrock-runtime.{region}.amazonaws.com"
            f"/model/{model_id}/invoke"
        )

    def invoke(
        self,
        user_message: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int = 2048,
    ) -> str:
        """
        Invoke the model and return the assistant text reply.

        Args:
            user_message:  The user turn content.
            system_prompt: Optional system context — sent as the top-level
                           Nova "system" field, not as a messages role.
            max_tokens:    Maximum tokens to generate (default 2048).

        Returns:
            The model's text reply as a plain string.

        Raises:
            RuntimeError: BEDROCK_API_KEY not set.
            httpx.HTTPStatusError: Non-2xx HTTP response.
        """
        api_key = os.environ.get("BEDROCK_API_KEY")
        if not api_key:
            raise RuntimeError("BEDROCK_API_KEY not set in environment")

        payload: dict = {
            "messages": [
                {"role": "user", "content": [{"text": user_message}]}
            ],
            "inferenceConfig": {
                "temperature": 0,
                "maxTokens": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = [{"text": system_prompt}]

        response = httpx.post(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        text = response.json()["output"]["message"]["content"][0]["text"]
        return self._strip_markdown(text)

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Strip markdown code fences that Nova sometimes wraps around JSON output."""
        text = text.strip()
        if text.startswith("```"):
            text = text[text.index("\n") + 1:] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
        return text.strip()
