"""
LLM Client - OpenAI integration for structured decision extraction.
"""

import json
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI client for structured decision extraction."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (if None, will use OPENAI_API_KEY env var)
            model: Model to use for extraction (default: gpt-4o)
        """
        self.client = OpenAI(api_key=api_key)
        self.model = model
        logger.info(f"Initialized OpenAI client with model: {model}")

    def extract_decision_json(self, decision_text: str) -> str:
        """
        Extract structured decision JSON from free-form text.

        Args:
            decision_text: Free-form decision description

        Returns:
            Raw JSON string containing structured decision

        Raises:
            Exception: If OpenAI API call fails
        """
        schema_description = """
{
  "decision_statement": "string (10-1000 chars, clear executable action)",
  "goals": [
    {
      "description": "string (3-500 chars)",
      "metric": "string or null"
    }
  ],
  "kpis": [
    {
      "name": "string (3-200 chars)",
      "target": "string or null",
      "measurement_frequency": "string or null"
    }
  ],
  "risks": [
    {
      "description": "string (3-500 chars)",
      "severity": "string or null (Low/Medium/High/Critical)",
      "mitigation": "string or null"
    }
  ],
  "owners": [
    {
      "name": "string (2-200 chars)",
      "role": "string or null",
      "responsibility": "string or null"
    }
  ],
  "required_approvals": ["string"],
  "assumptions": [
    {
      "description": "string (3-500 chars)",
      "criticality": "string or null"
    }
  ],
  "confidence": 0.0 to 1.0
}
"""

        system_prompt = f"""You are a decision extraction system for enterprise governance.

Your task: Convert free-form decision text into structured JSON ONLY.

Output ONLY valid JSON matching this schema:
{schema_description}

Requirements:
- Extract decision_statement: Clear, executable action
- Extract goals: List of organizational outcomes
- Extract kpis: List of measurable metrics with name and optional target
- Extract risks: List of potential failure vectors with description and optional severity
- Extract owners: List of accountable roles (at least ONE required)
- Extract required_approvals: List of approval candidate names/roles
- Extract assumptions: List of implicit beliefs with description
- Set confidence: Float 0.0-1.0 based on extraction certainty

Rules:
- Output ONLY valid JSON, no explanations or markdown
- If information is missing, use empty lists []
- Always include at least one owner
- Be conservative with confidence scores
- Extract actual content, don't make up information"""

        user_message = f"""Extract structured decision from this text:

{decision_text}

Output valid JSON only."""

        try:
            logger.info(f"Calling OpenAI API with model: {self.model}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0,  # Deterministic extraction
                response_format={"type": "json_object"}  # Force JSON output
            )

            raw_response = response.choices[0].message.content
            logger.info(f"Received response from OpenAI ({len(raw_response)} chars)")
            logger.debug(f"Raw response: {raw_response[:200]}...")

            return raw_response

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
