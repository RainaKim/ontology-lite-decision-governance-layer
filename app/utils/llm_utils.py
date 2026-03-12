import json
from typing import Optional


def extract_json(text: str) -> Optional[dict]:
    """Extract and parse JSON from an LLM response string.

    Handles:
    - Plain JSON
    - Markdown-fenced JSON (```json ... ```)
    - JSON embedded within surrounding prose
    """
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        end_of_first_line = text.find("\n")
        if end_of_first_line != -1:
            text = text[end_of_first_line + 1:]
    if text.endswith("```"):
        text = text[:text.rfind("```")]
    text = text.strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Fall back: find outermost braces
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            result = json.loads(text[start:end])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None
